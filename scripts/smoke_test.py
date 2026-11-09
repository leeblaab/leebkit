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

# 6. A2 hardening: path confinement + loud missing-image abort
esc = {"schema": 1, "name": "esc", "target": 2.0, "fps": 24,
       "shots": [{"t": 2.0, "image": "../app.py", "captions": []}]}
try:
    Engine(esc)
    ok("engine rejects ../ traversal image", False, "no abort raised")
except SystemExit as e:
    ok("engine rejects ../ traversal image", "not found or outside" in str(e))
abs_img = {"schema": 1, "name": "abs", "target": 2.0, "fps": 24,
           "shots": [{"t": 2.0, "image": os.path.join(ROOT, "media", "img_00010.png"), "captions": []}]}
try:
    Engine(abs_img)
    ok("engine rejects absolute image path", False, "no abort raised")
except SystemExit as e:
    ok("engine rejects absolute image path", "not found or outside" in str(e))
from core.engine import load_preset
try:
    load_preset("../app")
    ok("preset loader rejects traversal", False, "loaded outside presets/")
except (ValueError, FileNotFoundError) as e:
    ok("preset loader rejects traversal", isinstance(e, ValueError), str(e)[:80])
ok("upload magic-byte helper", True)  # covered below via app import
try:
    import importlib
    _app = importlib.import_module("app")
    sniff_ok = (_app._sniff_image(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
                and _app._sniff_image(b"\xff\xd8\xff\xe0abc")
                and _app._sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP")
                and not _app._sniff_image(b"MZ\x90\x00this is an exe"))
    ok("upload magic-byte sniff", sniff_ok)
except Exception as e:
    ok("upload magic-byte sniff", False, str(e)[:120])

# 7. long subtitle auto-wraps instead of clipping (regression: promo v1 sub)
long_sub = {"schema": 1, "name": "subwrap", "target": 2.0, "fps": 24,
            "shots": [{"t": 2.0, "captions": [
                {"kind": "title_block", "at": 0.3, "text": "FULLY OFFLINE",
                 "sub": "NO CLOUD. NO ACCOUNT. YOUR MACHINE ONLY. ZERO UPLOADS EVER."}]}]}
eng = Engine(long_sub)
flags = CH.check_project(eng)
errs = [f for f in flags if f.get("severity") == "error"]
ok("long sub wraps (no overflow error)", not errs, str(errs))

# 8. UI inline JS must parse (a '#' comment line once killed the whole script:
# empty dropdowns on a healthy server). node --check if present, else basic scan.
import re as _re
html = open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8").read()
scripts = [m.group(1) for m in _re.finditer(r"<script>(.*?)</script>", html, _re.S)]
jsblob = "\n".join(scripts)
bad_lines = [i + 1 for i, ln in enumerate(jsblob.splitlines()) if ln.lstrip().startswith("#")]
ok("ui js no # comments", not bad_lines, "lines %s" % bad_lines if bad_lines else "")
try:
    tmpjs = os.path.join(TMP, "ui_inline.js")
    open(tmpjs, "w", encoding="utf-8").write(jsblob)
    nr = subprocess.run(["node", "--check", tmpjs], capture_output=True, text=True)
    ok("ui js parses (node)", nr.returncode == 0, (nr.stderr or "")[-300:])
except FileNotFoundError:
    print("SKIP node --check (node not installed)")

print(("SMOKE PASS (%d checks)" % (0 if fails else 0)) if not fails else "SMOKE FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
