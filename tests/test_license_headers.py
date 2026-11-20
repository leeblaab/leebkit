# SPDX-License-Identifier: AGPL-3.0-only
"""B1 (v1.6) — license-header consistency gate.

Audit #2 B1 (verified real): all 48 tracked .py files lacked an SPDX header while
README/LICENSE declare AGPL-3.0-only. Gate: every tracked .py carries
`SPDX-License-Identifier: AGPL-3.0-only` within its first three lines (so the
notice is visible at the top, not buried), and the count matches git ls-files.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDLE = "SPDX-License-Identifier: AGPL-3.0-only"

files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                       capture_output=True, text=True).stdout.split()
FAILS = []
if not files:
    print("FAIL no tracked .py found (git ls-files empty)")
    sys.exit(1)
for f in files:
    p = os.path.join(ROOT, f)
    try:
        head = open(p, encoding="utf-8").read().split("\n")[:3]
    except Exception as ex:
        FAILS.append("%s (read error %s)" % (f, ex))
        continue
    if not any(NEEDLE in ln for ln in head):
        FAILS.append(f)
if FAILS:
    print("FAIL %d tracked .py missing top-of-file SPDX AGPL header:" % len(FAILS))
    for f in FAILS[:20]:
        print("  " + f)
else:
    print("PASS all %d tracked .py carry SPDX AGPL-3.0-only header" % len(files))
print("\n%d FAIL(S)" % (1 if FAILS else 0))
sys.exit(1 if FAILS else 0)
