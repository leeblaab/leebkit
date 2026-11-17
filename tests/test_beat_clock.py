# v1.42 item 3: beat clock — BED_BPM single source + Engine.beat_phase + FrameCtx.beat
import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

import core.audio as A
from core.engine import Engine


def base_proj(**over):
    p = {"schema": 1, "target": 4.0, "fps": 24, "width": 320, "height": 480,
         "preset": "onyx", "music": {"mode": "none"},
         "shots": [{"fill": "solid", "t": 4.0,
                    "captions": [{"kind": "kicker", "at": 0.3, "text": "BEAT"}]}]}
    p.update(over)
    return p


def test_bed_bpm_table():
    assert A.BED_BPM == {"pulse": 120, "low_drive": 92, "sparkle": 130,
                         "synthwave": 100}
    # every procedural bed name has a tempo (ambient_glow: no clock = None)
    for name in A.BEDS:
        assert (name in A.BED_BPM) or name == "ambient_glow", name


def test_beat_phase_values():
    e = Engine(base_proj(music={"bed": "pulse"}))
    assert e.BPM == 120
    # 120bpm -> beat every 0.5s; at fps 24 frame 12 = 0.5s = phase 0 (wrap)
    assert abs(e.beat_phase(0.0) - 0.0) < 1e-9
    assert abs(e.beat_phase(0.25) - 0.5) < 1e-9
    assert abs(e.beat_phase(0.5) - 0.0) < 1e-9   # wraps
    assert abs(e.beat_phase(1.0) - 0.0) < 1e-9


def test_beat_none_without_clock():
    e = Engine(base_proj())                    # mode none -> no clock
    assert e.BPM is None and e.beat_phase(1.0) is None
    e2 = Engine(base_proj(music={"bed": "file:song.mp3"}))   # file bed, no BPM.json yet
    assert e2.BPM is None and e2.beat_phase(1.0) is None


def test_bpm_override():
    e = Engine(base_proj(bpm=96))
    assert e.BPM == 96
    assert abs(e.beat_phase(60 / 96) - 0.0) < 1e-9
    for bad in ("x", 25, 300):
        try:
            Engine(base_proj(bpm=bad))
            raise AssertionError("bpm %r accepted" % (bad,))
        except ValueError:
            pass


def test_frame_ctx_beat():
    # FrameCtx receives the clock; deterministic across separate Engine builds
    import core.captions as C
    seen = []
    src = C.DISPATCH["kicker"]
    def spy(eng, dr, L, k, ctx, e2):
        seen.append(ctx.beat)
        return src(eng, dr, L, k, ctx, e2)
    real = C.DISPATCH["kicker"]
    C.DISPATCH["kicker"] = spy
    try:
        for eng in (Engine(base_proj(music={"bed": "sparkle"})),
                    Engine(base_proj(music={"bed": "sparkle"}))):
            eng.render_layer(0, 1.0, 24)       # frame idx 24 -> g = 1.0
    finally:
        C.DISPATCH["kicker"] = real
    assert len(seen) == 2 and seen[0] is not None and seen[0] == seen[1], seen
    # sparkle 130bpm at g=1.0 -> frac(130/60)=frac(2.1666..)=1/6
    assert abs(seen[0] - (130 / 60.0 % 1.0)) < 1e-9


def main():
    for fn in (test_bed_bpm_table, test_beat_phase_values,
               test_beat_none_without_clock, test_bpm_override,
               test_frame_ctx_beat):
        fn()
        print("PASS", fn.__name__)
    print("BEAT CLOCK PASS")


if __name__ == "__main__":
    main()
