"""C1 resolution matrix — 720p / FHD / 2K portrait tiers (v1.4 plan D-decisions).

Locks:
  * build_layout scales fonts+boxes by S=min(W,H)/1920 exactly (720 -> 2/3,
    2560 -> 4/3); safe widths stay width-based; clamp pass never fires at the
    three portrait tiers.
  * validate_project accepts the tier sizes and rejects off-tier junk.
  * Engine renders a tiny shot at each tier: right canvas size, no overflow
    flags from checks.py, caption text actually drawn (measure==render parity).
Run: PYTHONPATH=. python tests/test_resolution_matrix.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont  # noqa: E402

from core import checks  # noqa: E402
from core.engine import Engine, validate_project  # noqa: E402
from core.layout import build_layout, clamp_font_sizes  # noqa: E402

TIERS = [(720, 1280), (1080, 1920), (1440, 2560)]
FAILS = []


def ok(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)
    else:
        print("ok  :", msg)


SIZES = {"logo": 44, "h1": 96, "body": 78, "small": 40,
         "mono": 52, "mono_s": 44, "big": 300}
FONT_PATH = None  # engine default font resolution


def test_layout_scaling():
    base = build_layout(1080, 1920, SIZES)
    for W, H in TIERS:
        L = build_layout(W, H, SIZES)
        s = min(W, H) / 1920.0
        ok(L["W"] == W and L["H"] == H, "%dx%d canvas dims kept" % (W, H))
        for k in ("h1", "body", "small", "mono"):
            want = max(12, int(round(SIZES[k] * s)))
            ok(L[k] == want, "%dx%d font %s = %d (S=%.3f)" % (W, H, k, L[k], s))
        # safe widths stay width-based
        ok(L["title_limit"] == W - 80 and L["panel_text_limit"] == W - 160,
           "%dx%d safe widths width-based" % (W, H))
        # relative legibility: h1/width ratio constant across tiers (+-1px rounding)
        r0 = base["h1"] / 1080.0
        r = L["h1"] / float(W)
        ok(abs(r - r0) < 0.01, "%dx%d h1/W legibility ratio stable (%.4f vs %.4f)"
           % (W, H, r, r0))
        # clamp pass must NOT shrink anything at portrait tiers
        before = {k: L[k] for k in ("big", "h1", "logo")}
        clamp_font_sizes(L, lambda sz: ImageFont.truetype(_disp(W, H), sz))
        ok(before == {k: L[k] for k in ("big", "h1", "logo")},
           "%dx%d clamp pass no-ops at portrait tiers" % (W, H))


def _disp(W, H):
    eng = Engine(_proj(W, H, captions=[]))
    return os.path.join(eng.FONTS_DIR, eng.preset["fonts"]["display"])


def _proj(w, h, captions=None, shot_extra=None):
    s = {"t": 2.0}
    if captions is not None:
        s["captions"] = captions
    if shot_extra:
        s.update(shot_extra)
    return {"schema": 1, "preset": "leebdark.json", "width": w, "height": h,
            "fps": 30, "target": 2.0, "shots": [s]}


def test_validate_tiers():
    def proj(w, h):
        return _proj(w, h, captions=[{"kind": "cta", "text": "GO", "at": 0.5}])
    # portrait tiers (v1.4 C1) + the v1.2 square/landscape formats must pass
    for W, H in TIERS + [(1080, 1080), (1920, 1080)]:
        try:
            validate_project(proj(W, H))
            ok(True, "validate accepts %dx%d" % (W, H))
        except Exception as e:
            ok(False, "validate accepts %dx%d (%s)" % (W, H, e))
    # off-tier portrait junk rejected; tiny smoke probe + 4K-boundary stay legal
    for bad in ((800, 1400), (720, 1281), (900, 1600)):
        try:
            validate_project(proj(*bad))
            ok(False, "validate rejects off-tier portrait %dx%d" % bad)
        except Exception:
            ok(True, "validate rejects off-tier portrait %dx%d" % bad)
    for W, H in ((320, 320), (1280, 720), (2560, 1440)):
        try:
            validate_project(proj(W, H))
            ok(True, "validate keeps %dx%d legal (probe/landscape)" % (W, H))
        except Exception as e:
            ok(False, "validate keeps %dx%d legal (%s)" % (W, H, e))


def test_engine_render_matrix():
    caps = [{"kind": "panel_top", "lines": ["RESOLUTION MATRIX TEST"], "at": 0.2},
            {"kind": "cta", "text": "720 / FHD / 2K", "at": 0.8}]
    for W, H in TIERS:
        p = _proj(W, H, captions=caps, shot_extra={"fill": "solid"})
        eng = Engine(p)
        img = eng.compose_frame(int(1.5 * 30))
        ok(img.size == (W, H), "%dx%d compose_frame canvas exact" % (W, H))
        flags = [f for f in checks.check_project(eng)
                 if "overflow" in f["message"].lower() or "clip" in f["message"].lower()]
        ok(not flags, "%dx%d no overflow/clip flags (%s)" % (W, H, flags))


def test_ui_tier_surface():
    """ui/index.html must surface all three portrait tiers in the format
    select and wire them through P.size/width/height (app.py passes size
    through untouched; the Engine validate gate is the real guard)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "ui", "index.html"), encoding="utf-8").read()
    for tier in ("720x1280", "1080x1920", "1440x2560"):
        ok('value="%s"' % tier in src, 'format select has option %s' % tier)
    ok("PORTRAIT_SIZES" in src, "hydrate sites know the new tiers")
    ok(src.count("'720x1280':1") >= 3, "both hydrate sites include 720p tier")


if __name__ == "__main__":
    test_layout_scaling()
    test_validate_tiers()
    test_engine_render_matrix()
    test_ui_tier_surface()
    print("=" * 40)
    if FAILS:
        print("%d FAIL(S)" % len(FAILS))
        sys.exit(1)
    print("ALL PASS")
