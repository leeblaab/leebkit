"""v1.42 item 1 (C0b): accent_word honors per-caption `colors`.

Gap found auditing the advisor doc against v1.41: draw_accent_word passed the
preset ACCENT unconditionally, so an accent_word with colors:[...] rendered in
the preset accent regardless (the kind's underline/rule keeps the accent —
single-animated-property rule). Fix reuses the v1.4 tint machinery
(_kin_cols): per-word cycle when a colors list is present; NO list -> preset
ACCENT byte-for-byte (goldens untouched).

Parity gate in metrics.measure(): `colors` on any kind must be a non-empty
list of <= 4 palette names defined in the ACTIVE preset (the checker reads
the same preset dict the renderer builds PAL from — agree by construction).

Run: PYTHONPATH=. python tests/test_accent_colors.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core.checks import check_project       # noqa: E402
from core.engine import Engine, hex2rgb     # noqa: E402


def _proj(colors=None):
    cap = {"kind": "accent_word", "at": 0.3, "text": "ALPHA BETA"}
    if colors is not None:
        cap["colors"] = colors
    return {"schema": 1, "target": 2.0, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [{"fill": "solid", "t": 2.0, "captions": [cap]}]}


def _band_pixels(eng):
    """Bright pixels in the accent_frac band of a settled frame."""
    img = eng.compose_frame(int(1.4 * eng.FPS)).convert("RGB")
    W, H = img.size
    y0, y1 = int(H * eng.L["accent_frac"]), int(H * (eng.L["accent_frac"] + 0.09))
    out = []
    px = img.load()
    for y in range(y0, y1):
        for x in range(W):
            c = px[x, y]
            if sum(c) > 240:
                out.append(c)
    return out


def _close(c, t, tol=48):
    return all(abs(a - b) <= tol for a, b in zip(c, t))


def test_default_accent_unchanged():
    eng = Engine(_proj())
    band = _band_pixels(eng)
    assert band, "empty accent band"
    hits = sum(1 for c in band if _close(c, eng.ACCENT))
    assert hits > 200, ("preset accent missing", hits, len(band))


def test_colors_render_per_word():
    # onyx palette carries pink; the other word stays white -> two clusters
    eng = Engine(_proj(colors=["pink", "white"]))
    band = _band_pixels(eng)
    pink = hex2rgb(eng.preset["colors"]["pink"])
    hits_pink = sum(1 for c in band if _close(c, pink))
    hits_white = sum(1 for c in band if _close(c, eng.WHITE))
    assert hits_pink > 100, ("pink word missing", hits_pink, len(band))
    assert hits_white > 100, ("white word missing", hits_white, len(band))


def test_checker_flags_bad_colors():
    # unknown palette name -> error flag (not a silent fallback)
    eng = Engine(_proj(colors=["notacolor"]))
    flags = [f for f in check_project(eng) if f["kind"] == "colors"]
    assert flags, "unknown color name not flagged"
    # >4 names -> error
    eng = Engine(_proj(colors=["white", "pink", "accent", "dim", "bg"]))
    flags = [f for f in check_project(eng) if f["kind"] == "colors"]
    assert flags, ">4 color names not flagged"
    # valid list -> clean on the colors gate
    eng = Engine(_proj(colors=["pink", "white"]))
    flags = [f for f in check_project(eng) if f["kind"] == "colors"]
    assert not flags, flags


def main():
    for fn in (test_default_accent_unchanged, test_colors_render_per_word,
               test_checker_flags_bad_colors):
        fn()
        print("PASS", fn.__name__)
    print("ACCENT COLORS PASS")


if __name__ == "__main__":
    main()
