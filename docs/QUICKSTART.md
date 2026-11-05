# REELKIT Quickstart

## Run it
Double-click `start.bat` (first run creates a venv and installs deps), or:

    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8735

Open **http://127.0.0.1:8735** — everything is local; the app makes zero
network calls.

## Make a video
1. Drop 1–10 images into the drop zone → they become numbered shot cards.
2. Set each shot's duration chip (2/3/4/5/6s) — the right rail shows the running
   total against your target length.
3. Type caption lines (one per line, big two-line style) and an optional
   voice-over line per shot.
4. Pick a **preset** (leebdark / neonlight), a **music bed** (procedural or your
   own mp3 in `music/`), and a **voice** (Piper models in `vo/models/`).
5. Hit **Storyboard ⚑** — one strip, all shots, plus automatic red-flags for
   text overflow, animations that can't finish in their shot window, empty
   image slots, and VO longer than its shot. Fix flagged cards (red border)
   before rendering.
6. Hit **Render MP4** (or `Ctrl+Enter`). Watch the progress bar; the finished
   file appears under Outputs (`output/<name>.mp4`).

## CLI (no browser)
    python render_cli.py myproject.json --out output/my.mp4

Project JSON is the source of truth: hand-edit `projects/*.json` or start from
`samples/leebdark_sample.json`. Schema notes in README §Project JSON.

## Voice-over setup (optional)
    pip install piper-tts
Download a voice model (e.g. `en_US-lessac-medium.onnx` + `.json`) into
`vo/models/` — one-time download, offline afterwards. Without any models the
voice selector just shows "none" and renders stay music-only.

## Quality gate
Every render ends with an ffprobe check that both streams match the target
duration to 0.1s — a mux desync fails the render loudly instead of shipping a
broken file.
