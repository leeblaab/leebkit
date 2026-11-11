"""LEEBKIT core — storyboard checks (the four auto-red-flags) + thumbnails.

Implemented as CODE, not eyeballs (pixel-mask QA beats vision-QA per spec):
  1. text overflow      — PIL getlength vs safe width at chosen font/size
  2. animation won't finish — timing math: every caption's settle time
     must land before shot end (word-stagger formula checked numerically)
  3. empty image slot   — shot references an image that doesn't resolve
  4. VO longer than shot — generated line duration vs its shot window

v1.3 C4: all layout/timing math comes from core/metrics.measure() — the same
numbers captions.py computes at draw time. Renderer and checker agree by
construction; this file must never re-derive formulas (that drift bit us twice).
"""
import os

from PIL import Image, ImageDraw, ImageFont

from .engine import FONTS_DIR, Engine, clamp01
from . import metrics as M


def _font(engine, kind):
    return {"h1": engine.H1, "body": engine.BODY, "mono": engine.MONO,
            "mono_s": engine.MONOS, "small": engine.SMALL, "logo": engine.LOGO,
            "big": engine.BIG}.get(kind, engine.H1)


def check_project(engine):
    """Returns list of flags: {shot, kind, message, severity}."""
    flags = []
    W = engine.W
    safe_w = engine.L["safe_w"]   # aspect-aware (core/layout.py)
    starts = engine.starts

    for i, s in enumerate(engine.shots):
        t = float(s["t"])
        fill = s.get("fill") or ("image" if s.get("image") else "solid")

        # --- flag 3: empty image slot ---
        if fill == "image":
            f = s.get("image")
            if not f or f not in engine.bases:
                flags.append({"shot": i, "kind": "empty_slot", "severity": "error",
                              "message": "shot %d has no image (slot empty or file missing)" % i})

        for L in s.get("captions", []):
            k = L["kind"]
            at = float(L.get("at", 0.2))
            m = M.measure(engine, L, k, t, at)   # same numbers as the draw path

            # --- flag 1: text overflow (PIL measured) ---
            def over(txt, fnt, limit=safe_w, label=None):
                w = fnt.getlength(txt)
                if w > limit:
                    flags.append({"shot": i, "kind": "overflow", "severity": "error",
                                  "message": "shot %d %s: '%s' measures %.0fpx > safe %.0fpx"
                                             % (i, label or k, txt[:38], w, limit)})
            LIM = engine.L   # aspect-aware safe widths (core/layout.py)
            if k in ("panel_top", "panel_mid"):
                # measure the WRAPPED result from metrics: the engine auto-wraps
                # long lines, so only genuinely unbreakable input (one monster
                # word) should ever flag overflow here
                for wl in m["lines"]:
                    over(wl, engine.H1, limit=LIM["panel_text_limit"])
            elif k == "title_block":
                # wrap-aware measured check via metrics: flag each line that
                # STILL overflows
                f_t = engine.LOGO if m["tsize"] == engine.L["logo"] else \
                    engine._mkfont(engine.preset["fonts"]["display"], m["tsize"])
                for tl in m["lines"]:
                    over(tl, f_t, limit=W - m["trk"] * max(0, len(tl) - 1), label="title")
                if L.get("sub"):
                    # wrap-aware: the engine auto-wraps subs (fit_small_lines),
                    # so flag only lines that STILL overflow after wrapping
                    for sl in m.get("sub_lines", []):
                        over(sl, engine.SMALL, limit=LIM["title_limit"], label="subtitle")
            elif k in ("accent_word", "cta", "small", "handle", "big_number"):
                if k == "small":
                    # engine wraps the note inside its chip, so only a single
                    # monster word can actually overflow (longest via metrics)
                    over(m["longest_word"], engine.SMALL, limit=LIM["small_chip_limit"])
                else:
                    lim = {"cta": LIM["cta_limit"], "big_number": W - 80}.get(k, W - 80)
                    over(L.get("text", ""), engine.H1 if k == "accent_word" else
                         (engine.BODY if k in ("cta", "handle") else engine.SMALL), limit=lim)
            elif k == "cap_lines":
                for wl in m["lines"]:
                    over(wl, engine.BODY, limit=LIM["panel_text_limit"])
            elif k == "chips":
                if m["total"] > LIM["chips_total_limit"]:
                    flags.append({"shot": i, "kind": "overflow", "severity": "error",
                                  "message": "shot %d chips row %.0fpx > safe %.0fpx"
                                             % (i, m["total"], LIM["chips_total_limit"])})
            elif k == "terminal":
                # audit #9: renderer uses MONO for rows 0-1 and MONOS below
                # (captions.draw_terminal) — checker measured every row with
                # MONO, so small-font rows were under-flagged.
                for r, rline in enumerate(L.get("rows", [])):
                    fnt = engine.MONO if r < 2 else engine.MONOS
                    if rline.strip() and fnt.getlength(rline) > LIM["term_line_limit"]:
                        flags.append({"shot": i, "kind": "overflow", "severity": "warn",
                                      "message": "shot %d terminal line '%s' clips (engine truncates it)"
                                                 % (i, rline[:38])})

            # --- flag 2: animation won't finish before shot end ---
            if k in ("panel_top", "panel_mid"):
                # timing runs on metrics' wrapped lines + settle clock. The old
                # dead branch also matched literal kind "mid"; no schema or
                # sample uses it (audit confirmed) — dropped.
                if m["span"] > 1.0:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d panel line too many words (stagger window %.2fs > 1s)"
                                             % (i, m["span"])})
                if m["done_at"] > t - 0.15:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d panel words finish at %.2fs but shot ends at %.2fs"
                                             % (i, m["done_at"], t)})
            elif k == "cap_lines":
                # timing runs on WRAPPED lines via metrics (audit B#3)
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d cap lines finish at %.2fs > shot end %.2fs" % (i, m["done_at"], t)})
            elif k == "terminal":
                if m["rows_done"] > t or m["typing_done"] < 0.8:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d terminal needs %.2fs but shot is only %.2fs"
                                             % (i, max(m["rows_done"], 1.5), t)})
            elif k == "chips":
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d chips finish at %.2fs > shot end %.2fs" % (i, m["done_at"], t)})

    # --- flag 4: VO longer than its shot window ---
    voice = engine.proj.get("voice", "none")
    if voice and voice != "none":
        from . import audio as A
        scratch = os.path.join(os.path.dirname(__file__), "..", "output", "_vocheck")
        for L in engine.proj.get("vo_lines", []):
            if not L.get("text"):
                continue
            try:
                dur, _ = A.vo_duration(L["text"], voice, scratch,
                                       speed=float(engine.proj.get("voice_speed", 1.0)))
            except Exception as e:
                flags.append({"shot": L.get("shot", -1), "kind": "vo", "severity": "error",
                              "message": "VO gen failed: %s" % e})
                continue
            if "shot" in L:
                si = int(L["shot"])
                window = float(engine.shots[si]["t"]) - float(L.get("offset", 0.0))
            else:
                # absolute placement: must fit inside the timeline tail
                si = -1
                window = float(engine.DUR) - float(L["at"])
            if dur > window + 0.05:
                flags.append({"shot": si, "kind": "vo", "severity": "error",
                              "message": "VO '%s' is %.2fs but its shot window leaves only %.2fs"
                                         % (L["text"][:38], dur, window)})
    return flags


