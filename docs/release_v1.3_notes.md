# v1.3 — the reliability release

Everything since v1.2, hardened by a golden-frame test harness and two rounds
of live testing on a real Windows machine.

## Engine
- **Golden-frame harness**: scripted fixture renders + per-OS perceptual
  baselines (`tests/golden_baselines/`); 37 smoke checks green, including a
  headless-browser pass of the whole UI.
- **Single source of truth**: storyboard checks and the renderer now share the
  caption kind-dispatch (`core/captions.py`) — the "storyboard says OK, render
  throws" bug class is gone.
- **Fit/wrap metrics cached per Engine** (no behavior change; golden tests prove
  frame-identical output).

## Queue (v1.3 live-test, this release)
- Upload paths are media-dir-relative end to end — fixes the "outside media
  dir" render abort and corrupted upload previews.
- Worker probe falls back to threads when `mp.Pool` children are blocked by
  restricted sessions; pool disabled by default on Windows (WinError 87).
- Queue cap raised 4 -> 20.

## UI
- **Animations pane** (v1.35): CapCut-style left ANIMATIONS column — 270
  animated webp tiles rendered through the real engine path, click to apply
  transitions/camera moves to a shot.
- **Project load dropdown** (v1.36): pick any saved project in the queue pane.
- **Per-job cancel** + visible queue depth.
- Progress bar tracks the *running* job; outputs list newest-first by file
  mtime.
- Shot thumbnails fixed (media-relative src), gallery paints at boot.

## Docs
- README re-measured honestly (warm full-corpus end-to-end ~17s, no inflated
  speed claims); flagship promo re-rendered as `promo_v13.mp4` with an
  ffprobe gate (h264 1080x1920 30fps, exact frame count, aac audio).
