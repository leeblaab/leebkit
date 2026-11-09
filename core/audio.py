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
    tmp = path + ".tmp48k.wav"
    r = subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(SR_OUT), "-ac", "1", tmp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("cannot decode music file %s:\n%s" % (path, r.stderr[-800:]))
    d, sr = read_wav_mono(tmp)
    os.remove(tmp)
    return d


def scan_music():
    """User beds in music/ + procedural names."""
    out = [{"id": "synthwave", "label": "Synthwave (procedural)"},
           {"id": "pulse", "label": "Pulse (procedural)"},
           {"id": "none", "label": "No music"}]
    if os.path.isdir(MUSIC_DIR):
        for f in sorted(os.listdir(MUSIC_DIR)):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                out.append({"id": "file:" + f, "label": f})
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


BEDS = {"synthwave": bed_synthwave, "pulse": bed_pulse}


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


def piper_line(text, voice_id, out_wav):
    model = os.path.join(VO_MODELS, voice_id + ".onnx")
    if not os.path.exists(model):
        raise RuntimeError("voice model not found: %s (run setup_vo.bat)" % model)
    # NOTE: piper 1.8's `-f FILE` path crashes on Python 3.14 (wave.py bug), so
    # synthesize into a temp dir via --output-dir and move the result ourselves.
    import tempfile
    os.makedirs(os.path.dirname(out_wav) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="piper_")
    try:
        r = subprocess.run([PY311, "-m", "piper", "-m", model, "--output-dir", tmp],
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


def vo_duration(text, voice_id, scratch):
    """Generate one line and return its duration in seconds (cached by hash)."""
    import hashlib
    h = hashlib.sha256((voice_id + "|" + text).encode("utf-8")).hexdigest()[:16]
    p = os.path.join(scratch, "vo_%s.wav" % h)
    if not os.path.exists(p):
        piper_line(text, voice_id, p)
    d, sr = read_wav_mono(p)
    return len(d) / sr, p


# --------------------------------------------------------------- bed assembly
def shot_timeline(proj):
    starts, acc = [], 0.0
    for s in proj["shots"]:
        starts.append(acc)
        acc += float(s["t"])
    cuts = [starts[i] for i in range(1, len(starts))]
    return starts, cuts


def vo_plan(proj, voice_id, scratch):
    """Resolve project vo_lines -> (start, dur, text) placements. VO start is
    absolute; shot/offset resolve against the shot timeline."""
    starts, _ = shot_timeline(proj)
    plan = []
    for L in proj.get("vo_lines", []):
        if not L.get("text"):
            continue
        if "shot" in L:
            st = starts[int(L["shot"])] + float(L.get("offset", 0.0))
        else:
            st = float(L["at"])
        dur, _ = vo_duration(L["text"], voice_id, scratch)
        plan.append((st, dur, L["text"]))
    return plan


def build_audio(proj, media_dir=None, scratch=None, music_override=None):
    """Full audio bed -> 48kHz stereo WAV path. Hard-asserts TOTAL length."""
    music_cfg = music_override or proj.get("music") or {"mode": "procedural", "bed": "synthwave"}
    voice = proj.get("voice", "none")
    dur = float(proj["target"])
    starts, cuts = shot_timeline(proj)
    TOTAL = int(round(dur * SR_OUT))

    if scratch is None:
        scratch = os.path.join(ROOT, "output", "_audio_scratch")
    os.makedirs(scratch, exist_ok=True)

    # ---- music bed ----
    mode = music_cfg.get("mode", "procedural")
    if mode == "none" or music_cfg.get("bed") == "none":
        music = np.zeros(TOTAL)
    elif mode == "file":
        fn = str(music_cfg.get("bed", "")).replace("file:", "")
        path = fn if os.path.isabs(fn) else os.path.join(MUSIC_DIR, fn)
        d = load_music_file(path)
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

    # ---- VO bed (numpy floats; NEVER bytearray slicing) ----
    vo = np.zeros(TOTAL)
    ducks = []
    if voice and voice != "none" and proj.get("vo_lines"):
        plan = vo_plan(proj, voice, scratch)
        for st, d, text in plan:
            i0 = int(st * SR_OUT)
            data, sr = read_wav_mono(vo_duration(text, voice, scratch)[1])
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
