"""LEEBKIT server — FastAPI app serving the UI + /api/* endpoints. Offline:
binds 127.0.0.1 only, zero network calls."""
import json
import os
import shutil
import asyncio

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import time as _time

from core.engine import Engine, load_preset, validate_project
from core import audio as A
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
                 if f.startswith(("strip_", "anim_", "vo_", "music_"))]
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
    return Engine(proj, media_dir=os.path.join(ROOT, "media"))


# ------------------------------------------------------------------ meta APIs
@app.get("/api/meta")
def meta():
    presets = [{"id": f[:-5], "label": load_preset(f).get("name", f[:-5])}
               for f in sorted(os.listdir(os.path.join(ROOT, "presets"))) if f.endswith(".json")]
    music = [{"id": m if isinstance(m, str) else m["id"], "procedural": m["id"] in A.BEDS}
             for m in (A.scan_music() or ["synthwave", "pulse"])
             for m in [dict(m) if isinstance(m, dict) else {"id": m}]]
    return {"presets": presets, "music": music, "voices": A.list_voices(),
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
    rel = os.path.relpath(dest, ROOT).replace("\\", "/")
    return {"path": rel, "url": "/" + rel}


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
    scratch = VOPREV_DIR
    os.makedirs(scratch, exist_ok=True)
    _prune_cache(scratch)
    try:
        dur, path = A.vo_duration(text, voice, scratch)
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
    try:
        j = QUEUE.submit(proj, media_dir=os.path.join(ROOT, "media"))
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
    for f in sorted(os.listdir(od), reverse=True):
        if f.endswith(".mp4") and f not in ignored:
            out.append({"file": f, "url": "/output/" + f,
                        "size": os.path.getsize(os.path.join(od, f))})
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
    names = [f for f in os.listdir(od) if f.endswith(".mp4")]
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


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "ui", "index.html"))
