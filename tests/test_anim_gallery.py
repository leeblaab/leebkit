"""v1.36 live-test obs #1 regression: animation gallery tiles must render for
every preset. The C1 portrait-tier whitelist rejected the old 540x960 internal
gallery size, so generate_gallery crashed inside Engine.__init__ and the UI
showed "rendering..." placeholders forever. In-process only (never the live
server). Run: PYTHONPATH=. python tests/test_anim_gallery.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from core import anim_gallery as AG          # noqa: E402
from core.engine import Engine, load_preset  # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" — " + detail if detail else ""))
    if not cond:
        fails.append(name)


def main():
    # 1. gallery render size must be tier-legal for portrait projects
    P = load_preset("neonlight")
    capA, capB = AG._demo_captions()
    proj = {"schema": 1, "name": "anim", "target": 2.0, "fps": 30,
            "width": AG.RENDER_W, "height": AG.RENDER_H,
            "shots": [{"t": 1.0, "transition": "cut", "captions": capA},
                      {"t": 1.0, "transition": "cut", "captions": capB}]}
    try:
        Engine(proj, preset=P)
        ok("gallery render size tier-legal", True,
           "%dx%d" % (AG.RENDER_W, AG.RENDER_H))
    except ValueError as e:
        ok("gallery render size tier-legal", False, str(e))

    # 2. every tile for every preset becomes ready (idempotent build)
    for preset in ("leebdark", "neonlight"):
        try:
            AG.generate_gallery(preset)
        except Exception as e:
            ok("gallery builds for %s" % preset, False, repr(e))
            continue
        m = AG.gallery_manifest(preset)
        not_ready = [it["id"] for c in m["categories"] for it in c["items"]
                     if not it["ready"]]
        ok("all tiles ready (%s)" % preset, not not_ready, str(not_ready[:5]))
        tiny = []
        seen = set()
        for c in m["categories"]:
            for it in c["items"]:
                p = os.path.join(AG.GALLERY_DIR, it["url"].rsplit("/", 1)[1])
                if p in seen:
                    continue
                seen.add(p)
                if not os.path.exists(p) or os.path.getsize(p) < 1000:
                    tiny.append(p)
        ok("tiles non-trivial webp (%s)" % preset, not tiny, str(tiny[:3]))

    print("\n%d FAIL(S)" % len(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
