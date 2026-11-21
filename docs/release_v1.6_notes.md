# LEEBKIT v1.6 — hardening + speed release

No new caption kinds this time — v1.6 makes the engine harder to break and twice as fast to run.

## What's new for users

- **Faster renders.** The `--finish` audio pass now parallelizes across all cores instead of forcing a single worker. Measured on a 34-second showcase reel (1020 frames @ 1080x1920): wall time 35s -> 10s. Output is byte-identical to before the speedup (verified by SHA-256).
- **Clearer errors.** Malformed projects now fail fast with friendly messages (missing shot data, oversized caption lists, wrong value types) instead of deep engine tracebacks. Limits are enforced before rendering starts.
- **Consistent licensing.** Every Python file in the repo now carries the `AGPL-3.0-only` SPDX header, with a CI test that keeps it true forever.
- **UI input hardening.** Numeric and option fields in the editor (bars/width/Y fine, preset/music/voice pickers) are properly escaped — no more raw-value injection paths.
- **New showcase draft:** `drafts/masterclass_v16.json` — an 8-shot reel demonstrating the full v1.5 kinetic caption surface (steps ease, color_wave idle, glitch fx, per-caption exits).

## Quality gates at this tag

- Smoke suite: 62 checks PASS
- Golden corpus: 1314 frames byte-match PASS (Linux + Windows)
- Determinism: release MP4 SHA-256 identical across job counts and before/after the perf fix
