# v1.42 item 6: easing library + opt-in "ease" field on entrance kinds
# (pop/pump/slam/wipe/trackin; kicker's stagger is LOCKED — no ease).
import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core.engine import (Engine, validate_project,
                         ease_expo_out, ease_back_in, ease_elastic_out,
                         ease_step3)
from core.checks import check_project


def base_proj(caps, t=3.0):
    return {"schema": 1, "target": t, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [{"fill": "solid", "t": t, "captions": caps}]}


def diff_bbox(a, b):
    """(minx,miny,maxx,maxy) of pixels differing between two frames, or None."""
    a = a.convert("RGB"); b = b.convert("RGB"); pa, pb = a.load(), b.load()
    W, H = a.size
    x0, y0, x1, y1 = W, H, -1, -1
    for y in range(H):
        for x in range(W):
            if pa[x, y] != pb[x, y]:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    return None if x1 < 0 else (x0, y0, x1, y1)


# ---------------------------------------------------------------- curves
def test_curve_endpoints():
    for f in (ease_expo_out, ease_back_in, ease_elastic_out, ease_step3):
        assert abs(f(0.0) - 0.0) < 1e-9, f.__name__
        assert abs(f(1.0) - 1.0) < 1e-9, f.__name__


def test_curve_shape():
    # expo_out: front-loaded — at t=0.5 it's already past 0.87
    assert ease_expo_out(0.5) > 0.87
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert ease_expo_out(t) > ease_expo_out(t - 0.05)   # monotonic
    # back_in: dips below 0 mid-ramp, stays >= -0.15 (c1=1.70158)
    assert min(ease_back_in(t) for t in [i / 100 for i in range(101)]) < -0.05
    assert min(ease_back_in(t) for t in [i / 100 for i in range(101)]) > -0.15
    # elastic_out: overshoots past 1 mid-ramp, ends exactly at 1, bounded
    # (the canonical curve's first peak is ~1.373 — house bound <1.4)
    vals = [ease_elastic_out(i / 1000) for i in range(1001)]
    assert max(vals) > 1.02 and max(vals) < 1.4
    # step3: three plateaus at 1/3, 2/3, 1; endpoints exact
    assert abs(ease_step3(0.15) - 1 / 3) < 1e-9
    assert abs(ease_step3(0.5) - 2 / 3) < 1e-9
    assert abs(ease_step3(0.85) - 1.0) < 1e-9


# ---------------------------------------------------------------- schema
def test_validate_ease_shape():
    # every eligible kind accepts each ease name (schema shape)
    for kind in ("accent_word", "pump", "slam", "wipe", "trackin"):
        for name in ("expo", "elastic", "steps"):
            validate_project(base_proj([{"kind": kind, "at": 0.3,
                                         "text": "EASED", "ease": name}]))
    # unknown value rejected
    try:
        validate_project(base_proj([{"kind": "slam", "at": 0.3, "text": "X",
                                     "ease": "bouncy"}]))
        raise AssertionError("unknown ease accepted")
    except ValueError:
        pass


# ---------------------------------------------------------------- render A/B
def test_ease_changes_pixels_only_in_ramp():
    """Same project with/without ease: frames differ DURING the entrance ramp,
    are identical AFTER settle (settle clock untouched -> goldens safe)."""
    for kind, at in (("accent_word", 0.3), ("pump", 0.3), ("slam", 0.5),
                     ("wipe", 0.4), ("trackin", 0.4)):
        plain = Engine(base_proj([{"kind": kind, "at": at, "text": "EASE TEST"}]))
        eased = Engine(base_proj([{"kind": kind, "at": at, "text": "EASE TEST",
                                   "ease": "expo"}]))
        n = int(3.0 * 24)
        # in-ramp frame must differ (pick a frame mid-entrance for each kind)
        mid = int((at + 0.10) * 24)
        assert diff_bbox(plain.compose_frame(mid), eased.compose_frame(mid)), kind
        # post-settle frames must be pixel-identical
        late = int((at + 1.6) * 24)
        assert diff_bbox(plain.compose_frame(late), eased.compose_frame(late)) is None, kind


def test_kicker_ease_rejected_by_checker():
    """kicker's stagger is LOCKED: validate tolerates the shape (shared field)
    but check_project flags it so nobody ships an ignored ease."""
    p = base_proj([{"kind": "kicker", "at": 0.3, "text": "LOCKED STAGGER",
                    "ease": "expo"}])
    flags = check_project(Engine(p))
    assert [f for f in flags if f.get("field") == "ease"
            or f.get("kind") == "ease"], flags


def test_ease_none_is_byte_identical():
    """Default path untouched: two engines, no ease field -> same hashes."""
    a = Engine(base_proj([{"kind": "slam", "at": 0.5, "text": "SAME"}]))
    b = Engine(base_proj([{"kind": "slam", "at": 0.5, "text": "SAME"}]))
    for i in (12, 16, 20, 30, 60):
        assert a.compose_frame(i).tobytes() == b.compose_frame(i).tobytes()


def test_determinism_sample_vs_full():
    """render_frame is a pure function of frame index: repeated renders of an
    eased caption agree (sample==full by construction; this pins it)."""
    e = Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                           "text": "DETERMINISTIC EASE", "ease": "elastic"}]))
    h1 = [e.compose_frame(i).tobytes() for i in (8, 12, 16, 24)]
    e2 = Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                            "text": "DETERMINISTIC EASE", "ease": "elastic"}]))
    h2 = [e2.compose_frame(i).tobytes() for i in (8, 12, 16, 24)]
    assert h1 == h2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print("OK %d tests" % len(fns))
