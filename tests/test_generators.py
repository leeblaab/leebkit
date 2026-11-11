#!/usr/bin/env python3
"""v1.4 C3 — background generator core tests (written RED-first).

Run:  PYTHONPATH=. .venv/Scripts/python.exe tests/test_generators.py

Covers the plan's C3 gates: determinism (same call -> identical pixels),
driver continuity (consecutive offsets stay coherent, no per-frame noise
resample), palette freeze (fixed designed palettes, independent of the
project color preset), grain coherence (one static texture drifting with the
driver, NOT fresh noise per frame), cache identity (static layers reused),
validate_project gen-name whitelist, and the engine fill="gen:<name>" branch.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = []


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" — " + detail if detail else ""))
    if not cond:
        fails.append(name)


def base_proj(fill):
    return {"schema": 1, "name": "gentest", "target": 2.0, "fps": 24,
            "width": 320, "height": 480, "voice": "none",
            "music": {"bed": "none"},
            "shots": [{"t": 2.0, "transition": "cut", "fill": fill,
                       "captions": []}]}


def main():
    # ---- module + preset registry -------------------------------------
    try:
        from core import generators as G
    except Exception as e:
        print("FAIL import core.generators — %s" % e)
        print("\n%d FAILURES" % (len(fails) + 1))
        sys.exit(1)

    PRESETS = ["midnight_drift", "grid_pulse", "paper_grain",
               "ember_flow", "deep_current", "signal_field"]
    for p in PRESETS:
        ok("preset registered: %s" % p, p in G.GEN_PRESETS,
           ", ".join(sorted(G.GEN_PRESETS)) if p not in G.GEN_PRESETS else "")

    W, H = 320, 480

    # ---- determinism: identical call -> identical pixels --------------
    a = G.render("midnight_drift", W, H, offset=1.7, amp=1.0)
    b = G.render("midnight_drift", W, H, offset=1.7, amp=1.0)
    ok("determinism: same (preset,W,H,offset,amp) -> identical array",
       a == b if not hasattr(a, "tobytes") else a.tobytes() == b.tobytes())

    # different offset -> different pixels (it must actually animate)
    c = G.render("midnight_drift", W, H, offset=1.9, amp=1.0)
    same = (a == c) if not hasattr(a, "tobytes") else (a.tobytes() == c.tobytes())
    ok("offset changes pixels (driver actually drives)", not same)

    # ---- driver continuity: consecutive frames move, never jump -------
    f0 = G.render("grid_pulse", W, H, offset=1.00, amp=1.0)
    f1 = G.render("grid_pulse", W, H, offset=1.04, amp=1.0)   # 1 frame @24fps
    f2 = G.render("grid_pulse", W, H, offset=3.50, amp=1.0)   # far away
    import numpy as np
    g0, g1, g2 = (np.asarray(x, dtype=np.int16) for x in (f0, f1, f2))
    d_near = int(np.abs(g1 - g0).mean())
    d_far = int(np.abs(g2 - g0).mean())
    ok("driver continuity: neighbor-frame delta < far-frame delta",
       d_near < d_far, "near=%d far=%d" % (d_near, d_far))

    # ---- grain coherence: paper_grain must NOT resample noise per frame
    # Fresh-noise-per-frame makes the NEIGHBOR delta as big as the far delta.
    p0 = G.render("paper_grain", W, H, offset=2.00, amp=1.0)
    p1 = G.render("paper_grain", W, H, offset=2.04, amp=1.0)
    p2 = G.render("paper_grain", W, H, offset=5.50, amp=1.0)
    h0, h1, h2 = (np.asarray(x, dtype=np.int16) for x in (p0, p1, p2))
    dn = int(np.abs(h1 - h0).mean())
    df = int(np.abs(h2 - h0).mean())
    ok("grain coherence: static texture drifts (neighbor delta << far delta)",
       dn * 3 < df, "near=%d far=%d" % (dn, df))

    # ---- palette freeze: designed colors, independent of anything else -
    pal = G.palette("midnight_drift")
    pal2 = G.palette("midnight_drift")
    ok("palette frozen across calls", list(pal) == list(pal2))
    try:
        import json as _json
        pdir = os.path.join(ROOT, "presets")
        proj_presets = set()
        for fn in os.listdir(pdir):
            if not fn.endswith(".json"):
                continue
            d = _json.load(open(os.path.join(pdir, fn), encoding="utf-8"))
            for key in ("bg", "accent", "white"):
                v = (d.get("colors") or {}).get(key)
                if v:
                    proj_presets.add(v.lower())
        assert proj_presets, "no project preset colors found — check presets/ dir"
        hit = []
        for gp in PRESETS:
            for c in G.palette(gp):
                if str(c).lower() in proj_presets:
                    hit.append((gp, c))
        ok("generator palettes do not reuse project-preset colors", not hit,
           "overlap: %s" % hit if hit else "")
    except Exception as e:
        ok("palette freeze check ran", False, str(e))

    # ---- cache identity: static layers reused across offsets ----------
    G.render("signal_field", W, H, offset=0.0, amp=1.0)   # warm the key
    n1 = len(G._LAYER_CACHE)
    G.render("signal_field", W, H, offset=9.0, amp=1.0)
    n2 = len(G._LAYER_CACHE)
    ok("static layers cached per (preset,W,H) — second offset adds no new layer",
       n2 == n1, "cache entries %d -> %d" % (n1, n2))

    # ---- validate_project whitelist -----------------------------------
    from core.engine import validate_project
    try:
        validate_project(base_proj("gen:ember_flow"))
        ok("validate accepts fill=gen:ember_flow", True)
    except ValueError as e:
        ok("validate accepts fill=gen:ember_flow", False, str(e))
    try:
        validate_project(base_proj("gen:not_a_preset"))
        ok("validate REJECTS unknown gen name", False, "no error raised")
    except ValueError:
        ok("validate REJECTS unknown gen name", True)
    try:
        validate_project(base_proj("grid"))
        ok("validate still accepts legacy fill=grid", True)
    except ValueError as e:
        ok("validate still accepts legacy fill=grid", False, str(e))

    # ---- engine branch: fill=gen:<name> renders through Engine --------
    try:
        from core.engine import Engine
        eng = Engine(base_proj("gen:deep_current"), media_dir=os.path.join(ROOT, "samples", "media"))
        img0 = eng.compose_frame(12)
        img1 = eng.compose_frame(30)
        ok("engine renders gen: shot (frames differ over time)",
           img0.tobytes() != img1.tobytes())
        # dim overlay must still apply on top of generated bases
        eng2 = Engine({**base_proj("gen:deep_current"),
                       "shots": [{"t": 2.0, "transition": "cut", "fill": "gen:deep_current",
                                  "dim": 1.0, "captions": []}]},
                      media_dir=os.path.join(ROOT, "samples", "media"))
        dimg = eng2.compose_frame(12)
        ok("dim overlay applies over generated base (max channel < 90 at dim=1.0)",
           int(np.asarray(dimg).max()) < 90, "max=%d" % int(np.asarray(dimg).max()))
    except Exception as e:
        ok("engine gen branch renders", False, repr(e))

    print()
    if fails:
        print("%d FAILURES: %s" % (len(fails), ", ".join(fails)))
        sys.exit(1)
    print("ALL GENERATOR TESTS PASS")


if __name__ == "__main__":
    main()
