"""REELKIT CLI render entry.

  python render_cli.py samples/leebdark_sample.json [--media DIR] [--out FILE]
                       [--no-audio] [--draft] [--jobs N]

Renders frames (optionally parallel across processes), encodes with ffmpeg,
then builds + muxes audio unless --no-audio. Verifies output with ffprobe.
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _worker_init(proj_path, media_dir):
    global _ENG
    from core.engine import Engine
    with open(proj_path, "r", encoding="utf-8") as f:
        _ENG = Engine(json.load(f), media_dir=media_dir)


def _worker_chunk(args):
    a, b, frames_dir = args
    for idx in range(a, b):
        _ENG.compose_frame(idx).save(os.path.join(frames_dir, "f_%04d.jpg" % idx), quality=92)
    return b - a


def render_frames(proj_path, media_dir, frames_dir, n, jobs=1, progress=None):
    os.makedirs(frames_dir, exist_ok=True)
    chunk = max(1, (n + jobs - 1) // jobs)
    ranges = [(a, min(a + chunk, n), frames_dir) for a in range(0, n, chunk)]
    t0 = time.time()
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs, initializer=_worker_init, initargs=(proj_path, media_dir)) as pool:
            done = 0
            for k, cnt in enumerate(pool.imap_unordered(_worker_chunk, ranges)):
                done += cnt
                if progress:
                    progress(done, n)
    else:
        _worker_init(proj_path, media_dir)
        for a, b, _ in ranges:
            _worker_chunk((a, b, frames_dir))
            if progress:
                progress(b, n)
    return time.time() - t0


def encode_video(frames_dir, out_mp4, fps=30, crf="18", preset_v="slow"):
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(frames_dir, "f_%04d.jpg"),
           "-c:v", "libx264", "-preset", preset_v, "-crf", crf,
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg video encode failed:\n" + r.stderr[-2000:])


def main():
    ap = argparse.ArgumentParser(description="REELKIT CLI renderer")
    ap.add_argument("project")
    ap.add_argument("--media", default=None, help="dir to resolve shot image paths from")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--draft", action="store_true", help="fast encode (preset veryfast crf 23)")
    ap.add_argument("--jobs", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    args = ap.parse_args()

    proj_path = os.path.abspath(args.project)
    with open(proj_path, "r", encoding="utf-8") as f:
        proj = json.load(f)
    name = proj.get("name", os.path.splitext(os.path.basename(proj_path))[0])
    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_mp4 = args.out or os.path.join(out_dir, "%s.mp4" % name)
    frames_dir = os.path.join(out_dir, "_frames_%s" % name)
    media_dir = args.media or ROOT

    n = int(round(proj["target"] * proj.get("fps", 30)))
    print("rendering %d frames (%d jobs)..." % (n, args.jobs), flush=True)
    dt = render_frames(proj_path, media_dir, frames_dir, n, jobs=args.jobs,
                       progress=lambda d, t: print("  %d/%d" % (d, t), flush=True) if d % 150 == 0 else None)
    print("frames done in %.1fs — encoding video..." % dt, flush=True)
    fps = proj.get("fps", 30)
    encode_video(frames_dir, out_mp4, fps=fps,
                 crf="23" if args.draft else "18",
                 preset_v="veryfast" if args.draft else "slow")

    if not args.no_audio:
        from core import audio as A
        wav = A.build_audio(proj, media_dir=media_dir, scratch=os.path.join(out_dir, "_audio_%s" % name))
        tmp = out_mp4 + ".muxed.mp4"
        cmd = ["ffmpeg", "-y", "-i", out_mp4, "-i", wav, "-c:v", "copy", "-c:a", "aac",
               "-b:a", "192k", "-shortest", tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("mux failed:\n" + r.stderr[-2000:])
        os.replace(tmp, out_mp4)
        A.verify_durations(out_mp4, proj["target"])

    # cleanup scratch frames
    import shutil
    shutil.rmtree(frames_dir, ignore_errors=True)
    print("OK ->", out_mp4)
    return out_mp4


if __name__ == "__main__":
    main()
