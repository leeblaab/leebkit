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


_checks_done = 0


def ok(name, cond, detail=""):
    global _checks_done
    _checks_done += 1
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
    pr = subprocess.run(["ffprobe", "-v", "error", "-count_frames",
                         "-show_entries", "stream=codec_type,width,height,duration,nb_read_frames",
                         "-of", "json", out_mp4], capture_output=True, text=True)
    try:
        st = json.loads(pr.stdout)["streams"]
        v = next(s for s in st if s["codec_type"] == "video")
        ok("ffprobe square", int(v["width"]) == 1080 and int(v["height"]) == 1080
           and abs(float(v["duration"]) - 4.0) < 0.15, json.dumps(v))
        # frame-count gate: duration tolerance alone would hide a dropped or
        # duplicated frame (N = target*fps; draft renders run at project fps)
        nf = int(v.get("nb_read_frames", -1))
        ok("frame count == target*fps", nf == 4 * int(p.get("fps", 24)), "nb_read_frames=%s" % nf)
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
except FileNotFoundError as e:   # ValueError-family, NOT SystemExit (audit #8):
    ok("engine rejects ../ traversal image", "not found or outside" in str(e))
abs_img = {"schema": 1, "name": "abs", "target": 2.0, "fps": 24,
           "shots": [{"t": 2.0, "image": os.path.join(ROOT, "media", "img_00010.png"), "captions": []}]}
try:
    Engine(abs_img)
    ok("engine rejects absolute image path", False, "no abort raised")
except FileNotFoundError as e:
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

# 7b. transition whitelist (audit #1): typo'd transitions rejected at validate time
badtr = {"schema": 1, "name": "tr", "target": 2.0, "fps": 24,
         "shots": [{"t": 2.0, "transition": "wipe_leftt", "captions": []}]}
try:
    validate_project(badtr)
    ok("validate rejects unknown transition", False, "accepted typo")
except ValueError as e:
    ok("validate rejects unknown transition", "not implemented" in str(e))
# and the real kinds pass validation + compose (wipe_left/wipe_up implemented now)
from core.engine import TRANSITIONS
good = all(t in TRANSITIONS for t in ("cut", "fade", "slideL", "whip", "flashdip", "wipe_left", "wipe_up"))
ok("TRANSITIONS covers engine kinds", good)
wproj = {"schema": 1, "name": "wipe", "target": 2.0, "fps": 24,
         "shots": [{"t": 1.0, "transition": "cut"},
                   {"t": 1.0, "transition": "wipe_left"}]}
try:
    e2 = Engine(wproj)
    e2.compose_frame(int(1.3 * 24))   # mid-wipe frame
    ok("wipe_left composes a frame", True)
except Exception as e:
    ok("wipe_left composes a frame", False, str(e)[:120])

# 7c. music config normalization (audit #2): UI's {file:...} shape -> mode file
from core.audio import _normalize_music
mn = _normalize_music({"file": "song.mp3"})
ok("music {file:x.mp3} normalizes to mode=file", mn["mode"] == "file" and mn["bed"] == "song.mp3", str(mn))
ok("music {bed:synthwave} stays procedural", _normalize_music({"bed": "synthwave"})["mode"] == "procedural")
ok("music file: prefix accepted", _normalize_music({"bed": "file:track.wav"})["mode"] == "file")

# 7d. queue survives a missing-image job (audit #8): worker thread must live on,
# and the NEXT job must still render. Tiny 1-shot/1s/no-audio jobs keep this cheap;
# below the >=60-frame threshold so it takes the serial path (no mp.Pool in smoke).
import time as _t
from core.queue import QUEUE, QueueFull, MAX_QUEUED


def j_done(j):
    return j.state in ("done", "error", "canceled")


tiny = {"schema": 1, "name": "smkq", "target": 1.0, "fps": 24, "width": 320, "height": 320,
        "voice": "none", "music": {"bed": "none"},
        "shots": [{"t": 1.0, "transition": "cut", "captions": []}]}