def storyboard_strip(engine, out_path, max_w=1080, thumb_h=None):
    """One thumbnail per shot (mid-late in the shot = animation settled).
    Returns list of flag dicts; writes a single strip PNG."""
    flags = check_project(engine)
    n = len(engine.shots)
    tw = max_w // n if n <= 5 else 216
    th = int(tw * engine.H / engine.W)
    strip = Image.new("RGB", (tw * n, th + 4), (10, 10, 14))
    dr = ImageDraw.Draw(strip)
    fnt = ImageFont.truetype(os.path.join(FONTS_DIR, "JetBrainsMono-var.ttf"), max(12, tw // 16))
    try:
        fnt.set_variation_by_name("Bold")
    except Exception:
        pass
    flag_by_shot = {}
    for f in flags:
        flag_by_shot.setdefault(f["shot"], []).append(f)

    for i, s in enumerate(engine.shots):
        lt = float(s["t"]) * 0.75          # settled moment
        img = engine.render_layer(i, lt, i * 1234 + 7)
        img = img.resize((tw, th), Image.LANCZOS)
        strip.paste(img, (i * tw, 0))
        fl = flag_by_shot.get(i, [])
        if fl:
            dr.rectangle((i * tw, 0, i * tw + tw, th), outline=(255, 60, 60), width=3)
            label = "!" + fl[0]["kind"]
            dr.text((i * tw + 6, th - 20), label, font=fnt, fill=(255, 80, 80))
        else:
            dr.rectangle((i * tw, 0, i * tw + tw, th), outline=(0, 229, 255), width=2)
    strip.save(out_path)
    return flags
