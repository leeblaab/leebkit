"""C4 (v1.41) — S5 absolute music-bed paths map into the shipped music/ folder.

Audit #1 S5: the v1.31 confinement only guards RELATIVE beds; an absolute bed
path in project JSON bypassed it entirely and build_audio would read ANY file
on disk. Yasser ruling: fix = basename-map absolutes into music/ (the UI file
picker hands over absolutes from C:\Products\reelkit\music — same basename, so
the shipped copy is the right one), then apply realpath confinement to the
resolved path unconditionally.

Gates drive core.audio._resolve_bed() directly (same helper build_audio uses):
1. absolute path whose basename exists in music/  -> mapped into music/
2. absolute path OUTSIDE music/ with a foreign name -> ValueError
3. relative escape bed ("../x") -> still rejected (v1.31 behavior intact)
4. plain basename bed -> maps into music/ (regression)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio  # noqa: E402

MUSIC = os.path.join(ROOT, "music")
BED = "bed_cave_drone.mp3"

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


resolve = getattr(audio, "_resolve_bed", None)
if resolve is None:
    print("FAIL _resolve_bed() missing from core.audio — RED on HEAD")
    sys.exit(1)

# 1. absolute path inside music/ — the UI file-picker case
p = resolve(os.path.join(MUSIC, BED))
check("absolute bed inside music/ maps to itself",
      os.path.realpath(p) == os.path.realpath(os.path.join(MUSIC, BED)), p)

# 2. absolute path elsewhere on disk with a foreign name -> must reject
try:
    p = resolve(os.path.join(ROOT, "docs", "not_a_bed.mp3"))
    check("absolute bed outside music/ rejected", False, "returned %s" % p)
except ValueError:
    check("absolute bed outside music/ rejected", True)

# 2b. absolute path to a REAL file outside music/ whose basename also exists
#     in music/ -> maps to the shipped copy (never reads the foreign file)
foreign = os.path.join(ROOT, "output", BED)
shipped = os.path.join(MUSIC, BED)
if not os.path.exists(foreign):
    import shutil
    shutil.copyfile(shipped, foreign)
try:
    p = resolve(foreign)
    check("foreign absolute with known basename maps into music/",
          os.path.realpath(p) == os.path.realpath(shipped), p)
finally:
    os.remove(foreign)

# 3. relative escape still rejected (v1.31 regression guard)
try:
    p = resolve("../secrets.mp3")
    check("relative escape bed still rejected", False, "returned %s" % p)
except ValueError:
    check("relative escape bed still rejected", True)

# 4. plain basename still works
p = resolve(BED)
check("basename bed maps into music/",
      os.path.realpath(p) == os.path.realpath(shipped), p)

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
