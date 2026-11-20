# SPDX-License-Identifier: AGPL-3.0-only
"""v1.5 item 7 test-first: slam_v2 (scale-only decision per benchmark).

Benchmark verdict (scripts/bench_sprite.py, run on the kinds corpus shot at
1080x1920): full-frame AFFINE sprite transform costs +1737% vs per-frame
redraw — PIL resamples the ENTIRE 1080x1920 canvas even though only the word
box matters. Per the plan's gate (proceed with sprites only at <= +15%),
slam_v2 ships SCALE-ONLY on the existing mkfont redraw path: slam entrance +
squash-stretch (scaleY 0.8 -> 1.1 -> 1 over SLAM_RAMP) + a deterministic
motion trail (2 echo pastes at decaying alpha from earlier scales, pure
function of t). This test locks the clocks/shape BEFORE pixels land.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine, validate_project
from core import metrics as M


def base_proj(caps):
    return {"schema": 1, "name": "t", "preset": "leebdark", "target": 2.0,
            "fps": 30, "music": {"mode": "none"},
            "shots": [{"t": 2.0, "transition": "cut", "captions": caps}]}


# ---------------------------------------------------------------- schema
def test_validate_slam_v2():
    validate_project(base_proj([{"kind": "slam_v2", "at": 0.3, "text": "V2"}]))
    # unknown kind still rejected (whitelist discipline)
    try:
        validate_project(base_proj([{"kind": "slam_v3", "at": 0.3, "text": "X"}]))
        raise AssertionError("unknown kind accepted")
    except ValueError:
        pass


# ---------------------------------------------------------------- clocks
def test_metrics_settle_clock():
    proj = base_proj([{"kind": "slam_v2", "at": 0.4, "text": "CLOCK"}])
    eng = Engine(proj)
    L = proj["shots"][0]["captions"][0]
    m = M.measure(eng, L, "slam_v2", 2.0, float(L["at"]))
    assert abs(m["done_at"] - (0.4 + M.SLAM_RAMP)) < 1e-9, \
        "slam_v2 settle must come from the shared slam clock family"
    # settled caption -> no flags; late-at caption -> 'timing' flag (the
    # single-beat kinds family gate in checks.py, same one slam uses)
    from core.checks import check_project
    flags = [f for f in check_project(eng) if f["kind"] in ("settle", "timing")]
    assert not flags, "settled slam_v2 must not raise settle/timing flags: %s" % flags
    late = base_proj([{"kind": "slam_v2", "at": 1.80, "text": "LATE"}])
    lflags = [f for f in check_project(Engine(late)) if f["kind"] in ("settle", "timing")]
    assert lflags, "late slam_v2 must raise a settle/timing flag"


# ---------------------------------------------------------------- render A/B
def test_squash_stretch_and_trail_pixels():
    proj = base_proj([{"kind": "slam_v2", "at": 0.3, "text": "SQUASH"}])
    eng = Engine(proj)
    i = 0
    # INSIDE the entrance (the shared prog gate fully opens at at+0.32; the
    # slam ramp ends at at+0.26 -> A/B window is lt 0.34..0.5): squash + trail
    # must change pixels vs plain slam.
    diffs = 0
    for lt in (0.34, 0.40, 0.46):
        base = base_proj([{"kind": "slam", "at": 0.3, "text": "SQUASH"}])
        eng2 = Engine(base)
        a = eng.compose_frame(int(round((eng.starts[i] + lt) * eng.FPS)))
        b = eng2.compose_frame(int(round((eng2.starts[i] + lt) * eng2.FPS)))
        if a.tobytes() != b.tobytes():
            diffs += 1
    assert diffs == 3, \
        "slam_v2 entrance frames must differ from plain slam (squash+trail): %d/3" % diffs
    # settled frames identical to plain slam at rest (scale 1, trail gone)
    a = eng.compose_frame(int(round((eng.starts[i] + 1.8) * eng.FPS)))
    b = Engine(base_proj([{"kind": "slam", "at": 0.3, "text": "SQUASH"}])) \
        .compose_frame(int(round((eng.starts[i] + 1.8) * eng.FPS)))
    assert a.tobytes() == b.tobytes(), "settled slam_v2 must equal settled slam"


# ---------------------------------------------------------------- determinism
def test_determinism_sample_vs_full():
    proj = base_proj([{"kind": "slam_v2", "at": 0.3, "text": "DET"}])
    h1 = [Engine(proj).compose_frame(i).tobytes() for i in (8, 12, 16, 24)]
    eng = Engine(proj)
    h2 = [eng.compose_frame(i).tobytes() for i in (8, 12, 16, 24)]
    assert h1 == h2


if __name__ == "__main__":
    for f in (test_validate_slam_v2, test_metrics_settle_clock,
              test_squash_stretch_and_trail_pixels,
              test_determinism_sample_vs_full):
        f()
        print("PASS " + f.__name__)
    print("OK 4 tests")
