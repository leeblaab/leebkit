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


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
FONTS_DIR = os.path.join(ASSETS, "fonts")

BG_DEFAULT = (10, 10, 14)


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
    w = int(proj.get("width", 1080))
    h = int(proj.get("height", 1920))
    if not (320 <= w <= 3840 and 320 <= h <= 3840):
        raise ValueError("width/height must be 320-3840 (got %dx%d)" % (w, h))
    fps = int(proj.get("fps", 30))
    if fps not in (24, 30):
        raise ValueError("fps must be 24 or 30 (got %d)" % fps)
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
        for c in s.get("captions", []):
            if "kind" not in c:
                raise ValueError("shot %d caption missing kind" % i)
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
            raise SystemExit("[LEEBKIT] ERROR: shot image(s) not found or outside media "
                             "dir (render aborted, no black frames): %s"
                             % ", ".join(sorted(set(self.bad_images))))

        self._grid = None
        self._collage = None
        self._grad_cache = {}

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
        for root, _, files in os.walk(d):
            if any(seg in root for seg in ("output", "frames", ".git")):
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
        last resort. Returns (lines, size, tracking)."""
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
        return lines, size, trk

    def wrap_words(self, dr, words, fnt, limit, tracking=0):
        """Greedy word-wrap: group `words` so each line measures <= limit px.
        A single over-long word stays on its own line (checks.py flags it)."""
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
        return lines

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

    def draw_title_lines(self, dr, y_center, lines, fnt, fill, tracking, line_h):
        ys = [y_center - (len(lines) - 1) * line_h / 2 + j * line_h for j in range(len(lines))]
        for y, l in zip(ys, lines):
            self.draw_center_text(dr, y, l, fnt, fill, tracking=tracking)
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

        if base is not None:
            z = self.track(g)
            px, py = self.CAM.get(s.get("cam"), (0, 0))
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
        TRK = P.get("tracking", {})

        for L in s.get("captions", []):
            k = L["kind"]
            at = float(L.get("at", 0.2))
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
            # panel_* kinds are the shot's message itself (fill=solid frames):
            # run their clock 0.45s early so a black beat never holds with an
            # empty card (Yasser's sheet9 QA: dead gaps before word-pop lines).
            if k in ("panel_top", "panel_mid"):
                at -= 0.45
            if transition_out:
                # re-apply the freeze to the shifted clock too
                prog = min(prog, clamp01((float(s["t"]) - at) / 0.32))
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

            if k == "title_block":
                txt = L.get("text", "")
                # auto-wrap to the safe width (shrink only as last resort) so a
                # long title can never run past the frame edge
                lines, tsize, trk = self.fit_title(dr, txt, LY["logo"], LY["title_limit"])
                tfnt = self.LOGO if tsize == LY["logo"] else \
                    self._mkfont(self.preset["fonts"]["display"], tsize)
                line_h = int(tsize * LY["title_line_h_k"])
                nlines = max(1, len(lines))
                # underline + subtitle ride below the last title line
                base_y = H * LY["title_frac"] - (nlines - 1) * line_h / 2
                self.draw_title_lines(dr, base_y - slide, lines, tfnt,
                                      (WHITE[0], WHITE[1], WHITE[2], a), trk, line_h)
                lw = int(min(LY["ul_max"], max(LY["ul_min"], tsize * 4)) * ease_o(prog))
                ul_y = H * LY["title_frac"] + (nlines - 1) * line_h / 2 + int(tsize * LY["ul_gap_k"])
                dr.rectangle(((W - lw) / 2, ul_y - slide, (W + lw) / 2, ul_y + LY["ul_h"] - slide),
                             fill=(ACCENT[0], ACCENT[1], ACCENT[2], a))
                sub = L.get("sub", "")
                if sub:
                    # auto-wrap long subs to the safe text width so a single
                    # over-long line can never clip at the frame edge, then
                    # translucent dark plate(s) behind each wrapped line
                    sub_lines = self.fit_small_lines(dr, sub, self.SMALL, TRK.get("sub", 0))
                    sy = ul_y + int(tsize * 0.42) + LY["sub_gap"] - slide
                    pad = LY["sub_pad"]
                    line_h_s = int(self.SIZES["small"] * 1.35)
                    plate_a = int(150 * min(1.0, prog * 1.3))
                    for li, sl in enumerate(sub_lines):
                        ly_ = sy + li * line_h_s
                        sw = self._measure_tracked(dr, sl, self.SMALL, TRK.get("sub", 0))
                        dr.rounded_rectangle(((W - sw) / 2 - pad, ly_ - pad,
                                              (W + sw) / 2 + pad, ly_ + LY["small"] + pad),
                                             radius=LY["sub_radius"], fill=(0, 0, 0, plate_a))
                        self.draw_center_text(dr, ly_, sl, self.SMALL,
                                              (DIMC[0], DIMC[1], DIMC[2], a), tracking=TRK.get("sub", 14))
            elif k == "accent_word":
                self.word_pop(dr, H * LY["accent_frac"] - slide, self.H1, L["text"], ACCENT, prog, tracking=2, alpha_cap=a_gate)
            elif k in ("panel_top", "panel_mid"):
                # auto-wrap user lines to the safe text width, then grow the
                # panel box to fit the wrapped line count (Yasser's shot-3 clip)
                lines = self.fit_panel_lines(dr, L["lines"], self.H1)
                n = len(lines)
                ph = LY["line_h_panel"] * n + LY["panel_extra_h"]
                py = H * (LY["panel_top_frac"] if k == "panel_top" else LY["panel_mid_frac"])
                pa = clamp01(prog / 0.5)
                box_a = int(P.get("panel_alpha", 224) * ease_o(pa))
                if a_gate is not None:
                    box_a = min(box_a, a_gate)
                dr.rounded_rectangle((LY["panel_x"], py - slide, W - LY["panel_x"], py + ph - slide), radius=26,
                                     fill=(self.PANEL[0], self.PANEL[1], self.PANEL[2], box_a))
                wprog = clamp01((lt - at - 0.28) / 0.95)
                nw = [len(l.split(" ")) for l in lines]
                span = max(nw) * 0.18 + 0.36          # word_pop internal stagger window
                Sv = (1.0 - span) / (n - 1) if n > 1 else 0.0   # line offsets (completion formula)
                for j, line in enumerate(lines):
                    col = ACCENT if (j == n - 1 and (line.endswith(".") or k == "panel_mid")) else WHITE
                    self.word_pop(dr, py + LY["panel_pad_y"] + j * LY["line_h_panel"] - slide,
                                  self.H1, line, col,
                                  wprog * (span / 0.55) - j * Sv, tracking=2, alpha_cap=a_gate)
            elif k == "small":
                # box rect was miscomputed: x+w+30 (not w+60 -> could invert and
                # crash rounded_rectangle), and long notes wrap inside a capped
                # chip instead of running off-frame
                txt = L["text"]
                sl_lines = self.wrap_words(dr, txt.split(" "), self.SMALL, LY["small_chip_limit"]) or [""]
                w = max(dr.textlength(l, font=self.SMALL) for l in sl_lines)
                x = (W - w) / 2
                bh = LY["small_chip_h"] + (len(sl_lines) - 1) * LY["small_line_h"]
                chip_a = int(195 * ease_o(prog))
                if a_gate is not None:
                    chip_a = min(chip_a, a_gate)
                dr.rounded_rectangle((x - LY["small_pad_x"], H * LY["small_frac"] - slide,
                                      x + w + LY["small_pad_x"], H * LY["small_frac"] + bh - slide),
                                     radius=16, fill=(self.PANEL[0], self.PANEL[1], self.PANEL[2],
                                                      chip_a))
                for j, l in enumerate(sl_lines):
                    self.draw_center_text(dr, H * LY["small_frac"] + j * LY["small_line_h"] - slide, l, self.SMALL,
                                          (WHITE[0], WHITE[1], WHITE[2], a))
            elif k == "cta":
                txt = L["text"]
                w = dr.textlength(txt, font=self.BODY)
                x = (W - w) / 2
                y = H * LY["cta_frac"] - slide
                pad = LY["cta_pad"]
                # clamp the outline box to the frame so a long CTA can never
                # draw past the edge (checks.py flags the overflow instead)
                dr.rounded_rectangle((max(LY["cta_edge"], x - pad), y + LY["cta_top_off"],
                                      min(W - LY["cta_edge"], x + w + pad), y + LY["cta_bot_off"]),
                                     radius=18,
                                     outline=(ACCENT[0], ACCENT[1], ACCENT[2], a), width=4)
                dr.text((x, y), txt, font=self.BODY, fill=(WHITE[0], WHITE[1], WHITE[2], a))
            elif k == "handle":
                self.draw_center_text(dr, H * LY["handle_frac"] - slide, L["text"], self.BODY,
                                      (ACCENT[0], ACCENT[1], ACCENT[2], a), tracking=4)
            elif k == "big_number":
                txt = L["text"]
                w = dr.textlength(txt, font=self.BIG)
                e = ease_ow(prog)
                bn_a = int(255 * e)
                if a_gate is not None:
                    bn_a = min(bn_a, a_gate)
                dr.text(((W - w) / 2, H * LY["bignum_frac"] + (1 - e) * 50 - slide), txt, font=self.BIG,
                        fill=(ACCENT[0], ACCENT[1], ACCENT[2], bn_a))
            elif k == "cap_lines":
                wp = clamp01((lt - at) / 0.3)
                if transition_out:
                    wp = min(wp, clamp01((float(s["t"]) - at) / 0.3))
                for j, line in enumerate(L["lines"]):
                    self.word_pop(dr, H * LY["caplines_frac"] + j * LY["capline_h"] - slide, self.BODY, line, WHITE,
                                  wp - j * 0.45, tracking=3, alpha_cap=a_gate)
            elif k == "terminal":
                box_h = LY["term_box_h"]
                y0 = H * LY["term_y_frac"]
                ta = int(P.get("term_alpha", 238) * ease_o(prog))
                if a_gate is not None:
                    ta = min(ta, a_gate)
                dr.rounded_rectangle((LY["term_x"], y0 - slide, W - LY["term_x"], y0 + box_h - slide), radius=26,
                                     fill=(10, 12, 16, ta))
                dr.rounded_rectangle((LY["term_x"], y0 - slide, W - LY["term_x"], y0 + LY["term_head_h"] - slide), radius=26,
                                     fill=(24, 28, 34, ta))
                for d_, cc in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
                    dr.ellipse((LY["term_dot0"] + d_ * LY["term_dot_step"], y0 + LY["term_dot_y"] - slide,
                                LY["term_dot0"] + (d_ + 1) * LY["term_dot_step"], y0 + LY["term_dot_y"] + LY["term_dot_step"] - slide),
                               fill=(cc[0], cc[1], cc[2], a))
                # typing runs until ~1s before shot end; bar animates mid-shot: no freeze
                rows = L.get("rows", ["> PROMPT", "", "> RENDERING...", "░░░░░░░░░░░░  0%"])
                prompt_txt = rows[1] if len(rows) > 1 else ""
                type_end = float(s["t"]) - 1.0
                prog_t = clamp01((lt - 0.5) / max(0.3, type_end - 0.5))
                typed = prompt_txt[: int(len(prompt_txt) * prog_t)]
                cursor = "_" if int(g * 2.4) % 2 == 0 else " "
                # progress bar is FULLY automatic: any row that starts with the
                # block glyphs (or a bare percent like "0%") gets replaced by the
                # live █░ bar + percent — the user never types a static value.
                # Fill window scales with shot length: starts 1/3 in, ends 0.5s
                # before shot end (so it lands exactly at 100%).
                t_shot = float(s["t"])
                b_start = t_shot / 3.0
                bt = clamp01((lt - b_start) / max(0.5, t_shot - b_start - 0.5))
                bar = int(12 * bt)
                pct = int(100 * bt)

                def _bar_row(x):
                    xs = x.strip()
                    return bool(xs) and (xs[0] in "█░" or (xs.endswith("%") and len(xs) <= 6))
                shown = [rows[0], typed + cursor]
                for extra in rows[2:]:
                    if _bar_row(extra):
                        shown.append("  " + "█" * bar + "░" * (12 - bar) + "  " + str(pct) + "%")
                    else:
                        shown.append(extra)
                yy = y0 + LY["term_rows_y"]
                for r, line in enumerate(shown):
                    appear = clamp01((lt - 0.4 - r * 0.5) / 0.3)
                    if transition_out:
                        appear = min(appear, clamp01((float(s["t"]) - 0.4 - r * 0.5) / 0.3))
                    if appear <= 0:
                        break
                    colr = ACCENT if line.startswith(">") else (205, 210, 220)
                    if "%" in line and pct > 0:
                        colr = ACCENT
                    fnt = self.MONO if r < 2 else self.MONOS
                    # typed mono lines must fit measured width or they clip at panel edge
                    maxw = LY["term_line_limit"]
                    while fnt.getlength(line) > maxw and len(line) > 1:
                        line = line[:-1]
                    row_a = int(255 * appear)
                    if a_gate is not None:
                        row_a = min(row_a, a_gate)
                    dr.text((LY["term_row_x"], yy - slide), line, font=fnt,
                            fill=(colr[0], colr[1], colr[2], row_a))
                    yy += LY["term_line_h_a"] if r < 2 else LY["term_line_h_b"]
            elif k == "chips":
                chips = L["items"]
                widths = [dr.textlength(c, font=self.MONOS) + LY["chip_extra_w"] for c in chips]
                gap = LY["chip_gap"]
                total = sum(widths) + gap * (len(chips) - 1)
                x = (W - total) / 2
                y = H * LY["chips_frac"]
                for ci, c in enumerate(chips):
                    appear = clamp01((lt - at - ci * 0.35) / 0.4)
                    if transition_out:
                        # freeze stagger clock at shot end, then let a_gate fade it
                        appear = min(appear, clamp01((float(s["t"]) - at - ci * 0.35) / 0.4))
                    if appear <= 0:
                        break
                    aa = int(255 * ease_o(appear))
                    if a_gate is not None:
                        aa = min(aa, a_gate)
                    sl = int((1 - ease_o(appear)) * 30)
                    dr.rounded_rectangle((x, y + sl, x + widths[ci], y + LY["chip_h"] + sl),
                                         radius=LY["chip_h"] // 2,
                                         fill=(10, 12, 16, aa),
                                         outline=(ACCENT[0], ACCENT[1], ACCENT[2], aa), width=3)
                    dr.text((x + LY["chip_text_dx"], y + LY["chip_text_y"] + sl), c, font=self.MONOS,
                            fill=(WHITE[0], WHITE[1], WHITE[2], aa))
                    x += widths[ci] + gap

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
            else:  # fade
                frame = Image.blend(frame, nx, pe)
        return frame
