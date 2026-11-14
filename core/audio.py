"""LEEBKIT audio: procedural numpy beds + user music files + Piper VO + ducking.

Ported from the proven make_audio.py (synthwave bed) and make_vo.py (VO bed).
Pitfalls baked in:
  * VO bed built with numpy FLOAT arrays placed at int(start*SR) — never
    bytearray slicing (silently halves duration).
  * assert final bed length == TOTAL frames.
  * mux is verified by ffprobe on BOTH streams afterwards (verify_durations).
"""
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(ROOT, "music")
VO_MODELS = os.path.join(ROOT, "vo", "models")
SR_OUT = 48000          # final bed sample rate
def _find_py311():
    """Locate a Python 3.11-3.13 interpreter for the piper subprocess (piper's CLI
    breaks on 3.14's wave module). Honors LEEBKIT_PY311, then common install dirs."""
    import glob as _glob
    cand = [os.environ.get("LEEBKIT_PY311", "")]
    local = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
    for v in ("Python311", "Python312", "Python313"):
        cand.append(os.path.join(local, v, "python.exe"))
    cand += sorted(_glob.glob(os.path.join(local, "Python3.1*", "python.exe")))
    if sys.version_info[:2] in ((3, 11), (3, 12), (3, 13)):
        cand.append(sys.executable)
    for c in cand:
        if c and os.path.isfile(c):
            return c
    return cand[0] or sys.executable


PY311 = _find_py311()


# --------------------------------------------------------------- basic helpers
def onepole(x, alpha):
    """vectorized one-pole lowpass via impulse-response convolution"""
    n = len(x)
    L = min(n, 512)
    k = alpha * (1 - alpha) ** np.arange(L)
    return np.convolve(x, k[:L], mode="full")[:n]


def saw_harm(f, tt, n=14):
    s = np.zeros_like(tt)
    for k in range(1, n + 1):
        s += np.sin(2 * np.pi * f * k * tt) / k
    return s * 0.5


