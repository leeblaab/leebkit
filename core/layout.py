"""LEEBKIT core — aspect-aware layout metrics (v1.2).

One place that turns (W, H) into every positional/size number the engine and
the checks used to hardcode for 1080x1920. Portrait numbers are kept EXACTLY
(1080x1920 reproduces the v1.1 pixel layout); landscape/square derive from
them via a scale factor S = min(W, H) / 1920 so nothing overlaps or clips at
other ratios:

  * horizontal safe margins (fit_title W-80, fit_panel_lines W-160, ...) stay
    width-based — they shrink naturally on narrower canvases;
  * vertical anchors stay as fractions of H;
  * every fixed pixel size (font sizes, panel heights, paddings, line
    heights) is scaled by S and re-clamped against the horizontal safe width.

Engine.build_layout() produces this from the merged preset; presets may add a
"landscape" block {"scale": 0.62} to tune per-style.
"""


def build_layout(W, H, sizes, landscape=None):
    """sizes is the preset dict (keys: logo/h1/body/small/mono/mono_s/big).
    Returns a dict of plain ints/floats the engine reads instead of constants."""
    L = {}
    L["W"], L["H"] = W, H
    S = min(W, H) / 1920.0            # portrait 1080x1920 -> exactly 1.0
    cfg = landscape or {}
    if H <= W:                        # landscape or square canvas
        S *= float(cfg.get("scale", 0.62))

    def sc(v):
        return max(12, int(round(v * S)))

    # ---- fonts (sizes; engine may shrink further via clamp pass) ----
    L["logo"] = sc(sizes["logo"])
    L["h1"] = sc(sizes["h1"])
    L["body"] = sc(sizes["body"])
    L["small"] = sc(sizes["small"])
    L["mono"] = sc(sizes["mono"])
    L["mono_s"] = sc(sizes["mono_s"])
    L["big"] = sc(sizes["big"])

    # ---- horizontal safe widths (width-based) ----
    L["title_limit"] = W - 80
    L["panel_text_limit"] = W - 160
    L["safe_w"] = W - 160             # checks: panel inner text budget
    L["small_chip_limit"] = W - 260
    L["cta_limit"] = W - 140
    L["term_line_limit"] = W - 200
    L["chips_total_limit"] = W - 80

    # ---- panel_top / panel_mid ----
    L["panel_x"] = sc(50)
    L["panel_pad_y"] = sc(40)
    L["line_h_panel"] = sc(110)
    L["panel_extra_h"] = sc(70)
    L["panel_top_frac"] = 0.14
    L["panel_mid_frac"] = 0.36

    # ---- title_block ----
    L["title_frac"] = 0.38
    L["title_line_h_k"] = 1.06        # multiplier of the (fitted) title size
    L["ul_min"], L["ul_max"] = sc(140), sc(560)
    L["ul_h"] = max(4, sc(8))
    L["ul_gap_k"] = 0.34              # underline gap below last line, * tsize
    L["sub_gap"] = sc(65)
    L["sub_pad"] = sc(18)
    L["sub_radius"] = sc(14)

    # ---- small note chip ----
    L["small_frac"] = 0.615
    L["small_chip_h"] = sc(72)
    L["small_line_h"] = sc(46)
    L["small_pad_x"] = sc(30)

    # ---- cta ----
    L["cta_frac"] = 0.545
    L["cta_pad"] = sc(34)
    L["cta_top_off"] = -sc(18)
    L["cta_bot_off"] = sc(92)
    L["cta_edge"] = sc(10)

    # ---- handle / accent_word ----
    L["handle_frac"] = 0.73
    L["accent_frac"] = 0.415

    # ---- v1.4 C4e market-style kinds (kicker / burst — no box, no plate) ----
    L["kicker_frac"] = 0.30
    L["kicker_trk"] = max(6, int(round(16 * S)))   # letterspaced small caps
    L["kicker_rule_h"] = max(2, int(round(4 * S)))
    L["kicker_rule_gap"] = sc(18)
    L["burst_frac"] = 0.44

    # ---- big_number ----
    L["bignum_frac"] = 0.24

    # ---- cap_lines ----
    L["caplines_frac"] = 0.60
    L["capline_h"] = sc(95)

    # ---- terminal ----
    L["term_x"] = sc(60)
    L["term_y_frac"] = 0.47
    L["term_box_h"] = sc(700)
    L["term_head_h"] = sc(70)
    L["term_dot0"] = sc(92)
    L["term_dot_step"] = sc(44)
    L["term_dot_y"] = sc(24)
    L["term_rows_y"] = sc(104)
    L["term_row_x"] = sc(100)
    L["term_line_h_a"] = sc(86)       # first two rows (mono)
    L["term_line_h_b"] = sc(74)       # extra rows (mono_s)

    # ---- chips ----
    L["chips_frac"] = 0.585
    L["chip_text_dx"] = sc(30)       # text x-offset inside chip
    L["chip_extra_w"] = sc(60)       # width padding per chip
    L["chip_gap"] = sc(26)
    L["chip_h"] = sc(86)
    L["chip_text_y"] = sc(23)

    # ---- shared motion offsets (scale with canvas) ----
    L["slide_dy"] = max(10, int(round(36 * S)))   # caption slide-in rise
    from . import metrics as _M   # C7: title pop-in rise shares the metrics clock source
    L["title_rise"] = max(8, int(round(_M.TITLE_RISE_PX * S)))
    return L


def clamp_font_sizes(L, measure):
    """Second safety pass for narrow canvases: shrink display sizes until a
    digit-string probe fits the horizontal safe width (e.g. big_number 300px
    fine at 1080 wide, too fat at 640). `measure(size) -> font` builds a font
    at that size. Mutates L in place."""
    for key, limit in (("big", L["W"] - 160), ("h1", L["panel_text_limit"]),
                       ("logo", L["title_limit"])):
        while L[key] > 24:
            try:
                w = measure(L[key]).getlength("000")
            except Exception:
                break
            if w <= limit:
                break
            L[key] = max(24, int(L[key] * 0.9))
