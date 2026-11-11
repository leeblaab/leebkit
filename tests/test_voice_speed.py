"""v1.4 C2 — voice speed control gates (tests-first).

Locks, in order:
1. validate_project tolerates/normalizes optional `voice_speed` (schema stays 1)
   and rejects junk values at the boundary.
2. vo_duration's cache key INCLUDES speed — same text+voice at two speeds must
   be two different cache files (the stale-audio bug this whole commit exists
   to prevent).
3. piper_line threads piper's `--length-scale` CLI flag: speed S -> length
   scale 1/S (S>1 = faster speech = shorter wav), rounded to 2 decimals.

The subprocess-level checks monkeypatch core.audio.subprocess — they never run
piper here; the real PY311 synth + ffprobe duration gate lives in the C2 gate
chain (see docs/v1.4_plan.md).
"""
import hashlib
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio as A  # noqa: E402
from core.engine import validate_project  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


# ------------------------------------------------------- validate_project gate
_base = {"schema": 1, "name": "vspd", "target": 2.0, "fps": 24,
         "width": 320, "height": 480, "voice": "none", "music": {"bed": "none"},
         "shots": [{"t": 2.0, "transition": "cut", "captions": []}]}


def vp(**kw):
    return validate_project({**_base, **kw})


try:
    p = vp()
    check("validate tolerates missing voice_speed (default 1.0)",
          p.get("voice_speed", 1.0) == 1.0, repr(p.get("voice_speed")))
except ValueError as e:
    check("validate tolerates missing voice_speed (default 1.0)", False, str(e))

for v in (0.8, 1.0, 1.25):
    try:
        p = vp(voice_speed=v)
        check("validate accepts voice_speed=%s" % v, p.get("voice_speed") == v,
              repr(p.get("voice_speed")))
    except ValueError as e:
        check("validate accepts voice_speed=%s" % v, False, str(e))

try:
    vp(voice_speed=0.5)
    check("validate rejects voice_speed=0.5 (out of range)", False, "no raise")
except ValueError:
    check("validate rejects voice_speed=0.5 (out of range)", True)

try:
    vp(voice_speed="fast")
    check("validate rejects non-numeric voice_speed", False, "no raise")
except ValueError:
    check("validate rejects non-numeric voice_speed", True)


# ------------------------------------------------- cache key includes speed
class SpySub:
    """Captures the piper argv, writes a tiny silent wav where piper would."""
    def __init__(self):
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(list(cmd))
        # find --output-dir <tmp> and drop a 0.1 s mono 22050 wav in it
        out = cmd[cmd.index("--output-dir") + 1]
        import wave as _w
        p = os.path.join(out, "spy.wav")
        with _w.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * int(0.1 * 22050))

        class R:
            returncode = 0
            stderr = ""
        return R()


scratch = tempfile.mkdtemp(prefix="vspd_scratch_")
real_subprocess = A.subprocess
try:
    # a real voice model must exist for piper_line to get past the model check;
    # any shipped model works — this spy never loads it.
    models = [f[:-5] for f in os.listdir(A.VO_MODELS) if f.endswith(".onnx")] \
        if os.path.isdir(A.VO_MODELS) else []
    if not models:
        print("SKIP cache-key + threading checks (no piper model in vo/models/)")
    else:
        voice = models[0]
        A.subprocess = SpySub()
        d1, p1 = A.vo_duration("speed gate line", voice, scratch)
        d2, p2 = A.vo_duration("speed gate line", voice, scratch, speed=1.25)
        check("cache key includes speed (different wav per speed)",
              os.path.basename(p1) != os.path.basename(p2),
              "%s vs %s" % (p1, p2))

        # second call at each speed must be a cache HIT (no new subprocess)
        n_before = len(A.subprocess.calls)
        d1b, p1b = A.vo_duration("speed gate line", voice, scratch)
        d2b, p2b = A.vo_duration("speed gate line", voice, scratch, speed=1.25)
        check("speed cache hits (no re-synth)", len(A.subprocess.calls) == n_before
              and p1b == p1 and p2b == p2)

        # ---- param threading: --length-scale on the piper argv ----
        ls = [c for c in A.subprocess.calls if "--length-scale" in c]
        check("piper_line threads --length-scale for speed=1.25", len(ls) >= 1,
              "calls=%d" % len(A.subprocess.calls))
        if ls:
            v = float(ls[-1][ls[-1].index("--length-scale") + 1])
            # speed 1.25 (faster speech) -> length scale 1/1.25 = 0.8
            check("length-scale value = 1/speed (1.25 -> 0.8)", abs(v - 0.8) < 1e-6,
                  "got %r" % v)

        # explicit speed=1.0 must match the default call exactly (same file,
        # same argv shape)
        d3, p3 = A.vo_duration("speed gate line", voice, scratch, speed=1.0)
        check("explicit speed=1.0 == default (same cache file)", p3 == p1)

        # no-speed legacy call must still have worked above; and a fresh text
        # at default speed with NO --length-scale flag keeps the old argv shape
        A.subprocess.calls.clear()
        A.vo_duration("legacy shape line", voice, scratch)
        legacy = A.subprocess.calls[-1]
        check("default-speed piper argv unchanged (no length-scale flag)",
              "--length-scale" not in legacy, " ".join(legacy))
finally:
    A.subprocess = real_subprocess
    shutil.rmtree(scratch, ignore_errors=True)

print()
if FAILS:
    print("VOICE SPEED TESTS FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ALL VOICE SPEED TESTS PASS")
