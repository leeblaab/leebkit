"""Animation gallery (v1.35) — CapCut-style looping webp previews for every
transition and camera move, rendered on the preset's BLANK background through
the real engine paths (no user images involved).

Two shots per transition demo: shot A settled content, shot B carries the
transition label (engine semantics: a transition belongs to the NEXT shot), so
the XF window lands at tA - XF .. tA and every thumbnail shows the move.
Camera demos bake the pan into one long shot — CAM vectors are pixel offsets on
the overscanned base, so they need an image; the gallery generates a cheap
procedural gradient+grid base per preset once (never touches media/, never
touches golden-hash scope: builds its own small Engines like style previews).

Lazy + cached forever under output/_animgallery/<anim_id>.webp (keyed by preset
id too, so switching presets re-renders). Generation is synchronous per anim —
the UI opens the pane lazily and fills tiles as they arrive."""

import hashlib
import io
import json
import os

from PIL import Image, ImageDraw

from core.engine import Engine, load_preset

GALLERY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", "_animgallery")

# CapCut-style category rail — ids are the engine's own transition/cam names.
ANIM_CATEGORIES = [
    {"id": "favorites", "label": "Favorites",
     "items": ["fade", "wipe_left", "slideL", "whip", "pushin"]},
    {"id": "wipes", "label": "Wipes", "items": ["wipe_left", "wipe_up"]},
    {"id": "slides", "label": "Slides", "items": ["slideL", "slideR"]},
    {"id": "transitions", "label": "Transitions",
     "items": ["cut", "fade", "whip", "flashdip"]},
    {"id": "camera", "label": "Camera",
     "items": ["pushin", "pushin2", "pushout", "panup", "pandown", "pandiag"]},
]

ANIM_LABELS = {
    "cut": "Cut", "fade": "Fade", "wipe_left": "Wipe \u2192", "wipe_up": "Wipe \u2191",
    "slideL": "Slide from left", "slideR": "Slide from right",
    "whip": "Whip pan", "flashdip": "Flash dip",
    "pushin": "Push in", "pushin2": "Push in, deep", "pushout": "Pull out",
    "panup": "Pan up", "pandown": "Pan down", "pandiag": "Diagonal pan",
}

