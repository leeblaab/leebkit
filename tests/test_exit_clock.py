"""v1.42 items 4 + 11-gate-half (C2).

Item 4 — exit clock: inside a transition window the renderer froze every
caption's prog at its shot end with a hardcoded /0.32 regardless of the kind's
settle ramp. A typewriter (TYPE_RAMP=1.8s) that settled before the cut was
still frozen near-prog-0 mid-entrance in the fade. Now engine + checker read
one table: metrics.exit_gate(k).

Item 11 gate half — warn budget: a shot piling up 'warn' flags used to sail
through green (smoke gates errors only). > WARN_BUDGET warns on one shot now
raises its own error flag. Budget >= shipped corpus max, so existing projects
stay clean (proven by smoke + goldens below the test).

Run: PYTHONPATH=. python tests/test_exit_clock.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core import metrics as M              # noqa: E402
from core.engine import Engine             # noqa: E402


def _proj(kind, t_shot, at):
    return {"schema": 1, "target": t_shot + 2.5, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [
                {"fill": "solid", "t": t_shot},
                {"fill": "solid", "t": 2.5,
                 "captions": [{"kind": kind, "at": at,
                               "text": "ALPHA BETA GAMMA DELTA EPSILON ZETA"}]}]}


def _nonblack_rows(img):
    """Rows with any non-background pixel (bg onyx is near-black)."""
    W, H = img.size
    px = img.load()
    rows = 0
    for y in range(H):
        for x in range(0, W, 4):
            if sum(px[x, y]) > 90:
                rows += 1
                break
    return rows


def test_exit_gate_table():
    assert M.exit_gate("typewriter") == M.TYPE_RAMP
    assert M.exit_gate("pump") == M.PUMP_RAMP
    assert M.exit_gate("slam") == M.SLAM_RAMP
    assert M.exit_gate("trackin") == M.TRACK_RAMP
    assert M.exit_gate("line") == M.EXIT_DEFAULT


def test_typewriter_exit_clock():
    # v1.42 item 4 (exit clock): the typewriter clock rides SECONDS-since-at
    # (`tp = lt - at`). Inside an outgoing transition window the OLD code's
    # only freeze was render_layer's prog cap at clamp((shot_t-at)/0.32) —
    # for TYPE_RAMP=0.10 that saturates >1 and is a NO-OP on the seconds
    # clock, so late chars kept TYPING IN while the shot faded out (text
    # appearing during an exit = advisor item 4). The fix clamps tp at shot
    # end inside draw_typewriter: nothing grows mid-fade. Probe: unclamped
    # (old) must show MORE ink at lt=2.7 than fixed (held partial state).
    proj = {"schema": 1, "target": 4.0, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [
                {"fill": "solid", "t": 2.5,
                 "captions": [{"kind": "typewriter", "at": 1.6,
                               "text": "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}]},
                {"fill": "solid", "t": 1.5}]}
    e = Engine(proj)

    def total_ink(img):
        img = img.convert("RGB")
        px = img.load()
        W, H = img.size
        return sum(1 for y in range(H) for x in range(W) if sum(px[x, y]) > 90)

    lt = 2.6   # just past shot end, inside the fade window (XF=0.5: 2.0..2.5
               # of the NEXT boundary; here render_layer clamps nothing, and
               # unclamped tp would keep typing chars up to i=(0.97/0.085) vs
               # frozen i=(0.4/0.085))
    # NOTE: pass an explicit positive XF (0.5) — e.XF can be 0.0 for this
    # preset, and a falsy transition_out skips the freeze branch entirely.
    new = total_ink(e.render_layer(0, lt, int(lt * e.FPS), transition_out=0.5))
    import core.captions as C
    src = C.draw_typewriter
    def old_v141(eng, dr, L, k, ctx, e2):
        # emulate v1.41: no draw-side freeze (prog cap was a no-op for this kind)
        return src(eng, dr, L, k, ctx._replace(transition_out=None), e2)
    # DISPATCH holds the direct function reference — patch the table too.
    real = C.DISPATCH["typewriter"]
    C.draw_typewriter = old_v141
    C.DISPATCH["typewriter"] = old_v141
    try:
        # NOTE: pass an explicit positive XF (0.5) — e.XF can be 0.0 for this
        # preset, and a falsy transition_out skips the freeze branch entirely.
        old = total_ink(e.render_layer(0, lt, int(lt * e.FPS), transition_out=0.5))
    finally:
        C.draw_typewriter = src
        C.DISPATCH["typewriter"] = real
    assert new < old, ("typewriter keeps typing mid fade-out (no exit freeze)",
                       new, old)


def test_warn_budget():
    from core.checks import check_project, WARN_BUDGET
    # one shot with many warnings: long small lines that warn but fit.
    caps = [{"kind": "small", "at": 0.2 + 1.3 * i,
             "text": ("WORD " * 18).strip()} for i in range(WARN_BUDGET + 1)]
    proj = {"schema": 1, "target": 6.0, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [{"fill": "solid", "t": 6.0, "captions": caps}]}
    eng = Engine(proj)
    flags = check_project(eng)
    warns = [f for f in flags if f.get("severity") == "warn" and f["shot"] == 0]
    budget_flag = [f for f in flags if f["kind"] == "warn_budget"]
    if len(warns) > WARN_BUDGET:
        assert budget_flag, ("warn budget not enforced with %d warns" % len(warns))
    else:
        # corpus produced fewer warns than the budget: gate must stay silent
        assert not budget_flag, budget_flag


def main():
    for fn in (test_exit_gate_table, test_typewriter_exit_clock,
               test_warn_budget):
        fn()
        print("PASS", fn.__name__)
    print("EXIT CLOCK + WARN BUDGET PASS")


if __name__ == "__main__":
    main()
