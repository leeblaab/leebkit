# v1.42 item 4: per-caption exit motion — rise / wipe / scale (opt-in `exit`)
import core.metrics as M
from core.engine import Engine, validate_project
from core.checks import check_project


def base_proj(caps, t=3.0):
    return {"schema": 1, "target": t, "fps": 24, "width": 320, "height": 480,
            "preset": "onyx", "music": {"mode": "none"},
            "shots": [{"fill": "solid", "t": t, "captions": caps}]}


def ink(img):
    img = img.convert("RGB"); px = img.load(); W, H = img.size
    return sum(1 for y in range(H) for x in range(W) if sum(px[x, y]) > 90)


def test_validate_exit_whitelist():
    ok = base_proj([{"kind": "accent_word", "at": 0.3, "text": "GO", "exit": "rise"}])
    validate_project(ok)
    for bad in ("float", "spin"):
        p = base_proj([{"kind": "accent_word", "at": 0.3, "text": "GO", "exit": bad}])
        try:
            validate_project(p)
            raise AssertionError("exit %r accepted" % bad)
        except ValueError:
            pass


def test_checker_settle_gate():
    # exit window starts at shot_t - EXIT_RAMP; a line that settles AFTER that
    # (+0.1 tolerance) must flag kind 'exit'.
    late = base_proj([{"kind": "accent_word", "at": 2.9, "text": "TOO LATE LINE",
                       "exit": "rise"}], t=3.0)
    flags = check_project(Engine(late))
    assert [f for f in flags if f["kind"] == "exit"], flags
    settled = base_proj([{"kind": "accent_word", "at": 0.3, "text": "EARLY LINE",
                          "exit": "rise"}], t=3.0)
    flags2 = check_project(Engine(settled))
    assert not [f for f in flags2 if f["kind"] == "exit"], flags2


def test_rise_exit_lifts_before_cut():
    # settled accent_word at lt=2.9 (shot t=3.0): with exit=rise the line has
    # LIFTED ~30px out of its resting band by the cut. PIL truth (probe 22/23):
    # an RGBA fill alpha on dr.text is a PAINT op — a=89 glyph lands at full
    # ink on black; only a<=0 erases — so rise's visible motion is the LIFT,
    # not an ink-count drop. Assert the whole glyph band moved up clear of
    # where the settled line sits.
    caps_plain = [{"kind": "accent_word", "at": 0.3, "text": "EXIT RISE"}]
    caps_rise = [dict(caps_plain[0], exit="rise")]
    lt = 2.9   # ep = (2.9-2.75)/0.25 = 0.6 -> dy ~ -30px

    def band(img):
        img = img.convert("RGB"); px = img.load(); W, H = img.size
        rows = [y for y in range(H) if sum(1 for x in range(W) if sum(px[x, y]) > 90)]
        return (min(rows), max(rows))

    a = band(Engine(base_proj(caps_plain)).render_layer(0, lt, int(lt * 24)))
    b = band(Engine(base_proj(caps_rise)).render_layer(0, lt, int(lt * 24)))
    assert b[1] < a[0], ("rise exit did not lift clear of the settled band", a, b)


def test_wipe_exit_closes_right_edge():
    caps_wipe = [{"kind": "accent_word", "at": 0.3, "text": "WIPE OUT HERE",
                  "exit": "wipe"}]
    lt = 2.875   # ep = 0.5 -> half the run still revealed
    a = ink(Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                               "text": "WIPE OUT HERE"}])).render_layer(0, lt, int(lt * 24)))
    b = ink(Engine(base_proj(caps_wipe)).render_layer(0, lt, int(lt * 24)))
    assert b < a, ("wipe exit not closing", a, b)


def test_scale_exit_shrinks():
    caps_sc = [{"kind": "accent_word", "at": 0.3, "text": "SCALE DOWN",
                "exit": "scale"}]
    lt = 2.95   # ep ~0.8 -> q small enough that the last word's stagger clock
                # (wt = (prog - i*0.18)/0.36) dies; at ep=0.5 all words are
                # still full-alpha (PIL paint-op truth, see rise test above)
    a = ink(Engine(base_proj([{"kind": "accent_word", "at": 0.3,
                               "text": "SCALE DOWN"}])).render_layer(0, lt, int(lt * 24)))
    b = ink(Engine(base_proj(caps_sc)).render_layer(0, lt, int(lt * 24)))
    assert b < a, ("scale exit not shrinking", a, b)


def test_no_exit_field_unchanged():
    # byte-identical discipline: without the field, FrameCtx.exit_p is None and
    # every draw path takes the shipped branch (goldens cover this too).
    import core.captions as C
    seen = []
    src = C.DISPATCH["accent_word"]
    def spy(eng, dr, L, k, ctx, e2):
        seen.append(ctx.exit_p)
        return src(eng, dr, L, k, ctx, e2)
    real = C.DISPATCH["accent_word"]
    C.DISPATCH["accent_word"] = spy
    try:
        Engine(base_proj([{"kind": "accent_word", "at": 0.3, "text": "PLAIN"}])
               ).render_layer(0, 1.0, 24)
    finally:
        C.DISPATCH["accent_word"] = real
    assert seen == [None], seen


def main():
    for fn in (test_validate_exit_whitelist, test_checker_settle_gate,
               test_rise_exit_lifts_before_cut,
               test_wipe_exit_closes_right_edge, test_scale_exit_shrinks,
               test_no_exit_field_unchanged):
        fn()
        print("PASS", fn.__name__)
    print("EXIT MOTION PASS")


if __name__ == "__main__":
    main()
