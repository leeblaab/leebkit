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
from .layout import merge_layout
from . import metrics as M


def _font(engine, kind):
    return {"h1": engine.H1, "body": engine.BODY, "mono": engine.MONO,
            "mono_s": engine.MONOS, "small": engine.SMALL, "logo": engine.LOGO,
            "big": engine.BIG}.get(kind, engine.H1)


WARN_BUDGET = 3   # v1.5 item 11 gate half: max 'warn' flags per shot before
                  # the shot itself becomes an error flag (smoke gates errors)


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

        # v1.4 composition layer: per-shot layout overrides merged over the
        # preset defaults — checker budgets against the SAME geometry the
        # renderer draws with (renderer/checker agree by construction).
        LY = merge_layout(engine.L, s.get("layout"))
        _caps = s.get("captions", [])
        for ci, L in enumerate(_caps):
            k = L["kind"]
            at = float(L.get("at", 0.2))
            left = L.get("align") == "left"
            # v1.5 C9.1: per-caption place/y rides the SAME merge the draw
            # path uses (metrics.place_merge returns LY itself when absent ->
            # zero change for shipped projects). Checker budgets what the
            # renderer draws, agree-by-construction as always.
            cap_LY = M.place_merge(LY, L)
            avail_w = (engine.W - 2 * LY["left_inset"]) if left else None
            m = M.measure(engine, L, k, t, at, avail_w=avail_w, LY=cap_LY)   # same numbers as the draw path

            # --- v1.5 item 11 gate half: per-shot warn budget -----------------
            # A shot with more 'warn' flags than WARN_BUDGET is an error flag of
            # its own: the smoke suite gates errors, so a project that piles up
            # warnings can no longer sail through green (the advisor's "warn
            # walls" gap). Budget is deliberately >= shipped corpus max so every
            # existing golden/smoke project stays clean.
            if ci == len(_caps) - 1:
                shot_warns = [f for f in flags
                              if f.get("shot") == i and f.get("severity") == "warn"]
                if len(shot_warns) > WARN_BUDGET:
                    flags.append({"shot": i, "kind": "warn_budget", "severity": "error",
                                  "message": "shot %d carries %d warnings (budget %d)"
                                             % (i, len(shot_warns), WARN_BUDGET)})

            # --- v1.5: caption `colors` gate (list cap + palette names) ---
            if m.get("colors_error"):
                flags.append({"shot": i, "kind": "colors", "severity": "error",
                              "message": "shot %d %s: %s" % (i, k, m["colors_error"])})

            # --- v1.5 item 4: exit-motion gate (settle BEFORE exit starts) ---
            _xef = M.exit_flag(L, m.get("done_at"), t)
            if _xef:
                flags.append({"shot": i, "kind": "exit", "severity": "error",
                              "message": "shot %d %s: %s" % (i, k, _xef)})

            # --- v1.5 item 5: idle-motion gate (eligible kind + settles with
            # a real window inside the shot; renderer uses the SAME done_at) ---
            _idf = M.idle_flag(L, m.get("done_at"), t)
            if _idf:
                flags.append({"shot": i, "kind": "idle", "severity": "error",
                              "message": "shot %d %s: %s" % (i, k, _idf)})

            # --- v1.5 item 6: easing eligibility (kicker's stagger is LOCKED;
            # no clock change for the allowed kinds -> no settle re-gate) ---
            _ezf = M.ease_flag(L)
            if _ezf:
                flags.append({"shot": i, "kind": "ease", "severity": "error",
                              "message": "shot %d %s: %s" % (i, k, _ezf)})

            # --- v1.5 item 8: FX eligibility (fx needs an entrance kind with
            # a settle clock; renderer reads the SAME fx_flag rule) ---
            _fxf = M.fx_flag(L, m.get("done_at"))
            if _fxf:
                flags.append({"shot": i, "kind": "fx", "severity": "error",
                              "message": "shot %d %s: %s" % (i, k, _fxf)})

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
                # word) should ever flag overflow here. The plate spans the
                # frame at panel_x regardless of align; left-aligned text sits
                # inside it, so budget = plate width (panel_text_limit already
                # equals W - 2*panel_x*... derived in layout.py — stay there).
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
                elif k == "burst":
                    # burst draws at h1 * up to 1.0 scale (overshoot peaks at
                    # 1.0; measure at full size so the flag is conservative)
                    bf = engine._mkfont(engine.preset["fonts"]["display"],
                                        engine.L["h1"])
                    over(L.get("text", ""), bf, limit=W - 80)
                else:
                    lim = {"cta": LIM["cta_limit"], "big_number": W - 80}.get(k, W - 80)
                    over(L.get("text", ""), engine.H1 if k == "accent_word" else
                         (engine.BODY if k in ("cta", "handle") else engine.SMALL), limit=lim)
            elif k == "cap_lines":
                for wl in m["lines"]:
                    over(wl, engine.BODY, limit=(avail_w or LIM["panel_text_limit"]))
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
            elif k == "kicker":
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d kicker finishes at %.2fs > shot end %.2fs"
                                             % (i, m["done_at"], t)})
            elif k in ("typewriter", "pump", "flashpop", "maskline"):
                # v1.36 (Onyx draft): long-stagger kinds must settle inside the
                # shot; typewriter lines also need a width check (draw path is
                # center-fit but does NOT wrap — a too-long line clips).
                # v1.4 kinetic drafts: flashpop/maskline are word-stagger kinds
                # with the same contract.
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d %s finishes at %.2fs > shot end %.2fs"
                                             % (i, k, m["done_at"], t)})
                if k == "typewriter":
                    pieces, total = engine.tracked_pieces(
                        ImageDraw.Draw(Image.new("RGB", (8, 8))),
                        L.get("text", ""), engine.BODY, 3)
                    if total > W - 80:
                        flags.append({"shot": i, "kind": "overflow", "severity": "error",
                                      "message": "shot %d typewriter line %.0fpx > safe %.0fpx"
                                                 % (i, total, W - 80)})
            elif k in ("wipe", "split", "slam", "slam_v2", "trackin",
                       "rule_draw"):
                # v1.4 kinetic drafts: single-beat kinds — settle on their
                # metrics clock AND width gate at the draw font (h1; slam's
                # overscan start is measured like burst, conservatively).
                # v1.5 item 9: rule_draw joins the family (done_at = at +
                # POP_RAMP; its width is a fraction of safe_w by schema, so
                # no text-overflow gate applies — w bounds gated in metrics).
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d %s finishes at %.2fs > shot end %.2fs"
                                             % (i, k, m["done_at"], t)})
                if k == "wipe":
                    for wl in engine.wrap_words(
                            ImageDraw.Draw(Image.new("RGB", (8, 8))),
                            L.get("text", "").split(" "), engine.H1,
                            engine.L["safe_w"]):
                        over(wl, engine.H1, limit=engine.L["safe_w"], label="wipe line")
                elif k == "trackin":
                    # tracking at t=0 widens the lockup: check the WIDE state
                    trk = int(engine.L["h1"] * 0.35)
                    over(L.get("text", ""), engine.H1,
                         limit=W - 80 - trk * max(0, len(L.get("text", "")) - 1),
                         label="trackin")
                elif k == "split":
                    over(L.get("text", ""), engine.H1, limit=W - 80)
                else:  # slam: rest size must fit; overscan start is transient
                    bf = engine._mkfont(engine.preset["fonts"]["display"],
                                        int(engine.L["h1"] * M.SLAM_FROM))
                    over(L.get("text", ""), bf, limit=W - 40, label="slam")
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
            elif k == "title_block":
                # C7: title elements settle on the shared TITLE_PLATE_K clock;
                # gate like panels/chips so a late `at` never leaves the
                # underline still growing at the cut.
                if m["done_at"] > t - 0.1:
                    flags.append({"shot": i, "kind": "timing", "severity": "error",
                                  "message": "shot %d title elements finish at %.2fs > shot end %.2fs" % (i, m["done_at"], t)})

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