# validate_project floors width/height at 320: render tiles at 360x640 and
# downscale to 270x480 for the grid (LANCZOS down keeps text crisp)
TILE_W, TILE_H = 270, 480
RENDER_W, RENDER_H = 540, 960
TRANS_FPS = 30          # denser sampling of the XF window (validate gates fps 24/30)
CAM_FPS = 24            # 2.5s pan sweep -> 60 frames
WEBP_MS = {"trans": 1000 // TRANS_FPS, "cam": 1000 // CAM_FPS}


def _demo_captions():
    """A and B get the SAME caption text: the transition itself (edge sweep,
    slide offset, dip) must be what changes between frames, not the words —
    with different words every move reads as a text swap. at=0.45: A's text is
    fully entered (entry anim 0.32s) BEFORE the XF window opens at tA-XF=0.65,
    and B's own-clock render at window start (p*OV ~ 0.18s) is still mid-entry —
    so B content grows left-to-right under the wipe edge instead of pre-popping
    before it (probe: at=0.05 made B fully settled = invisible sweep)."""
    a = [{"kind": "title_block", "at": 0.10, "text": "CUT TO"},
         {"kind": "cta", "at": 0.10, "text": "THE MOVE"}]
    b = [{"kind": "title_block", "at": 0.10, "text": "CUT TO"},
         {"kind": "cta", "at": 0.10, "text": "THE MOVE"}]
    return a, b


def _gallery_preset(preset):
    """Gallery-local preset copy: raise xf so the transition window spans ~12
    frames at TRANS_FPS — a 0.5s window is 12 frames in a real video but only
    6 here, too fast to read on a looping thumbnail. Engine reads xf from the
    preset dict (engine.py self.XF); presets themselves stay untouched."""
    P = load_preset(preset) if isinstance(preset, str) else dict(preset)
    P = dict(P)
    P["xf"] = 0.55
    return P


def _cam_base(preset):
    """Procedural gradient+grid base image sized like the Engine's overscanned
    base, so pan/zoom crops actually move pixels. Built once per preset."""
    from core.engine import hex2rgb
    eng_bg = hex2rgb(preset["colors"]["bg"])
    acc = hex2rgb(preset["colors"]["accent"])
    w, h = 380, 676                      # 270*1.35 x 480*1.35-ish (overscan headroom)
    img = Image.new("RGB", (w, h))
    top = tuple(min(255, c + 46) for c in eng_bg)
    for y in range(h):
        t = y / h
        img.paste(tuple(int(top[i] * (1 - t) + eng_bg[i] * t) for i in range(3)),
                  (0, y, w, y + 1))
    dr = ImageDraw.Draw(img, "RGBA")
    step = max(48, w // 7)              # coarse blocks: motion reads at tile scale
    for gy in range(0, h + 1, step):    # horizon-ish grid: pans become visible
        dr.line((0, gy, w, gy), fill=(acc[0], acc[1], acc[2], 90), width=3)
    for gx in range(0, w + 1, step):
        dr.line((gx, 0, gx, h), fill=(acc[0], acc[1], acc[2], 60), width=2)
    r = w // 4                          # big disc: zoom/pan direction unmistakable
    cx, cy = w // 2, int(h * 0.38)
    dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(acc[0], acc[1], acc[2], 150))
    return img


def _anim_frames(anim_id, preset):
    """Render the demo frames for one animation through the real Engine."""
    W, H = RENDER_W, RENDER_H
    P = _gallery_preset(preset)
    capA, capB = _demo_captions()
    if anim_id == "cut":
        # hard switch mid-clip: A settles, B enters with its own pop so the
        # frame visibly JUMPS at tA (no blend window exists for a cut)
        fps, tA, tB = TRANS_FPS, 1.0, 0.6
        capB = [{"kind": "title_block", "at": 0.10, "text": "CUT TO"},
                {"kind": "cta", "at": 0.35, "text": "THE MOVE"}]
        proj = {"schema": 1, "name": "anim", "target": tA + tB, "fps": fps,
                "width": W, "height": H, "shots": [
                    {"t": tA, "transition": "cut", "captions": capA},
                    {"t": tB, "transition": "cut", "captions": capB}]}
        eng = Engine(proj, preset=P)
        frames = [eng.compose_frame(i) for i in range(eng.N)]
    elif anim_id in ("fade", "wipe_left", "wipe_up", "slideL", "slideR", "whip", "flashdip"):
        # window = tA-XF .. tA (the move itself). validate floors shot length
        # at 0.5s; pad B after the window, crop frames to end AT tA.
        # ENGINE SEMANTICS (compose_frame): XF is zeroed when SHOT A's own label
        # is cut/none — a "cut" on A kills the outgoing window entirely (probe:
        # fired=[] with A=cut, fired=all-window with A=fade). So A carries a
        # non-cut label; B carries the demoed anim_id, which governs the blend.
        fps, tA, tB = TRANS_FPS, 1.2, 0.5
        proj = {"schema": 1, "name": "anim", "target": tA + tB, "fps": fps,
                "width": W, "height": H, "shots": [
                    {"t": tA, "transition": "fade", "captions": capA},
                    {"t": tB, "transition": anim_id, "captions": capB}]}
        eng = Engine(proj, preset=P)
        # crop to the XF window (the move itself): transition label on shot B
        # governs BOTH boundaries of A|B (engine.py compose_frame)
        xfw = min(eng.XF, tA - 1e-6)
        i0 = max(0, int((tA - xfw) * fps))
        i1 = min(eng.N, int(round(tA * fps)))   # last visible frame of A's window
        frames = [eng.compose_frame(i) for i in range(i0, i1)]
    elif anim_id in ("pushin", "pushin2", "pushout", "panup", "pandown", "pandiag"):
        fps, tS = CAM_FPS, 2.5
        # no image key: Engine renders a flat BG and camera offsets do nothing.
        # Bake the pan/zoom crop into our own frames instead (same CAM vector +
        # easing math as render_layer), then draw preset captions on top via the
        # real Engine path so tiles look like finished output.
        from core.engine import cam_name, ease_io
        proj = {"schema": 1, "name": "anim", "target": tS, "fps": fps,
                "width": W, "height": H, "shots": [
                    {"t": tS, "transition": "cut", "captions": capA}]}
        eng = Engine(proj, preset=P)
        base = _cam_base(preset).resize((eng.BW, eng.BH), Image.LANCZOS)
        px, py = eng.CAM.get(anim_id, (0, 0))
        frames = []
        for idx in range(eng.N):
            lt = idx / float(fps)
            z = eng.track(lt)
            p = ease_io(min(1.0, lt / tS))
            cx, cy = eng.BW / 2 + px * p, eng.BH / 2 + py * p
            cw, ch = int(eng.BW / z), int(eng.BH / z)
            x0 = int(max(0, min(eng.BW - cw, cx - cw / 2)))
            y0 = int(max(0, min(eng.BH - ch, cy - ch / 2)))
            img = base.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS)
            # real caption path: reuse render_layer's caption drawing by feeding
            # our composited base as the shot's image base and dim=0.
            eng.bases["_baked"] = img
            eng.shots[0]["image"] = "_baked"
            eng.shots[0]["dim"] = 0.0
            frames.append(eng.compose_frame(idx))
    else:
        raise ValueError("unknown animation id: %s" % anim_id)
    if (W, H) != (TILE_W, TILE_H):
        frames = [f.resize((TILE_W, TILE_H), Image.LANCZOS) for f in frames]
    return frames, fps