def read_wav_mono(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    if ch == 2:
        data = data.reshape(-1, 2).mean(axis=1)
    return data, sr


def resample(data, sr_in, sr_out):
    if sr_in == sr_out:
        return data
    n_out = int(round(len(data) * sr_out / sr_in))
    x_old = np.linspace(0.0, 1.0, len(data))
    x_new = np.linspace(0.0, 1.0, n_out)
    return np.interp(x_new, x_old, data)


def load_music_file(path):
    """Any mp3/wav via ffmpeg -> 48k mono float."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".tmp48k.wav")
    os.close(fd)
    r = subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(SR_OUT), "-ac", "1", tmp],
                       capture_output=True, text=True)
    try:
        if r.returncode != 0:
            raise RuntimeError("cannot decode music file %s:\n%s" % (path, r.stderr[-800:]))
        d, sr = read_wav_mono(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return d


def scan_music():
    """User beds in music/ + procedural names."""
    out = [{"id": "synthwave", "label": "Synthwave (procedural)"},
           {"id": "pulse", "label": "Pulse (procedural)"},
           {"id": "low_drive", "label": "Low Drive (procedural)"},
           {"id": "sparkle", "label": "Sparkle (procedural)"},
           {"id": "ambient_glow", "label": "Ambient Glow (procedural)"},
           {"id": "none", "label": "No music"}]
    if os.path.isdir(MUSIC_DIR):
        for f in sorted(os.listdir(MUSIC_DIR)):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                # C4e obs #2 (Yasser): friendly names in the picker. The three
                # CC0 beds ship with known track titles (ATTRIBUTIONS.md); any
                # other file gets its name humanized (underscores -> spaces).
                _pretty = {"bed_cave_drone.mp3": "Ambient Cave Drone (CC0)",
                           "bed_one_cool_minute.mp3": "One Cool Minute (CC0)",
                           "bed_old_key.mp3": "Old Key (CC0)"}
                label = _pretty.get(f) or (f.rsplit(".", 1)[0]
                                           .replace("_", " ").replace("-", " ").strip())
                out.append({"id": "file:" + f, "label": label})
    return out


# ------------------------------------------------------------- procedural beds
CHORD = [[55.0, 82.5, 110.0, 164.81],      # Amin feel
         [43.65, 65.41, 87.31, 130.81],    # darker
         [49.0, 73.42, 98.0, 146.83]]      # Gm feel


def bed_synthwave(dur, cuts, t_typing=None):
    """The proven promo_audio recipe, generalized to any duration + cut times."""
    SR = SR_OUT
    t = np.arange(int(SR * dur)) / SR
    out = np.zeros_like(t)
    rng = np.random.default_rng(7)

    # sections split at cuts (up to 6), cycling chord colors
    bounds = [0.0] + sorted(cuts) + [dur]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)][:6]
    for (s0, s1), ch in zip(segs, [CHORD[i % 3] for i in range(6)]):
        if s1 - s0 < 0.5:
            continue
        m = (t >= s0) & (t < s1)
        tt = t[m]
        d = np.zeros_like(tt)
        for f in ch:
            d += saw_harm(f * 1.003, tt) + saw_harm(f * 0.997, tt)
        d *= (0.5 + 0.5 * np.sin(2 * np.pi * 0.13 * tt)) ** 0.6
        d = onepole(d, 0.06)
        env = np.minimum(1, np.minimum(tt / 0.8, (s1 - s0 - tt) / 0.8))
        out[m] += d * env * 0.05

    # pulse bass: eighth notes 120bpm between first and last cut
    body0 = bounds[1] if len(bounds) > 2 else 0.0
    body1 = bounds[-2] if len(bounds) > 2 else dur
    bpm = 120
    step = 60 / bpm / 2
    for n, ts in enumerate(np.arange(body0, body1, step)):
        m = (t >= ts) & (t < ts + step)
        tt = t[m] - ts
        if n % 4 == 0:
            f = 55.0
        elif n % 2:
            continue
        else:
            f = 49.0
        b = np.sin(2 * np.pi * f * tt) * np.exp(-tt * 6) + 0.4 * np.sin(4 * np.pi * f * tt) * np.exp(-tt * 10)
        env = np.exp(-tt * 3.2)
        out[m] += b * (env * 0.5 + (0.18 if n % 4 else 0)) * 0.16

    # hats: sixteenths, highpassed noise, accent offbeats
    noise = rng.standard_normal(len(t))
    hp = noise - onepole(noise, 0.3)
    for ts in np.arange(body0, body1, step / 2):
        m = (t >= ts) & (t < ts + 0.04)
        amp = 0.03 if int(round((ts - body0) / (step / 2))) % 2 else 0.012
        out[m] += hp[m] * np.exp(-(t[m] - ts) * 90) * amp

    # impacts at cuts: kick thump + noise crash
    for c in cuts:
        m = (t >= c) & (t < min(dur, c + 1.2))
        tt = t[m] - c
        k = np.sin(2 * np.pi * (48 * np.exp(-tt * 7) + 30) * tt) * np.exp(-tt * 7)
        cr = rng.standard_normal(m.sum()) * np.exp(-tt * 5) * 0.16
        out[m] += k * 0.5 + cr

    # risers into mid-show cuts (skip the first two and last)
    big = [c for c in cuts][2:-1] if len(cuts) > 4 else []
    for c in big:
        s = c - 1.6
        m = (t >= max(0, s)) & (t < c)
        tt = t[m] - s
        p = tt / (c - s)
        out[m] += rng.standard_normal(m.sum()) * p ** 2 * 0.10
        out[m] += np.sin(2 * np.pi * (200 + 900 * p) * tt) * p ** 2 * 0.08

    # typing blips over a given window (terminal shots)
    if t_typing:
        s0, s1 = t_typing
        for ts in np.arange(s0 + 0.4, s1 - 0.4, 0.13):
            m = (t >= ts) & (t < ts + 0.05)
            tt = t[m] - ts
            f = rng.uniform(1800, 2600)
            out[m] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 70) * 0.05

    # whooshes at each cut
    for c in cuts:
        s = max(0.0, c - 0.35)
        e = min(dur, c + 0.25)
        m = (t >= s) & (t < e)
        tt = t[m] - s
        p = np.clip(tt / 0.6, 0, 1)
        w = rng.standard_normal(m.sum()) * (np.sin(np.pi * p) ** 2) * 0.12
        out[m] += onepole(w, 0.2)

    # fades + limiter
    out[: int(SR * 0.7)] *= np.linspace(0, 1, int(SR * 0.7))
    tail = min(int(SR * 2.5), len(out) // 3)
    out[-tail:] *= np.linspace(1, 0, tail) ** 1.5
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.86
    return np.tanh(out * 1.4) / np.tanh(1.4) * 0.9


def bed_pulse(dur, cuts, t_typing=None):
    """Simpler second bed: minor-key pluck arpeggio + kick on the cuts."""
    SR = SR_OUT
    t = np.arange(int(SR * dur)) / SR
    out = np.zeros_like(t)
    rng = np.random.default_rng(11)
    scale = [220.0, 261.63, 329.63, 392.0, 440.0]
    step = 60 / 100 / 2          # 100bpm eighths
    for n, ts in enumerate(np.arange(0.5, dur - 0.5, step)):
        m = (t >= ts) & (t < ts + step)
        tt = t[m] - ts
        f = scale[(n * 3) % len(scale)]
        p = np.sin(2 * np.pi * f * tt) * np.exp(-tt * 5)
        p += 0.3 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 8)
        out[m] += p * 0.10
    for c in cuts:
        m = (t >= c) & (t < min(dur, c + 1.0))
        tt = t[m] - c
        out[m] += np.sin(2 * np.pi * (50 * np.exp(-tt * 6) + 28) * tt) * np.exp(-tt * 6) * 0.4
    out[: int(SR * 0.5)] *= np.linspace(0, 1, int(SR * 0.5))
    tail = min(int(SR * 2.0), len(out) // 3)
    out[-tail:] *= np.linspace(1, 0, tail) ** 1.5
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.8
    return out


def bed_low_drive(dur, cuts, t_typing=None):
    """92bpm dark-drive bed: gliding sub bass, sparse clap, hat rolls. Heavier
    and slower than synthwave — good for hard-cut product/feature montages."""
    SR = SR_OUT
    t = np.arange(int(SR * dur)) / SR
    out = np.zeros_like(t)
    rng = np.random.default_rng(23)
    bpm = 92
    beat = 60 / bpm
    # sub bass: root per section (cycle CHORD roots), glide into each note
    bounds = [0.0] + sorted(cuts) + [dur]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)][:6]
    roots = [CHORD[i % 3][0] for i in range(6)]
    body0 = bounds[1] if len(bounds) > 2 else 0.5
    body1 = bounds[-2] if len(bounds) > 2 else dur - 0.5
    for n, ts in enumerate(np.arange(max(0.4, body0), min(dur - 0.3, body1), beat)):
        m = (t >= ts) & (t < min(dur, ts + beat * 1.9))
        tt = t[m] - ts
        root = next((r for (s0, s1), r in zip(segs, roots) if s0 <= ts < s1), roots[0])
        f0, f1 = root * 1.5, root          # downward glide each note
        ph = 2 * np.pi * (f1 * tt + (f0 - f1) * tt * np.exp(-tt * 6))
        sub = np.sin(ph) * np.exp(-tt * 2.2)
        out[m] += sub * 0.34
    # clap: bandpassed noise bursts on beats 2 and 4 of each bar
    claps = rng.standard_normal(len(t))
    claps = onepole(claps, 0.5) - onepole(onepole(claps, 0.5), 0.05)
    for n, ts in enumerate(np.arange(max(0.4, body0), min(dur - 0.3, body1), beat)):
        if n % 4 not in (1, 3):
            continue
        m = (t >= ts) & (t < ts + 0.12)
        tt = t[m] - ts
        out[m] += claps[m] * np.exp(-tt * 28) * 0.30
    # hats: sixteenth rolls, accent every other, roll fill into each cut
    step = beat / 4
    for ts in np.arange(max(0.4, body0), min(dur - 0.2, body1), step):
        m = (t >= ts) & (t < ts + 0.035)
        amp = 0.05 if int(round((ts - body0) / step)) % 2 else 0.022
        out[m] += rng.standard_normal(m.sum()) * np.exp(-(t[m] - ts) * 110) * amp
    for c in cuts:                              # roll fill in the last beat
        for ts in np.arange(max(0.0, c - beat), c, step / 2):
            m = (t >= ts) & (t < ts + 0.03)
            p = (ts - (c - beat)) / beat
            out[m] += rng.standard_normal(m.sum()) * np.exp(-(t[m] - ts) * 130) * (0.02 + 0.05 * max(0, p))
    # impacts at cuts: kick thump + crash
    for c in cuts:
        m = (t >= c) & (t < min(dur, c + 1.1))
        tt = t[m] - c
        k = np.sin(2 * np.pi * (44 * np.exp(-tt * 6) + 30) * tt) * np.exp(-tt * 6)
        out[m] += k * 0.5 + rng.standard_normal(m.sum()) * np.exp(-tt * 4.5) * 0.14
    if t_typing:
        s0, s1 = t_typing
        for ts in np.arange(s0 + 0.4, s1 - 0.4, 0.13):
            m = (t >= ts) & (t < ts + 0.05)
            tt = t[m] - ts
            out[m] += np.sin(2 * np.pi * rng.uniform(1600, 2200) * tt) * np.exp(-tt * 70) * 0.045
    out[: int(SR * 0.6)] *= np.linspace(0, 1, int(SR * 0.6))
    tail = min(int(SR * 2.2), len(out) // 3)
    out[-tail:] *= np.linspace(1, 0, tail) ** 1.5
    # loudness trim to the pulse/synthwave band (mean ~-19 dBFS) so beds
    # switch without a volume jump in the UI audition A/B; BEFORE normalize
    # so the peak bound below still holds
    out *= 1.15
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.84
    return np.tanh(out * 1.3) / np.tanh(1.3) * 0.9


def bed_sparkle(dur, cuts, t_typing=None):
    """130bpm bright upbeat bed: fast A-minor pluck arpeggio, four-on-floor
    kick, offbeat open hat — for energetic launches and feature teasers."""
    SR = SR_OUT
    t = np.arange(int(SR * dur)) / SR
    out = np.zeros_like(t)
    rng = np.random.default_rng(31)
    bpm = 130
    beat = 60 / bpm
    scale = [220.0, 261.63, 329.63, 392.0, 440.0, 523.25]
    step = beat / 2                            # eighth-note arps
    for n, ts in enumerate(np.arange(0.3, dur - 0.4, step)):
        m = (t >= ts) & (t < ts + step)
        tt = t[m] - ts
        f = scale[(n * 5) % len(scale)]        # coprime walk = never repeats flatly
        p = np.sin(2 * np.pi * f * tt) * np.exp(-tt * 7)
        p += 0.35 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 11)
        env = 0.75 + 0.25 * np.sin(2 * np.pi * (ts / (beat * 8)) * 2)
        out[m] += p * 0.095 * env
    # four-on-floor kick
    for ts in np.arange(0.3, dur - 0.4, beat):
        m = (t >= ts) & (t < ts + 0.3)
        tt = t[m] - ts
        out[m] += np.sin(2 * np.pi * (52 * np.exp(-tt * 8) + 30) * tt) * np.exp(-tt * 8) * 0.42
    # offbeat open hat
    for ts in np.arange(0.3 + beat / 2, dur - 0.4, beat):
        m = (t >= ts) & (t < ts + 0.09)
        tt = t[m] - ts
        out[m] += rng.standard_normal(m.sum()) * np.exp(-tt * 35) * 0.05
    # crash + uplifter at each cut
    for c in cuts:
        m = (t >= c) & (t < min(dur, c + 1.4))
        tt = t[m] - c
        out[m] += rng.standard_normal(m.sum()) * np.exp(-tt * 3.5) * 0.16
        s = max(0.0, c - 1.2)
        m2 = (t >= s) & (t < c)
        tt2 = t[m2] - s
        p2 = tt2 / (c - s)
        out[m2] += np.sin(2 * np.pi * (300 + 1200 * p2) * tt2) * p2 ** 2 * 0.06
    if t_typing:
        s0, s1 = t_typing
        for ts in np.arange(s0 + 0.4, s1 - 0.4, 0.13):
            m = (t >= ts) & (t < ts + 0.05)
            tt = t[m] - ts
            out[m] += np.sin(2 * np.pi * rng.uniform(2000, 2800) * tt) * np.exp(-tt * 70) * 0.045
    out[: int(SR * 0.5)] *= np.linspace(0, 1, int(SR * 0.5))
    tail = min(int(SR * 2.0), len(out) // 3)
    out[-tail:] *= np.linspace(1, 0, tail) ** 1.5
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.82
    return out


def bed_ambient_glow(dur, cuts, t_typing=None):
    """Beatless pad bed: slow-swelling stacked saw pads cycling the chord
    colors + soft noise wash + gentle swell into each cut. For voice-heavy
    explainers where drums would fight the VO."""
    SR = SR_OUT
    t = np.arange(int(SR * dur)) / SR
    out = np.zeros_like(t)
    rng = np.random.default_rng(41)
    bounds = [0.0] + sorted(cuts) + [dur]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    for si, ((s0, s1), ch) in enumerate(zip(segs, [CHORD[i % 3] for i in range(len(segs))])):
        if s1 - s0 < 0.4:
            continue
        m = (t >= s0) & (t < s1)
        tt = t[m] - s0
        d = np.zeros_like(tt)
        for f in ch:
            d += saw_harm(f * 0.5 * 1.004, tt, n=8) + saw_harm(f * 0.5 * 0.996, tt, n=8)
        d = onepole(d, 0.02)                    # dark pad: heavy lowpass
        swell = np.sin(np.pi * np.clip(tt / (s1 - s0), 0, 1)) ** 0.7
        d *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.09 * tt + si)
        out[m] += d * swell * 0.045
    # soft noise wash (air), very low
    wash = onepole(rng.standard_normal(len(t)), 0.4) - onepole(onepole(rng.standard_normal(len(t)), 0.4), 0.02)
    out += wash * 0.012
    # gentle swell into each cut (no drums — VO-friendly)
    for c in cuts:
        s = max(0.0, c - 1.8)
        if c - s < 0.3:
            continue
        m = (t >= s) & (t < min(dur, c + 0.8))
        tt = t[m] - s
        p = np.clip(tt / (c - s + 0.8), 0, 1)
        out[m] += onepole(rng.standard_normal(m.sum()), 0.25) * np.sin(np.pi * p) ** 2 * 0.06
    if t_typing:
        s0, s1 = t_typing
        for ts in np.arange(s0 + 0.4, s1 - 0.4, 0.13):
            m = (t >= ts) & (t < ts + 0.05)
            tt = t[m] - ts
            out[m] += np.sin(2 * np.pi * rng.uniform(1700, 2400) * tt) * np.exp(-tt * 70) * 0.04
    out[: int(SR * 1.2)] *= np.linspace(0, 1, int(SR * 1.2))
    tail = min(int(SR * 2.5), len(out) // 3)
    out[-tail:] *= np.linspace(1, 0, tail) ** 1.5
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.8
    # loudness trim to the pulse/synthwave band (see low_drive note)
    return out * 0.65


BEDS = {"synthwave": bed_synthwave, "pulse": bed_pulse,
        "low_drive": bed_low_drive, "sparkle": bed_sparkle,
        "ambient_glow": bed_ambient_glow}


# ------------------------------------------------------------------ Piper VO
def list_voices():
    """Piper voice models present in vo/models/ (+ 'none')."""
    out = [{"id": "none", "label": "No voiceover"}]
    if os.path.isdir(VO_MODELS):
        for f in sorted(os.listdir(VO_MODELS)):
            if f.endswith(".onnx"):
                out.append({"id": f[:-5], "label": f[:-5]})
    return out


def piper_available():
    try:
        r = subprocess.run([PY311, "-m", "piper", "--help"], capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


VO_SPEED_RANGE = (0.7, 1.5)  # sane bounds; UI offers 0.8/1.0/1.25


def piper_line(text, voice_id, out_wav, speed=1.0):
    model = os.path.join(VO_MODELS, voice_id + ".onnx")
    if not os.path.exists(model):
        raise RuntimeError("voice model not found: %s (run setup_vo.bat)" % model)
    # NOTE: piper 1.8's `-f FILE` path crashes on Python 3.14 (wave.py bug), so
    # synthesize into a temp dir via --output-dir and move the result ourselves.
    import tempfile
    os.makedirs(os.path.dirname(out_wav) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="piper_")
    cmd = [PY311, "-m", "piper", "-m", model, "--output-dir", tmp]
    # v1.4 C2: speech speed via piper's --length-scale (LS>1 = slower). Speed S
    # maps to LS=1/S; omit the flag entirely at 1.0 so the default argv shape —
    # and every existing cached line — stays exactly as before.
    if abs(float(speed) - 1.0) > 1e-9:
        cmd += ["--length-scale", "%.2f" % (1.0 / float(speed))]
    try:
        r = subprocess.run(cmd,
                           input=text, text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError("piper failed: " + (r.stderr or "")[-400:])
        wavs = sorted(f for f in os.listdir(tmp) if f.endswith(".wav"))
        if not wavs:
            raise RuntimeError("piper produced no output")
        src = os.path.join(tmp, wavs[0])
        if len(wavs) > 1:  # stitch multi-sentence lines with 250 ms gaps
            parts = [read_wav_mono(os.path.join(tmp, w))[0] for w in wavs]
            gap = np.zeros(int(0.25 * 22050), dtype=np.int16)
            merged = np.concatenate([p for pair in zip(parts, [gap] * len(parts)) for p in pair][:-1])
            import wave as _w
            with _w.open(src, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
                w.writeframes(merged.tobytes())
        if os.path.exists(out_wav):
            os.remove(out_wav)
        shutil.move(src, out_wav)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_wav


def vo_duration(text, voice_id, scratch, speed=1.0):
    """Generate one line and return its duration in seconds (cached by hash).
    v1.4 C2: the cache key includes speed — same text+voice at different
    speeds are different wavs; without this, sped lines serve stale audio."""
    import hashlib
    speed = float(speed)
    sp = "" if abs(speed - 1.0) < 1e-9 else "|s%.2f" % speed
    h = hashlib.sha256((voice_id + "|" + text + sp).encode("utf-8")).hexdigest()[:16]
    p = os.path.join(scratch, "vo_%s.wav" % h)
    if not os.path.exists(p):
        piper_line(text, voice_id, p, speed=speed)
    d, sr = read_wav_mono(p)
    return len(d) / sr, p


def vo_duration_probe(voice_id, scratch, speed=1.0):
    """Cheap fixed-sentence synthesis used by the UI audition button — probes
    the whole chain (model + subprocess + decode) with a tiny input."""
    return vo_duration("This is how I sound in your promo.", voice_id, scratch,
                       speed=speed)


# --------------------------------------------------------------- bed assembly
def shot_timeline(proj):
    starts, acc = [], 0.0
    for s in proj["shots"]:
        starts.append(acc)
        acc += float(s["t"])
    cuts = [starts[i] for i in range(1, len(starts))]
    return starts, cuts


def vo_plan(proj, voice_id, scratch):
    """Resolve project vo_lines -> (start, dur, text, wav_path) placements. VO
    start is absolute; shot/offset resolve against the shot timeline. v1.41 C1:
    also returns the synthesized wav path so build_audio's mix loop never
    re-synthesizes without the project speed (audit #1 B1)."""
    starts, _ = shot_timeline(proj)
    vspeed = float(proj.get("voice_speed", 1.0))  # v1.4 C2
    plan = []
    for L in proj.get("vo_lines", []):
        if not L.get("text"):
            continue
        if "shot" in L:
            st = starts[int(L["shot"])] + float(L.get("offset", 0.0))
        else:
            st = float(L["at"])
        dur, wav = vo_duration(L["text"], voice_id, scratch, speed=vspeed)
        plan.append((st, dur, L["text"], wav))
    return plan


def _resolve_bed(fn):
    """v1.41 C4 (audit #1 S5): confine EVERY music bed to the shipped music/
    folder — v1.31 only guarded relative beds, so an absolute path in project
    JSON read any file on disk. The UI's file picker hands over absolutes that
    point INTO music/, so basename-map absolutes into music/ (same basename =
    same shipped track) and reject anything that doesn't resolve inside it."""
    fn = str(fn or "")
    if not fn:
        raise ValueError("music bed is empty")
    base = os.path.basename(fn)
    path = os.path.join(MUSIC_DIR, base)
    _b = os.path.realpath(MUSIC_DIR)
    _p = os.path.realpath(path)
    if not (_p == _b or _p.startswith(_b + os.sep)):
        raise ValueError("music bed %r escapes the music/ folder" % fn)
    # v1.4 C4b hard gate: every music/-resolved bed must actually exist —
    # a mapped name with no shipped track fails loud, never silent.
    if not os.path.isfile(_p):
        raise ValueError("music bed %r not found in the music/ folder" % fn)
    return path


def _normalize_music(cfg):
    """One shape for the music config, whatever wrote it (audit #2). The UI
    historically wrote {"file": "x.mp3"} with no mode -> build_audio then fell
    through to a procedural bed: silent wrong output. Derive mode from the
    keys present; also accept scan_music's "file:name" bed id."""
    if not cfg:
        return {"mode": "procedural", "bed": "synthwave"}
    cfg = dict(cfg)
    bed = cfg.get("bed") or cfg.get("file") or ""
    if bed.startswith("file:"):
        bed = bed[len("file:"):]
    if bed in ("", None):
        return {"mode": "procedural", "bed": "synthwave"}
    if bed == "none":
        return {"mode": "none", "bed": "none"}
    looks_like_file = any(str(bed).lower().endswith(ext)
                          for ext in (".mp3", ".wav", ".m4a", ".ogg"))
    # C4e (Yasser live test obs #1): an explicit mode:"file" must ALWAYS win —
    # the UI writes exactly that. The old condition also demanded mode NOT be
    # procedural, so a file bed arriving with a stale/mismatched mode silently
    # fell through to procedural and rendered the wrong track.
    if cfg.get("mode") == "file" or ("file" in cfg and looks_like_file) or \
            (cfg.get("mode") not in ("procedural", "file") and looks_like_file
             and bed not in BEDS):
        return {"mode": "file", "bed": str(bed)}
    # A bare filename that is NOT a procedural bed name is a file bed too,
    # whatever mode string came along with it (scan_music ids carry no mode).
    if looks_like_file and bed not in BEDS:
        return {"mode": "file", "bed": str(bed)}
    return {"mode": "procedural", "bed": str(bed)}


def build_audio(proj, media_dir=None, scratch=None, music_override=None):
    """Full audio bed -> 48kHz stereo WAV path. Hard-asserts TOTAL length."""
    music_cfg = _normalize_music(music_override or proj.get("music"))
    voice = proj.get("voice", "none")
    dur = float(proj["target"])
    starts, cuts = shot_timeline(proj)
    TOTAL = int(round(dur * SR_OUT))

    # v1.36 (Onyx draft): per-letter keyboard clicks for typewriter captions,
    # sampled exactly where the draw path lands each glyph (at + i*TYPE_STEP).
    # No shipped project uses kind "typewriter" -> type_clicks stays empty and
    # every existing render's audio is byte-identical.
    from . import metrics as _M
    type_clicks = []
    for si, s in enumerate(proj["shots"]):
        for L in s.get("captions", []):
            if L.get("kind") == "typewriter":
                t0 = starts[si] + float(L.get("at", 0.2))
                n = len(str(L.get("text", "")))
                type_clicks.extend(t0 + i * _M.TYPE_STEP for i in range(n))

    if scratch is None:
        scratch = os.path.join(ROOT, "output", "_audio_scratch")
    os.makedirs(scratch, exist_ok=True)

    # ---- music bed ----
    mode = music_cfg.get("mode", "procedural")
    if mode == "none" or music_cfg.get("bed") == "none":
        music = np.zeros(TOTAL)
    elif mode == "file":
        fn = str(music_cfg.get("bed", "")).replace("file:", "")
        path = _resolve_bed(fn)
        d = load_music_file(path)
        # v1.4 CC0 beds: external tracks arrive at whatever loudness they were
        # mastered at (commercial masters sit ~-9 dBFS mean vs our procedural
        # band ~-19); match the procedural loudness band, then peak-normalize
        # to 0.84 exactly like bed_pulse — otherwise a hot master buries VO.
        mean = float(np.mean(np.abs(d))) if len(d) else 0.0
        if mean > 0:
            d = d * (10 ** ((-19.5 - (20 * np.log10(mean))) / 20.0))
        peak = float(np.max(np.abs(d))) if len(d) else 0.0
        if peak > 0:
            d = d / peak * 0.84
        music = np.zeros(TOTAL)
        n = min(len(d), TOTAL)
        music[:n] = d[:n]
    else:
        bed_fn = BEDS.get(music_cfg.get("bed", "synthwave"), bed_synthwave)
        # typing blips over any terminal caption shots
        t_typing = None
        for i, s in enumerate(proj["shots"]):
            if any(c.get("kind") == "terminal" for c in s.get("captions", [])):
                t_typing = (starts[i], starts[i] + float(s["t"]))
                break
        music = bed_fn(dur, cuts, t_typing)
    # beds build on beat grids; a float dur can land one sample off TOTAL and
    # break the mix add (kinetic drafts surfaced this at 21.4s targets).
    if len(music) != TOTAL:
        music = np.resize(music, TOTAL)

    # ---- VO bed (numpy floats; NEVER bytearray slicing) ----
    vo = np.zeros(TOTAL)
    ducks = []
    if voice and voice != "none" and proj.get("vo_lines"):
        plan = vo_plan(proj, voice, scratch)
        for st, d, text, wav in plan:
            i0 = int(st * SR_OUT)
            data, sr = read_wav_mono(wav)  # v1.41 C1: the sped wav from the plan
            data = resample(data, sr, SR_OUT)
            n = len(data)
            if i0 + n > TOTAL:
                raise RuntimeError("VO line %r (%.2fs) overruns the %.1fs timeline at %.2fs"
                                   % (text[:40], d, dur, st))
            fade = int(0.03 * SR_OUT)
            g = np.ones(n)
            g[:fade] *= np.linspace(0, 1, fade)
            g[-fade:] *= np.linspace(1, 0, fade)
            vo[i0:i0 + n] += data * g
            ducks.append([round(st - 0.15, 3), round(st + n / SR_OUT + 0.15, 3)])

    # ---- duck music under VO (0.12s ramps to ~45%) ----
    if ducks:
        env = np.ones(TOTAL)
        ramp = int(0.12 * SR_OUT)
        for a, b in ducks:
            i0, i1 = max(0, int(a * SR_OUT)), min(TOTAL, int(b * SR_OUT))
            seg = np.full(i1 - i0, 0.45)
            r0, r1 = min(ramp, len(seg) // 2), min(ramp, len(seg) - min(ramp, len(seg) // 2))
            seg[:r0] = np.linspace(1, 0.45, r0)
            seg[-r1:] = np.linspace(0.45, 1, r1)
            env[i0:i1] = np.minimum(env[i0:i1], seg)
        music = music * env

    # ---- mix + soft limit (music*0.9 + vo*1.25) ----
    mix = music * 0.9 + vo * 1.25
    if type_clicks:
        # mechanical key clicks: noise transient + tick, alternating pitch so
        # repeated letters never sound like one drone; ducked under the VO.
        rng = np.random.default_rng(11)
        for ci, ts in enumerate(type_clicks):
            i0 = int(ts * SR_OUT)
            n = int(0.035 * SR_OUT)
            if i0 + n > TOTAL:
                continue
            tt = np.arange(n) / SR_OUT
            amp = 0.16 * (0.8 + 0.4 * rng.random())
            cl = rng.standard_normal(n) * np.exp(-tt * 260) * 0.7
            cl += np.sin(2 * np.pi * rng.uniform(1500, 2300) * tt) * np.exp(-tt * 160) * 0.5
            duck = 0.4 if (voice != "none" and vo.any()) else 1.0
            mix[i0:i0 + n] += cl * amp * duck
    mix = np.tanh(mix * 1.4) / np.tanh(1.4)
    peak = np.max(np.abs(mix)) if np.any(mix) else 1.0
    mix = mix / peak * 0.93 if peak > 0 else mix

    assert len(mix) == TOTAL, "bed length %d != TOTAL %d" % (len(mix), TOTAL)
    stereo = np.repeat(mix[:, None], 2, axis=1)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    out_wav = os.path.join(scratch, "bed.wav")
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR_OUT)
        w.writeframes(pcm.tobytes())
    # hard gate at the file level too
    with wave.open(out_wav, "rb") as w:
        assert w.getnframes() == TOTAL, "wav frames %d != TOTAL %d" % (w.getnframes(), TOTAL)
    return out_wav


# ------------------------------------------------------------- mux + verify
def ffprobe_streams(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,duration,width,height,r_frame_rate",
                        "-of", "json", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffprobe failed: " + r.stderr[-400:])
    return json.loads(r.stdout)["streams"]


def verify_durations(path, expected, expect_audio=True):
    """Hard gate: video (and audio when present/expected) within 0.15s of expected."""
    st = ffprobe_streams(path)
    vd = next((float(s["duration"]) for s in st if s["codec_type"] == "video"), None)
    ad = next((float(s["duration"]) for s in st if s["codec_type"] == "audio"), None)
    problems = []
    if vd is None or abs(vd - expected) > 0.15:
        problems.append("video duration %s != %.2f" % (vd, expected))
    if expect_audio and (ad is None or abs(ad - expected) > 0.15):
        problems.append("audio duration %s != %.2f" % (ad, expected))
    if problems:
        raise RuntimeError("A/V verification FAILED for %s: %s" % (path, "; ".join(problems)))
    return vd, ad
