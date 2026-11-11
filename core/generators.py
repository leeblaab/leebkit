"""v1.4 C3 — procedural background generators (the six locked presets).

Design decisions this module enforces (docs/v1.4_plan.md D2/D4/D5/D6):
  * Fixed DESIGNED palettes per preset (D2) — a generator's colors never
    follow the project color preset; they ship with the preset itself.
  * ONE shared motion driver per shot (D4): every animated layer reads the
    same phase `offset` and scales it by its own multiplier (pattern 0.6x,
    vignette stationary). Layer-to-layer parallax comes from those
    multipliers, never from independent clocks.
  * Amplitude tiers (D5): `amp` is a multiplier on DISPLACEMENT only —
    "Subtle" ≈ 0.4x amplitude; shot speed never feeds back into the driver.
  * Grain = ONE static noise texture drifting with the driver (never fresh
    noise per frame), so neighbor frames stay coherent.
  * Perf (D6): coordinate grids + static pattern layers are built once per
    (preset, W, H) and cached; per-frame work is vectorized numpy only —
    no Python pixel loops. The Engine calls this at BASE resolution
    (BW/8), not output resolution, and the animated accumulation runs in a
    single float16 scalar layer merged into RGB once at the end: the hot
    cost scales with pixels-touched-per-layer, so one merge beats N.

Public API:
  GEN_PRESETS        name -> spec dict (palette, grain params, ...)
  render(name, W, H, offset, amp=1.0) -> PIL.Image RGB at native (W, H).
      `offset` is the shared-driver position in seconds for THIS shot; the
      Engine passes lt * per-shot speed itself — this module never knows
      about shots, fps or easing.
  palette(name) -> tuple of designed hex colors (frozen).
"""
import hashlib
import math

import numpy as np
from PIL import Image

# ---------------------------------------------------------------- presets
# Six locked names (v1.4 decision). Each spec is fully self-contained:
# the palette is part of the preset identity.
GEN_PRESETS = {
    "midnight_drift": {
        "label": "Midnight Drift",
        "palette": ("#0b1020", "#16213e", "#3a5f8f", "#7fb3d5"),  # bg, mid, glow, highlight
        "waves": 3,            # drifting sine ridge layers
        "grain_gain": 10,
    },
    "grid_pulse": {
        "label": "Grid Pulse",
        "palette": ("#0a0f0c", "#123524", "#2e7d4f", "#8ce0b0"),
        "grid_step": 64,       # px at FHD reference height
        "grain_gain": 8,
    },
    "paper_grain": {
        "label": "Paper Grain",
        "palette": ("#17150f", "#2a2419", "#6b5d3f", "#c9b98c"),
        "grain_gain": 26,      # the hero texture of this preset
    },
    "ember_flow": {
        "label": "Ember Flow",
        "palette": ("#140b06", "#3a1608", "#a34a1c", "#f0a35e"),
        "blobs": 4,            # soft warm blobs on lissajous paths
        "grain_gain": 9,
    },
    "deep_current": {
        "label": "Deep Current",
        "palette": ("#04121a", "#0a2e3b", "#1f6f78", "#5fd0c2"),
        "waves": 4,
        "grain_gain": 7,
    },
    "signal_field": {
        "label": "Signal Field",
        "palette": ("#0d0d12", "#1c1e2a", "#4b5375", "#9aa6d8"),
        "cells": 24,           # dot lattice count along the width
        "grain_gain": 9,
    },
}

# per-layer motion multipliers against the ONE shared driver (D4).
MULT_PATTERN = 0.6    # pattern layers lag the driver
MULT_GRAIN = 1.0      # grain texture drifts with the driver
# vignette is stationary: multiplier 0, never in the animated path at all.

_LAYER_CACHE = {}     # (preset, W, H) -> dict of static float32 layers
_GRID_CACHE = {}      # (W, H) -> (X, Y, R) normalized coordinate grids


def palette(name):
    spec = GEN_PRESETS[name]
    return tuple(spec["palette"])


def _hex(c):
    c = c.lstrip("#")
    return np.array([int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)], dtype=np.float32)


def _grids(W, H):
    """Normalized coordinate grids + radial falloff, cached per size."""
    key = (W, H)
    g = _GRID_CACHE.get(key)
    if g is None:
        x = np.linspace(-1.0, 1.0, W, dtype=np.float32)
        y = np.linspace(-1.0, 1.0, H, dtype=np.float32)
        X, Y = np.meshgrid(x, y)
        R = np.sqrt(X * X + Y * Y)
        g = (X, Y, np.minimum(R, 1.7))
        _GRID_CACHE[key] = g
    return g


def _hex_grid(color, W, H):
    """Full-frame constant color layer (float32 RGB), cached with the layers."""
    return np.broadcast_to(_hex(color), (H, W, 3)).copy()


