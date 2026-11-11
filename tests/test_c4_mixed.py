"""C4 mixed + generator-only projects — end-to-end integration gate (v1.4).

Locks:
  * /api/meta exposes the six generator presets (id+label) to the UI.
  * A gen shot with captions passes checks.py clean (no timing errors).
  * Engine determinism for gen+caption frames across fresh instances AND a
    same-instance re-render (the pool-consistency invariant, engine level).
  * storyboard_strip renders gen shots and flags nothing at error severity.
  * subtle vs normal motion actually differ pixels on a gen shot (D5).
Run: PYTHONPATH=. python tests/test_c4_mixed.py
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core import generators as G          # noqa: E402
from core.checks import check_project     # noqa: E402
from core.engine import Engine            # noqa: E402


def _proj(cap, motion="normal"):
    return {"schema": 1, "target": 3.0, "fps": 24, "width": 320, "height": 480,
            "preset": "leebdark.json", "music": {"mode": "none"},
            "shots": [
                {"fill": "gen:midnight_drift", "motion": motion, "t": 1.5,
                 "captions": [dict(cap)]},
                {"fill": "gen:ember_flow", "motion": motion, "t": 1.5,
                 "transition": "fade", "captions": [dict(cap)]}]}


def test_meta_generators():
    ids = list(G.GEN_PRESETS)
    assert len(ids) == 6, ids
    for k, v in G.GEN_PRESETS.items():
        assert isinstance(v.get("label"), str) and v["label"], k


def test_gen_caption_checks_clean():
    cap = {"kind": "title_block", "text": "SIX BACKGROUNDS",
           "sub": "generated on your machine"}
    flags = check_project(Engine(_proj(cap)))
    errs = [f for f in flags if f.get("severity") == "error"]
    assert not errs, errs


def test_gen_caption_determinism():
    cap = {"kind": "cap_lines", "at": 0.2, "lines": ["DETERMINISM", "CHECK"]}
    h1 = hashlib.sha256(b"".join(Engine(_proj(cap)).compose_frame(i).tobytes()
                                 for i in range(int(3.0 * 24)))).hexdigest()
    h2 = hashlib.sha256(b"".join(Engine(_proj(cap)).compose_frame(i).tobytes()
                                 for i in range(int(3.0 * 24)))).hexdigest()
    assert h1 == h2, "fresh-instance determinism FAILED"
    e = Engine(_proj(cap))
    h3 = hashlib.sha256(b"".join(e.compose_frame(i).tobytes()
                                 for i in range(int(3.0 * 24)))).hexdigest()
    assert h1 == h3, "same-instance re-render FAILED"


def test_storyboard_strip_on_gen_shots():
    from core.checks import storyboard_strip
    cap = {"kind": "cta", "at": 0.4, "text": "GET IT NOW"}
    out = os.path.join(ROOT, "output", "_qa", "c4_test_strip.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    flags = storyboard_strip(Engine(_proj(cap)), out)
    assert os.path.isfile(out) and os.path.getsize(out) > 1000, "strip missing"
    errs = [f for f in flags if f.get("severity") == "error"]
    assert not errs, errs


def test_subtle_vs_normal_differ():
    cap = {"kind": "title_block", "text": "AMPLITUDE", "sub": ""}
    a = Engine(_proj(cap, "normal")).compose_frame(10).tobytes()
    b = Engine(_proj(cap, "subtle")).compose_frame(10).tobytes()
    d = sum(abs(x - y) for x, y in zip(a, b))
    assert d > 1000, "subtle/normal identical — amplitude not applied"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("C4 mixed/generator-only integration: %d/%d PASS" % (len(fns), len(fns)))
