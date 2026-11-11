"""core/captions.py — per-kind caption drawing (v1.3 C3a).

The if/elif kind chain that lived in Engine.render_layer is moved HERE as
one function per kind: same statements, same order, zero logic change
(golden-frame harness proves pixel identity before this commit lands).

Engine passes explicit groups instead of leaking itself into a god-ctx:

  eng  -> the Engine; kinds call its shared layout helpers (fit_title,
          word_pop, draw_center_text, ...), which STAY on Engine in C3a.
          C3b relocates fit/wrap math into per-kind measure() with an
          Engine-level metrics cache.
  dr   -> ImageDraw on the frame
  L    -> the caption dict
  k    -> kind name (panel_top/panel_mid share one function)
  ctx  -> FrameCtx: scalars + clocks the old chain read from locals
  e    -> (clamp01, ease_o, ease_ow) easing tuple from engine module

No import of core.engine here (engine imports captions lazily inside
render_layer to avoid a cycle)."""

from collections import namedtuple
import math

from PIL import Image, ImageDraw

from . import metrics as M   # stagger-clock constants: draw and checks share one source

# every scalar the old chain read from render_layer locals, in one explicit
# group — style + frame clocks, not a god-ctx of Engine state.
FrameCtx = namedtuple("FrameCtx", [
    "W", "H",              # output frame size
    "LY",                  # layout dict (Engine.L)
    "P",                   # merged preset dict
    "TRK",                 # preset tracking dict
    "WHITE", "ACCENT", "DIMC",   # colors (PANEL stays on eng: panel/small read it there)
    "PAL",                   # v1.36: preset color-name -> rgb dict for per-caption
                             # "colors" overrides (empty dict = palette not used)
    "lt", "at",            # shot-local time, caption start (post-preamble shift)
    "g",                   # global time (terminal cursor blink)
    "shot_t",              # float(shot["t"])
    "prog",                # gated caption progress 0..1
    "a",                   # gated alpha 0..255
    "slide",               # eased slide offset px
    "a_gate",              # outgoing-transition alpha cap or None
    "transition_out",      # XF window length or None (stagger-freeze input)
    "cap_idx",             # (shot_idx, caption_idx): C3b per-caption cache slot
])


def _wrap(eng, dr, words, fnt, limit, tracking=0, ctx=None):
    """C3b: fit/wrap call routed through the Engine metrics cache. The result
    depends only on (words, font, limit, tracking) — never on time or draw
    state — so within one Engine build it is computed ONCE per caption slot
    and reused for every frame.

    Slot key includes the words tuple: if two projects share an Engine
    instance with different text at the same (shot, caption) index, the first
    call's cache would otherwise serve the second project stale lines."""
    if ctx is None:
        return eng.wrap_words(dr, words, fnt, limit, tracking=tracking)
    ck = ("wrap", ctx.cap_idx, tuple(words), id(fnt), limit, tracking)
    hit = eng._metrics_cache.get(ck)
    if hit is None:
        hit = eng.wrap_words(dr, words, fnt, limit, tracking=tracking)
        eng._metrics_cache[ck] = hit
    return list(hit)   # copy so callers never mutate the cache


def _draw_tinted_line(eng, dr, y_center, words, fills, fnt, tracking):
    """v1.36 (Onyx draft): draw one title line word-by-word with per-word RGBA
    fills, mirroring draw_center_text's tracked layout math exactly (per-char
    advances + tracking) so tinted lines sit pixel-identical to white ones."""
    W = eng.W
    wsp = dr.textlength(" ", font=fnt)
    pieces = []   # (char_or_space, advance)
    for wi, w in enumerate(words):
        for c in w:
            pieces.append((c, dr.textlength(c, font=fnt), fills[wi]))
        if wi < len(words) - 1:
            pieces.append((" ", wsp, None))
    total = sum(a + tracking for (c, a, f) in pieces) - tracking
    x = (W - total) / 2
    for c, adv, fill in pieces:
        if fill is not None:
            dr.text((x, y_center), c, font=fnt, fill=fill)
        x += adv + tracking


