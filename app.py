"""LEEBKIT server — FastAPI app serving the UI + /api/* endpoints. Offline:
binds 127.0.0.1 only, zero network calls."""
import json
import os
import shutil
import asyncio
import hashlib
import io
import logging

from PIL import Image

log = logging.getLogger("reelkit")

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import time as _time

from core.engine import Engine, load_preset, validate_project
from core import audio as A
from core import generators as G
from core.checks import storyboard_strip, check_project
from core.queue import QUEUE, QueueFull, ROOT

app = FastAPI(title="LEEBKIT by LEEBLAAB")

UPLOAD_DIR = os.path.join(ROOT, "media", "uploads")
PROJECTS_DIR = os.path.join(ROOT, "projects")
PREVIEW_DIR = os.path.join(ROOT, "output", "_previews")
VOPREV_DIR = os.path.join(ROOT, "output", "_voprev")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)

PREVIEW_MAX = 200   # prune preview caches (audit #7: they grew forever)


def _prune_cache(d, keep=PREVIEW_MAX):
    """Keep the newest `keep` files in a preview cache dir; delete the rest.
    Cheap (listdir+stat) and runs at most once per preview request."""
    try:
        names = [f for f in os.listdir(d)
                 if f.startswith(("strip_", "anim_", "vo_", "music_", "style_", "genprev_"))]
    except OSError:
        return
    if len(names) <= keep:
        return
    paths = [(os.path.getmtime(os.path.join(d, f)), f) for f in names]
    paths.sort()
    for _, f in paths[:len(names) - keep]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass


def _proj_engine(proj):
    # normalize legacy/absolute image paths BEFORE Engine loads them (Engine
    # itself never calls validate; every app path goes through here)
    try:
        validate_project(proj)
    except ValueError:
        pass  # surface real schema errors at the normal gate, not this one
    return Engine(proj, media_dir=os.path.join(ROOT, "media"))


# ------------------------------------------------------------------ meta APIs
@app.get("/api/meta")
def meta():
    presets = [{"id": f[:-5], "label": load_preset(f).get("name", f[:-5])}
               for f in sorted(os.listdir(os.path.join(ROOT, "presets"))) if f.endswith(".json")]
    # C4e obs #2 (Yasser): the dropdown showed raw ids/file names — pass the
    # friendly label from scan_music through to the UI.
    music = [{"id": m if isinstance(m, str) else m["id"],
              "label": (m.get("label") or m["id"]) if isinstance(m, dict) else m,
              "procedural": (m if isinstance(m, str) else m["id"]) in A.BEDS}
             for m in (A.scan_music() or ["synthwave", "pulse"])
             for m in [dict(m) if isinstance(m, dict) else {"id": m}]]
    return {"presets": presets, "music": music, "voices": A.list_voices(),
            # v1.36 obs #2: ship each generator preset's designed palette so the
            # UI picker can show colour chips — the user could not tell what a
            # gen shot would look like before rendering it.
            "generators": [{"id": k, "label": v["label"], "palette": list(v["palette"])}
                           for k, v in G.GEN_PRESETS.items()],
            "piper_ready": bool(A.piper_available() and len(A.list_voices()) > 1)}


@app.get("/api/images")
def images():
    out = []
    for root, _, files in os.walk(os.path.join(ROOT, "media")):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                rel = os.path.relpath(os.path.join(root, f), ROOT).replace("\\", "/")
                out.append(rel)
    return {"images": sorted(out)}


MAX_UPLOAD_BYTES = 32 * 1024 * 1024  # 32 MB cap (A2 hardening)