badj = QUEUE.submit({**tiny, "shots": [{**tiny["shots"][0], "image": "definitely_missing_zz.png"}]},
                    media_dir=os.path.join(ROOT, "media"))
goodj = QUEUE.submit(dict(tiny), media_dir=os.path.join(ROOT, "media"))
deadline = _t.time() + 90
while _t.time() < deadline:
    if j_done(badj) and j_done(goodj):
        break
    QUEUE.wait_change(1.0)
ok("queue survives missing-image job (audit #8)",
   badj.state == "error" and goodj.state == "done",
   "bad=%s(%s) good=%s" % (badj.state, badj.error, goodj.state))

# 7e. queue cap + cancel (audit #3)
try:
    for _ in range(MAX_QUEUED + 6):   # cap is configurable; test tracks it (was hardcoded 10 vs MAX=4)
        QUEUE.submit(dict(tiny), media_dir=os.path.join(ROOT, "media"))
    ok("queue refuses >MAX_QUEUED submits", False, "accepted 10 submissions")
except QueueFull:
    ok("queue refuses >MAX_QUEUED submits", True)

# 7f. camera-name gate (v1.21 audit): "cam" and "camera" both accepted, unknown
# names fail loud; promo_v12 ships the canonical key so its pans actually apply.
try:
    validate_project({"schema": 1, "target": 3.0, "shots": [
        {"t": 3.0, "image": "x.png", "camera": "spinzoom"}]})
    ok("unknown camera name rejected (both keys)", False, "spinzoom accepted")
except ValueError:
    _p12 = json.load(open(os.path.join(ROOT, "samples", "promo_v12.json"), encoding="utf-8"))
    from core.camutil import cam_name as _cn
    ok("unknown camera name rejected (both keys)",
       all("camera" not in s and _cn(s) is not None for s in _p12["shots"]),
       "promo_v12: %s" % [(s.get("cam"), s.get("camera")) for s in _p12["shots"]])

# drain remaining queued jobs (they are tiny; cancel the still-queued ones fast)
deadline = _t.time() + 90
while _t.time() < deadline:
    snaps = QUEUE.snapshot()
    if snaps and all(s["state"] in ("done", "error", "canceled") for s in snaps):
        break
    QUEUE.wait_change(1.0)

# smoke self-cleanup: queue-job outputs (smkq_*.mp4) were left behind by every
# run — 20 identical files piled up before this existed (follow-up audit hygiene).
for f in os.listdir(os.path.join(ROOT, "output")):
    if f.startswith("smkq_") and f.endswith(".mp4"):
        try:
            os.remove(os.path.join(ROOT, "output", f))
        except OSError:
            pass

# 7d. animations gallery (v1.35): manifest + tiles for every card in the rail
from core import anim_gallery as AG
_gm = AG.gallery_manifest("leebdark")
if any(not it["ready"] for c in _gm["categories"] for it in c["items"]):
    AG.generate_gallery("leebdark")  # cold checkout (CI/fresh install): build once, same as /api/gallery does
    _gm = AG.gallery_manifest("leebdark")
ok("gallery manifest has 5 categories", len(_gm["categories"]) == 5, str(len(_gm["categories"])))
_all_items = [it for c in _gm["categories"] for it in c["items"]]
ok("gallery covers 14 unique cards", len(set(i["id"] for i in _all_items)) == 14, str(len(set(i["id"] for i in _all_items))))
ok("gallery tiles ready", all(i["ready"] for i in _all_items),
   str([i["id"] for i in _all_items if not i["ready"]]))
