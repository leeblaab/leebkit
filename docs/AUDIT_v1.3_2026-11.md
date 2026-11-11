# LEEBKIT full audit — v1.3 (0c47887) — 2026-11-11

Scope: full code review of all tracked source (~4,150 LOC), security pass, dependency check,
CI gates, and a housekeeping inventory. **Nothing was deleted** — cleanup candidates are listed
in §6 pending green light.

State at audit time: `master` @ `0c47887` (tag v1.3), working tree clean, GitHub release live.

---

## 1. Summary verdict

The codebase is in good shape for a solo product: small surface, single source of truth
(`core/checks.py` + `core/metrics.py` shared by renderer and checker), defensive path handling
in the engine/queue, real CI gates on both OSes, and per-OS golden baselines. No critical
vulnerabilities found. The issues are mostly **hardening gaps** (local-only trust assumptions)
and **disk bloat**.

Ratings: Architecture A · Security B+ (local-tool threat model) · Tests/gates A− · Hygiene C
(500 MB+ of gitignored debris on disk).

LOC map: app.py 448 · render_cli.py 128 · core/ 2,486 (engine 677, captions 335, audio 472,
queue 330, anim_gallery 230, checks 188, layout 133, metrics 104, camutil 13) ·
scripts/ 456 · ui/index.html 644 (one inline script, `node --check` green).

---

## 2. Security audit

### What's already good (verified in code)
- **No secrets anywhere** in tracked files (grep sweep for keys/tokens/passwords: zero hits).
- **Server binds 127.0.0.1 only** (`start.bat` → uvicorn :8735). Not LAN-exposed.
- **Upload hardening**: filename sanitization, magic-byte sniffing, 32 MB cap, streamed to
  `.part` then atomic rename (app.py `_sniff_image`/upload).
- **Path confinement**: `Engine._media_path`/`_within` rejects absolute paths and traversal for
  shot images; `load_preset` real-path-confinement to `presets/`; `/api/project/{fname}` uses
  `os.path.basename` (no traversal).
- **No shell=True, no os.system, no eval/exec, no pickle.loads, no yaml.load.** All subprocess
  calls use argv lists (ffmpeg/ffprobe/piper) — no injection vector from user text.
- **Queue discipline**: MAX_QUEUED=20 cap, KEEP_FINISHED=20, cancel flag checked per frame,
  BaseException guard, `finally` cleanup of `_frames_*`/`_audio_*` scratch.

### Findings (ranked)

**S1 — MEDIUM: arbitrary local file read via music bed path.**
`core/audio.py:381`: `path = fn if os.path.isabs(fn) else os.path.join(MUSIC_DIR, fn)` — a
project JSON with an absolute `music_file` makes ffmpeg read ANY local file (exfiltrated as the
rendered audio track). Same story for any `..`-relative path. Harmless for self-use; it's a
read primitive if the UI is ever exposed or a downloaded project JSON is loaded.
Fix: confine to MUSIC_DIR with `_within()` after realpath, like `_media_path` already does.

