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

# ---- v1.4 CC0 external beds (music/*.mp3, provenance in music/ATTRIBUTIONS.md)
# build_audio mode=file: loudness-matched to the procedural band then peak 0.84,
# so a hot or quiet master can never bury VO or drift out of the mix band.
_cc0 = sorted(f for f in os.listdir(A.MUSIC_DIR) if f.startswith("bed_")
              and f.endswith(".mp3"))
check("CC0 beds present", len(_cc0) >= 2, _cc0)
check("CC0 provenance file", os.path.isfile(os.path.join(A.MUSIC_DIR, "ATTRIBUTIONS.md")))
_proj = {"target": 15.0, "voice": "none", "shots": [
    {"t": 7.5, "fill": "gen:midnight_drift", "captions": []},
    {"t": 7.5, "fill": "gen:grid_pulse", "captions": []}]}
_scratch = os.path.join(ROOT, "output", "_music_beds_scratch")
for fn in _cc0:
    p = dict(_proj)
    p["music"] = {"mode": "file", "bed": fn}
    wav = A.build_audio(p, scratch=os.path.join(_scratch, fn[:-4]))
    import wave as _w
    with _w.open(wav, "rb") as w:
        sr = w.getframerate()
        d = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        if w.getnchannels() == 2:
            d = d.reshape(-1, 2).mean(axis=1)
    check("%s bed length" % fn, len(d) == int(15.0 * sr), "%d" % len(d))
    mean_db = 20 * np.log10(max(float(np.mean(np.abs(d))), 1e-9))
    check("%s mix band" % fn, -23.0 <= mean_db <= -8.0, "mean=%.1f dBFS" % mean_db)
# traversal guard must still fire for relative beds escaping music/
try:
    p = dict(_proj)
    p["music"] = {"mode": "file", "bed": "../secrets"}
    A.build_audio(p, scratch=_scratch)
    check("CC0 traversal guard", False, "no ValueError")
except ValueError:
    check("CC0 traversal guard", True)

print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)

# C4e obs #1 (Yasser live test): file-bed id/mode robustness. The UI writes
# mode:"file" with a "file:<name>" bed; older hand-written configs carry a bare
# filename or even a stale mode. Every shape must resolve to mode=file — never
# silently fall through to a procedural bed.
from core.audio import _normalize_music as _nm
check("CC0 file: id + explicit file mode", _nm({"mode": "file", "bed": "file:bed_cave_drone.mp3"})["mode"] == "file")
check("CC0 bare filename + stale procedural mode", _nm({"mode": "procedural", "bed": "bed_old_key.mp3"})["mode"] == "file")
check("CC0 file: id + procedural mode", _nm({"mode": "procedural", "bed": "file:bed_one_cool_minute.mp3"})["mode"] == "file")
check("CC0 procedural bed name untouched", _nm({"mode": "procedural", "bed": "synthwave"})["mode"] == "procedural")

print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
