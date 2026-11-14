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