**S2 — LOW-MED: `/api/project/{fname}` reads ANY `*.json` in projects/.** No traversal (basename),
but all 8 personal save-files are enumerable/readable by any page that can reach the port. A
drive-by webpage cannot POST cross-origin to this API today (FastAPI has no CORS middleware =
browsers block cross-origin *reads*; simple POSTs without preflight ARE accepted server-side
though — a CSRF-style write vector: a malicious page could queue renders on your machine while
the app is open). Fix: bind stays 127.0.0.1 (done), plus a same-Origin check middleware on
/api/* (~5 lines) closes the CSRF hole.

**S3 — LOW: XSS surface in UI.** `esc()` exists but isn't applied everywhere; template literals
interpolate into innerHTML unescaped (`${p.label}`, `${o.file}`, shot caption text at line 253,
`${it.label}`). Project names are server-sanitized to `[A-Za-z0-9._- ]` so today's data can't
carry `<script>`; the risk is latent (future fields, preset labels). Also `href="${o.url}"` is
unquoted-sink-style — a filename starting `javascript:` would fire on click. Fix: one `esc()`
pass over every interpolation in index.html, or switch to textContent for user strings.

**S4 — LOW: `/output` and `/media` static mounts expose the whole trees**, including
`output/_previews/` storyboard strips (they render YOUR caption text + images). Fine on
localhost; just don't ever port-bind this 0.0.0.0.

**S5 — INFO: no auth at all.** By design for a local tool. If LEEBKIT is ever packaged for
distribution, add a token or keep the 127.0.0.1 contract in README as a security note.

**S6 — PRIVACY (tracked file): `docs/DESIGN_NOTES.md:11` contains your personal path**
`C:\Users\learn\Documents\ComfyUI\output\others\OT\Dataset\leebphotoz_promo\build_video_v4.py`
in the PUBLIC repo. It points at your OT/dataset area — the exact thing that must stay private
per the kit rule. Fix: replace with a generic phrase ("an earlier personal promo script").
One-line patch, needs commit green light.

**S7 — DEPS: pinned but stale-ish.** fastapi 0.162 / starlette 1.10 / uvicorn 0.54 / pillow 13.0
/ numpy 2.5.4 — pins match the venv exactly (good), upper bounds present (good). No known
RCE-class CVEs apply to this usage, but pillow is the classic attack surface for image parsing;
worth a `pip list --outdated` review at each release. piper-tts is optional-extra (correct).

---

## 3. Code review — quality notes

- **Architecture**: clean layering (engine → captions/metrics/checks; queue isolates rendering;
  app.py is pure HTTP glue). The "renderer and checker agree by construction" rule in checks.py
  is enforced by convention + smoke; keep it.
- **app.py:160 / get_project**: `json.load(open(p))` without context manager (fd leak on CPython
  until GC; same in save_project). Cosmetic, but a one-line fix each.
- **save_project name sanitizer** allows `"."`/`".."`-ish names (`.` and spaces pass) →
  `"... .json"` edge cases. Tighten: reject names that strip to empty or are all dots.
- **queue.py `_spawn_ok` fallback** (mp.Pool probe → threads) is good defensive engineering;
  the probe runs once per process — fine.
- **engine.py load_preset** realpath-confinement correct.
- **audio.py**: subprocess timeouts present; ffprobe duration probe guarded. The PY311
  interpreter discovery chain is fragile by nature but self-heals with clear errors.
- **ui/index.html (644 lines, one inline script)**: works and passes node --check, but it's the
  single biggest maintainability item — no modules, delegated events everywhere, esc() applied
  inconsistently (see S3). Not urgent; split only when adding features.
- **CI wording drift**: `smoke.yml` step says "30 checks"; git history says 37 since v1.35.
  Cosmetic but it's the exact kind of stale claim the audit culture here hates — sync it.
- **No LICENSE file** in repo (README says MIT?) — confirm and add if missing before Show HN.

---

## 4. Tests & gates status

- Linux push gate: smoke + golden `--sample 10` (green at HEAD; linux baseline committed).
- Windows weekly cron gate: full-corpus golden vs `hashes.json`.
- Golden harness covers 3 presets × boundary frames, per-OS baselines — strong for a solo project.
- Gap: golden corpus has no landscape preset frames and no music-bed audio path (audio is
  ffprobe-gated in smoke only). Acceptable; note it.

## 5. Dependencies & environment

requirements.txt pins == installed venv versions exactly; `tools/ffmpeg` portable download in
setup.bat pulls BtbN latest (unpinned — acceptable for a user-side installer, worth a comment
that renders may drift across ffmpeg builds). `.venv_ci` mirrors CI python 3.12 locally.

---

## 6. Housekeeping inventory — deletion candidates (NOTHING deleted; awaiting green light)

All gitignored unless noted. Sizes from live scan at audit time.

| # | Path | Size | What it is | Recommendation |
|---|------|------|------------|----------------|
| H1 | `output/` loose QA mp4/png/_qa/_c6 files | ~500 MB | v1.2/v1.3 QA renders, promo intermediates (promo_v13.mp4 itself is on GitHub release assets) | DELETE most; keep nothing — release asset is the source of truth |
| H2 | `output/_previews/` | ~7 MB | storyboard strips containing personal caption text | DELETE |
| H3 | `media/` loose `img_*.png` uploads | ~158 MB | old upload sessions; projects referencing them are also scratch | DELETE (samples/media/ is tracked, safe) |
| H4 | `scratch/` probe debris | ~173 MB | smoke/golden/probe leftovers | DELETE all |
| H5 | `projects/*.json` personal saves (_fixcheck.json … v13_promo.json) | <1 MB | may contain private VO text | KEEP or move to a private folder; never commit (gitignore already covers) |
| H6 | `.venv_ci/` | ~109 MB | CI mirror env — rebuildable in 2 min from requirements.txt | optional DELETE |
| H7 | `__pycache__` dirs outside venvs (3 stray) | <1 MB | bytecode | DELETE |
| H8 | `vo/models/` | ~297 MB | piper voices | **KEEP** (regenerating needs downloads; setup_vo.bat documented) |

Reclaimable total: ~840 MB (H1–H4, H6–H7). Free-disk watch: the disk got tight during v1.3
work — worth doing before the next build session.

---

## 7. Action plan

**Now (tiny, code, needs your commit green light):**
1. S1: confine `music_file` to MUSIC_DIR via realpath+within (audio.py:381). ~4 lines.
2. S6: scrub personal path from `docs/DESIGN_NOTES.md:11`. 1 line.
3. Sync smoke.yml wording "30 checks" → actual count; add LICENSE file if missing.
4. `esc()` sweep in ui/index.html interpolations (S3). ~15 spots.

**Next session:**
5. Same-Origin guard middleware on /api/* (S2 CSRF). ~6 lines + 1 smoke check.
6. get_project/save_project: context managers + reject all-dot project names.
7. Housekeeping H1–H4, H6–H7 once you give the green light (~840 MB back).

**Later / when packaging for distribution:**
8. Split ui/index.html into modules when features land next.
9. Dependency refresh at v1.4 (pillow especially).
10. README security note: "localhost-only by design, never bind 0.0.0.0."
