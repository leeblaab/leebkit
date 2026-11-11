"""v1.4 C5 — share export formats (GIF / animated WebP) gates.

The GIF/WebP encoder lives in render_cli (encode_share, frame_dir_to_gif,
frame_dir_to_webp) and the cap constants live in core/share_caps.py so CLI,
app and tests read ONE source of truth ("GIF is a share teaser, not the
master" — plan risk #3, cap locked by Yasser 2026-11-11: 640px / 6s / 12fps).

Gates (all tiny + fast):
  - caps module shape (CLI/app/UI can never disagree on the numbers)
  - gif_step frame sampling math (exact indices, never > cap seconds)
  - a real GIF encode from PNG frames: ffprobe says gif / <=640 wide /
    <=6s / fps<=12 / no audio stream
  - a real animated WebP encode: webp / full source size kept / duration ok
  - oversized source -> truncated frame set (cap enforced at the FILE level,
    not just promised in help text)
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- caps module
try:
    from core.share_caps import GIF_MAX_W, GIF_MAX_S, GIF_FPS, WEBP_MAX_W, WEBP_MAX_S
    check("share_caps importable", True)
except Exception as e:
    check("share_caps importable", False, str(e))
    print("FAILED: share_caps import")
    sys.exit(1)

check("GIF cap = 640px (Yasser ruling)", GIF_MAX_W == 640, GIF_MAX_W)
check("GIF cap = 6s", GIF_MAX_S == 6.0, GIF_MAX_S)
check("GIF fps = 12", GIF_FPS == 12, GIF_FPS)
check("WebP caps >= GIF caps (webp is the roomier teaser)",
      WEBP_MAX_W >= GIF_MAX_W and WEBP_MAX_S >= GIF_MAX_S,
      "%dx%.0fs" % (WEBP_MAX_W, WEBP_MAX_S))

# ---------------------------------------------------------------- encoder fns
from render_cli import encode_share, frame_dir_to_gif, frame_dir_to_webp, gif_step  # noqa: E402

# sampling math: 30fps source -> every 3rd frame = 10fps; never exceeds cap
check("gif_step(30) samples to <=12fps", gif_step(30) == 3 and 30 / gif_step(30) <= GIF_FPS,
      "step=%d -> %g fps" % (gif_step(30), 30.0 / gif_step(30)))
check("gif_step(12) keeps every frame", gif_step(12) == 1)
check("gif_step(24) -> 12fps (exact divisor keeps every 2nd frame)", gif_step(24) == 2 and 24 / gif_step(24) <= GIF_FPS,
      "step=%d" % gif_step(24))
# frame-count window: sampled frames of a cap-length source never exceed cap*fps
check("gif_window caps seconds", len(range(0, int(GIF_MAX_S * 30), gif_step(30))) <= GIF_MAX_S * GIF_FPS + 1,
      "%d frames" % len(range(0, int(GIF_MAX_S * 30), gif_step(30))))


def _frames(dirpath, n, w=320, h=480, fps=24):
    """Deterministic PNG frame sequence (moving square on gradient-ish bg)."""
    os.makedirs(dirpath, exist_ok=True)
    for i in range(n):
        im = Image.new("RGB", (w, h), (16 + i % 30, 18, 24))
        x = (i * 7) % (w - 40)
        from PIL import ImageDraw
        ImageDraw.Draw(im).rectangle([x, h // 2 - 20, x + 40, h // 2 + 20], fill=(0, 200, 255))
        im.save(os.path.join(dirpath, "f_%04d.png" % i))
    return n


TMP = os.path.join(ROOT, "scratch", "share_fmt")
shutil.rmtree(TMP, ignore_errors=True)

# ---------------------------------------------------------------- GIF encode
fd = os.path.join(TMP, "frames")
N = _frames(fd, 72, fps=24)   # 3.0s @24fps — under the 6s cap
gif_path = os.path.join(TMP, "tiny.gif")
info = frame_dir_to_gif(fd, gif_path, src_fps=24, src_w=320)
st = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                     "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,duration",
                     "-of", "json", gif_path], capture_output=True, text=True)
sj = json.loads(st.stdout or "{}")
streams = sj.get("streams", [])
v = next((s for s in streams if s.get("codec_type") == "video"), {})
a = [s for s in streams if s.get("codec_type") == "audio"]
check("GIF file exists + ffprobe ok", os.path.isfile(gif_path) and st.returncode == 0,
      (st.stderr or "")[-200:])
check("GIF codec is gif", v.get("codec_name") == "gif", v.get("codec_name"))
check("GIF width <= 640", int(v.get("width", 99999)) <= GIF_MAX_W, v.get("width"))
dur = float(v.get("duration") or (int(v.get("nb_frames", 0)) / GIF_FPS))
check("GIF duration <= 6s", dur <= GIF_MAX_S + 0.25, "%.2fs" % dur)
num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
fps = float(num) / float(den or 1)
check("GIF fps <= 12", fps <= GIF_FPS + 0.5, "%g fps" % fps)
check("GIF has no audio stream (teaser is silent)", not a, str([s.get("codec_name") for s in a]))
check("GIF frame count = sampled window", int(v.get("nb_frames", 0)) == len(range(0, N, gif_step(24))),
      "nb=%s want=%d" % (v.get("nb_frames"), len(range(0, N, gif_step(24)))))

# ---------------------------------------------------------------- WebP encode
webp_path = os.path.join(TMP, "tiny.webp")
winfo = frame_dir_to_webp(fd, webp_path, src_fps=24)
# ffmpeg 8's ffprobe cannot read animated-webp dims/frame counts (reports a
# stub stream: width=0, nb_frames=N/A) — PIL is the honest prober for webp.
from PIL import Image as _PILImage  # noqa: E402
_im = _PILImage.open(webp_path)
_nwebp = 0
try:
    while True:
        _im.seek(_nwebp)
        _nwebp += 1
except EOFError:
    pass
check("WebP file exists", os.path.isfile(webp_path))
check("WebP codec is webp (PIL format)", _im.format == "WEBP", _im.format)
check("WebP keeps source size (<= cap)", _im.size == (320, 480) and _im.size[0] <= WEBP_MAX_W,
      "%dx%d" % _im.size)
check("WebP frame count = sampled window", _nwebp == len(range(0, N, gif_step(24))),
      "n=%d want=%d" % (_nwebp, len(range(0, N, gif_step(24)))))

# ---------------------------------------------------------------- cap truncation
# 12s @24fps = 288 frames -> GIF must keep <= 6s worth AND downscale to 640.
fd2 = os.path.join(TMP, "frames_long")
N2 = _frames(fd2, 288, w=1080, h=1920, fps=24)
gif2 = os.path.join(TMP, "long.gif")
frame_dir_to_gif(fd2, gif2, src_fps=24, src_w=1080)
st3 = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                      "stream=codec_type,codec_name,width,height,nb_frames,duration,r_frame_rate",
                      "-of", "json", gif2], capture_output=True, text=True)
sj3 = json.loads(st3.stdout or "{}")
v3 = next((s for s in sj3.get("streams", []) if s.get("codec_type") == "video"), {})
n3 = int(v3.get("nb_frames", 0))
check("12s source -> GIF truncated to <=6s cap", n3 > 0 and n3 <= int(GIF_MAX_S * GIF_FPS),
      "kept %d of %d frames" % (n3, N2))
_dur3 = float(v3.get("duration") or 0)
check("12s source -> GIF ffprobe duration <=6s", _dur3 <= GIF_MAX_S + 0.05, "%.2fs" % _dur3)
check("1080w source -> GIF downscaled to <=640", int(v3.get("width", 99999)) <= GIF_MAX_W,
      v3.get("width"))

# webp long: truncated to WEBP_MAX_S too (PIL frame-count probe)
webp2 = os.path.join(TMP, "long.webp")
frame_dir_to_webp(fd2, webp2, src_fps=24)
_im2 = _PILImage.open(webp2)
_n2 = 0
try:
    while True:
        _im2.seek(_n2)
        _n2 += 1
except EOFError:
    pass
check("12s source -> WebP truncated to cap", 0 < _n2 <= int(WEBP_MAX_S * GIF_FPS),
      "kept %d of %d sampled frames" % (_n2, N2))
check("1080w source -> WebP downscaled to <=960", _im2.size[0] <= WEBP_MAX_W,
      "%dx%d" % _im2.size)

# encode_share dispatch + bad format
try:
    encode_share(fd, os.path.join(TMP, "x.avi"), fmt="avi", src_fps=24, src_w=320)
    check("encode_share rejects unknown format", False)
except ValueError:
    check("encode_share rejects unknown format", True)

shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
