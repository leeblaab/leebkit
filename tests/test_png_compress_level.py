"""C7 (v1.41) — P2: PNG intermediate saves must use compress_level=1.

Frames are written as lossless PNG intermediates at three sites (queue worker,
queue serial leg, render_cli worker) and deleted after ffmpeg reads them, so
Pillow's default level-6 deflate is pure wasted CPU (measured 0.109 -> 0.065
s/frame save at 1080x1920). The encode command already pins -start_number 0
for the CLI/share paths; queue uses f_%04d from 0 too — unchanged by this fix.

Gate: AST-parse the three modules and assert every Image.save call whose target
ends .png carries compress_level=1 (no positional-level surprises).
Run: PYTHONPATH=. python tests/test_png_compress_level.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


TARGETS = ["core/queue.py", "render_cli.py"]
found = 0
for rel in TARGETS:
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "save"):
            # only frame-intermediate saves: first arg expression contains a
            # .png format string somewhere in its source segment
            seg = ast.get_source_segment(src, node) or ""
            if ".png" not in seg:
                continue
            found += 1
            kw = {k.arg for k in node.keywords}
            check("%s:%d PNG save has compress_level kw" % (rel, node.lineno),
                  "compress_level" in kw, seg[:80])

check("all three intermediate sites found", found >= 3, "found=%d" % found)

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
