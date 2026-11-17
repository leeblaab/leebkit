"""v1.5 item 8 test-first: opt-in "fx": "glitch" (RGB-split channel fringe).

Spec (docs/_local_v1.5_plan.md): fx on accent_word/burst ("big_word" family)/slam_v2
(schema + validate). ACTIVE ONLY within the entrance ramp: R/Cyan channel
offsets +/- (4..12) px driven by a sin STEP of the beat clock (item 3; falls
back to a seed time function when beat is None), amplitude scaled by the
ramp's remaining energy — settles to ZERO at done_at. Cost gate: two extra
tinted paste layers, no gaussian, no per-pixel loops. Checker: fx needs an
entrance kind with a settle clock (flag otherwise).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine, validate_project
from core import metrics as M


def base_proj(caps, bpm=None):
    d = {"schema": 1, "name": "t", "preset": "leebdark", "target": 2.0,
         "fps": 30, "music": {"mode": "none"},
         "shots": [{"t": 2.0, "transition": "cut", "captions": caps}]}
    if bpm is not None:
        d["bpm"] = bpm     # engine reads the project-level `bpm` override
    return d


# ---------------------------------------------------------------- schema
def test_validate_fx():
    validate_project(base_proj([{"kind": "accent_word", "at": 0.3,
                                 "text": "FX OK", "fx": "glitch"}]))
    try:
        validate_project(base_proj([{"kind": "accent_word", "at": 0.3,
                                     "text": "BAD", "fx": "shake"}]))
        assert False, "unknown fx must raise"
    except ValueError:
        pass


# ---------------------------------------------------------------- checker
def test_checker_fx_needs_settle_clock():
    from core.checks import check_project
    # eligible kind + settles inside the shot -> no fx flag
    eng = Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                             "text": "GOOD FX", "fx": "glitch"}]))
    assert not [f for f in check_project(eng) if f["kind"] == "fx"], \
        "settled accent_word with glitch fx must not flag"
    # ineligible kind (no entrance settle clock to ride) -> flagged
    bad = Engine(base_proj([{"kind": "small", "at": 0.3,
                             "text": "BAD HOST", "fx": "glitch"}]))
    assert [f for f in check_project(bad) if f["kind"] == "fx"], \
        "fx on a non-entrance kind must raise an fx flag"


# ---------------------------------------------------------------- pixels
def test_glitch_pixels_ramp_only():
    def frame(kind, fx, lt):
        caps = [{"kind": kind, "at": 0.3, "text": "GLITCH"}]
        if fx:
            caps[0]["fx"] = fx
        eng = Engine(base_proj(caps, bpm=120))
        return eng.compose_frame(int(round((eng.starts[0] + lt) * eng.FPS)))

    # inside the entrance (accent_word ramp ends at at+0.32): fringe changes px
    d = sum(1 for lt in (0.36, 0.42, 0.48)
            if frame("accent_word", "glitch", lt).tobytes()
            != frame("accent_word", None, lt).tobytes())
    assert d == 3, "fx must change pixels inside the entrance ramp: %d/3" % d
    # settled (done_at long past): fx frame byte-identical to no-fx frame
    for kind in ("accent_word", "burst", "slam_v2"):
        a = frame(kind, "glitch", 1.8)
        b = frame(kind, None, 1.8)
        assert a.tobytes() == b.tobytes(), \
            "%s settled frame with fx must equal the no-fx frame" % kind


def test_glitch_beat_and_seed_paths():
    # beat=None (no bed) still glitches via the seed fallback, deterministically
    def f(lt, bpm):
        eng = Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                                 "text": "GLITCH", "fx": "glitch"}], bpm=bpm))
        return eng.compose_frame(int(round((eng.starts[0] + lt) * eng.FPS)))

    assert f(0.42, None).tobytes() != f(0.42, 120).tobytes(), \
        "beat and seed paths are different clocks; both must render"
    # each path deterministic across fresh engines (pure function of frame)
    assert f(0.42, None).tobytes() == f(0.42, None).tobytes()
    assert f(0.42, 120).tobytes() == f(0.42, 120).tobytes()


# ---------------------------------------------------------------- determinism
def test_determinism_sample_vs_full():
    proj = base_proj([{"kind": "burst", "at": 0.3, "text": "DET FX",
                       "fx": "glitch"}], bpm=128)
    h1 = [Engine(proj).compose_frame(i).tobytes() for i in (12, 15, 18)]
    eng = Engine(proj)
    h2 = [eng.compose_frame(i).tobytes() for i in (12, 15, 18)]
    assert h1 == h2


if __name__ == "__main__":
    for f in (test_validate_fx, test_checker_fx_needs_settle_clock,
              test_glitch_pixels_ramp_only, test_glitch_beat_and_seed_paths,
              test_determinism_sample_vs_full):
        f()
        print("PASS " + f.__name__)
    print("OK 5 tests")
