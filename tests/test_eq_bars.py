"""v1.5 item 10 (C5): eq_bars kind + VO envelope mix.

"kind": "eq_bars": N bars (default 5, <=7) standing at the bottom safe
margin, heights = abs-sine stack seeded per bar slot, amplitude modulated by
the bed's beat clock when one exists (seed-time fallback otherwise). With a
project `voice` AND vo_lines overlapping the shot, the VO RMS envelope mixes
into the bar heights (precomputed ONCE per shot from the cached piper wavs,
stdlib wave only — no numpy in engine code). Always animating: terminal-like,
no done_at gate; validate gates n/width/at inside the safe area. Determinism:
every input is a pure function of frame index + project JSON -> sample == full.
"""
import json, hashlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine, validate_project
from core import metrics as M


def base_proj(caps, **extra):
    p = {"schema": 1, "name": "t", "preset": "leebdark", "target": 2.0,
         "fps": 30, "music": {"mode": "none"},
         "shots": [{"t": 2.0, "transition": "cut", "captions": caps}]}
    p.update(extra)
    return p


# ---------------------------------------------------------------- schema
def test_validate_eq_bars():
    validate_project(base_proj([{"kind": "eq_bars", "at": 0.2}]))
    validate_project(base_proj([{"kind": "eq_bars", "at": 0.2,
                                 "n": 7, "w": 0.5}]))
    for bad in ({"n": 8}, {"n": 0}, {"w": 1.5}, {"w": 0.05}):
        cap = {"kind": "eq_bars", "at": 0.2}
        cap.update(bad)
        try:
            validate_project(base_proj([cap]))
            raise AssertionError("bad eq_bars field accepted: %r" % bad)
        except ValueError:
            pass


# ---------------------------------------------------------------- metrics
def test_metrics_no_done_at():
    # terminal-like: no settle clock, no timing flag even near shot end
    from core.checks import check_project
    eng = Engine(base_proj([{"kind": "eq_bars", "at": 1.8}]))
    m = M.measure(eng, {"kind": "eq_bars", "at": 1.8}, "eq_bars", 2.0, 1.8)
    assert "done_at" not in m, "eq_bars must not model a settle clock"
    flags = [f for f in check_project(eng) if f["kind"] == "timing"]
    assert not flags, "eq_bars wrongly flagged on timing: %r" % flags


# ---------------------------------------------------------------- pixels
import numpy as np


def _layer(proj, lt):
    eng = Engine(proj)
    return np.asarray(eng.render_layer(0, lt, int(round(lt * eng.FPS))),
                      dtype=int)


def _maxdiff(a, b):
    return int(np.abs(a - b).max())


def test_eq_bars_pixels():
    cap = {"kind": "eq_bars", "at": 0.2}
    f = {lt: _layer(base_proj([cap]), lt) for lt in (0.10, 0.50, 1.9)}
    e = {lt: _layer(base_proj([]), lt) for lt in (0.10, 0.50, 1.9)}

    def bar_px(a, b):
        return int((np.abs(a - b).sum(axis=2) > 60).sum())

    # before at: nothing paints (only grain differs)
    assert _maxdiff(f[0.10], e[0.10]) <= 40, "bars painted before at"
    # after at: bars present...
    assert bar_px(f[0.50], e[0.50]) > 200, "no bars after at"
    # ...and animating: heights differ frame to frame (bar pixels move)
    assert bar_px(f[0.50], f[1.9]) > 100, "bars frozen — must always animate"
    # safe area: bars stand ON the bottom safe line and never below it
    eng = Engine(base_proj([cap]))
    floor = eng.H - eng.L["bottom_inset"]
    d = np.abs(f[1.9] - e[1.9]) > 60
    assert int(d[floor + 2:, :, :].sum()) == 0, \
        "bars breach the bottom safe margin"
    assert int(d[:floor + 1, :, :].sum()) > 500, \
        "bar pixels must sit above the safe floor line"


# ---------------------------------------------------------------- determinism
def test_determinism_sample_vs_full():
    p = base_proj([{"kind": "eq_bars", "at": 0.2, "n": 6}], bpm=120)
    eng1 = Engine(p)
    eng2 = Engine(json.loads(json.dumps(p)))
    for lt in (0.5, 1.2):
        idx = int(round(lt * eng1.FPS))
        a = hashlib.sha256(eng1.render_layer(0, lt, idx).tobytes()).hexdigest()
        b = hashlib.sha256(eng2.render_layer(0, lt, idx).tobytes()).hexdigest()
        assert a == b, "sample vs full mismatch at %.2f" % lt


# ------------------------------------------------------- bed-wired envelope
def test_vo_envelope_from_bed():
    """set_vo_bed wires the real mix: a loud window in the bed must raise
    bar heights above the beat-only baseline; without the bed the envelope
    stays None (beat-only path, zero side effects)."""
    p = base_proj([{"kind": "eq_bars", "at": 0.2}], bpm=120)
    p["voice"] = "test"
    p["vo_lines"] = [{"shot": 0, "offset": 0.0, "text": "hello world"}]
    p["target"] = 4.0
    p["shots"][0]["t"] = 4.0
    eng = Engine(p)
    assert eng.vo_envelope(0) is None, "no bed wired -> envelope must be None"
    # fake bed: silent first half, full-scale square second half (2 s each)
    sr = 48000
    bed = [0.0] * (sr // 2) + [0.9] * (sr // 2)
    eng.set_vo_bed(bed)
    env = eng.vo_envelope(0)
    assert env is not None, "bed wired -> envelope must exist"
    early = env[int(0.5 * eng.FPS)]      # silent half
    late = env[int(3.5 * eng.FPS)]       # loud half
    assert late > 0.9 and early < 0.01, \
        "envelope must track the bed: early=%.3f late=%.3f" % (early, late)
    # bars with the bed wired must be TALLER than beat-only at a frame where
    # the beat stack is NOT already pinned at the ceiling. NOTE: eq_bar_height
    # reads n/w from the CAPTION dict L (not the layout), and `idx` indexes the
    # envelope by GLOBAL frame index.
    cap = {"kind": "eq_bars", "at": 0.2}
    envl = eng.vo_envelope(0)
    gi = int(round(3.5 * eng.FPS))     # inside the loud half of the fake bed
    h_beat = [M.eq_bar_height(eng, cap, b, 3.5, gi, None, gi)[1] for b in range(5)]
    h_bed = [M.eq_bar_height(eng, cap, b, 3.5, gi, envl, gi)[1] for b in range(5)]
    assert all(b >= a for a, b in zip(h_beat, h_bed)) and \
        sum(h_bed) > sum(h_beat), "bed must raise bar heights: %r vs %r" % (h_beat, h_bed)


if __name__ == "__main__":
    test_validate_eq_bars(); print("PASS test_validate_eq_bars")
    test_metrics_no_done_at(); print("PASS test_metrics_no_done_at")
    test_eq_bars_pixels(); print("PASS test_eq_bars_pixels")
    test_determinism_sample_vs_full(); print("PASS test_determinism_sample_vs_full")
    test_vo_envelope_from_bed(); print("PASS test_vo_envelope_from_bed")
    print("OK 5 tests")

