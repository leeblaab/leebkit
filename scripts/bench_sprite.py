"""v1.42 item 7 BENCHMARK: per-word RGBA sprite layers (translate/scale/rotate
via Image.transform AFFINE bilinear + alpha_composite) vs the current
per-frame PIL redraw path, measured on a slam-style caption inside the kinds
corpus shot at 1080x1920.

Decision rule from docs/_local_v1.5_plan.md: proceed with the sprite compositor for
slam_v2 ONLY if frame cost <= +15%; otherwise ship slam_v2 with scale-only math
on the existing draw path and document why here.

Run: PYTHONPATH=. .venv/Scripts/python.exe scripts/bench_sprite.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw

from core.engine import Engine


def timed(fn, n):
    """Return mean ms/frame over n calls (first call excluded: font cache)."""
    fn()  # warm caches (mkfont memo, text measur)
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000.0


def main():
    import json
    proj = json.load(open(os.path.join(ROOT, "tests", "golden",
                                       "kinds_corpus.json"), encoding="utf-8"))
    eng = Engine(proj)
    W, H = eng.W, eng.H
    # isolate ONE slam-style caption on a corpus shot: render the base frame
    # once, then re-draw only the slam layer per timing iteration.
    fnt = eng._mkfont(eng.preset["fonts"]["display"], int(eng.L["h1"]))
    txt = "SLAMWORD"
    N = 30

    canvas = Image.new("RGBA", (W, H), (12, 12, 14, 255))

    def redraw():
        c = canvas.copy()
        dr = ImageDraw.Draw(c)
        # mimic draw_slam's hot loop: font per frame + text draw
        f = eng._mkfont(eng.preset["fonts"]["display"],
                        int(eng.L["h1"] * (0.6 + 0.4 * (time.monotonic() % 1))))
        w = dr.textlength(txt, font=f)
        dr.text(((W - w) / 2, H * 0.4), txt, font=f, fill=(255, 255, 255, 255))
        return c

    # --- sprite path: rasterize the word ONCE at rest size; per frame just
    # AFFINE-transform (scale+translate) and alpha_composite.
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bdr = ImageDraw.Draw(base)
    bw = bdr.textlength(txt, font=fnt)
    bdr.text(((W - bw) / 2, H * 0.4), txt, font=fnt, fill=(255, 255, 255, 255))

    def sprite():
        c = canvas.copy()
        s = 0.6 + 0.4 * (time.monotonic() % 1)
        # scale about the text block center via AFFINE (bilinear)
        cx, cy = W / 2, H * 0.45
        aff = (s, 0, cx - s * cx, 0, s, cy - s * cy)
        layer = base.transform((W, H), Image.AFFINE, aff,
                               resample=Image.BILINEAR)
        Image.alpha_composite(c, layer)
        return c

    ms_redraw = timed(redraw, N)
    ms_sprite = timed(sprite, N)
    delta = (ms_sprite - ms_redraw) / ms_redraw * 100.0

    print("frame cost @ %dx%d, slam-style single caption:" % (W, H))
    print("  per-frame redraw : %8.2f ms/frame" % ms_redraw)
    print("  sprite AFFINE    : %8.2f ms/frame" % ms_sprite)
    print("  delta            : %+7.1f %%  (gate: proceed with sprites at <= +15%%)" % delta)
    verdict = "SPRITE PATH OK (<= +15%)" if delta <= 15.0 else \
              "SCALE-ONLY slam_v2 on existing path (> +15%)"
    print("VERDICT:", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
