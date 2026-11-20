# SPDX-License-Identifier: AGPL-3.0-only
"""C3 (v1.41) — S2 XSS hardening gates for ui/index.html (static analysis;
no browser needed).

Audit #1 S2: esc() escaped only " and < — a project-authored string reaching
an innerHTML template can break out via raw ' or &-based entity tricks, and
the shot thumbnail src="/media/${s.image}" interpolation had NO esc() at all.

Gates:
1. esc() escapes & (first), <, >, ", ' — all five.
2. No remaining unescaped project-string interpolation in an img src / a href
   position (pattern scan for ${...} inside src="..." / href="..." without esc).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8").read()

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


# --- 1. esc() body --------------------------------------------------------
m = re.search(r"const esc\s*=\s*s\s*=>\s*(.*);", html)
check("esc() found", bool(m))
if m:
    body = m.group(1)
    for ch, ent in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                    ('"', "&quot;"), ("'", "&#39;")):
        # the replace SOURCE char must appear escaped-quoted in the chain
        present = re.search(re.escape(ch), body) or ent in body
        check("esc() handles %s -> %s" % (ch, ent), present, body[:120])
    # & MUST be replaced first, else "&lt;" double-escapes to "&amp;lt;"
    def _pos(needle):
        for pat in ("/%s/g" % needle, '"%s"' % needle, "'%s'" % needle):
            i = body.find(pat)
            if i != -1:
                return i
        return -1
    i_amp, i_lt = _pos("&"), _pos("<")
    check("& replaced before <", i_amp != -1 and i_lt != -1 and i_amp < i_lt,
          "amp@%s lt@%s" % (i_amp, i_lt))

# --- 2. attribute-position interpolations must be esc()-wrapped -----------
bad = []
for mm in re.finditer(r'(?:src|href)="([^"]*)"', html):
    inner = mm.group(1)
    if "${" not in inner:
        continue
    # skip HTML-comment lines (grep hits inside comments are prose, not DOM)
    line_start = html.rfind("\n", 0, mm.start()) + 1
    if html[line_start:mm.start()].lstrip().startswith(("//", "<!--")):
        continue
    # every ${...} expression inside the attribute needs an esc() wrapper;
    # Date.now() is a timestamp (allowlisted exception). GEN_THUMBS must also
    # be wrapped — v1.4 C6b injects that constant from server data, so it is
    # no longer trusted-static.
    for expr in re.findall(r"\$\{([^{}]*)\}", inner):
        if "esc(" in expr or "Date.now()" in expr:
            continue
        bad.append((mm.group(0)[:40], expr[:60]))
check("no unescaped ${} inside src=/href= attributes", not bad, repr(bad))

# --- 2b. text-position interpolations of caption fields (v1.51 audit #2) ---
# c.kind reaches innerHTML in two places (animations list <b>, shot-card
# <label>). A hand-authored project JSON with a hostile "kind" string must
# not inject markup. Gate: no raw ${c.kind} left anywhere, and every
# interpolation of the caption-kind variable inside templates is esc()-wrapped.
raw_kind = [mm.group(0) for mm in re.finditer(r"\$\{(?!\s*esc\()[^{}]*c\.kind[^{}]*\}", html)]
check("no raw ${...c.kind...} interpolation outside esc()", not raw_kind, repr(raw_kind[:3]))
# same rule for the colors array we now render into an input value=
raw_colors = [mm.group(0) for mm in re.finditer(r'value="\$\{(?!\s*esc\()[^{}]*colors[^{}]*\}"', html)]
check("caption colors input value is esc()-wrapped", not raw_colors, repr(raw_colors[:3]))

# --- 2d. numeric caption field value attrs must be esc()-wrapped (v1.6 U1) ---
# eq_bars n/w and the Y-fine y field reach input value="${...}" raw. A loaded
# project JSON (loadProjectObj does NO client validation) can set them to a
# string like '"><img src=x onerror=...>' -> attribute breakout XSS in the
# editor before any server gate runs. Gate: every c.n/c.w/c.y value interpolation
# is esc()-wrapped (node-repro confirmed n/w unescaped pre-fix).
raw_num = [mm.group(0) for mm in re.finditer(r'value="\$\{(?!\s*esc\()[^{}]*c\.(?:n|w|y)\b[^{}]*\}"', html)]
check("numeric caption fields (n/w/y) input value esc()-wrapped", not raw_num, repr(raw_num[:3]))

# --- 2e. boot() preset/music/voice option id+label must be esc()-wrapped (v1.6 U2/U3) ---
# music ids/labels derive from filenames (a file dropped into music/ bypasses the
# upload safe-name filter); preset/voice ids+labels come from META. All reach
# <option value=/title=/text> via innerHTML. Positive gate: the esc-wrapped forms
# must be present (regression catches anyone removing esc()).
for needle in ("esc(p.id)", "esc(p.label)", "esc(m.id)", "esc(m.label||m.id)",
               "esc(v.id)", "esc(v.label||v.id)"):
    check("boot option escapes %s" % needle, needle in html)

# --- 2c. meta-driven option lists are static engine ids (no injection) ----
# capMotionOptions builds <option value="${o}"> from META tables; those come
# from /api/meta which ships engine constants only — assert the route emits
# plain identifiers so the UI can trust them without esc().
import json as _json
sys.path.insert(0, ROOT)
import app as _app  # noqa: E402
_meta_ep = {r.path: r.endpoint for r in _app.app.routes if hasattr(r, "endpoint")}["/api/meta"]
_m = _meta_ep()
for key in ("exit_kinds", "ease_names", "fx_names", "place_names",
            "place_kinds", "idle_kinds", "caption_kinds"):
    vals = _m.get(key)
    ok = isinstance(vals, list) and all(re.fullmatch(r"[a-z_0-9]+", v) for v in vals)
    check("meta %s are plain ids" % key, ok, repr(vals)[:80])

# --- 3. node --check on the inline script (syntax must survive) ----------
import subprocess, tempfile, shutil
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
if scripts and shutil.which("node"):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write("\n".join(scripts))
        p = f.name
    r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
    check("inline UI script parses (node --check)", r.returncode == 0, r.stderr[-300:])
    os.unlink(p)
else:
    print("SKIP node --check (no node or no inline scripts)")

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
