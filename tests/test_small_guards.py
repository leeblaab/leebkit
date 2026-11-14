"""C8 (v1.41) — small guards bundle (S6b/S6c/B4a/B4b + B3 doc note).

  S6b  upload routes: UploadFile.filename is Optional[str]; a multipart POST
       without a filename part reaches `file.filename.lower()` -> AttributeError
       -> 500 instead of 400. Called DIRECTLY (TestClient availability varies
       across interpreters): both routes must raise HTTPException(400).
  S6c  _sniff_audio: 1-byte head hits head[1] -> IndexError. Direct call.
  B4a  app.py logger name "reelkit" -> "leebkit" (brand; nothing greps logs —
       verified by grep, docs/_local only).
  B4b  /api/style_preview response said frames [45,135,300] while the route
       renders picks (45,135,330) — response must echo the real picks.
  B3   README Python-version one-liner: app on 3.11-3.14, Piper VO 3.11-3.13.
Run: PYTHONPATH=. python tests/test_small_guards.py
"""
import asyncio
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


import app as A  # noqa: E402
from fastapi import HTTPException, UploadFile  # noqa: E402

# ---- S6c: _sniff_audio must not IndexError on a short head ----
try:
    r = A._sniff_audio(b"\xFF")
    check("_sniff_audio(1 byte) returns cleanly", r is False, repr(r))
except IndexError:
    check("_sniff_audio(1 byte) returns cleanly", False, "IndexError on head[1]")

# ---- S6b: filename=None upload -> HTTPException 400, not AttributeError ----
for fn in (A.upload, A.music_upload):
    try:
        f = UploadFile(filename=None, file=io.BytesIO(b"ID3" + b"x" * 100))
        asyncio.run(fn(f))
        check("%s filename=None -> 400" % fn.__name__, False, "no exception raised")
    except HTTPException as e:
        check("%s filename=None -> 400" % fn.__name__, e.status_code == 400,
              "got %d" % e.status_code)
    except AttributeError as e:
        check("%s filename=None -> 400" % fn.__name__, False,
              "AttributeError (unguarded .lower()): %s" % e)

# ---- B4a: logger brand ----
check("logger name is 'leebkit'", A.log.name == "leebkit", A.log.name)

# ---- B4b: style_preview response echoes the REAL picks ----
src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
m = re.search(r"picks\s*=\s*\(([^)]*)\)", src)
check("style_preview picks found in source", bool(m))
if m:
    picks = [int(x) for x in m.group(1).replace(" ", "").split(",")]
    # response dict is built after the picks assignment — search from there so
    # unrelated route payloads (e.g. /api/preview's "frames") can't match
    tail = src[m.end():]
    resp_line = re.search(r'"frames":\s*(?:list\(picks\)|\[[^\]]*\])', tail)
    shown = ("picks" if "list(picks)" in resp_line.group(0) else
             [int(x) for x in re.search(r"\[([^\]]*)\]", resp_line.group(0)).group(1).split(",")]) \
        if resp_line else []
    check("style_preview response frames match picks", shown == "picks" or shown == picks,
          "picks=%s response=%s" % (picks, shown))

# ---- B4c: /api/meta carries the identity sentinel start.bat probes for ----
check("meta() returns app marker", '"app": APP_MARKER' in src and 'APP_MARKER = "leebkit"' in src)

# ---- B3: README python-version note ----
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("README states app 3.11-3.14 / Piper VO 3.11-3.13",
      re.search(r"3\.11.{0,6}3\.14", readme) and re.search(r"3\.11.{0,6}3\.13", readme))

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
