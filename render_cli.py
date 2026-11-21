# SPDX-License-Identifier: AGPL-3.0-only
"""LEEBKIT CLI render entry.

  python render_cli.py samples/leebdark_sample.json [--media DIR] [--out FILE]
                       [--no-audio] [--draft] [--jobs N]

Renders frames (optionally parallel across processes), encodes with ffmpeg,
then builds + muxes audio unless --no-audio. Verifies output with ffprobe.
"""
import argparse
import array
import json
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from core import share_caps  # noqa: E402  (C5: caps are one source of truth)


def _worker_init(proj_path, media_dir):
    global _ENG
    from core.engine import Engine
    with open(proj_path, "r", encoding="utf-8") as f:
        _ENG = Engine(json.load(f), media_dir=media_dir)


def _worker_init_bed(proj_path, media_dir, bed_wav):
    # v1.6 B2: --finish used to force jobs=1 (the audio bed lived on the
    # parent's engine only). The bed is pure data now — each worker loads it
    # from the already-built mix wav and calls set_vo_bed itself, so the
    # beat/envelope pass parallelizes exactly like the default path.
    _worker_init(proj_path, media_dir)
    import wave
    with wave.open(bed_wav, "rb") as w:
        assert w.getnchannels() == 2 and w.getsampwidth() == 2 \
            and w.getframerate() == 48000, \
            "bed wav must be the 48kHz stereo s16 build_audio output"
        n = w.getnframes()
        # de-interleave L channel: identical to build_audio's mono mix before
        # its np.repeat stereo write (same PCM scale), so the bed is pure data.
        pcm = array.array("h", w.readframes(n))
        _ENG.set_vo_bed(pcm[0::2])


def _worker_chunk(args):
    a, b, frames_dir = args
    for idx in range(a, b):
        # PNG, not JPEG: lossy-then-lossy (q92 -> crf 18) visibly softens grain
        # and text edges (audit #4). compress_level=1 (v1.41 C7 / audit #1 P2):
        # intermediates are deleted after encode — max deflate is wasted CPU.
        _ENG.compose_frame(idx).save(
            os.path.join(frames_dir, "f_%04d.png" % idx), compress_level=1)
    return b - a


