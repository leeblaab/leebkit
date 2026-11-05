"""REELKIT job queue — single background renderer with websocket-friendly progress.

One job at a time (simple). Progress = frames rendered / total, exposed via
get_jobs() polling or pushed to websocket clients by app.py.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

from .engine import Engine
from . import audio as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Job:
    def __init__(self, proj, media_dir):
        self.id = uuid.uuid4().hex[:10]
        self.proj = proj
        self.media_dir = media_dir
        self.name = proj.get("name", "project")
        self.state = "queued"          # queued|frames|encode|audio|mux|done|error
        self.frames_done = 0
        self.frames_total = int(round(float(proj["target"]) * proj.get("fps", 30)))
        self.error = None
        self.out = None
        self.started = time.time()

    def snapshot(self):
        return {"id": self.id, "name": self.name, "state": self.state,
                "frames_done": self.frames_done, "frames_total": self.frames_total,
                "pct": round(100.0 * self.frames_done / max(1, self.frames_total), 1),
                "error": self.error, "out": os.path.basename(self.out) if self.out else None}


class Queue:
    def __init__(self):
        self.jobs = []
        self.current = None
        self._lock = threading.Lock()

    def submit(self, proj, media_dir=None):
        with self._lock:
            j = Job(proj, media_dir or ROOT)
            self.jobs.append(j)
            t = threading.Thread(target=self._run, args=(j,), daemon=True)
            t.start()
            return j

    def _run(self, j):
        try:
            name = j.name + "_" + j.id[:6]
            out_dir = os.path.join(ROOT, "output")
            frames_dir = os.path.join(out_dir, "_frames_%s" % name)
            os.makedirs(frames_dir, exist_ok=True)
            eng = Engine(j.proj, media_dir=j.media_dir)
            j.state = "frames"
            for idx in range(j.frames_total):
                eng.compose_frame(idx).save(os.path.join(frames_dir, "f_%04d.jpg" % idx), quality=92)
                j.frames_done = idx + 1
            j.state = "encode"
            out_mp4 = os.path.join(out_dir, "%s.mp4" % name)
            wav = A.build_audio(j.proj, media_dir=j.media_dir,
                                scratch=os.path.join(out_dir, "_audio_%s" % name))
            j.state = "mux"
            cmd = ["ffmpeg", "-y", "-framerate", str(eng.FPS),
                   "-i", os.path.join(frames_dir, "f_%04d.jpg"),
                   "-i", wav,
                   "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                   "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart",
                   "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("ffmpeg: " + r.stderr[-600:])
            A.verify_durations(out_mp4, float(j.proj["target"]))   # hard gate
            shutil.rmtree(frames_dir, ignore_errors=True)
            j.out = out_mp4
            j.state = "done"
        except Exception as e:
            j.state = "error"
            j.error = str(e)

    def snapshot(self):
        return [j.snapshot() for j in self.jobs[-12:]]


QUEUE = Queue()
