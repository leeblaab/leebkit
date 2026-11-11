# LEEBKIT v1.3 — external audit cross-check (2026-11-11)

The other audit (read-only, pixel-probe-based, HEAD 0c47887) was re-verified claim-by-claim
against the code per project rule. Verdict: **high quality — 11 of its findings confirmed,
including 3 severe classes my own audit missed** (my pass looked at security/architecture;
its math-level probes found renderer/checker drift bugs). Merge status below.

## Confirmed by independent re-verification (code read + numeric probes)

| Ext-audit # | Claim | My verification | Verdict |
|---|---|---|---|
| 1 | cap_lines ≥4th line renders NOTHING (wp clamps at 1, slot j needs appear=wp−j·0.45 → slot 3 max = −0.35) | constants CAPLINE_RAMP=0.3/CAPLINE_LINE_STEP=0.45 confirmed; slot math reproduced: max appear 1.0/0.55/0.10/−0.35; word_pop early-returns at appear≤0 | **CONFIRMED — severe (silent content loss)** |
| 2 | metrics cap_lines `done_at = 1.0 + (n−1)·0.45` models unreachable wp | metrics.py:74 vs captions.py:216 clamp — exact match of claim | **CONFIRMED** |
| 3 | cap_lines overflow measured on WRAPPED lines while renderer draws RAW (off-canvas unflagged) | captions.py:217 comment literally says "draw path uses RAW lines (checks.py wraps+measures)" and checks.py measures m["lines"] from fit_panel_lines | **CONFIRMED — code documents the divergence instead of fixing it** |
| 4 | panel done_at formula over-states by ~0.6s → false red flags | reproduced numerically: `["ONE"], at=0.6, shot 1.5s → checker 1.83 vs real 1.23` (their numbers exactly) | **CONFIRMED** |
| 5 | caption `kind` never whitelisted; DISPATCH.get miss silently skips with a comment falsely claiming validation | engine.py:583-585 `continue # unknown kind: validate_project gates these` — validate only checks `"kind" in c` | **CONFIRMED (one-line fix)** |
| 6 | no bounds/type check on caption `at` | grep: only float(L.get("at",0.2)) at draw time; nothing in validate_project | **CONFIRMED** |
| 7 | anim_gallery endpoint awaits generate_gallery INLINE contradicting docstring; no in-flight lock, two writers share one `.part` name | app.py:304 `await asyncio.to_thread(AG.generate_gallery, preset)` — docstring says "in the background… instant" | **CONFIRMED** |
| 8 | terminal default rows: metrics has 3-entry default, captions has 4 (bar row) — duplicated literal drifted | both literals located, differ exactly as claimed | **CONFIRMED** |
| 9 | checks measures ALL terminal rows with engine.MONO; renderer uses MONOS for r≥2 | checks.py:96 `engine.MONO.getlength(rline)` vs layout split confirmed | **CONFIRMED (conservative direction)** |
| 10 | render_cli encodes crf 18/slow, queue encodes crf 19/medium — two recipes | grep confirms both lines | **CONFIRMED** |
| 11 | _scan_images skips dirs on unqualified substring ("frames" in root) | engine.py:265 `any(seg in root …)` confirmed | **CONFIRMED (low)** |

## Corrections to the external audit (per project rule, record rejected/partially-wrong items)

- **".venv_ci is not gitignored and is present in the tree" — FALSE as stated.** `.gitignore:6`
  has `.venv/` which matches `.venv_ci/` by prefix; `git ls-files .venv_ci` = empty (untracked).
  Derived lesson still adopted: add an explicit `.venv_ci/` line so future renames can't leak it.
- **Tag/message mismatch claim — true but stale context.** `v1.21` → commit saying "v1.3:" exists,
  but v1.21 was a never-pushed local alias deliberately kept (skill records this). Not a rewrite
  candidate; leave as-is, note it.
- Their ffmpeg start_number self-correction: matches our golden-harness reality (nb_read_frames
  gate passes) — accepted, and the "never add -start_number on theory" lesson is right.

## Where the two audits agree / differ from mine

Agree: security posture good + loopback-only caveat; music/upload path edges; esc() latent XSS;
"one source of truth" principle. Mine additionally found: S1 music absolute-path read (their audit
missed — sharpest remaining security edge), DESIGN_NOTES.md personal-path leak (privacy, tracked),
S2 CSRF/Origin, context-manager leaks, dot-name sanitizer edge, housekeeping table.
Theirs additionally found: the whole **checker-vs-renderer math drift class** (#1–4, 8, 9) — my
pass verified the architecture existed but never re-derived the formulas; their pixel probes did.

## Root cause (both audits concur)

"Two formulas, one animation": metrics.py approximates captions.py and comments keep them in sync.
Fix direction adopted from their plan: per-kind contract returning (draw ops + reachable settle),
plus **pure-math unit tests BEFORE the formula fix** (their step 7 — adopted; a permanently
invisible line is a stable byte string, so goldens can't catch #1).

## Merged fix order (supersedes my §7 action plan for code items)

1. Unit tests on metrics math against intended behavior (fail first) — new.
2. #5 kind whitelist + #6 `at` bounds (two lines, kills silent-nothing class).
3. #1+#2 shared cap_lines clock helper (lost content + bogus flag at once).
4. #3 measure what the renderer draws → decide auto-wrap vs flag (recommend auto-wrap).
5. #4+#8+#9 one pass aligning panel math, terminal default constant, terminal font.
6. #7 gallery background+lock, #10 encoder unification.
7. #11 component match, explicit .venv_ci ignore line, README "no auth; loopback only" line.
8. My S1 music confinement + S6 DESIGN_NOTES scrub + esc() sweep + smoke.yml wording — ride along.

## Housekeeping executed (green light 2026-11-11)

Deleted: output/ (501M), media/ loose uploads (255M incl. tracked-safe samples confirmed untouched),
scratch/ (173M), stray __pycache__ ×3 — all gitignored, `git status` clean after. Kept: vo/models,
.venv_ci, projects/*.json personal saves. ~930 MB reclaimed. NOTE: output/_animgallery cache is now
cold — first gallery open re-renders (~12s), self-heals by design (build-when-cold).
