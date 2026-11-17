# v1.5 item 5: idle motion — breathe (scale) + color_wave after SETTLE only
import os
import sys

ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

import core.metrics as M
from core.engine import Engine, validate_project
from core.checks import check_project


def base_proj(caps, t=3.0):
    return {"schema": 1, "target": t, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [{"fill": "solid", "t": t, "captions": caps}]}


def diff_bbox(a, b):
    """(minx,miny,maxx,maxy) of pixels differing between two frames, or None."""
    a = a.convert("RGB"); b = b.convert("RGB"); pa, pb = a.load(), b.load()
    W, H = a.size
    x0, y0, x1, y1 = W, H, -1, -1
    for y in range(H):
        for x in range(W):
            if pa[x, y] != pb[x, y]:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    return None if x1 < 0 else (x0, y0, x1, y1)


def test_validate_idle_shape():
    ok = base_proj([{"kind": "accent_word", "at": 0.3, "text": "GO", "idle": True}])
    validate_project(ok)
    p = base_proj([{"kind": "accent_word", "at": 0.3, "text": "GO", "idle": "yes"}])
    try:
        validate_project(p)
        raise AssertionError("non-bool idle accepted")
    except ValueError:
        pass


def test_checker_idle_gates():
    # ineligible kind -> flag 'idle'
    p = base_proj([{"kind": "terminal", "at": 0.3, "rows": ["A", "B"], "idle": True}])
    flags = check_project(Engine(p))
    assert [f for f in flags if f["kind"] == "idle"], flags
    # never settles inside the shot -> flag 'idle'
    late = base_proj([{"kind": "accent_word", "at": 2.9,
                       "text": "WAY TOO LATE TO SETTLE EVER", "idle": True}], t=3.0)
    flags2 = check_project(Engine(late))
    assert [f for f in flags2 if f["kind"] == "idle"], flags2
    # clean caption -> no idle flag
    good = base_proj([{"kind": "accent_word", "at": 0.3, "text": "EARLY", "idle": True}])
    flags3 = check_project(Engine(good))
    assert not [f for f in flags3 if f["kind"] == "idle"], flags3


def test_idle_done_at_matches_measure():
    """Renderer gate and checker read the SAME settle clock — idle_done_at must
    equal measure()'s done_at for every idle-eligible kind (parity by
    construction; this test is what keeps it that way)."""
    from core.engine import Engine as E
    eng = E(base_proj([{"kind": "accent_word", "at": 0.3, "text": "GO"}]))
    dr = None
    import PIL.Image, PIL.ImageDraw
    dr = PIL.ImageDraw.Draw(PIL.Image.new("RGB", (8, 8)))
    cases = [
        {"kind": "accent_word", "at": 0.3, "text": "ONE TWO THREE"},
        {"kind": "cta", "at": 0.4, "text": "GET STARTED TODAY"},
        {"kind": "small", "at": 0.2, "text": "note text here"},
        {"kind": "handle", "at": 0.2, "text": "@leebkit"},
        {"kind": "panel_top", "at": 0.4, "lines": ["first line here", "second one"]},
        {"kind": "kicker", "at": 0.3, "text": "NEW DROP OUT NOW"},
        {"kind": "typewriter", "at": 0.3, "text": "typed line"},
        {"kind": "pump", "at": 0.3, "text": "PUMP THE WORDS"},
        {"kind": "split", "at": 0.3, "text": "half and half"},
        {"kind": "maskline", "at": 0.3, "text": "masked words rise"},
    ]
    for L in cases:
        m = M.measure(eng, L, L["kind"], 6.0, float(L["at"]))
        want = m.get("done_at")
        got = M.idle_done_at(L["kind"], L, eng=eng)
        assert want is not None and got is not None and abs(want - got) < 1e-9, \
            "%s: measure=%s idle_done_at=%s" % (L["kind"], want, got)


def test_breathe_pixels_only_after_settle():
    """A/B on a real render: frames sampled INSIDE the idle window differ from
    their idle-off twins; frames BEFORE settle are byte-identical either way."""
    cap_on = {"kind": "accent_word", "at": 0.3, "text": "BREATHE WORDS", "idle": True}
    cap_off = dict(cap_on); del cap_off["idle"]
    on = Engine(base_proj([cap_on]))
    off = Engine(base_proj([cap_off]))
    done = M.idle_done_at("accent_word", cap_on)     # 0.3 + 2*0.18 + 0.36 = 0.90
    pre_on = on.render_layer(0, 0.5, 12)             # lt=0.5 < done
    pre_off = off.render_layer(0, 0.5, 12)
    assert diff_bbox(pre_on, pre_off) is None, "pixels moved BEFORE settle"
    moved = False
    for f in range(int(done * 24) + 1, 70):          # idle window to shot end
        lt = f / 24.0
        if lt >= 3.0 - M.EXIT_RAMP:
            break
        d = diff_bbox(on.render_layer(0, lt, f), off.render_layer(0, lt, f))
        if d is not None:
            moved = True
            # the diff must live in the accent-word band, not the whole frame
            assert d[3] - d[1] < 200, "idle diff spread outside the line: %r" % (d,)
    assert moved, "idle window produced ZERO pixel changes"


