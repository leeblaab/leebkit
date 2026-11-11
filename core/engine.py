"""LEEBKIT core — frame builder engine.

Generalization of the proven build_video_v4.py pipeline (LEEBLAAB promo).
Driven entirely by a project JSON (schema:1) + a preset style JSON.

Hard-won fixes baked in from day one:
  * ov-overlap transition fix: incoming layer renders on its OWN early clock
    lt = max(0, p*OV) during wipes, so text animates DURING the transition
    instead of showing a frozen settled preview that resets after the cut.
  * word-stagger completion formula: line offsets S=(1-span)/(n-1) with
    appear = wprog*(span/0.55) - j*S guarantee every word reaches progress>=1
    exactly at shot end.
  * global continuous zoom track (no camera reset at cuts).
"""
import json
import math
import os
import random

import numpy as np

from PIL import Image, ImageDraw, ImageFilter, ImageFont



from .layout import build_layout, clamp_font_sizes
from .camutil import cam_name
from .audio import VO_SPEED_RANGE  # v1.4 C2: one source of truth for speed bounds
from .generators import (GEN_PRESETS, render as gen_render,
                         render_base as gen_base,
                         composite_grain as gen_grain)  # v1.4 C3 / C4d
from . import captions as CAPTIONS   # per-kind draw (C3a); captions never imports engine


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
FONTS_DIR = os.path.join(ASSETS, "fonts")

BG_DEFAULT = (10, 10, 14)

# Transitions the engine actually implements. validate_project rejects anything
# else so a typo ("wipe_left") fails LOUD at save/submit time instead of
# silently rendering a fade (v1.2 audit #1).
TRANSITIONS = {"cut", "none", "fade", "slideL", "slideR", "whip", "flashdip",
               "wipe_left", "wipe_up"}
# camera pan names (zoom is a separate global track). validate_project gates
# these; the engine reads them via camutil.cam_name ("cam" OR "camera").
CAMERAS = {"pushin", "panup", "pandown", "pandiag", "pushout", "pushin2"}


# ---------------------------------------------------------------- easing utils
def ease_io(t):  # smoothstep in-out
    return t * t * (3 - 2 * t)


def ease_o(t):   # cubic out
    return 1 - (1 - t) ** 3


