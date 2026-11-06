# Contributing to LEEBKIT

Thanks for helping. Keep the three pillars (README): **light, offline, fast**.
PRs that add a network dependency, a frontend framework or a database will not
be accepted — that is the product.

## Ground rules
- Engine changes must keep `schema:1` project JSON backward-compatible, and
  land with a CLI render + frame-extract QA of the touched moments (cut points,
  typed-line finals). "It looks fine on my machine" is not a check.
- New caption kinds go in the engine first (CLI-tested), then surface in the UI.
- Transitions: any new transition must implement the overlap convention — it
  consumes `ov` seconds of the *previous* layer's tail (see `core/engine.py`).

## Developer Certificate of Origin
All contributions are provided under the AGPL-3.0 of this repository and must
carry a sign-off line in each commit message:

    Signed-off-by: Your Name <you@example.com>

(inline DCO — `git commit -s` adds it). Commits without sign-off will be asked
to be amended.

## Getting started
1. `start.bat` (creates `.venv`, installs deps, serves http://127.0.0.1:8735)
2. CLI dev loop: edit `core/`, then
   `python render_cli.py samples/leebdark_sample.json --media media --out output/test.mp4`
3. Open issues labeled `good-first-issue` are fair game; for anything bigger,
   open an issue first so we can agree on scope before you write code.
