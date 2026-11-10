"""core/metrics.py — per-kind measure() (v1.3 C4).

checks.py must never re-derive layout/timing math by mirroring render_layer
formulas — that drift already bit us twice (panel preamble missing from the
checker; cap_lines checked on raw instead of wrapped lines). Each kind's
measure() returns the SAME numbers its captions.py draw path computes at
draw time; checks assert on these. Renderer and checker agree by
construction.

done_at semantics (agreed v1.3): SETTLE TIME — the moment the last animated
element reaches progress 1 (same meaning as today's timing flags). The
storyboard strip keeps its fixed 0.75*shot_t sampling in v1.3; revisiting
sampling vs done_at is a v1.4 decision.

C4 scope: constants here are the single source for stagger clocks. captions.py
draw functions import them so a formula change lands in BOTH paths at once.
The Engine-level metrics cache (fit/wrap computed once per caption instead of
per frame) ships as C3b on top of this module."""

from PIL import Image, ImageDraw

# --- shared clock constants: SINGLE source for stagger math ---------------
PANEL_SHIFT = 0.45      # panel_* early-start preamble (C2)
POP_RAMP = 0.32         # generic prog ramp after `at` (render_layer gate)
PANEL_WDELAY = 0.28     # word-pop start delay inside panels
PANEL_WRAMP = 0.95      # word-pop progress ramp
WORD_STEP = 0.18        # per-word stagger step (word_pop)
WORD_RAMP = 0.36        # per-word appear ramp (word_pop)
CAPLINE_RAMP = 0.3      # cap_lines wp = (lt-at)/0.3
CAPLINE_LINE_STEP = 0.45
CHIP_STEP = 0.35
CHIP_RAMP = 0.4
TERM_FIRST_AT = 0.4     # terminal first row at lt=0.4 (kind clock, not `at`)
TERM_ROW_STEP = 0.5
TERM_ROW_RAMP = 0.3


def clamp01(t):
    return max(0.0, min(1.0, t))


def preamble_at(k, at):
    """Kind clock preamble — must match render_layer's preamble block."""
    if k in ("panel_top", "panel_mid"):
        return at - PANEL_SHIFT
    return at


def _probe_dr():
    return ImageDraw.Draw(Image.new("RGB", (8, 8)))


def measure(eng, L, k, shot_t, at_raw):
    """Per-kind measurements. Returns dict; keys vary by kind:
    lines/n, done_at (settle time), widths/total, rows_done/typing_done,
    tsize/trk, longest_word. Values equal what the draw path computes."""
    at = preamble_at(k, at_raw)
    m = {"at_eff": at}

    if k in ("panel_top", "panel_mid"):
        lines = eng.fit_panel_lines(_probe_dr(), L["lines"], eng.H1)
        n = len(lines)
        span = max(len(l.split(" ")) for l in lines) * WORD_STEP + WORD_RAMP
        Sv = (1.0 - span) / (n - 1) if n > 1 else 0.0
        # line j's last word lands when wprog*(span/0.55) - j*Sv >= span,
        # wprog = (lt-at-PANEL_WDELAY)/PANEL_WRAMP
        done_at = at + PANEL_WDELAY + PANEL_WRAMP * (1.0 + Sv * 0.55 / max(span, 1e-6))
        m.update(lines=lines, n=n, span=span, done_at=done_at)

    elif k == "cap_lines":
        cl = eng.fit_panel_lines(_probe_dr(), L["lines"], eng.BODY)
        # word_pop: line j appear = wp - j*CAPLINE_LINE_STEP; last line's last
        # word needs WORD_RAMP plus its own per-word stagger inside word_pop
        wp_done = 1.0 + (len(cl) - 1) * CAPLINE_LINE_STEP
        done_at = at + wp_done * CAPLINE_RAMP \
            + (max(len(l.split(" ")) for l in cl) - 1) * WORD_STEP + WORD_RAMP
        m.update(lines=cl, n=len(cl), done_at=done_at)

    elif k == "terminal":
        nrows = len(L.get("rows", ["> PROMPT", "", "> RENDERING..."]))
        rows_done = TERM_FIRST_AT + (nrows - 1) * TERM_ROW_STEP + TERM_ROW_RAMP
        typing_done = float(shot_t) - 1.0
        m.update(rows_done=rows_done, typing_done=typing_done)

    elif k == "chips":
        widths = [eng.MONOS.getlength(c) + eng.L["chip_extra_w"] for c in L["items"]]
        total = sum(widths) + eng.L["chip_gap"] * (len(L["items"]) - 1)
        done_at = at + (len(L["items"]) - 1) * CHIP_STEP + CHIP_RAMP
        m.update(widths=widths, total=total, done_at=done_at)

    elif k == "title_block":
        lines, tsize, trk = eng.fit_title(_probe_dr(), L.get("text", ""),
                                          eng.L["logo"], eng.L["title_limit"])
        m.update(lines=lines, tsize=tsize, trk=trk)
        if L.get("sub"):
            m["sub_lines"] = eng.fit_small_lines(_probe_dr(), L["sub"],
                                                 eng.SMALL, eng.TRK.get("sub", 0))

    elif k == "small":
        wl = max(L.get("text", "").split(" "),
                 key=lambda w: eng.SMALL.getlength(w), default="")
        m.update(longest_word=wl)

    return m
