"""Unit tests for the pure stagger/settle math (metrics.py) — v1.31 audit fix #1/#2/#4.

These test the INTENDED contract, agreed with Yasser's GO:
  * metrics.measure().done_at == the REAL settle time of the animation
    captions.py actually draws (single source of truth; checks must never
    re-derive — that drift bit us twice).
  * every drawn element is REACHABLE (appear > 0 at clock max): an invisible
    line is a perfectly stable byte string, so the golden harness cannot catch
    it (external audit finding #1, pixel-proven: only 2 of 3 cap_lines drew).
  * cap_lines AUTO-WRAP like panels (v1.31 behaviour change; golden baselines
    regenerate with it) — checker and renderer measure the same string.

Pure math only: fake eng objects with the real fit_panel_lines wrap semantics,
no PIL fonts, no rendering. Run: .venv python tests/test_metrics_math.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import metrics as M

# --- fake engine with the REAL fit_panel_lines semantics (word wrap to limit) ---
class FakeEng:
    """char_w px per char; panel_text_limit = limit px -> wraps words greedily."""
    def __init__(self, char_w=10, limit=920):
        self.L = {"panel_text_limit": limit}
        self._cw = char_w
        self.BODY = self.H1 = None   # fake fit ignores the font object

    def _wpx(self, s):
        return len(s) * self._cw

    def fit_panel_lines(self, dr, lines, fnt):
        out = []
        for l in lines:
            cur = ""
            for word in l.split(" "):
                cand = (cur + " " + word).strip()
                if self._wpx(cand) <= self.L["panel_text_limit"] or not cur:
                    cur = cand
                else:
                    out.append(cur)
                    cur = word   # real wrap_words: new line starts with this word
            if cur:
                out.append(cur)
        return out


def capline_step(n):
    """The v1.31 shared clock helper under test (metrics.capline_step)."""
    if not hasattr(M, "capline_step"):
        return M.CAPLINE_LINE_STEP   # pre-fix: constant -> tests fail (red)
    return M.capline_step(n)


def real_caplines_done(lines_wrapped):
    """Settle of the ACTUAL cap_lines draw path after normalization:
    wp = clamp01((lt-at)/CAPLINE_RAMP); line j appear = wp - j*step; inside
    word_pop the last word needs appear >= (nw-1)*WORD_STEP + WORD_RAMP.
    Returns (done_at_from_at_raw, n_reachable) — cap_lines has no preamble shift."""
    step = capline_step(len(lines_wrapped))
    worst, reachable = 0.0, 0
    for j, l in enumerate(lines_wrapped):
        req = (len(l.split(" ")) - 1) * M.WORD_STEP + M.WORD_RAMP
        wp_needed = req + j * step
        if wp_needed <= 1.0:
            reachable += 1
        worst = max(worst, wp_needed)
    return M.CAPLINE_RAMP * min(worst, 1.0), reachable


def real_panel_done(lines_wrapped, at_eff):
    """Settle of the ACTUAL panel word_pop: wprog=(lt-at-PWDELAY)/PWRAMP in [0,1],
    appear_j = wprog*(span/0.55) - j*Sv; line j lands when >= req_j."""
    n = len(lines_wrapped)
    span = max(len(l.split(" ")) for l in lines_wrapped) * M.WORD_STEP + M.WORD_RAMP
    Sv = (1.0 - span) / (n - 1) if n > 1 else 0.0
    worst = 0.0
    for j, l in enumerate(lines_wrapped):
        req = (len(l.split(" ")) - 1) * M.WORD_STEP + M.WORD_RAMP
        wp_needed = (req + j * Sv) / (span / 0.55)
        worst = max(worst, wp_needed)
    return at_eff + M.PANEL_WDELAY + M.PANEL_WRAMP * min(worst, 1.0)


FAILS = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print("%-4s %s %s" % (status, name, detail))
    if not cond:
        FAILS.append(name)


eng = FakeEng()

# --- #1 normalization: the LAST line must always be reachable (appear>0 at wp=1) ---
for n in (2, 3, 4, 6):
    step = capline_step(n)
    check("capline_step %d-line last-reachable" % n, step <= 1.0 / (n - 1) + 1e-9,
          "(step=%.4f needs <= %.4f)" % (step, 1.0 / (n - 1)))

# --- #1 reachability through measure(): every line's clock is REACHABLE at wp=1.
# (word_pop still shortens words whose own stagger window exceeds the clock —
# that's word_pop's documented behaviour, not invisible content.)
for n in (1, 2, 3, 4, 6):
    lines = ["WORD%d" % i for i in range(n)]
    m = M.measure(eng, {"lines": lines}, "cap_lines", shot_t=9.0, at_raw=0.2)
    step = capline_step(len(m["lines"]))
    clocks = [1.0 - j * step for j in range(len(m["lines"]))]
    check("cap_lines %d-line all-reachable" % n, all(c > 0 for c in clocks),
          "(clocks: %s)" % ["%.2f" % c for c in clocks])

# --- #3 cap_lines auto-wrap: the DRAW path wraps (audit #3); checked in the
# captions-import block below. measure() stays raw — checks.py and
# captions._wrap_panel wrap identically downstream. The wrap really splits:
# a 45-char line at char_w=10 with limit 200 -> 3 wrapped lines ---
_wrap_eng = FakeEng(char_w=10, limit=200)
_wrapped = _wrap_eng.fit_panel_lines(None, ["ALPHA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA"], None)
check("wrap splits overlong line", len(_wrapped) > 1 and all(len(l) * 10 <= 200 for l in _wrapped),
      "(%d wrapped lines)" % len(_wrapped))

# --- #2 done_at == REAL settle (at_raw clock: cap_lines has no preamble shift) ---
for lines in (["ALPHA BRAVO"], ["ONE", "TWO THREE"], ["A B C", "D E", "F"]):
    m = M.measure(eng, {"lines": lines}, "cap_lines", shot_t=9.0, at_raw=0.2)
    real, _ = real_caplines_done(m["lines"])
    check("cap_lines done_at==real %r" % (lines,), abs(m["done_at"] - 0.2 - real) < 1e-6,
          "(metrics %.3f vs real settle at_raw+%.3f)" % (m["done_at"], real))

# --- #4 panel done_at == REAL settle; no phantom overrun (audit pixel probes) ---
cases = [
    (["ONE"], 0.6),                    # audit probe: checker said 1.83, real 1.23
    (["ONE", "TWO"], 0.6),             # audit probe: checker 2.28, real 1.67
    (["A B C"], 0.2),
    (["A B", "C D E"], 0.4),
    (["X", "Y Z", "W P Q"], 0.3),      # line-order sensitivity
]
for lines, at in cases:
    m = M.measure(eng, {"lines": lines}, "panel_top", shot_t=9.0, at_raw=at)
    at_eff = M.preamble_at("panel_top", at)
    real = real_panel_done(m["lines"], at_eff)
    check("panel done_at==real %r at=%.1f" % (lines, at), abs(m["done_at"] - real) < 1e-6,
          "(metrics %.3f vs real %.3f)" % (m["done_at"], real))

# --- #8 terminal default rows: ONE constant shared by metrics and captions ---
try:
    from core import captions as C
    default_rows = getattr(M, "TERM_DEFAULT_ROWS", None)
    check("metrics.TERM_DEFAULT_ROWS exists", default_rows is not None)
    if default_rows is not None:
        m0 = M.measure(eng, {}, "terminal", shot_t=9.0, at_raw=0.2)
        m1 = M.measure(eng, {"rows": list(default_rows)}, "terminal", 9.0, 0.2)
        check("terminal default rows == metrics default",
              abs(m0["rows_done"] - m1["rows_done"]) < 1e-9)
        check("captions default uses SAME constant", C.M.TERM_DEFAULT_ROWS is M.TERM_DEFAULT_ROWS)
    # audit #3 pinned: draw_cap_lines wraps via _wrap_panel, never raw lines
    import inspect as _insp
    _src = _insp.getsource(C.draw_cap_lines)
    check("cap_lines draw path wraps", "_wrap_panel(eng, dr, L[\"lines\"]" in _src
          and "for j, line in enumerate(L[\"lines\"])" not in _src)
except ImportError as e:
    check("captions importable", False, str(e))

# --- preamble_at contract (unchanged) ---
check("preamble panel", abs(M.preamble_at("panel_top", 0.6) - (0.6 - M.PANEL_SHIFT)) < 1e-9)
check("preamble cap_lines unchanged", abs(M.preamble_at("cap_lines", 0.6) - 0.6) < 1e-9)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
