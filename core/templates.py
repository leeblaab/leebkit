"""C4b templates gallery — curated starter skeletons that load into the editor.

A template = a schema-1 project skeleton built ON the v1.4 generator: every
shot has fill="gen:<preset>" (six designed looks, core/generators.py), engine-
owned camera/transition variety, and copy slots the user rewrites in place.
No images required -> cold install renders one out of the box.

Rules locked by the plan (docs/v1.4_plan.md C4b):
  * quality over quantity: a small curated set, every one validate-clean;
  * files live in templates/ and are COMMITTED (projects/*.json stays
    gitignored personal save-files — templates are product content);
  * app.py serves them read-only at /api/templates; the UI "use" button
    hydrates P exactly like project-load does, so saving afterwards creates
    a NEW projects/ file and never writes back into templates/;
  * template JSONs carry NO vo_lines (stale shot indices after edits) and
    voice:"none": per-shot `vo` strings are the VO slots; syncVoLines() in
    the UI rebuilds vo_lines on save/render.

templates_meta.json is generated from the template files themselves (one
source of truth for names/labels/durations — a hand-written manifest drifts).
"""

import json
import os

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
TEMPLATES_DIR = os.path.join(ROOT, "templates")


def list_templates():
    """Manifest built from the template files: [{file,name,label,target,shots}].
    Skips unreadable files (same policy as /api/projects)."""
    out = []
    if not os.path.isdir(TEMPLATES_DIR):
        return out
    for f in sorted(os.listdir(TEMPLATES_DIR)):
        if not f.endswith(".json") or f.startswith("_"):
            continue
        try:
            p = json.load(open(os.path.join(TEMPLATES_DIR, f), encoding="utf-8"))
            out.append({"file": f, "name": p.get("name", f[:-5]),
                        "label": p.get("label", ""),
                        "target": p.get("target"),
                        # ordered unique gen fills — the UI paints a palette
                        # gradient from /api/meta palettes keyed by these ids
                        "gens": list(dict.fromkeys(
                            s.get("fill") for s in (p.get("shots") or [])
                            if str(s.get("fill", "")).startswith("gen:"))),
                        "shots": len(p.get("shots") or [])})
        except Exception:
            pass
    return out


def load_template(fname):
    """Return a deep copy of one template, keyed by basename only (no
    traversal). Raises ValueError for unknown names."""
    base = os.path.basename(str(fname))
    path = os.path.join(TEMPLATES_DIR, base)
    if not base.endswith(".json") or not os.path.isfile(path):
        raise ValueError("no such template: %s" % base)
    return json.load(open(path, encoding="utf-8"))
