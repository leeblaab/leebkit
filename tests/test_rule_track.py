"""v1.5 item 9 (C4): rule_draw micro-kind + track_collapse fx.

rule_draw: a standalone accent rule that draws left->right over POP_RAMP,
width from L["w"] (fraction of safe width) or measured text when no w.
track_collapse: fx on accent_word/title — tracking starts +18px and
collapses to 0 over TRACK_RAMP (trackin math inverted). Opt-in; default
path byte-identical.
"""
import json, hashlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine, validate_project
from core import metrics as M


def base_proj(caps):
    return {"schema": 1, "name": "t", "preset": "leebdark", "target": 2.0,
            "fps": 30, "music": {"mode": "none"},
            "shots": [{"t": 2.0, "transition": "cut", "captions": caps}]}


# ---------------------------------------------------------------- schema
def test_validate_rule_draw_and_fx():
    validate_project(base_proj([{"kind": "rule_draw", "at": 0.3, "w": 0.4}]))
    validate_project(base_proj([{"kind": "accent_word", "at": 0.3,
                                 "text": "TRK", "fx": "track_collapse"}]))
    validate_project(base_proj([{"kind": "title_block", "at": 0.3,
                                 "text": "A B", "fx": "track_collapse"}]))
    try:
        validate_project(base_proj([{"kind": "accent_word", "at": 0.3,
                                     "text": "X", "fx": "track_bloat"}]))
        raise AssertionError("bad fx name accepted")
    except ValueError:
        pass


# ---------------------------------------------------------------- checker
def test_checker_rule_draw_timing():
    # rule_draw must settle inside the shot (single-beat family)
    from core.checks import check_project
    p = base_proj([{"kind": "rule_draw", "at": 1.9, "w": 0.4}])
    flags = [f for f in check_project(Engine(p)) if f["kind"] == "timing"]
    assert flags, "rule_draw settling past shot end not flagged"


# ---------------------------------------------------------------- pixels: rule_draw
import numpy as np


def _layer(proj, lt):
    """Caption LAYER render (grain rides it too — per-frame seeded, so
    cross-frame hash equality is impossible; pixel-DIFF is the honest test:
    grain noise differs by <=30/255, a drawn rule is full-alpha accent)."""
    eng = Engine(proj)
    return np.asarray(eng.render_layer(0, lt, int(round(lt * eng.FPS))),
                      dtype=int)


def _maxdiff(a, b):
    return int(np.abs(a - b).max())


def test_rule_draw_pixels():
    cap = {"kind": "rule_draw", "at": 0.3, "w": 0.4}
    f = {lt: _layer(base_proj([cap]), lt) for lt in (0.10, 0.36, 0.50, 0.70, 1.9)}
    e = {lt: _layer(base_proj([]), lt) for lt in (0.10, 0.36, 0.50, 0.70, 1.9)}
    # before `at`: only grain noise differs (rule must not paint early)
    assert _maxdiff(f[0.10], e[0.10]) <= 40, "rule painted before at"
    # inside the ramp: a real accent bar appears and GROWS frame over frame
    # (early-ramp alpha rides prog*1.3, so gate on ACCENT-colored pixels)
    def accent_px(f, e):
        d = np.abs(f - e).sum(axis=2)
        return int((d > 60).sum())
    assert accent_px(f[0.36], e[0.36]) > 100, "no rule mid-ramp"
    assert accent_px(f[0.50], e[0.50]) > accent_px(f[0.36], e[0.36]), \
        "width not growing inside ramp"
    # settled: rule stays on screen, full-strength accent present
    assert _maxdiff(f[1.9], e[1.9]) > 150, "settled rule vanished"


# ---------------------------------------------------------------- fx: track_collapse
def test_track_collapse_pixels():
    cap = {"kind": "accent_word", "at": 0.3, "text": "COLLAPSE",
           "fx": "track_collapse"}
    plain = {"kind": "accent_word", "at": 0.3, "text": "COLLAPSE"}
    # same FRAME INDEX (same grain seed) -> any real diff is fx effect only
    f_fx = {lt: _layer(base_proj([cap]), lt) for lt in (0.10, 0.40, 0.60, 1.95)}
    f_pl = {lt: _layer(base_proj([plain]), lt) for lt in (0.10, 0.40, 0.60, 1.95)}
    assert _maxdiff(f_fx[0.10], f_pl[0.10]) == 0, "fx leaked before at"
    assert _maxdiff(f_fx[0.40], f_pl[0.40]) > 60, "no tracking offset mid-ramp"
    # settled: collapse ends at trk=0 -> frame must equal the plain kind's
    # settled frame byte-for-byte (convergent settle, like slam_v2)
    assert _maxdiff(f_fx[1.95], f_pl[1.95]) == 0, \
        "settled track_collapse != plain accent_word"


# ---------------------------------------------------------------- determinism
def test_determinism_sample_vs_full():
    caps = [{"kind": "rule_draw", "at": 0.3, "w": 0.4},
            {"kind": "accent_word", "at": 0.6, "text": "TRK FX",
             "fx": "track_collapse"}]
    p = base_proj(caps)
    eng1 = Engine(p)
    eng2 = Engine(json.loads(json.dumps(p)))
    for lt in (0.5, 1.2):
        idx = int(round(lt * eng1.FPS))
        a = hashlib.sha256(eng1.render_layer(0, lt, idx).tobytes()).hexdigest()
        b = hashlib.sha256(eng2.render_layer(0, lt, idx).tobytes()).hexdigest()
        assert a == b, "sample vs full mismatch at %.2f" % lt


if __name__ == "__main__":
    test_validate_rule_draw_and_fx(); print("PASS test_validate_rule_draw_and_fx")
    test_checker_rule_draw_timing(); print("PASS test_checker_rule_draw_timing")
    test_rule_draw_pixels(); print("PASS test_rule_draw_pixels")
    test_track_collapse_pixels(); print("PASS test_track_collapse_pixels")
    test_determinism_sample_vs_full(); print("PASS test_determinism_sample_vs_full")
    print("OK 5 tests")