def _static_layers(name, W, H):
    """Build (once) every static layer for a preset at this size:
    base gradient, pattern field, grain texture, vignette."""
    key = (name, W, H)
    layers = _LAYER_CACHE.get(key)
    if layers is not None:
        return layers
    spec = GEN_PRESETS[name]
    X, Y, R = _grids(W, H)
    p = spec["palette"]

    # base: vertical two-tone gradient between palette[0] and palette[1]
    gy = (Y * 0.5 + 0.5)[..., None]
    c0, c1 = _hex(p[0])[None, None], _hex(p[1])[None, None]
    base = c0 + (c1 - c0) * gy

    # pattern field: scalar in [0,1] built from coordinate grids only.
    kind = name
    if kind == "grid_pulse":
        step = spec["grid_step"] * (H / 1920.0)
        gx = np.abs(((X + 1.0) * W / 2.0) % step - step / 2.0)
        gy2 = np.abs(((Y + 1.0) * H / 2.0) % step - step / 2.0)
        field = (np.minimum(gx, gy2) < max(1.0, step * 0.03)).astype(np.float32)
    elif kind == "signal_field":
        n = spec["cells"]
        u = (X + 1.0) * 0.5 * n
        v = (Y + 1.0) * 0.5 * n * (H / W)
        ux, uy = np.floor(u), np.floor(v)
        fx, fy = u - ux, v - uy
        d2 = (fx - 0.5) ** 2 + (fy - 0.5) ** 2
        field = np.exp(-d2 * 34.0).astype(np.float32)
    else:
        field = None  # wave/blob presets compute their field per frame

    # grain: ONE static noise texture on a fixed-seed power-of-two tile,
    # sampled with modular wrap so the drift never exposes an edge and the
    # content stays frozen forever (coherent across frames). The tile is at
    # least as wide/tall as the frame, and the per-frame offset stays below
    # one axis span, so a crop window NEVER straddles the wrap line (that
    # would seam).
    g = spec["grain_gain"]
    if g:
        h = hashlib.sha256(("grain|%s|%d|%d" % (name, W, H)).encode()).digest()
        rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
        S = 1 << max(9, int(math.ceil(math.log2(max(W, H)))))
        grain_t = rng.standard_normal((S, S)).astype(np.float32) * (g / 2.0)
    else:
        grain_t = None

    # vignette: stationary radial darkening (never animated, D4)
    vig = (1.0 - 0.38 * (R ** 2)).astype(np.float32)[..., None]

    layers = {"base": base.astype(np.float32), "field": field,
              "grain": grain_t, "vig": vig, "X": X, "Y": Y}
    _LAYER_CACHE[key] = layers
    return layers


def _grain_crop(tile, dx, dy, W, H):
    """Crop of the static grain tile at integer offset. Callers must keep
    0 <= dx < tile_width - W and 0 <= dy < tile_height - H so the window
    never straddles the wrap line (no seam)."""
    xs = np.arange(dx, dx + W, dtype=np.int32)
    ys = np.arange(dy, dy + H, dtype=np.int32)
    return tile[np.ix_(ys, xs)]


def render(name, W, H, offset, amp=1.0):
    """Composite one generator frame at shared-driver position `offset`
    (seconds) with displacement amplitude `amp`. Returns PIL RGB image."""
    if name not in GEN_PRESETS:
        raise ValueError("unknown generator preset %r (choices: %s)"
                         % (name, ", ".join(sorted(GEN_PRESETS))))
    spec = GEN_PRESETS[name]
    L = _static_layers(name, W, H)
    X, Y = L["X"], L["Y"]
    p = spec["palette"]
    acc_glow = _hex(p[2])   # animated energy glows with palette[2] (D2)

    # ONE shared driver (D4): pattern layers see 0.6x of it.
    drv = float(offset) * 2.0 * math.pi * 0.10      # slow: one cycle / 10 s
    pmul = drv * MULT_PATTERN * float(amp)

    # All animated energy lands in ONE scalar layer (float16, D6), merged
    # into RGB once below — per-layer float32 RGB adds were the hot path.
    acc = np.zeros((H, W), dtype=np.float16)

    if name in ("midnight_drift", "deep_current"):
        for k in range(spec["waves"]):
            w = 0.9 + 0.35 * k
            ph = pmul * (1.0 + 0.25 * k) + k * 1.7
            ridge = np.sin(Y * (2.2 + k) * math.pi + X * 1.4 * w + ph,
                           dtype=np.float16)
            np.maximum(ridge, 0, out=ridge)          # thin moving ridges
            acc += ridge ** 6 * np.float16(0.35 / (1 + 0.5 * k))
    elif name == "ember_flow":
        for k in range(spec["blobs"]):
            a = pmul * (1.0 + 0.2 * k) + k * 2.1
            cx = 0.55 * math.cos(a * 0.7 + k)
            cy = 0.45 * math.sin(a * 0.9 + k * 1.3)
            d2 = (X - cx) ** 2 + (Y - cy) ** 2
            acc += np.exp(-d2 * 6.0, dtype=np.float16) * np.float16(0.30)
    elif L["field"] is not None:
        # grid_pulse / signal_field: static field, brightness breathes with
        # the driver and the lattice drifts by rolling its own mask — the
        # roll stays inside one copy (shift < W), never a wrapped crop.
        f = L["field"]
        shift = int(pmul * 12.0) % W
        if shift:
            f = np.roll(f, -shift, axis=1)
        pulse = 0.55 + 0.45 * math.sin(pmul * 2.0)
        acc += (f * (0.55 * pulse)).astype(np.float16)

    img = L["base"].copy()
    img += acc[..., None].astype(np.float32) * acc_glow[None, None]

    # grain texture drifts with the driver (static content, MOVING crop).
    # Offsets are wrapped into [0, tile - frame) so the crop window always
    # sits inside one tile copy (no seam at the wrap line).
    if L["grain"] is not None:
        Sh, Sw = L["grain"].shape
        gd = int(round(drv * MULT_GRAIN * float(amp) * 18.0))
        a = _grain_crop(L["grain"], gd % (Sw - W + 1), (-gd // 2) % (Sh - H + 1), W, H)
        img += a[..., None]

    # stationary vignette last (multiplier 0 — no driver term anywhere)
    img *= L["vig"]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