ok("gallery tile files exist", all(i["ready"] and os.path.isfile(os.path.join(ROOT, i["url"].lstrip("/").replace("/", os.sep))) for i in _all_items))
_fav = {i["id"] for i in _gm["categories"][0]["items"]}
ok("favorites reference real animations", bool(_fav) and _fav <= {i["id"] for i in _all_items}, str(sorted(_fav)))
_cam = [i for c in _gm["categories"] if c["id"] == "camera" for i in c["items"]]
ok("camera cards have kind=camera", all(i["kind"] == "camera" for i in _cam) and len(_cam) >= 6, str(len(_cam)))
_trans = [i for c in _gm["categories"] if c["id"] == "transitions" for i in c["items"]]
ok("transition cards have kind=transition", all(i["kind"] == "transition" for i in _trans), str(len(_trans)))

# 7g. generator shots ride the preview paths end-to-end (v1.4 C4): a mixed
# gen+image project must pass check_project clean, storyboard_strip must render
# it, and the anim-preview shape (single-shot mini project with _peek) must
# render a gen shot — same code path as /api/preview + /api/anim_preview.
from core.checks import storyboard_strip as _sbs
_genproj = {"schema": 1, "name": "c4smk", "target": 5.0, "fps": 24,
            "width": 320, "height": 480, "music": {"bed": "none"}, "voice": "none",
            "shots": [
                {"fill": "gen:midnight_drift", "motion": "normal", "t": 2.5,
                 "captions": [{"kind": "title_block", "at": 0.3, "text": "GEN SMOKE", "sub": "mixed"}]},
                {"fill": "gen:grid_pulse", "motion": "subtle", "t": 2.5, "transition": "fade",
                 "captions": [{"kind": "cta", "at": 0.4, "text": "GO"}]}]}
try:
    _ge = Engine(_genproj)
    _gflags = [f for f in CH.check_project(_ge) if f.get("severity") == "error"]
    ok("mixed gen project checks clean", not _gflags, str(_gflags))
    _strip_out = os.path.join(TMP, "c4_strip.png")
    _sflags = [f for f in _sbs(Engine(_genproj), _strip_out) if f.get("severity") == "error"]
    ok("storyboard strip renders gen shots", os.path.isfile(_strip_out) and os.path.getsize(_strip_out) > 1000 and not _sflags, str(_sflags))
    # anim-preview shape: single-shot mini project frozen at _peek (UI builds this)
    _mini = dict(_genproj); _mini["shots"] = [dict(_genproj["shots"][0])]; _mini["target"] = 2.5
    _me = Engine(_mini)
    _img = _me.render_layer(0, min(2.45, 0.3 + 0.16), 7)   # mid-animation peek
    ok("anim-preview frame on gen shot", _img.size == (320, 480))
except Exception as e:
    ok("generator preview paths (C4)", False, str(e)[:160])

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

# v1.36 obs #1: animation gallery tiles must actually become ready for every
# preset (the C1 tier whitelist silently killed the old 540x960 gallery size).
r = subprocess.run([PY, os.path.join(ROOT, "tests", "test_anim_gallery.py")],
                   capture_output=True, text=True, cwd=ROOT)
ok("anim gallery test suite", r.returncode == 0,
   (r.stdout or "")[-200:] + (r.stderr or "")[-200:])

# v1.4 C4b: every procedural bed must synthesize clean at all durations and
# scan_music() must agree with BEDS (UI dropdown can never list a dead id).
r = subprocess.run([PY, os.path.join(ROOT, "tests", "test_music_beds.py")],
                   capture_output=True, text=True, cwd=ROOT)
ok("music beds test suite", r.returncode == 0,
   (r.stdout or "")[-200:] + (r.stderr or "")[-200:])

# v1.4 C5: GIF/WebP share teasers must encode and respect the caps in
# core/share_caps.py (GIF 640px/6s/12fps — Yasser ruling).
r = subprocess.run([PY, os.path.join(ROOT, "tests", "test_share_formats.py")],
                   capture_output=True, text=True, cwd=ROOT)
ok("share formats test suite", r.returncode == 0,
   (r.stdout or "")[-200:] + (r.stderr or "")[-200:])

# counter bug (audit): the old expression was `(0 if fails else 0)` — always 0.
print(("SMOKE PASS (%d checks)" % _checks_done) if not fails else "SMOKE FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
