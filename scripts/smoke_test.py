"""LEEBKIT pre-tag smoke test — runs against the working tree, not a release.

Usage: python scripts/smoke_test.py
Exits 0 and prints PASS lines when everything is green; nonzero + FAIL otherwise.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = sys.executable
TMP = os.path.join(ROOT, "scratch", "smoke")
os.makedirs(TMP, exist_ok=True)
fails = []


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" — " + detail if detail else ""))
    if not cond:
        fails.append(name)


# 1. imports
try:
    from core.engine import Engine, validate_project
    from core.layout import build_layout, clamp_font_sizes
    from core import checks as CH
    from core.queue import QUEUE
    ok("imports", True)
except Exception as e:
    ok("imports", False, str(e))
    print("SMOKE FAILED (cannot import):", fails)
    sys.exit(1)

# 2. validate_project rejects bad input
bad = {"schema": 1, "shots": [{"t": 5}], "target": 5.0, "fps": 29, "width": 1080, "height": 1920}
try:
    validate_project(bad)
    ok("validate rejects bad fps", False)
except ValueError:
    ok("validate rejects bad fps", True)
bad2 = {"schema": 1, "shots": [{"t": 5}], "target": 7.0, "fps": 30}
try:
    validate_project(bad2)
    ok("validate rejects sum!=target", False)
except ValueError:
    ok("validate rejects sum!=target", True)

# 3. engines build at all three ratios + checks parity
proj = {"schema": 1, "name": "smoke", "target": 4.0, "fps": 24,
        "shots": [{"t": 4.0, "transition": "cut", "captions": [
            {"kind": "title_block", "at": 0.3, "text": "SMOKE TEST TITLE"},
            {"kind": "terminal", "at": 1.2, "rows": ["> smoke", "░░ 0%"]}]}]}
for w, h in ((1080, 1920), (1080, 1080), (1920, 1080)):
    p = dict(proj)
    p["width"], p["height"] = w, h
    try:
        eng = Engine(p)
        img = eng.compose_frame(eng.N - 1)
        good = img.size == (w, h)
        ok("engine %dx%d frame" % (w, h), good, str(img.size))
        flags = CH.check_project(eng)
        errs = [f for f in flags if f.get("severity") == "error"]
        ok("checks %dx%d no errors" % (w, h), not errs, str(errs))
    except Exception as e:
        ok("engine %dx%d" % (w, h), False, str(e))

# 4. CLI draft render (no audio) at square, then ffprobe gate
sq = os.path.join(TMP, "smoke_sq.json")
p = dict(proj)
p["width"], p["height"] = 1080, 1080
json.dump(p, open(sq, "w", encoding="utf-8"))
r = subprocess.run([PY, os.path.join(ROOT, "render_cli.py"), sq,
                    "--no-audio", "--draft", "--jobs", "2"],
                   capture_output=True, text=True, cwd=ROOT)
out_mp4 = os.path.join(ROOT, "output", "smoke.mp4")
ok("cli render", r.returncode == 0 and os.path.exists(out_mp4),
   (r.stderr or "")[-300:] if r.returncode != 0 else out_mp4)
if os.path.exists(out_mp4):
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration",
                         "-of", "json", out_mp4], capture_output=True, text=True)
    try:
        st = json.loads(pr.stdout)["streams"]
        v = next(s for s in st if s["codec_type"] == "video")
        ok("ffprobe square", int(v["width"]) == 1080 and int(v["height"]) == 1080
           and abs(float(v["duration"]) - 4.0) < 0.15, json.dumps(v))
    except Exception as e:
        ok("ffprobe square", False, str(e))
    os.remove(out_mp4)

# 5. CLI rejects --jobs 0
r = subprocess.run([PY, os.path.join(ROOT, "render_cli.py"), sq, "--jobs", "0"],
                   capture_output=True, text=True, cwd=ROOT)
ok("cli rejects --jobs 0", r.returncode != 0 and "jobs" in (r.stderr or "").lower())

print(("SMOKE PASS (%d checks)" % (0 if fails else 0)) if not fails else "SMOKE FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
