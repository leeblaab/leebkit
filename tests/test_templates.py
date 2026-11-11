"""v1.4 C4b — templates gallery gate (run as a script from repo root).

Templates are COMMITTED product content (unlike projects/ save-files), so this
test is the contract: every shipped template must pass the full check_project
(timing + whitelist + fit) with ZERO hard errors, be generator-only (cold
install renders with no images), and load through the traversal-safe loader.
"""
import os

from core.checks import check_project
from core.engine import Engine
from core.templates import TEMPLATES_DIR, list_templates, load_template

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


man = list_templates()
check("curated set >= 3 templates", len(man) >= 3)
files = sorted(f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".json"))
check("manifest mirrors the dir", [m["file"] for m in man] == files)

for f in files:
    t = load_template(f)
    # check_project runs on an Engine (flags carry severity); the tier loop
    # below builds one per size, so gate FHD here and collect its errors.
    eng_fhd = Engine(t)
    flags = check_project(eng_fhd)
    errs = [fl["message"] for fl in flags if fl.get("severity") == "error"]
    check("%s: zero hard errors" % f, not errs)
    if errs:
        print("   " + "\n   ".join(errs))
    for s in t["shots"]:
        if "image" in s or not str(s.get("fill", "")).startswith("gen:"):
            check("%s: generator-only shots" % f, False)
            break
    else:
        check("%s: generator-only shots" % f, True)
    check("%s: no vo_lines / voice none" % f,
          not t.get("vo_lines") and t.get("voice") == "none")
    m = next(x for x in man if x["file"] == f)
    check("%s: manifest agrees (shots/target/gens)" % f,
          m["shots"] == len(t["shots"]) and m["target"] == t["target"]
          and m["gens"] and all(g.startswith("gen:") for g in m["gens"]))

try:
    load_template("../app.py")
    check("loader blocks traversal", False)
except ValueError:
    check("loader blocks traversal", True)
try:
    load_template("nope.json")
    check("loader raises on unknown", False)
except ValueError:
    check("loader raises on unknown", True)

# the gallery "use" path: hydrated template renders at every portrait tier
# with zero extra edits (Engine composes cold — gen shots need no images).
t = load_template(files[0])
scratch = os.environ.get("TMPDIR") or "."
for size in ("720x1280", "1080x1920", "1440x2560"):
    w, h = map(int, size.split("x"))
    # Engine(proj, preset, media_dir): the 2nd positional is a preset DICT —
    # pass None here (load_preset resolves proj['preset'] itself; a bare id
    # string in this slot crashes at P["colors"], pitfall hit once).
    e = Engine(dict(t, size=size, width=w, height=h), None,
               os.path.join(scratch, "_tpl_%s" % size))
    fr = e.compose_frame(int(e.N * 0.4))   # returns a PIL Image
    check("%s: template composes %dx%d" % (files[0], w, h), fr.size == (w, h))

# app wiring (import only — NEVER touch the live :8735 server)
import app as appmod
routes = {r.path for r in appmod.app.routes}
check("/api/templates + /api/template routes",
      "/api/templates" in routes and "/api/template/{fname}" in routes)

print("---")
if fails:
    print("FAILED: " + ", ".join(fails))
    raise SystemExit(1)
n = 6 + 4 * len(files) + 2 + 3 + 1
print("ALL PASS (c4b templates gallery, %d checks)" % n)
