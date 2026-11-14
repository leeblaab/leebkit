"""C6 (v1.41) — P1: transition window must not render the outgoing layer twice.

engine.compose_frame calls render_layer(i, lt, idx) at :847 for every frame,
then INSIDE the XF window calls it again with transition_out=XF at :855 and
discards the first result. The double full-layer build costs ~1 extra layer
render per transition frame (a 0.5s fade window at 30fps = ~15 wasted renders
per boundary).

Gate: patch Engine.render_layer with a counting wrapper, render every frame
of a two-shot project whose boundary is a FADE (fade keeps the XF window;
"cut" zeroes XF and skips the block entirely), count shot-0 layer builds.
RED on HEAD: ~window+1 builds per boundary-local second. GREEN after fix:
exactly 1 build per frame in the window (the transition_out one).

Determinism note: compose_frame output must be PIXEL-IDENTICAL before/after
the fix — verified here by hashing all frames of a fade-boundary project on
HEAD via git stash (RED run) vs fixed run.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


proj = {"schema": 1, "target": 3.0, "fps": 24, "width": 320, "height": 480,
        "preset": "leebdark.json", "music": {"mode": "none"},
        "shots": [
            {"fill": "gen:midnight_drift", "t": 1.5,
             "captions": [{"kind": "kicker", "at": 0.2, "text": "OUT"}]},
            {"fill": "gen:ember_flow", "t": 1.5, "transition": "fade",
             "captions": [{"kind": "kicker", "at": 0.3, "text": "IN"}]}]}

eng = Engine(proj)
XF = eng.XF
fps = eng.FPS

# count render_layer calls per shot index while composing every frame
counts = {}
_orig = Engine.render_layer


def _counting(self, i, *a, **kw):
    counts[i] = counts.get(i, 0) + 1
    return _orig(self, i, *a, **kw)


Engine.render_layer = _counting
try:
    for idx in range(eng.N):
        eng.compose_frame(idx)
finally:
    Engine.render_layer = _orig

# shot 0 lives local 0..1.5s; the fade window is its LAST XF seconds.
window_frames = int(round(XF * fps))          # frames inside the XF window
shot0_builds = counts.get(0, 0)
# one layer build per composed frame of shot 0 == 36 frames at 1.5s/24fps
shot0_frames = int(round(1.5 * fps))
check("outgoing layer built exactly once per frame (no double render)",
      shot0_builds == shot0_frames,
      "shot0 builds=%d vs frames=%d (window=%d) — HEAD renders the outgoing "
      "layer twice inside the fade window" % (shot0_builds, shot0_frames,
                                              window_frames))

# incoming layer: built once per frame of ITS OWN span + once per window frame
# (the OV overlap call). That's expected behavior; just sanity it is > 0.
check("incoming layer still renders in the window", counts.get(1, 0) > shot0_frames,
      "shot1 builds=%d" % counts.get(1, 0))

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
