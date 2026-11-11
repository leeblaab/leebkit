"""v1.4 C4b — procedural music bed gates (all five beds).

Every BEDS entry must: run at short/mid/long durations, return EXACTLY
int(dur*SR_OUT) samples, be finite, have a real signal (RMS > 0), peak inside
(0, 0.95], and be deterministic (same inputs -> identical output). Also gates
scan_music() label/BEDS consistency so the UI dropdown can never list a bed
the engine would reject.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio as A  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


for bed_name, fn in sorted(A.BEDS.items()):
    for dur in (4.0, 12.0, 30.0):
        cuts = [d * 0.25 for d in range(1, 12)][: max(1, int(dur / 4))]
        y = fn(dur, cuts)
        n = int(dur * A.SR_OUT)
        check("%s %.0fs length" % (bed_name, dur), len(y) == n, "%d != %d" % (len(y), n))
        check("%s %.0fs finite" % (bed_name, dur), bool(np.all(np.isfinite(y))))
        rms = float(np.sqrt(np.mean(y ** 2)))
        peak = float(np.max(np.abs(y)))
        check("%s %.0fs signal" % (bed_name, dur), rms > 0.01, "rms=%.4f" % rms)
        check("%s %.0fs peak sane" % (bed_name, dur), 0.0 < peak <= 0.95, "peak=%.3f" % peak)
    y1 = fn(8.0, [2.5, 5.0], t_typing=(1.0, 6.0))
    y2 = fn(8.0, [2.5, 5.0], t_typing=(1.0, 6.0))
    check("%s deterministic" % bed_name, np.array_equal(y1, y2))

# scan_music must list exactly the BEDS names (procedural ids) + none
ids = [m["id"] for m in A.scan_music()]
check("scan_music lists all beds", all(b in ids for b in A.BEDS), ids)
check("scan_music has none", "none" in ids)
for m in A.scan_music():
    if m["id"] != "none" and not m["id"].startswith("file:"):
        check("scan_music id %s is a real bed" % m["id"], m["id"] in A.BEDS)

print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