def test_wave_pixels_only_after_settle():
    cap_on = {"kind": "kicker", "at": 0.3, "text": "WAVE LINE", "idle": True}
    cap_off = dict(cap_on); del cap_off["idle"]
    on = Engine(base_proj([cap_on]))
    off = Engine(base_proj([cap_off]))
    done = M.idle_done_at("kicker", cap_on)
    pre = diff_bbox(on.render_layer(0, 0.4, 9), off.render_layer(0, 0.4, 9))
    assert pre is None, "wave moved pixels BEFORE settle: %r" % (pre,)
    moved = any(diff_bbox(on.render_layer(0, f / 24.0, f),
                          off.render_layer(0, f / 24.0, f)) is not None
                for f in range(int(done * 24) + 1, 68))
    assert moved, "color_wave produced ZERO pixel changes"


def test_wave_fill_paths_pixels():
    """Every WAVE kind must actually ROUTE the wave (a missed draw path would
    sit silently green under the gate tests). A/B per kind: pre-settle frames
    byte-identical, post-settle frames differ."""
    cases = [
        {"kind": "typewriter", "at": 0.3, "text": "typed wave line", "idle": True},
        {"kind": "pump", "at": 0.3, "text": "PUMP WAVE WORDS", "idle": True},
        {"kind": "split", "at": 0.3, "text": "half and half", "idle": True},
        {"kind": "maskline", "at": 0.3, "text": "masked words rise", "idle": True},
    ]
    for cap_on in cases:
        cap_off = dict(cap_on); del cap_off["idle"]
        on = Engine(base_proj([cap_on]))
        off = Engine(base_proj([cap_off]))
        done = M.idle_done_at(cap_on["kind"], cap_on)
        pre = diff_bbox(on.render_layer(0, max(0.1, done * 0.4), 3),
                        off.render_layer(0, max(0.1, done * 0.4), 3))
        assert pre is None, "%s wave moved pixels BEFORE settle: %r" % (cap_on["kind"], pre)
        moved = any(diff_bbox(on.render_layer(0, f / 24.0, f),
                              off.render_layer(0, f / 24.0, f)) is not None
                    for f in range(int(done * 24) + 1, 68))
        assert moved, "%s color_wave produced ZERO pixel changes" % cap_on["kind"]


def test_breathe_fill_paths_pixels():
    """Same routing proof for the BREATHE kinds (small/handle/panel ride
    draw_center_text/word_pop `s` — a missed path = silent no-op)."""
    cases = [
        {"kind": "small", "at": 0.2, "text": "note breathe text", "idle": True},
        {"kind": "handle", "at": 0.2, "text": "@leebkit", "idle": True},
        {"kind": "panel_top", "at": 0.4, "lines": ["first breathe line", "second one"],
         "idle": True},
        {"kind": "cta", "at": 0.3, "text": "BREATHE CTA LINE", "idle": True},
    ]
    for cap_on in cases:
        cap_off = dict(cap_on); del cap_off["idle"]
        on = Engine(base_proj([cap_on]))
        off = Engine(base_proj([cap_off]))
        done = M.idle_done_at(cap_on["kind"], cap_on)
        pre = diff_bbox(on.render_layer(0, max(0.1, done * 0.4), 3),
                        off.render_layer(0, max(0.1, done * 0.4), 3))
        assert pre is None, "%s breathe moved pixels BEFORE settle: %r" % (cap_on["kind"], pre)
        moved = any(diff_bbox(on.render_layer(0, f / 24.0, f),
                              off.render_layer(0, f / 24.0, f)) is not None
                    for f in range(int(done * 24) + 1, 68))
        assert moved, "%s breathe produced ZERO pixel changes" % cap_on["kind"]


def test_no_idle_field_unchanged():
    """Byte-identical discipline: without the field, ctx.idle_s/idle_tint are
    None on every frame (goldens cover pixels; this covers the plumbing)."""
    import core.captions as C
    seen = []
    src = C.DISPATCH["cta"]
    def spy(eng, dr, L, k, ctx, e2):
        seen.append((ctx.idle_s, ctx.idle_tint))
        return src(eng, dr, L, k, ctx, e2)
    C.DISPATCH["cta"] = spy
    try:
        Engine(base_proj([{"kind": "cta", "at": 0.3, "text": "PLAIN"}])) \
            .render_layer(0, 1.0, 24)
    finally:
        C.DISPATCH["cta"] = src
    assert seen == [(None, None)], seen


def test_idle_is_deterministic():
    cap = {"kind": "panel_mid", "at": 0.4, "lines": ["idle panel line one", "two"],
           "idle": True}
    a = Engine(base_proj([cap]))
    b = Engine(base_proj([cap]))
    for f in (30, 45, 60):
        assert a.render_layer(0, f / 24.0, f).tobytes() == \
               b.render_layer(0, f / 24.0, f).tobytes(), "idle frame %d differs" % f


def main():
    for fn in (test_validate_idle_shape, test_checker_idle_gates,
               test_idle_done_at_matches_measure,
               test_breathe_pixels_only_after_settle,
               test_wave_pixels_only_after_settle,
               test_wave_fill_paths_pixels, test_breathe_fill_paths_pixels,
               test_no_idle_field_unchanged, test_idle_is_deterministic):
        fn()
        print("PASS", fn.__name__)
    print("IDLE MOTION PASS")


if __name__ == "__main__":
    main()