def render_frames(proj_path, media_dir, frames_dir, n, jobs=1, progress=None,
                  engine=None, bed_wav=None):
    """Render n frames into frames_dir. Pass `engine` (an already-built Engine)
    to force the single-process path. v1.6 B2: pass `bed_wav` (build_audio's
    mono mix) instead of a bed-carrying engine — pool workers load the wav in
    their initializer, so the --finish beat pass parallelizes too."""
    os.makedirs(frames_dir, exist_ok=True)
    chunk = max(1, (n + jobs - 1) // jobs)
    ranges = [(a, min(a + chunk, n), frames_dir) for a in range(0, n, chunk)]
    t0 = time.time()
    if engine is not None:
        global _ENG
        _ENG = engine
        jobs = 1
    if jobs > 1:
        import multiprocessing as mp
        init, initargs = (_worker_init_bed, (proj_path, media_dir, bed_wav)) \
            if bed_wav else (_worker_init, (proj_path, media_dir))
        with mp.Pool(jobs, initializer=init, initargs=initargs) as pool:
            done = 0
            for k, cnt in enumerate(pool.imap_unordered(_worker_chunk, ranges)):
                done += cnt
                if progress:
                    progress(done, n)
    else:
        if bed_wav:
            _worker_init_bed(proj_path, media_dir, bed_wav)
        else:
            _worker_init(proj_path, media_dir)
        for a, b, _ in ranges:
            _worker_chunk((a, b, frames_dir))
            if progress:
                progress(b, n)
    return time.time() - t0


def encode_video(frames_dir, out_mp4, fps=30, crf="18", preset_v="slow", audio_wav=None):
    """Single encoder definition (audit #10 v1.31): core/queue.py used to carry
    its own copy at crf 19/preset medium, so CLI and app outputs differed. The
    queue now calls this with the same quality constants; --draft overrides."""
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(frames_dir, "f_%04d.png")]
    if audio_wav:
        cmd += ["-i", audio_wav]
    cmd += ["-c:v", "libx264", "-preset", preset_v, "-crf", crf,
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
    if audio_wav:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd.append(out_mp4)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed:\n" + r.stderr[-2000:])


# ------------------------------------------------------- share export (v1.4 C5)
def gif_step(src_fps):
    """Decimation step so the GIF lands <= GIF_FPS fps (frame indices are
    sampled from the source sequence — captions never re-timed)."""
    return max(1, int(-(-src_fps // share_caps.GIF_FPS)))   # ceil div


def _share_window(src_fps, max_s):
    """Frame-index window enforcing the duration cap on the SOURCE fps."""
    return min(int(max_s * src_fps), 10 ** 9)


def frame_dir_to_gif(frames_dir, out_gif, src_fps, src_w, pattern="f_%04d.png"):
    """Palette-split GIF from an existing LEEBKIT frame dir: ffmpeg palettegen
    (full fps, downscaled) -> paletteuse dithering. Frame decimation to
    <=GIF_FPS and the duration/width caps come from core.share_caps — the file
    itself is capped, not just the help text ("GIF is a share teaser")."""
    # Decimate by frame INDEX (select), then relabel timestamps (setpts):
    # kept frames are exactly range(0, n, step) and duration = kept/step —
    # an fps= filter rounds timing to its own timebase and can keep one
    # frame too many past the cap.
    n_src = _count_frames(frames_dir, pattern)
    keep = min(_share_window(src_fps, share_caps.GIF_MAX_S), n_src)
    step = gif_step(src_fps)
    w = min(src_w, share_caps.GIF_MAX_W)
    if w != src_w:
        h = int(round(w * _frame_dims(frames_dir, pattern)[1] / src_w))
        scale = "scale=%d:%d:flags=lanczos," % (w, h - h % 2)
    else:
        scale = ""
    # NOTE on quoting (probe-verified vs ffmpeg 8): subprocess passes the arg
    # verbatim (no shell). Escape commas INSIDE a filter arg with \, and chain
    # filters with a bare comma. select's expression is ONE arg, so chaining
    # setpts after it needs the arg to end — put lte first so the decimation
    # math reads lte(n,K)*not(mod(n,S)) with only arg-internal escapes.
    # setpts=N/out_fps/TB (NOT bare N/fps): without /TB the pts lands ~1 tick
    # off in the gif timebase and the muxer drops frames (probe-verified:
    # 36 kept -> 2 with bare N/12, exact with /TB).
    sel = "select=lte(n\\,%d)*not(mod(n\\,%d)),setpts=N/%d/TB" % (keep - 1, step, src_fps // step)
    vf = scale + sel
    pal = out_gif + ".palette.png"
    base = ["ffmpeg", "-y", "-start_number", "0", "-framerate", str(src_fps),
            "-i", os.path.join(frames_dir, pattern)]
    gen = subprocess.run(base + ["-vf", vf + ",palettegen=max_colors=256\\:stats_mode=full", pal],
                         capture_output=True, text=True)
    if gen.returncode != 0:
        raise RuntimeError("gif palettegen failed:\n" + gen.stderr[-2000:])
    enc = subprocess.run(base + ["-i", pal,
                                 "-filter_complex",
                                 "[0:v]" + vf + "[base];[base][1:v]"
                                 "paletteuse=dither=bayer\\:bayer_scale=4\\:diff_mode=rectangle",
                                 "-loop", "0", out_gif], capture_output=True, text=True)
    try:
        os.remove(pal)
    except OSError:
        pass
    if enc.returncode != 0:
        raise RuntimeError("gif encode failed:\n" + enc.stderr[-2000:])
    return {"file": out_gif, "frames_kept": math.ceil(keep / step),
            "width": w, "fps": src_fps // step}


def frame_dir_to_webp(frames_dir, out_webp, src_fps, pattern="f_%04d.png"):
    """Animated WebP teaser: same index-decimation as GIF (motion reads
    identically), width capped at WEBP_MAX_W, duration at WEBP_MAX_S. Full-
    color encode — no palette pass."""
    n_src = _count_frames(frames_dir, pattern)
    keep = min(_share_window(src_fps, share_caps.WEBP_MAX_S), n_src)
    step = gif_step(src_fps)
    w0, h0 = _frame_dims(frames_dir, pattern)
    vf = "select=lte(n\\,%d)*not(mod(n\\,%d)),setpts=N/%d/TB" % (keep - 1, step, src_fps // step)
    if w0 > share_caps.WEBP_MAX_W:
        nw = share_caps.WEBP_MAX_W
        nh = int(round(nw * h0 / w0))
        vf += ",scale=%d:%d:flags=lanczos" % (nw, nh - nh % 2)
    r = subprocess.run(["ffmpeg", "-y", "-start_number", "0", "-framerate", str(src_fps),
                        "-i", os.path.join(frames_dir, pattern),
                        "-vf", vf + ",format=yuv420p", "-c:v", "libwebp",
                        "-loop", "0", "-quality", "80", out_webp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("webp encode failed:\n" + r.stderr[-2000:])
    return {"file": out_webp, "frames_kept": math.ceil(keep / step),
            "width": min(w0, share_caps.WEBP_MAX_W), "fps": src_fps // step}


def encode_share(frames_dir, out_path, fmt, src_fps, src_w, pattern="f_%04d.png"):
    fmt = (fmt or "").lower().lstrip(".")
    if fmt == "gif":
        return frame_dir_to_gif(frames_dir, out_path, src_fps, src_w, pattern=pattern)
    if fmt in ("webp", "animated-webp"):
        return frame_dir_to_webp(frames_dir, out_path, src_fps, pattern=pattern)
    raise ValueError("share format must be gif or webp (got %r)" % fmt)


def _count_frames(frames_dir, pattern="f_%04d.png"):
    n = 0
    while os.path.isfile(os.path.join(frames_dir, pattern % n)):
        n += 1
    return n


def _frame_dims(frames_dir, pattern="f_%04d.png"):
    from PIL import Image
    with Image.open(os.path.join(frames_dir, pattern % 0)) as im:
        return im.size


def main():  # CLI boundary: engine errors become exit codes here, nowhere else
    ap = argparse.ArgumentParser(description="LEEBKIT CLI renderer")
    ap.add_argument("project")
    ap.add_argument("--media", default=None, help="dir to resolve shot image paths from")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--draft", action="store_true", help="fast encode (preset veryfast crf 23)")
    ap.add_argument("--jobs", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    ap.add_argument("--gif", action="store_true",
                    help="also write a share GIF next to the mp4 (teaser caps: "
                         "%dpx / %.0fs / %dfps — from core.share_caps)"
                         % (share_caps.GIF_MAX_W, share_caps.GIF_MAX_S, share_caps.GIF_FPS))
    ap.add_argument("--webp", action="store_true",
                    help="also write a share animated WebP next to the mp4 "
                         "(caps: %dpx / %.0fs)" % (share_caps.WEBP_MAX_W, share_caps.WEBP_MAX_S))
    ap.add_argument("--finish", action="store_true",
                    help="v1.5 item 11b: assemble audio FIRST, wire the mix "
                         "into the engine, then re-render frames on it (single "
                         "job) before encode+mux — eq_bars/beat visuals react to "
                         "the REAL bed+VO envelope for ANY project, not only "
                         "eq_bars+voice. Costs one extra frame pass; default "
                         "path stays byte-identical.")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be >= 1 (got %d)" % args.jobs)

    proj_path = os.path.abspath(args.project)
    with open(proj_path, "r", encoding="utf-8") as f:
        proj = json.load(f)
    from core.engine import validate_project
    validate_project(proj)
    name = proj.get("name", os.path.splitext(os.path.basename(proj_path))[0])
    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_mp4 = args.out or os.path.join(out_dir, "%s.mp4" % name)
    frames_dir = os.path.join(out_dir, "_frames_%s" % name)
    media_dir = args.media or os.path.join(ROOT, "media")

    n = int(round(proj["target"] * proj.get("fps", 30)))

    # v1.5 C5: eq_bars bars ride the real audio bed. The mix only exists
    # after build_audio, so when a project has an eq_bars caption AND voice
    # audio, assemble audio FIRST and wire the mono mix into every engine
    # (Engine.set_vo_bed / _worker_init_bed) before rendering frames.
    # Projects without eq_bars keep the exact v1.41 order: frames -> encode
    # -> audio -> mux (byte-identical default path).
    from core import audio as A
    wav = None
    _eqb = any(c.get("kind") == "eq_bars"
               for s in proj["shots"] for c in s.get("captions", []))
    _voaudio = (not args.no_audio and proj.get("voice") not in (None, "none")
                and proj.get("vo_lines"))
    _audio_first = args.finish or (_eqb and _voaudio)
    if _audio_first:
        wav = A.build_audio(
            proj, media_dir=media_dir,
            scratch=os.path.join(out_dir, "_audio_%s" % name))

    print("rendering %d frames (%d jobs)..." % (n, args.jobs), flush=True)
    dt = render_frames(proj_path, media_dir, frames_dir, n, jobs=args.jobs,
                       progress=lambda d, t: print("  %d/%d" % (d, t), flush=True) if d % 150 == 0 else None,
                       bed_wav=wav if _audio_first else None)
    if args.finish:
        # v1.5 item 11b (--finish): the pass above ran before any bed existed
        # (build_audio's mix only fires at mix time), so re-render once with
        # the bed wired — every beat/envelope visual now reads the REAL final
        # mix. Deterministic: same wav, same pure clocks; v1.6 B2 parallelizes
        # this pass (workers self-wire via _worker_init_bed).
        print("re-rendering %d frames with audio bed wired (--finish)..." % n,
              flush=True)
        dt += render_frames(proj_path, media_dir, frames_dir, n, jobs=args.jobs,
                            progress=lambda d, t: print("  %d/%d" % (d, t), flush=True) if d % 150 == 0 else None,
                            bed_wav=wav)
    print("frames done in %.1fs — encoding video..." % dt, flush=True)
    fps = proj.get("fps", 30)
    encode_video(frames_dir, out_mp4, fps=fps,
                 crf="23" if args.draft else "18",
                 preset_v="veryfast" if args.draft else "slow")

    if not args.no_audio:
        if wav is None:
            wav = A.build_audio(proj, media_dir=media_dir, scratch=os.path.join(out_dir, "_audio_%s" % name))
        tmp = out_mp4 + ".muxed.mp4"
        cmd = ["ffmpeg", "-y", "-i", out_mp4, "-i", wav, "-c:v", "copy", "-c:a", "aac",
               "-b:a", "192k", "-shortest", tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("mux failed:\n" + r.stderr[-2000:])
        os.replace(tmp, out_mp4)
    from core import audio as A
    A.verify_durations(out_mp4, proj["target"], expect_audio=not args.no_audio)

    # C5 share teasers ride the SAME frame dir (no re-render); encoded AFTER
    # the mp4 gate so a bad master never yields share files. Frames survive
    # until this point — kept for exactly this reason.
    if args.gif or args.webp:
        fps = proj.get("fps", 30)
        w = int(proj.get("width", 1080))
        if args.gif:
            g = os.path.splitext(out_mp4)[0] + ".gif"
            info = encode_share(frames_dir, g, "gif", src_fps=fps, src_w=w)
            print("GIF -> %s (%d frames @%dfps, %dpx — teaser caps enforced)"
                  % (g, info["frames_kept"], info["fps"], info["width"]))
        if args.webp:
            wp = os.path.splitext(out_mp4)[0] + ".webp"
            info = encode_share(frames_dir, wp, "webp", src_fps=fps, src_w=w)
            print("WEBP -> %s (%d frames @%dfps, %dpx)"
                  % (wp, info["frames_kept"], info["fps"], info["width"]))

    # cleanup scratch frames
    import shutil
    shutil.rmtree(frames_dir, ignore_errors=True)
    print("OK ->", out_mp4)
    return out_mp4


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        # engine raises this for missing/outside-media shot images; the CLI is
        # the only place allowed to turn it into an exit (queue must catch it)
        print("[LEEBKIT] ERROR: %s" % e, file=sys.stderr)
        sys.exit(2)
