"""C1 (v1.41) — B1 regression: voice_speed must reach the FINAL mix.

Audit #1 B1: the build_audio VO mix loop re-synthesized each line WITHOUT the
project's voice_speed (vo_duration(text, voice, scratch)[1] — speed arg
dropped), so the final MP4 spoke at 1.0x while previews/duck windows/overrun
check used the sped duration. v1.4 C2 only gated the synthesis path.

The spy replaces core.audio.subprocess for piper_line (mkdtemp/run/move) so
the cached wav lands at its real hash name with a length that encodes the
speed (1.0 s speech at speed S -> 1/S seconds; LS=1/S). Checks:
1. each text synthesized exactly once per build (no double-synth at 2 keys)
2. every synth call carries the project speed (--length-scale 0.8 for 1.25x)
3. cached wavs physically exist with SPED length (~0.8 s)
4. overrun guard sees SPED lengths: a line that fits only when sped builds
   cleanly (unfixed code reads unsped 1.0 s segments and raises).
"""
import os
import shutil
import sys
import tempfile
import wave as _w

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio as A  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


class SpySub:
    """Replaces core.audio.subprocess for piper_line: mkdtemp + run (writes a
    speed-encoded silent wav into the output dir) + move (lands it at the
    caller's cache path)."""
    def __init__(self):
        self.calls = []          # length-scale values, one per synth

    def mkdtemp(self, *a, **k):
        return tempfile.mkdtemp(prefix="spypiper_")

    def run(self, cmd, **kw):
        ls = float(cmd[cmd.index("--length-scale") + 1]) if "--length-scale" in cmd else 1.0
        self.calls.append(ls)
        out = cmd[cmd.index("--output-dir") + 1]
        p = os.path.join(out, "spy.wav")
        with _w.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(A.SR_OUT)
            # 1.0 s of speech at speed S occupies 1/S seconds; LS = 1/S
            n = int(round(A.SR_OUT * ls)) if abs(ls - 1.0) > 1e-9 else A.SR_OUT
            w.writeframes(b"\x00\x00" * n)

        class R:
            returncode = 0
            stderr = ""
        return R()

    def move(self, src, dst):
        shutil.move(src, dst)


models = [f[:-5] for f in os.listdir(A.VO_MODELS) if f.endswith(".onnx")] \
    if os.path.isdir(A.VO_MODELS) else []
if not models:
    print("SKIP mix-path check (no piper model in vo/models/)")
else:
    voice = models[0]
    scratch = tempfile.mkdtemp(prefix="c1_mix_")
    real_subprocess = A.subprocess
    try:
        A.subprocess = SpySub()
        proj = {"schema": 1, "name": "c1", "target": 6.0, "fps": 24,
                "width": 320, "height": 480, "voice": voice,
                "voice_speed": 1.25, "music": {"bed": "none"},
                "vo_lines": [{"at": 0.5, "text": "one line here"},
                             {"at": 3.0, "text": "second spoken line"}],
                "shots": [{"t": 6.0, "transition": "cut", "captions": []}]}

        wav = A.build_audio(proj, scratch=scratch)

        n_synths = len(A.subprocess.calls)
        check("each VO line synthesized exactly once (no double-synth)",
              n_synths == 2, "synths=%d" % n_synths)
        check("all synths carry the project speed (length-scale 0.8)",
              all(abs(ls - 0.8) < 1e-6 for ls in A.subprocess.calls),
              repr(A.subprocess.calls))

        # cache files must exist at their hash names with SPED length (0.8 s)
        sped = [A.vo_duration(t, voice, scratch, speed=1.25)[1]
                for t in ("one line here", "second spoken line")]
        lens = []
        for p in sped:
            d, sr = A.read_wav_mono(p)
            lens.append(len(d) / sr)
        check("cached wavs are the sped ones (~0.8 s)",
              all(abs(x - 0.8) < 0.02 for x in lens), repr(lens))

        # overrun guard sees SPED lengths: line at 3.0 (sped 0.8 -> ends 3.8)
        # fits a 3.9 s timeline; unfixed code reads unsped 1.0 s and raises.
        proj2 = dict(proj, target=3.9)
        try:
            A.build_audio(proj2, scratch=scratch)
            check("sped line fits timeline that would overrun at 1.0x", True)
        except RuntimeError as e:
            check("sped line fits timeline that would overrun at 1.0x", False, str(e))
    finally:
        A.subprocess = real_subprocess
        shutil.rmtree(scratch, ignore_errors=True)

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
