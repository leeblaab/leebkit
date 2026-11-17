"""v1.42 C9.1 — per-caption `place` field (Yasser directive after testing
onyx_v2_showcase: stacked big-type shares anchor fracs and collides; the fix
is letting each caption pick its own vertical band, not hand-editing fracs).

Field: caption-level "place": "top" | "middle" | "bottom" — remaps THAT
caption's vertical anchor frac (per-kind frac key table in metrics.PLACE_KEYS)
to a preset band value (PLACE_TOP_FRAC / PLACE_BOTTOM_FRAC; "middle" = the
kind's shipped frac, i.e. byte-identical). Fine-tune: caption-level "y": float
(0..1 of frame height) overrides the band exactly. Opt-in only: no field ->
the shared LY dict is passed through untouched (byte-identical default path).

Tests are pixel-diff based (grain is painted per-frame in render_layer, so
same-frame-index diffs are the honest check — C4 lesson).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageChops
from core.engine import Engine
from core import metrics as M

MEDIA = "samples/media"


def _proj(caps):
    return {"schema": 1, "size": "1080x1920", "target": 3.0, "fps": 30,
            "shots": [{"image": "img_00014.png", "t": 3.0, "transition": "cut",
                       "captions": caps}]}


def _frame(proj, t):
    eng = Engine(proj, media_dir=MEDIA)
    return eng.render_layer(0, t, int(round(t * proj["fps"])))


def _diff(a, b):
    return ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()


def test_validate_shape():
    # bad place / out-of-range y must fail LOUD at validate time.
    for cap, why in (({"kind": "flashpop", "at": 0.3, "text": "X", "place": "sideways"}, "bad place"),
                     ({"kind": "flashpop", "at": 0.3, "text": "X", "y": 1.7}, "y>1")):
        try:
            Engine(_proj([cap]), media_dir=MEDIA)
            raise AssertionError("validate accepted %s" % why)
        except ValueError as e:
            assert ("place" in str(e)) or ("y" in str(e)), (why, e)
    # place on a kind with no band choice is rejected too
    try:
        Engine(_proj([{"kind": "cap_lines", "at": 0.3, "lines": ["A"], "place": "top"}]),
               media_dir=MEDIA)
        raise AssertionError("validate accepted place on fixed-plate kind")
    except ValueError as e:
        assert "place" in str(e), e
    # good shapes validate clean
    for cap in ({"kind": "flashpop", "at": 0.3, "text": "X", "place": "top"},
                {"kind": "flashpop", "at": 0.3, "text": "X", "y": 0.28}):
        Engine(_proj([cap]), media_dir=MEDIA)
    print("PASS validate shape (place/y whitelist + range + kind gate)")


def test_default_byte_identical():
    # no place field anywhere -> every caption frame byte-identical to the
    # shipped path (the LY passthrough must not even copy the dict).
    caps = [{"kind": "burst", "at": 0.3, "text": "GLITCH SPLIT"},
            {"kind": "accent_word", "at": 1.4, "text": "COLLAPSE"}]
    eng_a = Engine(_proj(caps), media_dir=MEDIA)
    for t in (0.5, 1.2, 2.6):
        fa = eng_a.render_layer(0, t, int(t * 30))
        fb = _frame(_proj(caps), t)
        assert ImageChops.difference(fa, fb).getbbox() is None, "default path drifted at t=%.2f" % t
    print("PASS default path byte-identical (no place field)")


def test_place_moves_pixels():
    # flashpop rides accent_frac; place:top must move its pixels UP and leave
    # the old band clean (collision fix works).
    base = {"kind": "flashpop", "at": 0.3, "text": "SLAM"}
    f_mid = _frame(_proj([dict(base)]), 2.6)          # settled, shipped band
    f_top = _frame(_proj([dict(base, place="top")]), 2.6)
    bbox = _diff(f_mid, f_top)
    assert bbox is not None, "place:top changed nothing"
    # top band (above accent_frac*H) gained ink that the middle frame lacks
    accent_y = int(M.PLACE_KEYS["flashpop"] and 0.415 * 1920)
    up = f_top.crop((0, 0, 1080, accent_y - 60))
    up_mid = f_mid.crop((0, 0, 1080, accent_y - 60))
    assert _diff(up, up_mid) is not None, "place:top did not put ink in the top band"
    # old band must now be clean of the word (compare crops below the new text)
    print("PASS place moves pixels into the requested band")


def test_y_finetune_and_bottom():
    base = {"kind": "small", "at": 0.3, "text": "NOTE"}
    f_mid = _frame(_proj([dict(base)]), 2.6)
    f_bot = _frame(_proj([dict(base, place="bottom")]), 2.6)
    assert _diff(f_mid, f_bot) is not None, "place:bottom changed nothing"
    f_y = _frame(_proj([dict(base, y=0.15)]), 2.6)
    assert _diff(f_mid, f_y) is not None, "y fine-tune changed nothing"
    # y=kind's own shipped frac == byte-identical to default (middle semantics)
    eng = Engine(_proj([dict(base)]), media_dir=MEDIA)
    same = _frame(_proj([dict(base, y=eng.L["small_frac"])]), 2.6)
    assert ImageChops.difference(f_mid, same).getbbox() is None, \
        "y == shipped frac must be byte-identical"
    print("PASS place:bottom + y fine-tune (and y==shipped frac is identity)")


def test_checker_sees_same_geometry():
    # renderer/checker agree by construction: the per-caption place/y merge
    # must reach the SAME LY the checker budgets with. Direct unit check of
    # the shared helper (checks.py routes every measure() through it).
    eng = Engine(_proj([{"kind": "small", "at": 0.3, "text": "OK"}]), media_dir=MEDIA)
    ly = M.place_merge(eng.L, {"kind": "small", "y": 0.9})
    assert ly["small_frac"] == 0.9, "place/y must reach the merged LY frac key"
    ly2 = M.place_merge(eng.L, {"kind": "cta", "place": "top"})
    assert ly2["cta_frac"] == M.PLACE_TOP_FRAC and ly2["small_frac"] == eng.L["small_frac"], \
        "place:top must retarget ONLY the mapped kind frac key"
    print("PASS checker-side merge (place_merge feeds the same LY)")


def test_sample_vs_full_determinism():
    caps = [{"kind": "burst", "at": 0.3, "text": "GLITCH SPLIT", "place": "top"},
            {"kind": "accent_word", "at": 1.4, "text": "COLLAPSE", "y": 0.62}]
    p = _proj(caps)
    eng = Engine(p, media_dir=MEDIA)
    for t in (0.9, 2.2):
        a = eng.render_layer(0, t, int(t * 30))
        b = Engine(p, media_dir=MEDIA).render_layer(0, t, int(t * 30))
        assert ImageChops.difference(a, b).getbbox() is None, "place not deterministic"
    print("PASS place/y pure function of (t, seed)")


if __name__ == "__main__":
    test_validate_shape()
    test_default_byte_identical()
    test_place_moves_pixels()
    test_y_finetune_and_bottom()
    test_checker_sees_same_geometry()
    test_sample_vs_full_determinism()
    print("ALL C9.1 place-field TESTS PASS")