def draw_title_block(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W = ctx.H, ctx.W
    LY, TRK = ctx.LY, ctx.TRK
    WHITE, ACCENT, DIMC, a, prog, slide = (ctx.WHITE, ctx.ACCENT, ctx.DIMC,
                                           ctx.a, ctx.prog, ctx.slide)
    txt = L.get("text", "")
    # v1.36 (Onyx draft): optional per-word colors on the title itself —
    # only active when the caption declares "colors"; every shipped project
    # omits it and keeps the single WHITE fill byte-for-byte.
    tnames = L.get("colors")
    tfills = None
    if tnames:
        cols = [ctx.PAL.get(n, WHITE) for n in tnames]
        tfills = [cols[j % len(cols)] for j in range(len(txt.split()))]
    # C7: ONE element clock for the whole block — settle gain TITLE_PLATE_K +
    # back-out rise (ease_ow, same overshoot curve word_pop uses; external
    # typography review). Glyphs, underline and sub plate lift together.
    ep = clamp01(prog * M.TITLE_PLATE_K)
    rise = (1 - ease_ow(ep)) * LY["title_rise"]
    # auto-wrap to the safe width (shrink only as last resort) so a
    # long title can never run past the frame edge
    lines, tsize, trk = eng.fit_title(dr, txt, LY["logo"], LY["title_limit"])
    tfnt = eng.LOGO if tsize == LY["logo"] else \
        eng._mkfont(eng.preset["fonts"]["display"], tsize)
    line_h = int(tsize * LY["title_line_h_k"])
    nlines = max(1, len(lines))
    # underline + subtitle ride below the last title line
    base_y = H * LY["title_frac"] - (nlines - 1) * line_h / 2
    if tfills is None:
        eng.draw_title_lines(dr, base_y - slide, lines, tfnt,
                             (WHITE[0], WHITE[1], WHITE[2], a), trk, line_h, rise=rise)
    else:
        # per-word fill: word index continues across wrapped lines so the
        # white/pink alternation follows the READING order of the title
        woff = 0
        ys = [base_y - slide + (j - (nlines - 1) / 2) * line_h - rise
              for j in range(nlines)]
        for y, ln in zip(ys, lines):
            words = ln.split()
            fills = [(tfills[woff + j][0], tfills[woff + j][1], tfills[woff + j][2], a)
                     for j in range(len(words))]
            woff += len(words)
            _draw_tinted_line(eng, dr, y, words, fills, tfnt, trk)
    lw = int(min(LY["ul_max"], max(LY["ul_min"], tsize * 4))
             * ease_o(ep))   # C7: shared settle clock
    ul_y = H * LY["title_frac"] + (nlines - 1) * line_h / 2 + int(tsize * LY["ul_gap_k"])
    dr.rectangle(((W - lw) / 2, ul_y - slide, (W + lw) / 2, ul_y + LY["ul_h"] - slide),
                 fill=(ACCENT[0], ACCENT[1], ACCENT[2], a))
    sub = L.get("sub", "")
    if sub:
        # auto-wrap long subs to the safe text width so a single
        # over-long line can never clip at the frame edge, then
        # translucent dark plate(s) behind each wrapped line
        sub_lines = _wrap(eng, dr, sub.split(" "), eng.SMALL,
                          eng.W - 160 - 2 * LY["sub_pad"],
                          tracking=TRK.get("sub", 0), ctx=ctx)
        sy = ul_y + int(tsize * 0.42) + LY["sub_gap"] - slide - rise   # C7: rides the same lift
        pad = LY["sub_pad"]
        line_h_s = int(eng.SIZES["small"] * 1.35)
        plate_a = int(150 * min(1.0, prog * M.TITLE_PLATE_K))   # C7: metrics constant replaces private 1.3
        for li, sl in enumerate(sub_lines):
            ly_ = sy + li * line_h_s
            sw = eng._measure_tracked(dr, sl, eng.SMALL, TRK.get("sub", 0))
            dr.rounded_rectangle(((W - sw) / 2 - pad, ly_ - pad,
                                  (W + sw) / 2 + pad, ly_ + LY["small"] + pad),
                                 radius=LY["sub_radius"], fill=(0, 0, 0, plate_a))
            eng.draw_center_text(dr, ly_, sl, eng.SMALL,
                                 (DIMC[0], DIMC[1], DIMC[2], a), tracking=TRK.get("sub", 14))


def draw_accent_word(eng, dr, L, k, ctx, e):
    H, LY, ACCENT, prog, slide = ctx.H, ctx.LY, ctx.ACCENT, ctx.prog, ctx.slide
    eng.word_pop(dr, H * LY["accent_frac"] - slide, eng.H1, L["text"], ACCENT,
                 prog, tracking=2, alpha_cap=ctx.a_gate)


def draw_panel(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, P = ctx.H, ctx.W, ctx.LY, ctx.P
    WHITE, ACCENT, prog, slide, lt, at, a_gate = (ctx.WHITE, ctx.ACCENT, ctx.prog,
                                                  ctx.slide, ctx.lt, ctx.at, ctx.a_gate)
    # auto-wrap user lines to the safe text width, then grow the
    # panel box to fit the wrapped line count (Yasser's shot-3 clip)
    lines = _wrap_panel(eng, dr, L["lines"], eng.H1, ctx)
    n = len(lines)
    ph = LY["line_h_panel"] * n + LY["panel_extra_h"]
    py = H * (LY["panel_top_frac"] if k == "panel_top" else LY["panel_mid_frac"])
    pa = clamp01(prog / 0.5)
    box_a = int(P.get("panel_alpha", 224) * ease_o(pa))
    if a_gate is not None:
        box_a = min(box_a, a_gate)
    dr.rounded_rectangle((LY["panel_x"], py - slide, W - LY["panel_x"], py + ph - slide), radius=26,
                         fill=(eng.PANEL[0], eng.PANEL[1], eng.PANEL[2], box_a))
    wprog = clamp01((lt - at - M.PANEL_WDELAY) / M.PANEL_WRAMP)
    nw = [len(l.split(" ")) for l in lines]
    span = max(nw) * M.WORD_STEP + M.WORD_RAMP   # word_pop internal stagger window
    Sv = (1.0 - span) / (n - 1) if n > 1 else 0.0   # line offsets (completion formula)
    for j, line in enumerate(lines):
        col = ACCENT if (j == n - 1 and (line.endswith(".") or k == "panel_mid")) else WHITE
        eng.word_pop(dr, py + LY["panel_pad_y"] + j * LY["line_h_panel"] - slide,
                     eng.H1, line, col,
                     wprog * (span / 0.55) - j * Sv, tracking=2, alpha_cap=a_gate)


def draw_small(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY = ctx.H, ctx.W, ctx.LY
    WHITE, prog, slide, a = ctx.WHITE, ctx.prog, ctx.slide, ctx.a
    # box rect was miscomputed: x+w+30 (not w+60 -> could invert and
    # crash rounded_rectangle), and long notes wrap inside a capped
    # chip instead of running off-frame
    txt = L["text"]
    sl_lines = _wrap(eng, dr, txt.split(" "), eng.SMALL, LY["small_chip_limit"], ctx=ctx) or [""]
    w = max(dr.textlength(l, font=eng.SMALL) for l in sl_lines)
    x = (W - w) / 2
    bh = LY["small_chip_h"] + (len(sl_lines) - 1) * LY["small_line_h"]
    chip_a = int(195 * ease_o(prog))
    if ctx.a_gate is not None:
        chip_a = min(chip_a, ctx.a_gate)
    dr.rounded_rectangle((x - LY["small_pad_x"], H * LY["small_frac"] - slide,
                          x + w + LY["small_pad_x"], H * LY["small_frac"] + bh - slide),
                         radius=16, fill=(eng.PANEL[0], eng.PANEL[1], eng.PANEL[2],
                                          chip_a))
    for j, l in enumerate(sl_lines):
        eng.draw_center_text(dr, H * LY["small_frac"] + j * LY["small_line_h"] - slide, l, eng.SMALL,
                             (WHITE[0], WHITE[1], WHITE[2], a))


def draw_cta(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, a, slide = ctx.H, ctx.W, ctx.LY, ctx.a, ctx.slide
    ACCENT, WHITE = ctx.ACCENT, ctx.WHITE
    txt = L["text"]
    w = dr.textlength(txt, font=eng.BODY)
    x = (W - w) / 2
    y = H * LY["cta_frac"] - slide
    pad = LY["cta_pad"]
    # clamp the outline box to the frame so a long CTA can never
    # draw past the edge (checks.py flags the overflow instead)
    dr.rounded_rectangle((max(LY["cta_edge"], x - pad), y + LY["cta_top_off"],
                          min(W - LY["cta_edge"], x + w + pad), y + LY["cta_bot_off"]),
                         radius=18,
                         outline=(ACCENT[0], ACCENT[1], ACCENT[2], a), width=4)
    dr.text((x, y), txt, font=eng.BODY, fill=(WHITE[0], WHITE[1], WHITE[2], a))


# ---- v1.4 C4e market-style kinds (tpl_stomp restyle) ----------------------
# Yasser's live-test feedback: boxed panels + noisy backgrounds read as "old
# style". These two kinds carry a phrase with NO box and NO plate: an accent
# hairline rule + letterspaced small caps (kicker), and a raw oversized pop
# word (burst). Clean stage, type does the work.

def draw_kicker(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, ACCENT, prog, slide, a = (ctx.H, ctx.W, ctx.LY, ctx.ACCENT,
                                        ctx.prog, ctx.slide, ctx.a)
    txt = L["text"]
    ep = clamp01(prog / M.KICKER_RAMP)
    trk = LY["kicker_trk"]
    w = eng._measure_tracked(dr, txt, eng.SMALL, trk)
    rule_w = int(w * ease_o(ep))          # rule grows with the settle clock
    y = H * LY["kicker_frac"] - slide
    # v1.36 (Onyx draft): "rule: false" drops the accent rule for a bare
    # letterspaced-caps line (drafts may restyle; shipped kickers keep it).
    if L.get("rule", True):
        dr.rectangle(((W - rule_w) / 2, y - LY["kicker_rule_gap"],
                      (W + rule_w) / 2, y - LY["kicker_rule_gap"] + LY["kicker_rule_h"]),
                     fill=(ACCENT[0], ACCENT[1], ACCENT[2], a))
    # letterspaced small caps, staggered rise (same overshoot curve as word_pop);
    # optional per-word "colors" (v1.36 draft tint), default ACCENT everywhere.
    knames = L.get("colors")
    kcols = [ctx.PAL.get(n, ACCENT) for n in knames] if knames else None
    words = txt.split(" ")
    wsp = dr.textlength(" ", font=eng.SMALL)
    ws = [dr.textlength(x, font=eng.SMALL) for x in words]
    total = sum(ws) + wsp * (len(words) - 1) + trk * sum(len(x) for x in words)
    x = (W - total) / 2
    for i, word in enumerate(words):
        wt = clamp01((ep - i * 0.15) / 0.45)
        if wt <= 0:
            x += ws[i] + wsp + trk * len(word)
            continue
        eoc = ease_ow(wt)
        aa = int(a * min(1.0, wt * 1.6))
        yy = y + (1 - eoc) * 24
        col = kcols[i % len(kcols)] if kcols else ACCENT
        if trk:
            for c in word:
                dr.text((x, yy), c, font=eng.SMALL,
                        fill=(col[0], col[1], col[2], aa))
                x += dr.textlength(c, font=eng.SMALL) + trk
        else:
            dr.text((x, yy), word, font=eng.SMALL,
                    fill=(col[0], col[1], col[2], aa))
            x += ws[i] + wsp


def draw_burst(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, ACCENT, prog, slide = ctx.H, ctx.W, ctx.LY, ctx.ACCENT, ctx.prog, ctx.slide
    txt = L["text"]
    # oversized pop-in: starts slightly SMALL and overshoots to full size —
    # the market stomp move (scale punch, no box, no plate)
    ez = ease_ow(prog)
    scale = 0.82 + 0.18 * ez
    fnt = eng._mkfont(eng.preset["fonts"]["display"], int(eng.L["h1"] * scale))
    w = dr.textlength(txt, font=fnt)
    a = int(255 * min(1.0, prog * 2.2))
    if ctx.a_gate is not None:
        a = min(a, ctx.a_gate)
    # v1.4 (kinetic drafts): burst honors an explicit per-caption "colors"
    # list (first name wins for the whole stomp word); without it the accent
    # fill is byte-identical to every shipped render. Fixes the Onyx draft's
    # "PINK." scene drawing cyan instead of pink (Yasser QA).
    col = ACCENT
    names = L.get("colors")
    if names:
        col = ctx.PAL.get(names[0], ACCENT)
    dr.text(((W - w) / 2, H * LY["burst_frac"] - slide), txt, font=fnt,
            fill=(col[0], col[1], col[2], a))


def _tint_pieces(L, ctx):
    """v1.36 (Onyx draft): per-word color list for a caption. L["colors"] =
    preset color NAMES cycled over words (e.g. ["white","pink"]); no list ->
    [None] meaning the kind's default color. Letters inside a word share the
    word's color unless L["tint_letters"] names per-CHARACTER colors."""
    names = L.get("colors")
    if not names:
        return None
    return [ctx.PAL.get(n, ctx.WHITE) for n in names]


def draw_typewriter(eng, dr, L, k, ctx, e):
    """v1.36 (Onyx draft): character-by-character typewriter reveal with a
    blinking caret — the market "typed line" move. Char i's appear clock:
    tp = (lt-at)/TYPE_RAMP normalized by render_layer's per-kind gate;
    tc = (tp - i*TYPE_STEP)/TYPE_RAMP, matching metrics done_at exactly."""
    clamp01 = e[0]
    H, W, LY, WHITE, lt, at, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                              ctx.lt, ctx.at, ctx.slide, ctx.a_gate)
    txt = L["text"]
    # seconds past the caption start (gate opens fully for this kind; the
    # transition_out freeze mirrors render_layer's outgoing-side kill switch)
    tp = lt - at
    if ctx.transition_out:
        tp = min(tp, float(ctx.shot_t) - at)
    fnt = eng.BODY
    trk = 3
    pieces, total = eng.tracked_pieces(dr, txt, fnt, trk)
    x0 = (W - total) / 2
    y = H * LY["caplines_frac"] - slide
    n_seen = 0
    tints = _tint_pieces(L, ctx)
    tl = L.get("tint_letters")   # optional per-char color names (same length as text)
    for i, (c, adv) in enumerate(pieces):
        tc = clamp01((tp - i * M.TYPE_STEP) / M.TYPE_RAMP)
        if tc <= 0:
            break
        n_seen = i + 1
        if c == " ":
            continue
        a = int(255 * min(1.0, tc * 3.0))
        if a_gate is not None:
            a = min(a, a_gate)
        col = WHITE
        if tl and i < len(tl):
            col = ctx.PAL.get(tl[i], WHITE)
        elif tints:
            # word index of this char
            wi = txt[:i].count(" ")
            col = tints[wi % len(tints)]
        dr.text((x0, y), c, font=fnt, fill=(col[0], col[1], col[2], a))
        x0 += adv
    # caret: blinks while typing, solid for 0.3s after the last char, gone once
    # the line has settled (skill rule: no perpetual idle motion). `done` is in
    # seconds — matches metrics done_at = at + (n-1)*TYPE_STEP + TYPE_RAMP.
    done = (len(pieces) - 1) * M.TYPE_STEP + M.TYPE_RAMP
    if (tp < done and int(ctx.g * 3.2) % 2 == 0) or (done <= tp < done + 0.3):
        ca = 200 if a_gate is None else min(200, a_gate)
        cw = int(eng.L["body"] * 0.14) | 1
        ch = int(eng.L["body"] * 0.9)
        dr.rectangle([x0 + 4, y + ch * 0.08, x0 + 4 + cw, y + ch],
                     fill=(255, 255, 255, ca))


def draw_pump(eng, dr, L, k, ctx, e):
    """v1.36 (Onyx draft): per-word scale punch ('word pumping') with optional
    per-word colors — the market hype move, no box, no plate."""
    H, W, LY, WHITE, ACCENT, lt, at, slide, a_gate = (
        ctx.H, ctx.W, ctx.LY, ctx.WHITE, ctx.ACCENT, ctx.lt, ctx.at, ctx.slide, ctx.a_gate)
    appear = lt - at   # seconds past start; gate opens fully for this kind
    if ctx.transition_out:
        appear = min(appear, float(ctx.shot_t) - at)
    names = L.get("colors") or ["white", "accent"]
    cols = [ctx.PAL.get(n, WHITE if n == "white" else ACCENT) for n in names]
    base = eng.L["h1"]
    eng.word_pump(dr, H * LY["burst_frac"] - slide,
                  lambda sz: eng._mkfont(eng.preset["fonts"]["display"], sz),
                  L["text"], cols, appear, tracking=0, base_size=base,
                  alpha_cap=a_gate)


def _kin_cols(L, ctx, default):
    """v1.4 kinetic drafts: per-caption 'colors' name list -> RGB list; empty
    list means the kind's single `default` color (byte-identical fallback)."""
    names = L.get("colors") or []
    if not names:
        return [default]
    return [ctx.PAL.get(n, default) for n in names]


def draw_wipe(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): mask-wipe reveal — glyphs sit still, a vertical
    edge sweeps across them left->right. Optional per-line 'colors'."""
    clamp01 = e[0]
    H, W, LY, WHITE, prog, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                            ctx.prog, ctx.slide, ctx.a_gate)
    lines = _wrap(eng, dr, L["text"].split(" "), eng.H1, LY["safe_w"], ctx=ctx)
    wp = clamp01(prog * M.WIPE_K)   # metrics done_at mirrors this gain
    cols = _kin_cols(L, ctx, WHITE)
    line_h = int(eng.L["h1"] * 1.06)
    n = max(1, len(lines))
    y0 = H * LY["accent_frac"] - (n - 1) * line_h / 2 - slide
    for j, ln in enumerate(lines):
        eng.line_wipe(dr, y0 + j * line_h, eng.H1, ln, cols[j % len(cols)],
                      wp, tracking=2, alpha_cap=a_gate)


def draw_split(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): split-slide — first half of the words slides in
    from the left, second half from the right, meeting at center."""
    clamp01, ease_o = e[0], e[1]
    H, W, LY, WHITE, prog, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                            ctx.prog, ctx.slide, ctx.a_gate)
    words = L["text"].split(" ")
    if not words or not "".join(words):
        return
    fnt = eng.H1
    mid = (len(words) + 1) // 2
    left, right = " ".join(words[:mid]).strip(), " ".join(words[mid:]).strip()
    lw = dr.textlength(left, font=fnt) if left else 0.0
    rw = dr.textlength(right, font=fnt) if right else 0.0
    gap = eng.L["h1"] * 0.22
    total = lw + rw + gap
    x = (W - total) / 2
    sp = ease_o(prog)   # settle on the shared gated clock; metrics done_at = at+POP_RAMP
    off = (1 - sp) * W * 0.35
    a = int(255 * min(1.0, prog * 2.0))
    if a_gate is not None:
        a = min(a, a_gate)
    cols = _kin_cols(L, ctx, WHITE)
    y = H * LY["accent_frac"] - slide
    if left:
        dr.text((x - off, y), left, font=fnt, fill=cols[0] + (a,))
    if right:
        dr.text((x + lw + gap + off, y), right, font=fnt,
                fill=cols[min(1, len(cols) - 1)] + (a,))


def draw_slam(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): scale-down slam — the word starts huge (past the
    frame) and falls into rest size: the market 'stamp' move."""
    clamp01 = e[0]
    H, W, LY, WHITE, prog, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                            ctx.prog, ctx.slide, ctx.a_gate)
    sp = clamp01(prog / M.SLAM_RAMP * 0.32)   # gate-normalized settle clock
    scale = M.SLAM_FROM - (M.SLAM_FROM - 1.0) * (sp ** 0.7)
    fnt = eng._mkfont(eng.preset["fonts"]["display"], int(eng.L["h1"] * scale))
    txt = L["text"]
    w = dr.textlength(txt, font=fnt)
    a = int(255 * min(1.0, prog * 3.0))
    if a_gate is not None:
        a = min(a, a_gate)
    col = _kin_cols(L, ctx, WHITE)[0]
    dr.text(((W - w) / 2, H * LY["burst_frac"] - slide), txt, font=fnt, fill=col + (a,))


def draw_trackin(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): tracking-expand — letters start wide apart and
    close ranks into the lockup while fading in."""
    clamp01 = e[0]
    H, W, LY, WHITE, prog, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                            ctx.prog, ctx.slide, ctx.a_gate)
    tp = clamp01(prog / M.TRACK_RAMP * 0.32)
    trk = int(eng.L["h1"] * 0.35 * (1 - e[1](tp)))
    a = int(255 * min(1.0, prog * 2.4))
    if a_gate is not None:
        a = min(a, a_gate)
    cols = _kin_cols(L, ctx, WHITE)
    txt = L["text"]
    # per-word color cycles; tracking shared across the line
    words = txt.split(" ")
    fnt = eng.H1
    wsp = dr.textlength(" ", font=fnt)
    ws = [dr.textlength(w, font=fnt) for w in words]
    total = sum(ws) + wsp * (len(words) - 1) + trk * sum(len(w) for w in words)
    x = (W - total) / 2
    y = H * LY["accent_frac"] - slide
    for i, w in enumerate(words):
        col = cols[i % len(cols)]
        cx = x
        for c in w:
            cw = dr.textlength(c, font=fnt)
            dr.text((cx, y), c, font=fnt, fill=col + (a,))
            cx += cw + trk
        x += ws[i] + wsp + trk * len(w)


def draw_flashpop(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): flash pop — each word snaps in with a brief
    alpha FLASH overshoot (flash to ~2x then settle). Per-word colors cycle."""
    clamp01 = e[0]
    H, W, LY, WHITE, lt, at, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                              ctx.lt, ctx.at, ctx.slide, ctx.a_gate)
    appear = lt - at
    if ctx.transition_out:
        appear = min(appear, float(ctx.shot_t) - at)
    words = L["text"].split(" ")
    fnt = eng.H1
    wsp = dr.textlength(" ", font=fnt)
    ws = [dr.textlength(w, font=fnt) for w in words]
    total = sum(ws) + wsp * (len(words) - 1)
    x = (W - total) / 2
    y = H * LY["accent_frac"] - slide
    cols = _kin_cols(L, ctx, WHITE)
    for i, w in enumerate(words):
        wt = clamp01((appear - i * M.FLASH_STEP) / M.FLASH_RAMP)
        if wt <= 0:
            x += ws[i] + wsp
            continue
        # flash curve: alpha spikes at the snap-in, settles to full by wt=1
        fa = min(255, int(255 * (0.4 + 1.6 * math.sin(math.pi * min(1.0, wt * 0.8))))) \
            if wt < 1 else 255
        if a_gate is not None:
            fa = min(fa, a_gate)
        e_ow = 1 - (1 - wt) ** 3
        dy = (1 - e_ow) * eng.L["h1"] * 0.06
        dr.text((x, y + dy), w, font=fnt, fill=cols[i % len(cols)] + (fa,))
        x += ws[i] + wsp


def draw_maskline(eng, dr, L, k, ctx, e):
    """v1.4 (kinetic drafts): line-mask typewriter — words rise from BEHIND a
    baseline mask (each word clipped until it clears the line), no caret."""
    clamp01 = e[0]
    H, W, LY, WHITE, lt, at, slide, a_gate = (ctx.H, ctx.W, ctx.LY, ctx.WHITE,
                                              ctx.lt, ctx.at, ctx.slide, ctx.a_gate)
    appear = lt - at
    if ctx.transition_out:
        appear = min(appear, float(ctx.shot_t) - at)
    txt = L["text"]
    fnt = eng.BODY
    words = txt.split(" ")
    wsp = dr.textlength(" ", font=fnt)
    ws = [dr.textlength(w, font=fnt) for w in words]
    total = sum(ws) + wsp * (len(words) - 1)
    x0 = (W - total) / 2
    y = H * LY["caplines_frac"] - slide
    cols = _kin_cols(L, ctx, WHITE)
    asc = int(eng.L["body"] * 1.05)   # mask window height above the baseline row
    x = x0
    for i, w in enumerate(words):
        wt = clamp01((appear - i * M.WORD_STEP) / M.WORD_RAMP)
        if wt <= 0:
            x += ws[i] + wsp
            continue
        rise = (1 - wt) ** 2 * asc   # quadratic rise out of the mask window
        a = int(255 * min(1.0, wt * 2.2))
        if a_gate is not None:
            a = min(a, a_gate)
        tmp = Image.new("RGBA", (int(ws[i]) + 8, asc), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.text((4, -rise), w, font=fnt, fill=cols[i % len(cols)] + (a,))
        eng._canvas.paste(tmp, (int(x) - 4, int(y)), tmp)
        x += ws[i] + wsp


def draw_handle(eng, dr, L, k, ctx, e):
    H, LY, ACCENT, slide = ctx.H, ctx.LY, ctx.ACCENT, ctx.slide
    eng.draw_center_text(dr, H * LY["handle_frac"] - slide, L["text"], eng.BODY,
                         (ACCENT[0], ACCENT[1], ACCENT[2], ctx.a), tracking=4)


def draw_big_number(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, ACCENT, prog, slide = ctx.H, ctx.W, ctx.LY, ctx.ACCENT, ctx.prog, ctx.slide
    txt = L["text"]
    w = dr.textlength(txt, font=eng.BIG)
    ez = ease_ow(prog)
    bn_a = int(255 * ez)
    if ctx.a_gate is not None:
        bn_a = min(bn_a, ctx.a_gate)
    dr.text(((W - w) / 2, H * LY["bignum_frac"] + (1 - ez) * 50 - slide), txt, font=eng.BIG,
            fill=(ACCENT[0], ACCENT[1], ACCENT[2], bn_a))


def _wrap_panel(eng, dr, lines, fnt, ctx):
    """fit_panel_lines routed through the per-caption cache (C3b)."""
    out = []
    for l in lines:
        out.extend(_wrap(eng, dr, l.split(" "), fnt, eng.L["panel_text_limit"], ctx=ctx))
    return out


def draw_cap_lines(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, LY, WHITE, lt, at, slide, a_gate = (ctx.H, ctx.LY, ctx.WHITE,
                                           ctx.lt, ctx.at, ctx.slide, ctx.a_gate)
    wp = clamp01((lt - at) / M.CAPLINE_RAMP)
    if ctx.transition_out:
        wp = min(wp, clamp01((float(ctx.shot_t) - at) / M.CAPLINE_RAMP))
    # v1.31 (audit #3): wrap like the checker/metrics do — RAW lines could run
    # off-canvas unflagged and the box grew only for panels. The old "pixels
    # would change" comment protected a divergence, not a feature: checker and
    # renderer must agree by construction. Golden baselines regenerate with it.
    lines = _wrap_panel(eng, dr, L["lines"], eng.BODY, ctx)
    step = M.capline_step(len(lines))   # normalized so the last line ALWAYS draws (audit #1)
    for j, line in enumerate(lines):
        eng.word_pop(dr, H * LY["caplines_frac"] + j * LY["capline_h"] - slide, eng.BODY, line, WHITE,
                     wp - j * step, tracking=3, alpha_cap=a_gate)


def draw_terminal(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY, P = ctx.H, ctx.W, ctx.LY, ctx.P
    ACCENT, prog, slide, lt, a_gate, g, a = (ctx.ACCENT, ctx.prog, ctx.slide,
                                             ctx.lt, ctx.a_gate, ctx.g, ctx.a)
    s_t = float(ctx.shot_t)
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
    rows = L.get("rows", M.TERM_DEFAULT_ROWS)   # single source (audit #8)
    prompt_txt = rows[1] if len(rows) > 1 else ""
    type_end = s_t - 1.0
    prog_t = clamp01((lt - 0.5) / max(0.3, type_end - 0.5))
    typed = prompt_txt[: int(len(prompt_txt) * prog_t)]
    cursor = "_" if int(g * 2.4) % 2 == 0 else " "
    # progress bar is FULLY automatic: any row that starts with the
    # block glyphs (or a bare percent like "0%") gets replaced by the
    # live \u2588\u2591 bar + percent — the user never types a static value.
    # Fill window scales with shot length: starts 1/3 in, ends 0.5s
    # before shot end (so it lands exactly at 100%).
    t_shot = s_t
    b_start = t_shot / 3.0
    bt = clamp01((lt - b_start) / max(0.5, t_shot - b_start - 0.5))
    bar = int(12 * bt)
    pct = int(100 * bt)

    def _bar_row(x):
        xs = x.strip()
        return bool(xs) and (xs[0] in "\u2588\u2591" or (xs.endswith("%") and len(xs) <= 6))
    shown = [rows[0], typed + cursor]
    for extra in rows[2:]:
        if _bar_row(extra):
            shown.append("  " + "\u2588" * bar + "\u2591" * (12 - bar) + "  " + str(pct) + "%")
        else:
            shown.append(extra)
    yy = y0 + LY["term_rows_y"]
    for r, line in enumerate(shown):
        appear = clamp01((lt - M.TERM_FIRST_AT - r * M.TERM_ROW_STEP) / M.TERM_ROW_RAMP)
        if ctx.transition_out:
            appear = min(appear, clamp01((s_t - M.TERM_FIRST_AT - r * M.TERM_ROW_STEP) / M.TERM_ROW_RAMP))
        if appear <= 0:
            break
        colr = ACCENT if line.startswith(">") else (205, 210, 220)
        if "%" in line and pct > 0:
            colr = ACCENT
        fnt = eng.MONO if r < 2 else eng.MONOS
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


def draw_chips(eng, dr, L, k, ctx, e):
    clamp01, ease_o, ease_ow = e
    H, W, LY = ctx.H, ctx.W, ctx.LY
    ACCENT, WHITE, lt, at, slide, a_gate = ctx.ACCENT, ctx.WHITE, ctx.lt, ctx.at, ctx.slide, ctx.a_gate
    chips = L["items"]
    widths = [dr.textlength(c, font=eng.MONOS) + LY["chip_extra_w"] for c in chips]
    gap = LY["chip_gap"]
    total = sum(widths) + gap * (len(chips) - 1)
    x = (W - total) / 2
    y = H * LY["chips_frac"]
    for ci, c in enumerate(chips):
        appear = clamp01((lt - at - ci * M.CHIP_STEP) / M.CHIP_RAMP)
        if ctx.transition_out:
            # freeze stagger clock at shot end, then let a_gate fade it
            appear = min(appear, clamp01((float(ctx.shot_t) - at - ci * M.CHIP_STEP) / M.CHIP_RAMP))
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
        dr.text((x + LY["chip_text_dx"], y + LY["chip_text_y"] + sl), c, font=eng.MONOS,
                fill=(WHITE[0], WHITE[1], WHITE[2], aa))
        x += widths[ci] + gap


DISPATCH = {
    "title_block": draw_title_block,
    "accent_word": draw_accent_word,
    "panel_top": draw_panel,
    "panel_mid": draw_panel,
    "small": draw_small,
    "cta": draw_cta,
    "handle": draw_handle,
    "kicker": draw_kicker,       # v1.4 C4e: rule + letterspaced caps, no box
    "burst": draw_burst,         # v1.4 C4e: oversized scale-punch word, no box
    "typewriter": draw_typewriter,  # v1.36 Onyx draft: per-char reveal + caret
    "pump": draw_pump,              # v1.36 Onyx draft: per-word scale punch
    "wipe": draw_wipe,              # v1.4 kinetic drafts: mask-wipe reveal
    "split": draw_split,            # v1.4: halves slide in from frame edges
    "slam": draw_slam,              # v1.4: scale-down stamp from oversize
    "trackin": draw_trackin,        # v1.4: tracking-expand lockup
    "flashpop": draw_flashpop,      # v1.4: word stagger w/ alpha flash
    "maskline": draw_maskline,      # v1.4: words rise out of a baseline mask
    "big_number": draw_big_number,
    "cap_lines": draw_cap_lines,
    "terminal": draw_terminal,
    "chips": draw_chips,
}
