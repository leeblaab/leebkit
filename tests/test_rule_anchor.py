"""v1.42 item 2 (C0a): rule-anchor regression probe.

The advisor claimed a "strikethrough" where an underline crosses wrapped
kicker text. Audit against v1.41 says both kicker rules and the title_block
underline are POST-FIT anchored (drawn from the fitted line geometry, not the
raw input). This test PROVES it: renders the advisor's exact scenario frame by
frame and asserts no rule rect ever overlaps a glyph row.

Pure pixel probe — no corpus/golden change. Run:
  PYTHONPATH=. .venv/Scripts/python.exe tests/test_rule_anchor.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image
from core.engine import Engine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _rule_rows(img, accent):
    """Rows that contain a long horizontal run of near-accent pixels
    (a rule line), vs rows containing ANY non-background glyph pixel."""
    W, H = img.size
    px = img.load()
    ar, ag, ab = accent[:3]
    rule_rows, glyph_rows = set(), set()
    for y in range(H):
        run = 0
        longest = 0
        glyphs = 0
        for x in range(W):
            r, g, b = px[x, y][:3]
            if abs(r - ar) < 40 and abs(g - ag) < 40 and abs(b - ab) < 40:
                run += 1
                longest = max(longest, run)
            elif r + g + b > 90:   # anything bright on the dark bg
                glyphs += 1
        if longest > W * 0.25:     # a rule spans >= a quarter of the frame
            rule_rows.add(y)
        if glyphs > 0:
            glyph_rows.add(y)
    return rule_rows, glyph_rows


def main():
    proj = {
        "schema": 1, "name": "rule_anchor_probe", "preset": "onyx",
        "size": "540x960", "fps": 30, "target": 4.0, "music": {"mode": "none"},
        "shots": [
            {"fill": "image", "image": "img_00014.png",
             "dim": 0.6, "t": 4.0, "transition": "cut",
             "captions": [
                 {"kind": "kicker", "at": 0.3, "rule": True,
                  "text": "TYPE THAT MOVES LIKE THIS AND WRAPS TO A SECOND LINE"},
                 {"kind": "title_block", "at": 1.2,
                  "text": "REAL FOOTAGE REAL MOTION KEEPS GOING LONG ENOUGH TO WRAP",
                  "sub": "SUB LINE"}]},
        ],
    }
    eng = Engine(proj)
    accent = eng.ACCENT
    bad = []
    for idx in range(0, int(eng.DUR * eng.FPS), 3):
        img = eng.compose_frame(idx).convert("RGB")
        rule_rows, glyph_rows = _rule_rows(img, accent)
        if not rule_rows:
            continue
        # a rule "crosses" text only if rule rows sit INSIDE the vertical
        # span of a multi-row glyph block (rows above/below are fine anchors)
        gr = sorted(glyph_rows)
        inside = [y for y in rule_rows
                  if gr and min(gr) < y < max(gr)
                  and any(abs(y - gy) <= 1 for gy in gr)]
        if inside:
            bad.append((idx, sorted(rule_rows)[:3], sorted(inside)[:6]))
    assert not bad, "rule overlaps glyph rows at frames: %s" % bad[:4]
    print("PASS: kicker rule + title underline stay clear of glyphs "
          "(%d frames probed)" % (int(eng.DUR * eng.FPS) // 3 + 1))


if __name__ == "__main__":
    main()