def ease_ow(t):  # back-out with overshoot
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    c1 = 1.36
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def clamp01(t):
    return max(0.0, min(1.0, t))


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------ project loading
def load_preset(name):
    # tolerate preset ids with or without the .json suffix (UI sends bare ids)
    if not name.endswith(".json"):
        name += ".json"
    path = name if os.path.isabs(name) else os.path.join(ROOT, "presets", name)
    pdir = os.path.realpath(os.path.join(ROOT, "presets"))
    rp = os.path.realpath(path)
    if not (rp == pdir or rp.startswith(pdir + os.sep)):
        # confinement: preset ids may never traverse outside the presets dir (A2)
        raise ValueError("preset must live in the presets/ directory: %r" % name)
    with open(rp, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_project(proj):
    """Schema-1 validation; raises ValueError with a readable message."""
    if proj.get("schema") != 1:
        raise ValueError("project schema must be 1 (got %r)" % proj.get("schema"))
    # media-relative convention (v1.2): Engine joins shot image paths onto
    # media_dir, so an "media/..."-prefixed path silently double-prefixes and
    # dies later as "outside media dir". Older writers produced that shape —
    # normalize at the boundary instead of failing the whole render.
    for s in proj.get("shots") or []:
        img = s.get("image")
        if isinstance(img, str) and (img == "media" or img.startswith("media/")):
            s["image"] = img[len("media/"):]
    w = int(proj.get("width", 1080))
    h = int(proj.get("height", 1920))
    if not (320 <= w <= 3840 and 320 <= h <= 3840):
        raise ValueError("width/height must be 320-3840 (got %dx%d)" % (w, h))
    # v1.4 C1: portrait projects must land on a supported tier — 9:16 at one of
    # 720p / FHD / 2K. Square and landscape formats stay free-form (v1.2), and
    # the 320x480 tiny-probe escape hatch stays legal for smoke/QA projects.
    if h > w:
        if (w, h) not in ((720, 1280), (1080, 1920), (1440, 2560), (320, 480)):
            raise ValueError(
                "portrait width/height must be a supported tier "
                "(720x1280, 1080x1920, 1440x2560 — got %dx%d; square and "
                "landscape formats accept any size in range)" % (w, h))
    fps = int(proj.get("fps", 30))
    if fps not in (24, 30):
        raise ValueError("fps must be 24 or 30 (got %d)" % fps)
    # v1.4 C2: optional speech speed (UI offers 0.8/1.0/1.25 = Slow/Normal/Fast).
    # Tolerated key — schema stays 1; gate the VALUE so junk fails at save time,
    # not as a piper crash mid-render. Normalized to float on the project dict.
    vs = proj.get("voice_speed", 1.0)
    try:
        vs = float(vs)
    except (TypeError, ValueError):
        raise ValueError("voice_speed must be a number (got %r)" % (proj.get("voice_speed"),))
    if not (VO_SPEED_RANGE[0] <= vs <= VO_SPEED_RANGE[1]):
        raise ValueError("voice_speed must be within %.2f-%.2f (got %.2f)"
                         % (VO_SPEED_RANGE[0], VO_SPEED_RANGE[1], vs))
    proj["voice_speed"] = vs
    shots = proj.get("shots") or []
    if not (1 <= len(shots) <= 10):
        raise ValueError("v1 supports 1-10 shots (got %d)" % len(shots))
    target = float(proj.get("target", 30.0))
    total = sum(float(s.get("t", 0)) for s in shots)
    if abs(total - target) > 1e-6:
        raise ValueError("shot durations sum to %.3fs but target is %.3fs" % (total, target))
    for i, s in enumerate(shots):
        if not (0.5 <= float(s.get("t", 0)) <= 15.0):
            raise ValueError("shot %d duration must be 0.5-15s" % i)
        tr = s.get("transition") or s.get("trans")
        if tr is not None and tr not in TRANSITIONS:
            raise ValueError("shot %d transition %r not implemented (choices: %s)"
                             % (i, tr, ", ".join(sorted(TRANSITIONS))))
        cam = cam_name(s)
        if cam is not None and cam not in CAMERAS:
            raise ValueError("shot %d camera %r unknown (choices: %s)"
                             % (i, cam, ", ".join(sorted(CAMERAS))))
        # v1.4 C3: fill="gen:<preset>" whitelist — an unknown generator name
        # fails LOUD at save/submit time (same rule as transitions/cameras),
        # not as a mid-render crash.
        fill = s.get("fill")
        if isinstance(fill, str) and fill.startswith("gen:"):
            if fill[4:] not in GEN_PRESETS:
                raise ValueError("shot %d fill %r unknown generator (choices: gen:%s)"
                                 % (i, fill, ", gen:".join(sorted(GEN_PRESETS))))
        for c in s.get("captions", []):
            if "kind" not in c:
                raise ValueError("shot %d caption missing kind" % i)
            # DISPATCH whitelist (audit #5): render_layer's .get(k) silently
            # skips unknown kinds — the comment there claimed validate gates
            # these; now it actually does.
            if c["kind"] not in CAPTIONS.DISPATCH:
                raise ValueError("shot %d caption kind %r unknown (choices: %s)"
                                 % (i, c["kind"], ", ".join(sorted(CAPTIONS.DISPATCH))))
            if "at" in c:
                a = float(c["at"])
                if not (0.0 <= a <= float(s.get("t", 0))):
                    raise ValueError("shot %d caption at=%.2fs outside shot window 0..%.2fs"
                                     % (i, a, float(s.get("t", 0))))
    return proj


class Engine:
    """Builds frames for one project. `render_frame(idx)` is the hot loop entry."""

    def __init__(self, proj, preset=None, media_dir=None):
        self.proj = validate_project(dict(proj))
        self.preset = preset or load_preset(self.proj.get("preset", "leebdark.json"))
        self.media_dir = media_dir or os.path.join(ROOT, "media")
        self.W = int(self.proj.get("width", 1080))
        self.H = int(self.proj.get("height", 1920))
        self.FPS = int(self.proj.get("fps", 30))
        self.DUR = float(self.proj["target"])
        self.N = int(round(self.DUR * self.FPS))

        P = self.preset
        C = P["colors"]
        self.TRK = P.get("tracking", {})   # checks.py measures sub widths with this
                                           # (was a render_layer-local; checker saw {} ->
                                           # flagged widths != rendered widths, audit #9)
        self.BG = hex2rgb(C["bg"])
        self.WHITE = hex2rgb(C["white"])
        self.ACCENT = hex2rgb(C["accent"])
        self.DIM = hex2rgb(C["dim"])
        self.PANEL = hex2rgb(C["panel"])
        S = P["sizes"]
        self.XF = float(P.get("xf", 0.5))
        self.OVER = float(P.get("overscan", 1.35))

        # ---- aspect-aware layout metrics (v1.2: 9:16 / 1:1 / 16:9) ----
        self.L = build_layout(self.W, self.H, S, P.get("landscape"))
        clamp_font_sizes(self.L, lambda sz: ImageFont.truetype(
            os.path.join(FONTS_DIR, P["fonts"]["display"]), sz))
        S = dict(S)
        for _k in ("logo", "h1", "body", "small", "mono", "mono_s", "big"):
            S[_k] = self.L[_k]

        # ---- fonts (bundled OFL variable fonts; weight via set_variation) ----
        def mk(fname, size, weight=None):
            path = os.path.join(FONTS_DIR, fname)
            f = ImageFont.truetype(path, size)
            if weight:
                try:
                    f.set_variation_by_name(weight)
                except Exception:
                    pass
            return f

        self._mkfont = mk   # used later (title shrink-to-fit) outside __init__ scope
        self.SIZES = S      # preset pixel sizes dict (used by wrap layout math)
        FD = P["fonts"]
        self.LOGO = mk(FD["display"], S["logo"])
        self.H1 = mk(FD["display"], S["h1"])
        self.BODY = mk(FD["body"], S["body"], "Bold")
        self.MONO = mk(FD["mono"], S["mono"], "Bold")
        self.MONOS = mk(FD["mono"], S["mono_s"])
        self.SMALL = mk(FD["body"], S["small"])
        self.BIG = mk(FD["display"], S["big"])

        # ---- shots + start times ----
        self.shots = self.proj["shots"]
        self.starts = []
        acc = 0.0
        for s in self.shots:
            self.starts.append(acc)
            acc += float(s["t"])

        # ---- global camera zoom track (continuous across cuts) ----
        ZK = P.get("camera_zoom_keyframes") or self._auto_zoom_track()
        self.ZK = [(float(a), float(b)) for a, b in ZK]

        self.CAM = {"pushin": (0, -26), "panup": (0, -70), "pandown": (0, 60),
                    "pandiag": (-46, -50), "pushout": (30, 20), "pushin2": (20, -30),
                    None: (0, 0), "": (0, 0)}

        # ---- image bases (overscanned for ken-burns headroom) ----
        self.BW, self.BH = int(self.W * self.OVER), int(self.H * self.OVER)
        self.bases = {}
        self.available_images = self._scan_images()
        self.bad_images = []
        for s in self.shots:
            f = s.get("image")
            if f and f not in self.bases:
                p = self._media_path(f)
                if p is None:
                    # path escapes media_dir (traversal/absolute) — loud, not silent
                    self.bad_images.append(f)
                    continue
                if os.path.exists(p):
                    self.bases[f] = self._load_base(p)
                else:
                    self.bad_images.append(f)
        if self.bad_images and any(s.get("image") for s in self.shots):
            # ValueError, NOT SystemExit: SystemExit is a BaseException, so it
            # escaped queue._run's `except Exception` and killed the single
            # worker thread forever (v1.2 audit #8). CLI converts this to an
            # exit at its own boundary.
            raise FileNotFoundError("shot image(s) not found or outside media "
                                    "dir (render aborted, no black frames): %s"
                                    % ", ".join(sorted(set(self.bad_images))))

        self._grid = None
        self._collage = None
        self._grad_cache = {}
        # C3b: fit/wrap metrics cache keyed (shot_idx, caption_idx). The
        # shrink/wrap loops in fit_title/fit_panel_lines are input-determined:
        # the same (project JSON, size, preset) always yields the same result,
        # so per-frame refits were pure repeated work. Engine instances are
        # built fresh per project (queue/CLI rebuild on every job; UI edits
        # rebuild via new submit), so the cache dies with the instance — no
        # invalidation hook needed.
        self._metrics_cache = {}

    # ------------------------------------------------------------------ media
    def _within(self, base, path):
        """True if path resolves inside base (containment for path inputs)."""
        b = os.path.realpath(base)
        p = os.path.realpath(path)
        return p == b or p.startswith(b + os.sep)

    def _media_path(self, fname):
        # confinement: project-supplied paths may never escape media_dir —
        # relative traversal (..) and absolute paths are rejected (A2 hardening)
        if os.path.isabs(fname):
            return None
        cand = os.path.join(self.media_dir, fname)
        if not self._within(self.media_dir, cand):
            return None
        return cand

    def _scan_images(self):
        d = self.media_dir
        out = []
        # audit #11 (v1.31): unqualified substring match — a media dir named
        # "keyframes" or "my_outputs" was skipped wholesale. Match path
        # COMPONENTS instead: only a real segment named output/frames/.git skips.
        skip = {"output", "frames", ".git"}
        for root, dirs, files in os.walk(d):
            if set(os.path.relpath(root, d).replace("\\", "/").split("/")) & skip:
                dirs[:] = []
                continue
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    out.append(os.path.relpath(os.path.join(root, f), d).replace("\\", "/"))
        return sorted(out)

    def _load_base(self, path):
        im = Image.open(path).convert("RGB")
        sc = max(self.BW / im.width, self.BH / im.height)
        im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
        x = (im.width - self.BW) // 2
        y = (im.height - self.BH) // 2
        return im.crop((x, y, x + self.BW, y + self.BH))

    def _pool(self):
        """Images available for grid/collage fills (project images first)."""
        used = [s["image"] for s in self.shots if s.get("image") and s["image"] in self.bases]
        pool = list(self.bases.values())
        others = []
        for rel in self.available_images:
            p = self._media_path(rel)
            if p is None:
                continue
            if p not in [self._media_path(u) for u in used] and rel not in self.bases:
                others.append(p)
            if len(pool) + len(others) >= 12:
                break
        for p in others[: max(0, 12 - len(pool))]:
            try:
                pool.append(self._load_base(p))
            except Exception:
                pass
        return pool

    def build_grid(self):
        if self._grid is not None:
            return self._grid
        g = Image.new("RGB", (self.BW, self.BH), self.BG)
        pool = self._pool()[:9]
        cw, ch = self.BW // 3, self.BH // 3
        for i, im in enumerate(pool):
            sc = max(cw / im.width, ch / im.height)
            r = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
            x = (r.width - cw) // 2
            y = (r.height - ch) // 2
            g.paste(r.crop((x, y, x + cw, y + ch)), ((i % 3) * cw, (i // 3) * ch))
        self._grid = g
        return g

    def build_collage(self):
        if self._collage is not None:
            return self._collage
        c = Image.new("RGB", (self.BW, self.BH), self.BG)
        rnd = random.Random(7)
        for im in self._pool()[:4]:
            sc = max(self.BW / im.width, self.BH / im.height) * 0.75
            r = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
            c.paste(r, (rnd.randint(-100, self.BW - 200), rnd.randint(-100, self.BH - 200)))
        self._collage = c.filter(ImageFilter.GaussianBlur(8))
        return self._collage

    # ------------------------------------------------------------- camera math
    def track(self, t):
        ZK = self.ZK
        if t <= ZK[0][0]:
            return ZK[0][1]
        for a, b in zip(ZK, ZK[1:]):
            if t <= b[0]:
                p = ease_io((t - a[0]) / (b[0] - a[0]))
                return a[1] + (b[1] - a[1]) * p
        return ZK[-1][1]

    def _auto_zoom_track(self):
        """Fallback zoom keyframes if the preset doesn't cover this duration."""
        ks, t = [], 0.0
        z = 1.06
        while t < self.DUR:
            ks.append((t, z))
            t += min(4.0, max(2.0, self.DUR / 8))
            z = 1.14 if z <= 1.1 else 1.05
        ks.append((self.DUR, 1.06))
        return ks

    # ------------------------------------------------------------- text helpers
    def draw_center_text(self, dr, y, txt, fnt, fill, tracking=0):
        W = self.W
        if tracking:
            ws = [dr.textlength(c, font=fnt) for c in txt]
            total = sum(ws) + tracking * (len(txt) - 1)
            x = (W - total) / 2
            for c, w in zip(txt, ws):
                dr.text((x, y), c, font=fnt, fill=fill)
                x += w + tracking
        else:
            w = dr.textlength(txt, font=fnt)
            dr.text(((W - w) / 2, y), txt, font=fnt, fill=fill)

    def _measure_tracked(self, dr, txt, fnt, tracking):
        return sum(dr.textlength(c, font=fnt) for c in txt) + tracking * max(0, len(txt) - 1)

    def fit_title(self, dr, txt, base_size, limit, tracking_scale=6 / 128):
        """Wrap title to <=limit px per line (word-first), shrink font only as a
        last resort. Returns (lines, size, tracking).

        C3b: results are cached per Engine on the exact args — they depend only
        on the project text + fonts + layout numbers, never on time or draw
        state, so the shrink loop runs once per caption instead of per frame."""
        ck = ("title", txt, base_size, limit, tracking_scale)
        hit = self._metrics_cache.get(ck)
        if hit is not None:
            return list(hit[0]), hit[1], hit[2]   # fresh list copy: callers mutate never, but keep the cache pristine
        words = txt.split()
        if not words:
            return [], base_size, 0
        lines, cur = [], ""
        for wd in words:
            cand = (cur + " " + wd).strip()
            if dr.textlength(cand, font=self.LOGO) <= limit or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        size = base_size
        trk = int(round(tracking_scale * size))
        while (max(self._measure_tracked(dr, l, self.LOGO, trk) for l in lines) > limit
               and size > 40):
            size = max(40, int(size * 0.92))
            trk = int(round(tracking_scale * size))
        if size != base_size:
            # rebuild wrap with the shrunk metrics (fewer lines possible)
            f_small = self._mkfont(self.preset["fonts"]["display"], size)
            lines, cur = [], ""
            for wd in words:
                cand = (cur + " " + wd).strip()
                if f_small.getlength(cand) <= limit - trk * max(0, len(cand) - 1) or not cur:
                    cur = cand
                else:
                    lines.append(cur)
                    cur = wd
            lines.append(cur)
        result = (lines, size, trk)
        self._metrics_cache[ck] = result
        return result

    def wrap_words(self, dr, words, fnt, limit, tracking=0):
        """Greedy word-wrap: group `words` so each line measures <= limit px.
        A single over-long word stays on its own line (checks.py flags it).

        C3b: cached per Engine — wrap output depends only on the words, font
        size/name, limit and tracking (never time/draw state), so the cache key
        uses the font's identity (name+size) instead of the transient Draw."""
        ck = ("wrap", tuple(words), getattr(fnt, "path", id(fnt)),
              fnt.size if isinstance(fnt.size, int) else tuple(fnt.size),
              limit, tracking)
        hit = self._metrics_cache.get(ck)
        if hit is not None:
            return hit
        lines, cur = [], []
        for wd in words:
            cand = " ".join(cur + [wd])
            if not cur or self._measure_tracked(dr, cand, fnt, tracking) <= limit:
                cur.append(wd)
            else:
                lines.append(" ".join(cur))
                cur = [wd]
        if cur:
            lines.append(" ".join(cur))
        self._metrics_cache[ck] = lines
        return list(lines)   # copy: callers may mutate the returned list, never the cache

    def fit_panel_lines(self, dr, lines, fnt):
        """Wrap raw panel/cap lines to the text safe width (W-160) so long user
        input can never clip at the frame edge. Returns wrapped line list."""
        limit = self.L["panel_text_limit"]
        out = []
        for l in lines:
            out.extend(self.wrap_words(dr, l.split(" "), fnt, limit))
        return out

    def fit_small_lines(self, dr, text, fnt, tracking):
        """Wrap a tracked small/sub line to the safe text width minus plate
        padding so an over-long sub can never clip at the frame edge."""
        limit = self.W - 160 - 2 * self.L["sub_pad"]
        return self.wrap_words(dr, text.split(" "), fnt, limit, tracking=tracking)

    def draw_title_lines(self, dr, y_center, lines, fnt, fill, tracking, line_h,
                         rise=0.0):
        """C7: `rise` = back-out overshoot offset (px) shared by the whole
        title block — glyphs, underline and sub plate lift as ONE element."""
        ys = [y_center - (len(lines) - 1) * line_h / 2 + j * line_h for j in range(len(lines))]
        for y, l in zip(ys, lines):
            self.draw_center_text(dr, y - rise, l, fnt, fill, tracking=tracking)
        return ys

    def word_pop(self, dr, y, fnt, txt, color, appear, tracking=0, dy=30, alpha_cap=None):
        """Whole-word staggered pop with overshoot. appear is this call's clock.
        alpha_cap: hard ceiling on glyph alpha (outgoing layer inside a
        transition window must fade even though its pop clock is frozen)."""
        if appear <= 0:
            return
        W = self.W
        words = txt.split(" ")
        wsp = dr.textlength(" ", font=fnt)
        ws = [dr.textlength(w, font=fnt) for w in words]
        total = sum(ws) + wsp * (len(words) - 1) + tracking * sum(len(w) for w in words)
        x = (W - total) / 2
        for i, w in enumerate(words):
            wt = clamp01((appear - i * 0.18) / 0.36)
            if wt <= 0:
                x += ws[i] + wsp + tracking * len(w)
                continue
            e = ease_ow(wt)
            a = int(255 * min(1.0, wt * 1.5))
            if alpha_cap is not None:
                a = min(a, alpha_cap)
            yy = y + (1 - e) * dy
            if tracking:
                for c in w:
                    cw = dr.textlength(c, font=fnt)
                    dr.text((x, yy), c, font=fnt, fill=(color[0], color[1], color[2], a))
                    x += cw + tracking
            else:
                dr.text((x, yy), w, font=fnt, fill=(color[0], color[1], color[2], a))
                x += ws[i]
            x += wsp + tracking

    # -------------------------------------------------------------- dim layer
    def _dim_overlay(self, dim):
        key = round(dim, 3)
        if key in self._grad_cache:
            return self._grad_cache[key]
        H = self.H
        grad = Image.new("L", (1, H))
        for yy in range(H):
            grad.putpixel((0, yy), int(255 * dim * (0.75 + 0.25 * math.sin(yy / H * math.pi))))
        black = Image.new("RGBA", (self.W, self.H), (8, 8, 12, 255))
        black.putalpha(grad.resize((self.W, self.H)))
        self._grad_cache[key] = black
        return black

    # ------------------------------------------------------------- layer kinds
    def render_layer(self, i, lt, idx, cut_mode=False, transition_out=None):
        """Render shot i at local time lt (frame seed idx). Returns RGB image."""
        W, H = self.W, self.H
        s = self.shots[i]
        g = self.starts[i] + lt
        fill = s.get("fill") or ("image" if s.get("image") else "solid")
        if fill == "grid":
            base = self.build_grid()
        elif fill == "collage":
            base = self.build_collage()
        elif s.get("image") and s["image"] in self.bases:
            base = self.bases[s["image"]]
        else:
            base = None

        # v1.4 C3: procedural generator bases ride the SAME overscanned crop
        # path as image bases (Ken Burns cost ceiling, D6). The shot's zoom
        # track and camera pan animate the crop; the generator itself runs on
        # ONE shared driver at local time lt, amplitude from the preset tier
        # (D4/D5) — never from shot speed. Fixed designed palettes (D2): the
        # project color preset is deliberately NOT consulted here.
        gen_name = fill[4:] if isinstance(fill, str) and fill.startswith("gen:") else None
        if gen_name is not None:
            # D6 cost ceiling: the generator runs on a base sized like the
            # overscanned Ken Burns crop (BW/8), then rides the SAME per-frame
            # crop+LANCZOS path as image bases — zoom track and camera pan
            # therefore apply to generated shots too.
            amp = 0.4 if s.get("motion", "normal") == "subtle" else 1.0
            bw, bh = max(64, int(self.BW / 8)), max(64, int(self.BH / 8))
            gbase = gen_base(gen_name, bw, bh, offset=lt, amp=amp)
            z = self.track(g)
            px, py = self.CAM.get(cam_name(s), (0, 0))
            p = ease_io(clamp01(lt / float(s["t"])))
            cx = bw / 2 + px * p
            cy = bh / 2 + py * p
            cw, ch = int(bw / z), int(bh / z)
            x0 = int(max(0, min(bw - cw, cx - cw / 2)))
            y0 = int(max(0, min(bh - ch, cy - ch / 2)))
            # C4d: upscale stays in the numpy world — PIL LANCZOS on the base
            # array's view, then integer grain add (composite_grain fast
            # path). Grain composited at OUTPUT resolution after the upscale:
            # baked into the BW/8 base and magnified ~8x it read as coarse
            # mushy snow (Yasser's live-test observation). Same drift rule
            # (grain_drift), same gains, just full-res texture underneath.
            up = np.asarray(Image.fromarray(np.asarray(gbase)).crop(
                (x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS))
            img = Image.fromarray(gen_grain(up, gen_name, W, H, offset=lt, amp=amp))
            base = img   # generated bases take the SAME dim-overlay path as images
        elif base is not None:
            z = self.track(g)
            px, py = self.CAM.get(cam_name(s), (0, 0))
            p = ease_io(clamp01(lt / float(s["t"])))
            cx = self.BW / 2 + px * p
            cy = self.BH / 2 + py * p
            cw, ch = int(self.BW / z), int(self.BH / z)
            x0 = int(max(0, min(self.BW - cw, cx - cw / 2)))
            y0 = int(max(0, min(self.BH - ch, cy - ch / 2)))
            img = base.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS)
        else:
            img = Image.new("RGB", (W, H), self.BG)

        dr = ImageDraw.Draw(img, "RGBA")
        dim = float(s.get("dim", 0.4))
        if base is not None and dim > 0:
            black = self._dim_overlay(dim)
            img.paste(Image.alpha_composite(img.convert("RGBA"), black).convert("RGB"), (0, 0))

        WHITE, ACCENT, DIMC = self.WHITE, self.ACCENT, self.DIM
        P = self.preset
        LY = self.L
        TRK = self.TRK

        for ci, L in enumerate(s.get("captions", [])):
            k = L["kind"]
            at = float(L.get("at", 0.2))
            # panel_* kinds are the shot's message itself (fill=solid frames):
            # run their clock 0.45s early so a black beat never holds with an
            # empty card (Yasser's sheet9 QA: dead gaps before word-pop lines).
            # MUST happen BEFORE prog/freeze: previously the shift was applied
            # after prog was computed from unshifted at, which cancelled the
            # early start inside transition windows (panel text froze near
            # prog~0 and faded out unseen) and left entry timing on ordinary
            # frames inconsistent with slide/gating (v1.3 C2).
            if k in ("panel_top", "panel_mid"):
                at -= CAPTIONS.M.PANEL_SHIFT
            prog = clamp01((lt - at) / 0.32)
            # outgoing-side kill switch: inside a transition window the incoming
            # layer runs its own early clock (OV) while this layer's lt keeps
            # running past the shot end — freeze each caption's animation clock
            # at its shot end so nothing GROWS, and fade every element out over
            # the window (Yasser: outgoing captions bled under the incoming
            # shot even in the shipped demo). Hard cuts never enter here.
            if transition_out:
                prog = min(prog, clamp01((float(s["t"]) - at) / 0.32))
                fade = 1.0 - clamp01((lt - float(s["t"])) / max(transition_out, 1e-6))
                if prog <= 0 or fade <= 0:
                    continue
                a_gate = int(255 * fade)
            else:
                a_gate = None
            if cut_mode and lt < at:
                continue
            if prog <= 0:
                continue
            a = int(255 * min(1.0, prog * 1.3))
            if a_gate is not None:
                # outgoing layer inside a transition window: cap the alpha at
                # the fade-out gate so both shots' text never sit visible together
                a = min(a, a_gate)
            slide = int((1 - ease_o(prog)) * LY["slide_dy"])

            _cf = CAPTIONS.DISPATCH.get(k)
            if _cf is None:
                continue    # unknown kind: validate_project gates these; belt & braces
            ctx = CAPTIONS.FrameCtx(
                W=W, H=H, LY=LY, P=P, TRK=TRK,
                WHITE=WHITE, ACCENT=ACCENT, DIMC=DIMC,
                lt=lt, at=at, g=g, shot_t=float(s["t"]),
                prog=prog, a=a, slide=slide,
                a_gate=a_gate, transition_out=transition_out,
                cap_idx=(i, ci))   # C3b: stable per-caption slot for fit/wrap caches
            _cf(self, dr, L, k, ctx, (clamp01, ease_o, ease_ow))
        # film grain (per-frame seeded; disabled in presets with grain_points=0)
        gp = int(P.get("grain_points", 90))
        if gp:
            rnd = random.Random(idx * 7919)
            for _ in range(gp):
                gx = rnd.randint(0, W - 1)
                gy = rnd.randint(0, H - 1)
                v = rnd.randint(200, 255)
                dr.point((gx, gy), fill=(v, v, v, rnd.randint(8, 30)))
        return img

    # ------------------------------------------------------------- transitions
    def compose_frame(self, idx):
        g = idx / self.FPS
        i = len(self.shots) - 1
        for k in range(len(self.shots)):
            if g < self.starts[k] + float(self.shots[k]["t"]):
                i = k
                break
        s = self.shots[i]
        lt = g - self.starts[i]
        # UI writes "transition"; legacy JSON used "trans" — honor both.
        # "cut"/"none" = hard instant switch: no fade window, no incoming-text
        # ghosting during the boundary frames (Yasser's round-3 complaint).
        kind = s.get("transition") or s.get("trans") or "fade"
        # NOTE: the label on shot i is honoured at BOTH boundaries around it by
        # design: cut_mode (hard cut) applies to this shot's render_layer calls,
        # while the transition block below uses shots[i+1]'s label for the
        # outgoing window. Do NOT zero XF based on shots[i-1] — that silently
        # kills the NEXT boundary's wipe/fade (verified by pixel-ownership probes).
        cut_mode = kind in ("cut", "none")
        XF = self.XF if not cut_mode else 0.0
        frame = self.render_layer(i, lt, idx, cut_mode=cut_mode)
        if i < len(self.shots) - 1 and XF > 0 and lt > float(s["t"]) - XF:
            p = (lt - (float(s["t"]) - XF)) / XF
            pe = ease_io(p)
            kind = self.shots[i + 1].get("transition") or self.shots[i + 1].get("trans") or "fade"
            # outgoing layer must be GONE by the time the wipe/blend lands:
            # fade its captions across the XF window (transition_out) so the
            # two shots' text never sit on screen together
            frame = self.render_layer(i, lt, idx, cut_mode=cut_mode, transition_out=XF)
            # ov-overlap fix: incoming layer runs its OWN clock through the wipe
            OV = float(self.shots[i + 1].get("ov", 0.25))
            nx = self.render_layer(i + 1, max(0.0, p * OV), idx + 90000)
            W, H = self.W, self.H
            if kind in ("slideL", "slideR"):
                off = int(W * pe)
                c = Image.new("RGB", (W, H), self.BG)
                if kind == "slideL":
                    c.paste(frame.transform((W, H), Image.AFFINE, (1, 0, -off, 0, 1, 0)), (0, 0))
                    c.paste(nx.transform((W, H), Image.AFFINE, (1, 0, W - off, 0, 1, 0)), (0, 0))
                else:
                    c.paste(frame.transform((W, H), Image.AFFINE, (1, 0, off, 0, 1, 0)), (0, 0))
                    c.paste(nx.transform((W, H), Image.AFFINE, (1, 0, -W + off, 0, 1, 0)), (0, 0))
                frame = c
            elif kind == "whip":
                b = int(20 * math.sin(math.pi * p))
                frame = Image.blend(frame, nx, pe)
                if b > 0:
                    frame = frame.filter(ImageFilter.GaussianBlur(b))
            elif kind == "flashdip":
                if p < 0.5:
                    frame = Image.blend(frame, Image.new("RGB", (W, H), self.BG), ease_io(p * 2) * 0.92)
                else:
                    q = ease_io((p - 0.5) * 2)
                    frame = Image.blend(Image.new("RGB", (W, H), self.BG), nx, q)
                    if p < 0.64:
                        d2 = ImageDraw.Draw(frame, "RGBA")
                        f = (0.64 - p) / 0.14
                        d2.rectangle((0, 0, W, H), fill=(self.ACCENT[0], self.ACCENT[1], self.ACCENT[2], int(85 * f)))
            elif kind == "wipe_left":
                # hard-edged directional wipe (the promo_v12 sample's choice):
                # incoming shot sweeps in from the LEFT edge rightwards
                off = int(W * pe)
                c = frame.copy()
                c.paste(nx.crop((0, 0, off, H)), (0, 0))
                frame = c
            elif kind == "wipe_up":
                off = int(H * pe)
                c = frame.copy()
                c.paste(nx.crop((0, H - off, W, H)), (0, H - off))
                frame = c
            else:  # fade
                frame = Image.blend(frame, nx, pe)
        return frame