def gallery_manifest(preset):
    try:
        load_preset(preset)
    except Exception as e:
        raise ValueError("unknown preset: %s" % e)
    cats = []
    for cat in ANIM_CATEGORIES:
        items = []
        for a in cat["items"]:
            key = "%s__%s" % (preset, a)
            h = hashlib.sha256(json.dumps([key, a], sort_keys=True).encode()).hexdigest()[:12]
            fname = "anim_%s.webp" % h
            items.append({"id": a, "label": ANIM_LABELS.get(a, a),
                          "kind": "camera" if a in ("pushin", "pushin2", "pushout",
                                                    "panup", "pandown", "pandiag") else "transition",
                          "url": "/output/_animgallery/" + fname,
                          "ready": os.path.exists(os.path.join(GALLERY_DIR, fname))})
        cats.append({"id": cat["id"], "label": cat["label"], "items": items})
    return {"categories": cats, "preset": preset}


def generate_gallery(preset):
    """Render every missing tile for this preset. Synchronous (caller runs it in
    a thread). Idempotent: existing webp files are kept forever. Tiles render
    once per unique anim id per preset; the manifest repeats them across
    categories sharing an item (Favorites) without re-rendering."""
    manifest = gallery_manifest(preset)
    P = load_preset(preset)
    os.makedirs(GALLERY_DIR, exist_ok=True)
    made = 0
    done = set()
    for cat in manifest["categories"]:
        for it in cat["items"]:
            path = os.path.join(GALLERY_DIR, it["url"].rsplit("/", 1)[1])
            if path in done:
                continue
            done.add(path)
            if os.path.exists(path):
                continue
            frames, fps = _anim_frames(it["id"], P)
            buf = io.BytesIO()
            frames[0].save(buf, format="WEBP", save_all=True,
                           append_images=frames[1:], duration=1000 // fps,
                           loop=0, quality=80)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(buf.getvalue())
            os.replace(tmp, path)      # atomic: UI never sees a half-written webp
            made += 1
    return manifest, made