def _sniff_image(head):
    """Magic-byte check: png/jpeg/webp only, regardless of filename."""
    if head.startswith(b"\x89PNG" + b"\x0d\x0a\x1a\x0a"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return False


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(400, "image only (png/jpg/webp)")
    safe = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    dest = os.path.join(UPLOAD_DIR, safe)
    n = 1
    base, ext = os.path.splitext(safe)
    while os.path.exists(dest):
        dest = os.path.join(UPLOAD_DIR, "%s_%d%s" % (base, n, ext))
        n += 1
    # stream with size cap + content sniffing: no oversized uploads, and the
    # bytes must actually be a png/jpeg/webp image (A2 hardening)
    head = await file.read(16)
    if not _sniff_image(head):
        raise HTTPException(400, "file contents are not a png/jpeg/webp image")
    total = len(head)
    with open(dest + ".part", "wb") as f:
        f.write(head)
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(dest + ".part")
                raise HTTPException(413, "image too large (max %d MB)"
                                    % (MAX_UPLOAD_BYTES // (1024 * 1024)))
            f.write(chunk)
    os.replace(dest + ".part", dest)
    # media-relative (v1.2 convention): Engine joins paths onto media_dir, so
    # ROOT-relative ("media/uploads/x.png") silently double-prefixed and every
    # render/storyboard died with "outside media dir" (live-test bug 4/3b).
    # Base MUST be media_dir (Engine's root), not UPLOAD_DIR — uploads live in
    # the uploads/ subdir, so relpath from UPLOAD_DIR dropped it and images
    # resolved to media/img_x.png (missing) -> corrupted preview + ENOENT render.
    rel = os.path.relpath(dest, os.path.join(ROOT, "media")).replace("\\", "/")
    return {"path": rel, "url": "/media/" + rel}


def _sniff_audio(head):
    """Magic-byte check for the four accepted music formats (mirrors the
    _sniff_image hardening on /api/upload)."""
    if head[:3] == b"ID3" or (head and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return True                                   # mp3 (tagged / raw frame)
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return True                                   # wav
    if head[4:8] == b"ftyp":
        return True                                   # m4a (iso-bmff)
    if head[:4] == b"OggS":
        return True                                   # ogg
    return False


@app.post("/api/music_upload")
async def music_upload(file: UploadFile = File(...)):
    """C4e obs #2 (Yasser): optional user music — upload a bed below the Music
    picker. Same hardening as /api/upload: safe name, size cap, content
    sniffing; lands in core.audio.MUSIC_DIR so scan_music picks it up and the
    /music mount can audition it."""
    if not file.filename.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
        raise HTTPException(400, "audio only (mp3/wav/m4a/ogg)")
    safe = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    if not safe or safe.startswith("."):
        raise HTTPException(400, "bad file name")
    os.makedirs(A.MUSIC_DIR, exist_ok=True)
    dest = os.path.join(A.MUSIC_DIR, safe)
    n = 1
    base, ext = os.path.splitext(safe)
    while os.path.exists(dest):
        dest = os.path.join(A.MUSIC_DIR, "%s_%d%s" % (base, n, ext))
        n += 1
    head = await file.read(16)
    if not _sniff_audio(head):
        raise HTTPException(400, "file contents are not a mp3/wav/m4a/ogg audio file")
    total = len(head)
    with open(dest + ".part", "wb") as f:
        f.write(head)
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(dest + ".part")
                raise HTTPException(413, "audio too large (max %d MB)"
                                    % (MAX_UPLOAD_BYTES // (1024 * 1024)))
            f.write(chunk)
    os.replace(dest + ".part", dest)
    name = os.path.basename(dest)
    return {"id": "file:" + name, "url": "/music/" + name}


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def projects():
    out = []
    for f in sorted(os.listdir(PROJECTS_DIR)):
        if f.endswith(".json"):
            try:
                p = json.load(open(os.path.join(PROJECTS_DIR, f), encoding="utf-8"))
                out.append({"file": f, "name": p.get("name", f), "target": p.get("target")})
            except Exception:
                pass
    return {"projects": out}


# ------------------------------------------------- templates gallery (v1.4 C4b)
from core import templates as TPL


@app.get("/api/templates")
def templates():
    """Curated starter skeletons shipped in templates/ (committed product
    content — unlike projects/*.json which stay gitignored save-files)."""
    return {"templates": TPL.list_templates()}


@app.get("/api/template/{fname}")
def get_template(fname: str):
    try:
        return TPL.load_template(fname)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/project/{fname}")
def get_project(fname):
    p = os.path.join(PROJECTS_DIR, os.path.basename(fname))
    if not os.path.exists(p):
        raise HTTPException(404, "no such project")
    return json.load(open(p, encoding="utf-8"))


@app.post("/api/project")
def save_project(proj: dict):
    try:
        validate_project(proj)
    except ValueError as e:
        raise HTTPException(422, str(e))
    name = "".join(c for c in proj.get("name", "untitled") if c.isalnum() or c in "._- ")
    path = os.path.join(PROJECTS_DIR, (name or "untitled") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2)
    return {"file": os.path.basename(path)}


# ---------------------------------------------------------------- preview/VO
@app.post("/api/preview")
async def preview(proj: dict):
    """Storyboard strip + the four auto-red-flags. Target <10s.
    Pillow work runs off the event loop (audit #6 second half) so a storyboard
    render never freezes websocket pushes or other requests."""
    return await asyncio.to_thread(_preview_sync, proj)


def _preview_sync(proj: dict):
    try:
        eng = _proj_engine(proj)
    except Exception as e:
        raise HTTPException(422, str(e))
    import hashlib
    h = hashlib.sha256(json.dumps(proj, sort_keys=True).encode()).hexdigest()[:12]
    out_png = os.path.join(PREVIEW_DIR, "strip_%s.png" % h)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    _prune_cache(PREVIEW_DIR)
    flags = storyboard_strip(eng, out_png)
    return {"strip": "/output/_previews/strip_%s.png" % h, "flags": flags}


@app.post("/api/anim_preview")
async def anim_preview(proj: dict):
    """One-frame render of a single-shot mini project (built by the UI) frozen
    at proj['_peek'] local seconds — shows exactly how a caption animation looks
    mid-in. The _peek key is stripped before Engine validation. Pillow work runs
    off the event loop (audit #6 second half)."""
    return await asyncio.to_thread(_anim_preview_sync, proj)


def _anim_preview_sync(proj: dict):
    peek = float(proj.pop("_peek", 0.0) or 0.0)
    # the preview shows the ANIMATION, not the photo: drop shot images so it
    # renders on the preset background and works even when the user's image
    # files are missing/moved (live-test bug 2: no black-frame abort here)
    for s in proj.get("shots", []):
        if s.get("image"):
            s["image"] = ""
            s.setdefault("dim", 0.0)
    try:
        eng = _proj_engine(proj)
    except Exception as e:
        raise HTTPException(422, str(e))
    import hashlib
    h = hashlib.sha256(json.dumps([proj, peek], sort_keys=True).encode()).hexdigest()[:12]
    out_png = os.path.join(PREVIEW_DIR, "anim_%s.png" % h)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    _prune_cache(PREVIEW_DIR)
    if not os.path.exists(out_png):
        eng.render_layer(0, peek, 7).save(out_png)
    return {"img": "/output/_previews/anim_%s.png" % h}


# ------------------------------------------------- style previews (v1.3 F slot)
_STYLE_SAMPLE = os.path.join(ROOT, "samples", "promo_v12.json")
STYLEPREV_DIR = os.path.join(ROOT, "output", "_styleprev")


def _style_preview_sync(preset: str):
    """One animated WebP per preset: three boundary frames of the sample promo
    rendered at HALF resolution THROUGH build_layout (a real 540x960 Engine —
    layout math identical to full res, never downscale-after-render). Frames:
    settled title beat, wipe-in mid-transition, settled panel beat. Animated
    webp, NOT gif: the 256-color palette bands cyan-on-black gradients.

    In-process off the event loop (to_thread), like every other preview route:
    a bounded mp sub-job is deliberately skipped — with one queue worker it
    would only delay real renders for a 3-frame job. Out of golden-hash scope
    by design (docs/v1.3_plan.md): builds its own half-res Engines, never
    touches the render pipeline."""
    try:
        P = load_preset(preset)   # confined to presets/ by load_preset
    except Exception as e:
        raise HTTPException(404, "unknown preset: %s" % e)
    proj = json.load(open(_STYLE_SAMPLE, encoding="utf-8"))
    proj["width"], proj["height"] = 540, 960
    try:
        eng = Engine(proj, preset=P, media_dir=os.path.join(ROOT, "samples", "media"))
    except Exception as e:
        raise HTTPException(422, str(e))
    # boundary picks (fps 30; shot starts 0/90/180/270, XF=0.5s): f45 settled
    # title beat in shot0; f135 mid wipe_left INTO shot2 (both title blocks +
    # chips visible); f330 settled CTA beat in shot3 (accent word + URL pill).
    # NOTE: early lt values inside a transition window draw NO text (outgoing
    # layer is frozen-fading, incoming captions wait for their own `at`) —
    # pick settled or mid-window frames where overlays are actually on screen.
    picks = (45, 135, 330)
    frames = [eng.compose_frame(i) for i in picks]
    # frame indices are part of the key so changing picks busts the cache
    h = hashlib.sha256(json.dumps([preset, proj["shots"], list(picks)], sort_keys=True).encode()).hexdigest()[:12]
    os.makedirs(STYLEPREV_DIR, exist_ok=True)
    _prune_cache(STYLEPREV_DIR)
    out_path = os.path.join(STYLEPREV_DIR, "style_%s.webp" % h)
    if not os.path.exists(out_path):
        buf = io.BytesIO()
        frames[0].save(buf, format="WEBP", save_all=True,
                       append_images=frames[1:], duration=[900, 500, 1400],
                       loop=0, quality=82)
        with open(out_path, "wb") as f:
            f.write(buf.getvalue())
    return {"url": "/output/_styleprev/style_%s.webp" % h,
            "frames": [45, 135, 300], "size": "540x960"}


@app.get("/api/style_preview/{preset}")
async def style_preview(preset: str):
    return await asyncio.to_thread(_style_preview_sync, preset)


# ------------------------------------------------- animation gallery (v1.35)
from core import anim_gallery as AG

# audit #7 (v1.31): one in-flight gallery build per preset. The old handler
# `await`ed the full ~12s render inline, so every browser poll while a build
# ran stacked ANOTHER full to_thread render — N tabs = N concurrent ffmpeg-free
# but CPU-heavy tile renders on a laptop. Now: first caller kicks a background
# task (returns the manifest with 'generating' placeholders immediately), and
# concurrent callers piggyback on the single in-flight task instead of stacking.
_GALLERY_TASKS: dict = {}


def _gallery_task(preset):
    t = _GALLERY_TASKS.get(preset)
    if t is not None and not t.done():
        return t

    async def _build():
        try:
            await asyncio.to_thread(AG.generate_gallery, preset)
        except Exception as e:
            # audit v1.36 (live-test obs #1): the bare `pass` made a broken
            # gallery size invisible — tiles sat on "rendering..." forever with
            # no trace. Log loudly; UI still shows placeholders next poll.
            log.warning("anim gallery build failed for %s: %s", preset, e)

    t = asyncio.create_task(_build())
    _GALLERY_TASKS[preset] = t
    return t


# ------------------------------------------------- generator picker previews (v1.36 obs #2)
GENPREV_DIR = os.path.join(ROOT, "output", "_genprevs")


def _gen_previews_sync():
    """One 2-frame looping webp per generator preset, rendered on the actual
    engine path (render_base + output-res grain via composite_grain — same code
    a real gen shot takes), with a caption panel overlaid so the picker shows
    what the shot will actually look like. Cached forever; 6 tiny files.
    Out of golden-hash scope by design (builds its own Engines)."""
    P = load_preset("leebdark.json")
    proj = {"schema": 1, "name": "genprev", "target": 3.0, "fps": 24,
            "width": 720, "height": 1280,   # C1 tier whitelist: portrait must be tier-legal
            "shots": [{"t": 3.0, "transition": "cut",
                       "captions": [{"kind": "title_block", "at": 0.10,
                                     "text": "WHAT THIS LOOKS LIKE"}],
                       "vo": ""}]}
    os.makedirs(GENPREV_DIR, exist_ok=True)
    _prune_cache(GENPREV_DIR)
    out = {}
    for gid in G.GEN_PRESETS:
        p2 = json.loads(json.dumps(proj))
        p2["shots"][0]["fill"] = "gen:" + gid
        p2["shots"][0]["motion"] = "normal"
        eng = Engine(p2, preset=P)   # fps 24 -> frames 36/72 = 1.5s/3.0s
        frames = [eng.compose_frame(i).resize((360, 640), Image.LANCZOS)
                  for i in (36, 72)]
        h = hashlib.sha256(json.dumps([gid, p2], sort_keys=True).encode()).hexdigest()[:12]
        path = os.path.join(GENPREV_DIR, "genprev_%s.webp" % h)
        if not os.path.exists(path):
            buf = io.BytesIO()
            frames[0].save(buf, format="WEBP", save_all=True,
                           append_images=frames[1:], duration=[1300, 1300],
                           loop=0, quality=80)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(buf.getvalue())
            os.replace(tmp, path)    # atomic (same rule as anim gallery tiles)
        out[gid] = "/output/_genprevs/genprev_%s.webp" % h
    return out


@app.get("/api/gen_previews")
async def gen_previews():
    """Animated thumb per generator preset for the shot-card picker grid."""
    try:
        return {"thumbs": await asyncio.to_thread(_gen_previews_sync)}
    except Exception as e:
        raise HTTPException(422, str(e))


@app.get("/api/anim_gallery/{preset}")
async def anim_gallery(preset: str):
    """Manifest of CapCut-style looping webp tiles for every transition/camera
    move on this preset's blank background. Tiles are cached forever under
    output/_animgallery (StaticFiles serves them at /output/_animgallery/...);
    missing ones render in the background after the manifest returns, so pane
    open is instant and tiles pop in as they arrive (~12s for all 14)."""
    try:
        manifest = AG.gallery_manifest(preset)   # raises ValueError on bad preset
    except Exception as e:
        raise HTTPException(404, "unknown preset: %s" % e)
    missing = any(not it["ready"] for c in manifest["categories"] for it in c["items"])
    if missing:
        _gallery_task(preset)   # single in-flight build per preset (audit #7)
    return AG.gallery_manifest(preset)


@app.post("/api/vo_preview")
async def vo_preview(req: dict):
    # piper subprocess (up to ~60s) must never block the event loop; the
    # semaphore keeps 4+ concurrent syntheses from swamping a laptop CPU (#6).
    async with _VO_SEM:
        return await asyncio.to_thread(_vo_preview_sync, req)


_VO_SEM = asyncio.Semaphore(2)


def _vo_preview_sync(req: dict):
    text, voice = req.get("text", "").strip(), req.get("voice", "")
    if not text or not voice or voice == "none":
        raise HTTPException(400, "need text + voice")
    try:  # v1.4 C2: carry the project speed into the preview cache too
        vspeed = float(req.get("speed", 1.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "speed must be a number")
    if not (A.VO_SPEED_RANGE[0] <= vspeed <= A.VO_SPEED_RANGE[1]):
        raise HTTPException(400, "speed must be within %.2f-%.2f"
                            % (A.VO_SPEED_RANGE[0], A.VO_SPEED_RANGE[1]))
    scratch = VOPREV_DIR
    os.makedirs(scratch, exist_ok=True)
    _prune_cache(scratch)
    try:
        dur, path = A.vo_duration(text, voice, scratch, speed=vspeed)
    except Exception as e:
        raise HTTPException(500, str(e))
    rel = "/output/_voprev/" + os.path.basename(path)
    return {"url": rel, "duration": round(dur, 2)}


@app.post("/api/music_preview")
async def music_preview(req: dict):
    """8-second audition of a procedural bed (numpy synth + wav write off-loop)."""
    return await asyncio.to_thread(_music_preview_sync, req)


def _music_preview_sync(req: dict):
    bed = req.get("bed", "synthwave")
    import numpy as np
    import wave
    fn = A.BEDS.get(bed)
    if not fn:
        raise HTTPException(400, "unknown bed")
    d = fn(8.0, [2.5, 5.0])
    pcm = (np.clip(d, -1, 1) * 32767).astype("<i2")
    p = os.path.join(ROOT, "output", "_voprev", "music_%s.wav" % bed)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(A.SR_OUT)
        w.writeframes(pcm.tobytes())
    return {"url": "/output/_voprev/music_%s.wav" % bed}


# ------------------------------------------------------------------- render
@app.post("/api/render")
def render(proj: dict):
    try:
        validate_project(proj)
    except ValueError as e:
        raise HTTPException(422, str(e))
    # v1.4 C5: optional share teaser format rides the job (caps enforced inside
    # encode_share from core.share_caps — GIF 640px/6s/12fps, WebP 960px/8s;
    # "GIF is a share teaser, not the master").
    fmt = (proj.pop("share_fmt", None) or "").lower().strip()
    if fmt and fmt not in ("gif", "webp"):
        raise HTTPException(422, "share_fmt must be 'gif' or 'webp' (got %r)" % fmt)
    try:
        j = QUEUE.submit(proj, media_dir=os.path.join(ROOT, "media"), share_fmt=fmt or None)
    except QueueFull as e:
        raise HTTPException(429, str(e))
    return {"job": j.snapshot()}


@app.post("/api/job/{job_id}/cancel")
def job_cancel(job_id: str):
    """Cancel a queued or running render (audit #3)."""
    if not QUEUE.cancel(job_id):
        raise HTTPException(404, "job %s not found or already finished" % job_id)
    return {"ok": True}


@app.get("/api/jobs")
def jobs():
    return {"jobs": QUEUE.snapshot()}


@app.get("/api/outputs")
def outputs():
    out = []
    od = os.path.join(ROOT, "output")
    ignored = _ignored_outputs(od)
    files = [f for f in os.listdir(od)
             if (f.endswith(".mp4") or f.endswith(".gif") or f.endswith(".webp"))
             and f not in ignored]
    # newest FIRST by modification time — the old reverse-alphabetical sort
    # buried fresh renders under older files (user: "the new video is never on top")
    files.sort(key=lambda f: os.path.getmtime(os.path.join(od, f)), reverse=True)
    for f in files:
        entry = {"file": f, "url": "/output/" + f,
                 "size": os.path.getsize(os.path.join(od, f))}
        # C5 share teasers ride beside their master in the listing (sorted by
        # mtime they land adjacent anyway); a teaser never shows without its mp4
        if not f.endswith(".mp4"):
            stem = os.path.splitext(f)[0]
            if not os.path.isfile(os.path.join(od, stem + ".mp4")):
                continue
        else:
            stem = f[:-4]
            for ext in (".gif", ".webp"):
                sib = stem + ext
                if os.path.isfile(os.path.join(od, sib)):
                    entry.setdefault("share", []).append(
                        {"file": sib, "url": "/output/" + sib,
                         "size": os.path.getsize(os.path.join(od, sib))})
        out.append(entry)
    return {"outputs": out}


# "Clear all" hides history entries from the UI listing ONLY — the MP4 files
# themselves are never deleted (Yasser was explicit about this).
def _ignored_outputs(od):
    p = os.path.join(od, ".history_ignore")
    try:
        with open(p, encoding="utf-8") as fh:
            return {l.strip() for l in fh if l.strip()}
    except OSError:
        return set()


@app.post("/api/outputs_clear")
def outputs_clear():
    od = os.path.join(ROOT, "output")
    os.makedirs(od, exist_ok=True)
    names = [f for f in os.listdir(od)
             if f.endswith(".mp4") or f.endswith(".gif") or f.endswith(".webp")]
    with open(os.path.join(od, ".history_ignore"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(_ignored_outputs(od) | set(names))) + "\n")
    return {"ok": True, "hidden": len(names)}


@app.websocket("/ws/progress")
async def progress(ws: WebSocket):
    await ws.accept()
    import asyncio
    try:
        while True:
            # push-based: the queue signals a condition var on every state change;
            # run the blocking wait in a thread so the event loop stays free
            # (was a hard 0.5s poll loop, audit #6)
            await asyncio.to_thread(QUEUE.wait_change, 2.0)
            await ws.send_json({"jobs": QUEUE.snapshot()})
    except (WebSocketDisconnect, RuntimeError):
        pass


# ---------------------------------------------------------------- static UI
app.mount("/assets", StaticFiles(directory=os.path.join(ROOT, "assets")), name="assets")
app.mount("/media", StaticFiles(directory=os.path.join(ROOT, "media")), name="media")
app.mount("/output", StaticFiles(directory=os.path.join(ROOT, "output")), name="output")
os.makedirs(os.path.join(ROOT, "music"), exist_ok=True)  # fresh install has no music/ — mounting a missing dir crashed startup
app.mount("/music", StaticFiles(directory=os.path.join(ROOT, "music")), name="music")


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "ui", "index.html"))
