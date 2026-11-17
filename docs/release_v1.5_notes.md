# LEEBKIT v1.5 — Kinetic Depth

Everything since v1.41, plus the placement model this line was missing: captions
no longer live where the preset says they live — they go where **you** put them.
Eleven capability additions in total, all opt-in, default path byte-identical
(1314-frame golden corpus green).

## New in v1.5

### Placement (C9.1)
- **`place` / `y` on kinetic captions** — `"place": "top" | "middle" | "bottom"`, or
  an explicit `"y": 0.42` fraction of frame height. Hosts on the band-anchored kinds
  (burst, slam/slam_v2, pump, flashpop, wipe, trackin, accent_word, split, maskline,
  big_number, small, cta, kicker, terminal); plate-geometry kinds (panel_*, cap_lines,
  chips, handle, title_block) reject it at save time. The pre-render checker and the
  renderer agree on it (metrics/checker parity), so a placed line can never silently
  overflow.

### Kinetic kinds & motion
- **`slam_v2`** — heavier two-stage slam with overshoot settle.
- **`accent_word`** — one word in the line carries its own color.
- **`rule_draw`** — a rule that draws itself on (post-fit anchored).
- **`eq_bars`** — live equalizer bars that ride the REAL audio bed
  (VO + music envelope), not a fake sine.
- **Opt-in per-caption motion fields**: `exit:` (`rise|wipe|scale`), `idle:` boolean
  shapes, `ease:` (`expo|elastic|steps`) and `fx:` (`glitch|track_collapse`) — all
  whitelisted per kind, gated at save time.

### Timing
- **Shared beat clock** — one tempo table drives both picture pulses and the beds;
  transitions land on beats.
- **File-bed BPM ledger** — your own MP3/WAV beds carry a known tempo (`music/BPM.json`)
  so beat visuals stay locked to them too: `"music": { "mode": "file", "bed": "..." }`.

### Audio
- **Real music beds, not synths** — the release video runs on a CC0 track
  (`bed_one_cool_minute.mp3`, loudness-matched to the mix), provenance in
  `music/ATTRIBUTIONS.md`. Procedural beds remain available as the zero-asset path.

### Pipeline
- **`render_cli.py --finish`** — assembles the audio mix FIRST, wires it into
  the engine, then renders frames on it, so `eq_bars` and beat-reactive visuals
  react to the actual final mix for ANY project. Costs one extra frame pass;
  the default path stays byte-identical.

## Release video

47s, 1080×1920 @30fps, fully voiced + music, all real photos (zero generated
backgrounds): `samples/release_v15.json` -> `output/release_v15.mp4`. One command:

```
python render_cli.py samples/release_v15.json --media samples/media --out output/release_v15.mp4 --finish
```

## Quality gates at this tag
- smoke suite: 60 checks (incl. placement field tests) — green
- golden frames: PASS, 1314 hashed frames (re-baselined exactly for the C9.1
  corpus drift: 12 shot-9 keys; everything else untouched)
- release render ffprobe gate: video and audio both exactly 47.00s

## What's next
**v2.0 — the monetization era** (was the old v1.5 plan): packaging, presets
storefront, licensing. The kinetic engine line is done; v2.0 builds on top of it.
