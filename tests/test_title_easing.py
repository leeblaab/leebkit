"""C7 gate: title_block pop-in element clocks share ONE settle time (metrics source).

The external typography review asked for overshoot easing on the title pop-in.
Ground truth (probe, 2026-11-11): word_pop/big_number ALREADY ease with back-out
overshoot (ease_ow); what title_block actually lacked was element-clock spread —
the underline grew on raw prog (lands at at+POP_RAMP) while the sub plate ran a
private prog*1.3 curve (lands early). Fix: one TITLE_PLATE_K constant, both
elements consume it plus a shared back-out rise (ease_ow -> TITLE_RISE_PX),
metrics.measure exposes done_at so checks gate title settle like panels/chips
do. This test locks that parity BEFORE any pixels change.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import Engine
from core import metrics as M

proj = json.load(open(os.path.join(ROOT, "tests", "golden", "kinds_corpus.json")))
eng = Engine(proj)
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# 1. constant exists and is > 1 (overshoot-style early settle), single source
check("TITLE_PLATE_K in metrics", hasattr(M, "TITLE_PLATE_K") and M.TITLE_PLATE_K > 1.0)

# 2. TITLE_RISE_PX in metrics: shared pop-in lift distance for the whole block
check("TITLE_RISE_PX in metrics", getattr(M, "TITLE_RISE_PX", 0) > 0)

# 3. measure(title_block) exposes done_at == at + POP_RAMP/TITLE_PLATE_K
L = {"kind": "title_block", "at": 0.2, "text": "GOLDEN TITLE", "sub": "SUBTITLE LINE"}
m = M.measure(eng, L, "title_block", shot_t=2.0, at_raw=0.2)
check("title done_at present", "done_at" in m)
check("title done_at formula", abs(m.get("done_at", -9) - (0.2 + M.POP_RAMP / M.TITLE_PLATE_K)) < 1e-9)

# 3. checks gate: a title whose settle crowds the shot end flags like panels do
bad = {"schema": 1, "name": "c7t", "preset": "leebdark.json", "width": 320, "height": 480,
       "target": 1.0, "fps": 30, "shots": [
           {"fill": "solid", "t": 1.0, "transition": "cut",
            "captions": [dict(L, at=0.95)]}]}
from core import checks as CK
eng_bad = Engine(bad)
flags = [f for f in CK.check_project(eng_bad) if "title" in str(f).lower()]
check("checks flags late title settle", len(flags) > 0)

print("---")
if fails:
    raise SystemExit("FAILED: " + ", ".join(fails))
print("ALL PASS (c7 title easing parity)")
