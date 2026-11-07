"""LEEBKIT server — FastAPI app serving the UI + /api/* endpoints. Offline:
binds 127.0.0.1 only, zero network calls."""
import json
import os
import shutil

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.engine import Engine, load_preset, validate_project
from core import audio as A
from core.checks import storyboard_strip, check_project
from core.queue import QUEUE, ROOT

app = FastAPI(title="LEEBKIT by LEEBLAAB")

UPLOAD_DIR = os.path.join(ROOT, "media", "uploads")
PROJECTS_DIR = os.path.join(ROOT, "projects")
PREVIEW_DIR = os.path.join(ROOT, "output", "_previews")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)


def _proj_engine(proj):
    return Engine(proj, media_dir=ROOT)


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
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
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
def preview(proj: dict):
    """Storyboard strip + the four auto-red-flags. Target <10s."""
    try:
        eng = _proj_engine(proj)
    except Exception as e:
        raise HTTPException(422, str(e))
    import hashlib
    h = hashlib.sha256(json.dumps(proj, sort_keys=True).encode()).hexdigest()[:12]
    out_png = os.path.join(PREVIEW_DIR, "strip_%s.png" % h)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    flags = storyboard_strip(eng, out_png)
    return {"strip": "/output/_previews/strip_%s.png" % h, "flags": flags}


@app.post("/api/anim_preview")
def anim_preview(proj: dict):
    """One-frame render of a single-shot mini project (built by the UI) frozen
    at proj['_peek'] local seconds — shows exactly how a caption animation looks
    mid-in. The _peek key is stripped before Engine validation."""
    peek = float(proj.pop("_peek", 0.0) or 0.0)
    try:
        eng = _proj_engine(proj)
    except Exception as e:
        raise HTTPException(422, str(e))
    import hashlib
    h = hashlib.sha256(json.dumps([proj, peek], sort_keys=True).encode()).hexdigest()[:12]
    out_png = os.path.join(PREVIEW_DIR, "anim_%s.png" % h)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    if not os.path.exists(out_png):
        eng.render_layer(0, peek, 7).save(out_png)
    return {"img": "/output/_previews/anim_%s.png" % h}


@app.post("/api/vo_preview")
def vo_preview(req: dict):
    text, voice = req.get("text", "").strip(), req.get("voice", "")
    if not text or not voice or voice == "none":
        raise HTTPException(400, "need text + voice")
    scratch = os.path.join(ROOT, "output", "_voprev")
    os.makedirs(scratch, exist_ok=True)
    try:
        dur, path = A.vo_duration(text, voice, scratch)
    except Exception as e:
        raise HTTPException(500, str(e))
    rel = "/output/_voprev/" + os.path.basename(path)
    return {"url": rel, "duration": round(dur, 2)}


@app.post("/api/music_preview")
def music_preview(req: dict):
    """8-second audition of a procedural bed."""
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
    j = QUEUE.submit(proj, media_dir=ROOT)
    return {"job": j.snapshot()}


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
            await ws.send_json({"jobs": QUEUE.snapshot()})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass


# ---------------------------------------------------------------- static UI
app.mount("/assets", StaticFiles(directory=os.path.join(ROOT, "assets")), name="assets")
app.mount("/media", StaticFiles(directory=os.path.join(ROOT, "media")), name="media")
app.mount("/output", StaticFiles(directory=os.path.join(ROOT, "output")), name="output")


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "ui", "index.html"))
