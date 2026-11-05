# REELKIT — by LEEBLAAB

**Kinetic promo videos. No cloud. No API. No subscription.**

Local webUI that turns 1–10 still images + captions into a finished vertical promo MP4
(animated stills, kinetic text, transitions, Piper voiceover, music with auto-ducking),
rendered entirely on your machine by Python + ffmpeg. Double-click `start.bat`,
work in `localhost:8000`, get an MP4.

Status: v1 build (spec signed off Nov 2026). License: AGPL-3.0 (code) — presets &
commercial packs stay proprietary to LEEBLAAB.

---

## Product pillars (the boss's filter — every decision passes these)

1. **Light** — stdlib + FastAPI + Pillow + numpy + Piper only. No frontend framework,
   no build step, no database. One folder, one `.bat`.
2. **Offline** — zero network calls after the one-time voice-model download. Never any API key.
3. **Easy to use** — a stranger must produce a good video in under 5 minutes with zero docs.
4. **Fast** — storyboard preview < 10s; full render streams progress; nothing re-renders that didn't change.
5. **Not complicated, but TOP-skilled UI polish** — dark, flush, typographic interface
   (the LEEBLAAB aesthetic: near-black `#0a0a0e`, cyan accent `#00e5ff`, white bold type).
   Micro-animations, keyboard shortcuts, honest progress. Simple surface, refined feel.

If a feature conflicts with these pillars, cut the feature — and tell Yasser why.

## Brand rules (non-negotiable)

- Product name: **REELKIT**. Byline everywhere: **REELKIT by LEEBLAAB** (maker credit, not co-brand).
- Tagline carries the offline promise: "No cloud. No API. No subscription." — never in the logo itself.
- Author name for this product line: **LEEBLAAB** (coding/AI products line; training kits use "Yasser Awadein" — do NOT mix).
- Fonts: open licenses only from day one — Archivo Black / Inter (headings, body), JetBrains Mono (terminal/mono). Bundle TTFs in `assets/fonts/`. Ship ATTRIBUTIONS.md (fonts OFL + Piper voices CC-BY credits).

## What v1 does (scope — agreed)

- **Aspect: 9:16 only** (1080x1920, 30fps). 1:1 and 16:9 deferred to v1.1.
- Upload up to 10 images (drag-drop or picker).
- Shot planner UI: cards per shot — image slot, on-screen caption lines, spoken VO line, duration, transition-in style, camera-move style. Reorder by drag. Durations must sum to target length (15/30/60s chips) — enforced live in UI.
- Text fields can also *generate* a shot plan from one idea-prompt box (rule-based template filler — NO LLM; see "no generation" note below).
- **VO**: Piper local, 2–3 voices with per-line PREVIEW button (~1s gen) plus "no VO" option.
  Voices = one-time friendly download at first setup (`setup_vo.bat`: fetches voice models from
  rhasspy/piper-voices, verifies SHA256, then fully offline forever; NOT committed to the repo —
  avoids git-lfs pain and keeps clone size light). Bundled starter: en_US-lessac-medium; also offer
  ralph-high + one female voice.
- **Music**: selector scans `music/` folder for user MP3/WAV + ships 2–3 procedural numpy beds (synthwave = the proven promo_audio recipe). Auto-duck under VO (0.12s ramps, ~45%).
- **Animation style / video style** = preset JSON files (`presets/`): colors, fonts, panel style, transition sequence, camera modes, easing. Ships: `leebdark.json` (the LEEBLAAB house style), 1–2 more. Users can hand-edit JSON.
- **Storyboard preview**: renders one thumbnail per shot (fast pass) with AUTO-RED-FLAGS before paying full render: text wider than safe width at chosen font, animation that won't finish before shot end, empty image slot, VO longer than its shot window.
- **Render job queue**: background job, frame-counter progress over websocket, output MP4 + kept project JSON.
- State = `projects/` folder, one human-readable JSON per promo (agreed: files, not a DB). `"schema": 1` field from day one — old project files must stay loadable forever.

## Explicitly OUT of v1

- Image generation of any kind (no ComfyUI, no APIs, no internet). "Datasets as templates" = static bundled image packs only, and that's post-v1 anyway.
- LLM anywhere. Prompt box is template-filler, not AI.
- Other aspect ratios, batch multi-project render, 2K/4K (Pro tier later), installers/bundled-python zip (post-v1 distribution work).

## Architecture (agreed)

```
reelkit/
  start.bat            -> launches venv python app.py, opens http://127.0.0.1:8000
  app.py               -> FastAPI: static UI + /api/* endpoints
  core/                -> pipeline engine (frame builder, transitions, audio, piper)
  ui/                  -> single-page vanilla JS/CSS (no framework), served static
  presets/             -> style JSONs
  music/               -> user beds + procedural generator
  vo/models/           -> piper .onnx voice models (git-lfs or download script)
  projects/            -> user project JSONs (schema:1)
  output/              -> rendered MP4s
```

- `/api/preview` — storyboard strip only (~5–10s)
- `/api/render` — background job; websocket pushes progress; ffmpeg mux at the end
- Pipeline code is a **generalization of proven working scripts** in
  `C:\Users\learn\Documents\ComfyUI\output\others\OT\Dataset\leebphotoz_promo\`:
  `build_video_v4.py` (frame builder, transitions incl. the ov-overlap fix),
  `make_audio.py` (numpy music), `make_vo.py` + `vo_gen.py` (Piper bed + ducking plan).
  Port them into `core/`, don't rewrite from scratch.

## Hard-won pitfalls already solved — reuse these fixes (see skill `kinetic-text-promo-video`)

- Transition "reset flow": incoming layer renders on early clock `lt=max(0,p*OV)` during wipes, NOT frozen settled preview. Mix per-shot OV values (0.9–1.2 lands text AT cut; 0.3 reveals after).
- Word-stagger math must guarantee every word reaches progress>=1 before shot end (formula in skill).
- VO bed: build with numpy float arrays (bytearray slicing silently halves duration); assert final length == TOTAL; ffprobe BOTH stream durations after mux (`-shortest` + truncated audio = video cut short — real incident).
- Piper install on Windows: system python311 `pip install --user piper-tts`; voice models from rhasspy/piper-voices HF repo.
- Typed monospace lines must fit measured font width (PIL getlength) or they clip at panel edge.
- Pixel-mask QA beats vision-QA for text claims (vision hallucinates both ways on dark frames). The v1 red-flag checks implement this as code, not eyeballs.

## Monetization frame (agreed direction)

GitHub repo AGPL (reach) + proprietary preset/template packs sold separately + future
Pro tier (2K/4K, batch rendering). Keep anything sellable OUT of the AGPL repo.
CONTRIBUTING.md must require DCO sign-off (protects future licensing options).

## Demo asset already exists

`C:\Users\learn\Documents\ComfyUI\output\others\OT\Dataset\leebphotoz_promo\LEEBLAAB_promo_v4_1080x1920.mp4`
— use as README hero demo and as the reference render to match quality bar.

---

SEE ALSO: `BUILD_PROMPT.md` (the kickoff prompt for the coding session), skill
`reelkit-project` (loaded automatically in future sessions).

## Quickstart (v1 built)

Run it: double-click **`start.bat`** → open **http://127.0.0.1:8735**. Full guide:
`docs/QUICKSTART.md`. CLI render without the browser:

    python render_cli.py samples/leebdark_sample.json --media media --out output/sample.mp4

Note: the app serves on port **8735** (not 8000 as sketched above — avoids
colliding with dev servers you may already run). Every render ends with an
ffprobe both-streams duration gate; a mux desync fails loudly.
