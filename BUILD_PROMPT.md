# BUILD_PROMPT — kick off a new Hermes session with this

> **Paste everything below the line as your first message in the new ReelKit session.**

---

Build REELKIT v1 at `C:\Products\reelkit\`. First read `C:\Products\reelkit\README.md`
in full — it is the signed-off spec (pillars, brand rules, scope, architecture, pitfalls).
Load skill `reelkit-project`, and skill `kinetic-text-promo-video` for the proven
pipeline details. Source scripts to port from:
`C:\Users\learn\Documents\ComfyUI\output\others\OT\Dataset\leebphotoz_promo\build_video_v4.py`,
`make_audio.py`, `make_vo.py`.

Build order (each step ends runnable, not stubbed):

1. **core engine first** — port build_video_v4 into `core/` driven by a project JSON
   (schema:1). CLI render of a sample project must produce an MP4 visually matching the
   v4 demo quality bar before any UI exists. Include ov-overlap transition fix and the
   word-stagger completion formula from day one.
2. **audio** — `core/audio.py`: procedural beds + user-file support + Piper VO lines +
   numpy bed assembly (float arrays, assert TOTAL length) + ducking + mux + ffprobe
   both-streams duration check as a hard gate.
3. **UI** — FastAPI + one vanilla-JS page: image drop zone, shot cards (drag-reorder),
   caption/VO fields, duration chips summing to target, voice selector with per-line
   preview, music selector, preset picker. Dark LEEBLAAB aesthetic (#0a0a0e / #00e5ff),
   Archivo Black + Inter + JetBrains Mono bundled. Polish bar: it must feel designed,
   not generated — spacing rhythm, hover states, keyboard shortcuts (Ctrl+Enter = render).
4. **storyboard preview endpoint** with the four auto-red-flags (text overflow via PIL
   getlength, animation-won't-finish timing check, empty slot, VO longer than shot).
5. **render queue + websocket progress**, then `start.bat`, README quickstart, LICENSE
   (AGPL-3.0), ATTRIBUTIONS.md, CONTRIBUTING.md with DCO line, .gitignore (frames/,
   audio scratch, output/).

Verify like we always do: after every render, ffprobe streams + extract frames at the
hard moments (cut points, typed-line finals) and check pixels programmatically.
The v4 demo MP4 is the quality bar — compare against it.

Rules while building:
- Light/offline/fast pillars are absolute (README). No frontend framework, no DB, no network.
- When something seems worth adding beyond spec, ASK first — Yasser wants simple kept simple.
- Correct him when he's wrong; he explicitly wants that.
- "do delegation" from Yasser means DO NOT delegate.
- Chat vs build: if he says chat, NO tool calls at all.
