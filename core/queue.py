"""LEEBKIT job queue — single background renderer with websocket-friendly progress.

One job at a time (simple): submissions go to a FIFO and one worker thread
renders them in order. Progress = frames rendered / total, exposed via
get_jobs() polling or pushed to websocket clients by app.py (condition-
variable push, no polling). Queue depth is capped, finished jobs are pruned,
and running jobs can be canceled (v1.2 audit #3/#6).
"""
import json
import os
import queue as _queue
import shutil
import subprocess
import threading
import time
import uuid

from .engine import Engine
from . import audio as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_QUEUED = 4          # jobs waiting beyond this are refused at submit (audit #3)
KEEP_FINISHED = 20      # finished/error/canceled jobs retained for UI history


class QueueFull(RuntimeError):
    pass


# ---- parallel frame workers (module-level so mp.Pool can pickle them;
# mirrors render_cli's _worker_init/_worker_chunk shape) ----
_FW = {}


def _frame_worker_init(proj_path, media_dir):
    from .engine import Engine
    with open(proj_path, "r", encoding="utf-8") as f:
        _FW["eng"] = Engine(json.load(f), media_dir=media_dir)


def _frame_chunk(args):
    a, b, frames_dir = args
    for idx in range(a, b):
        # PNG intermediates: JPEG q92 -> crf 19 was lossy-then-lossy (audit #4)
        _FW["eng"].compose_frame(idx).save(os.path.join(frames_dir, "f_%04d.png" % idx))
    return b - a


class Job:
    def __init__(self, proj, media_dir):
        self.id = uuid.uuid4().hex[:10]
        self.proj = proj
        self.media_dir = media_dir
        self.name = proj.get("name", "project")
        self.state = "queued"      # queued|frames|encode|audio|mux|done|error|canceled
        self.frames_done = 0
        self.frames_total = int(round(float(proj["target"]) * proj.get("fps", 30)))
        self.error = None
        self.out = None
        self.cancel_requested = False
        self.started = time.time()

    def snapshot(self):
        # frames are ~85% of wall time; encode/mux get the tail so the bar
        # keeps moving after frames finish instead of sticking at 100%
        pct = round(85.0 * self.frames_done / max(1, self.frames_total), 1)
        if self.state == "encode":
            pct = max(pct, 90.0)
        elif self.state in ("audio", "mux"):
            pct = max(pct, 95.0)
        elif self.state == "done":
            pct = 100.0
        return {"id": self.id, "name": self.name, "state": self.state,
                "frames_done": self.frames_done, "frames_total": self.frames_total,
                "pct": pct,
                "error": self.error, "out": os.path.basename(self.out) if self.out else None}


class Queue:
    def __init__(self):
        self.jobs = []
        self.current = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)  # state-change signal for websockets
        self._pending = _queue.Queue()
        self._prune_stale_scratch()  # crash/interrupt debris from previous runs (audit hygiene)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    @staticmethod
    def _prune_stale_scratch():
        # a fresh worker owns no jobs yet, so any _frames_*/_audio_* dir at startup
        # is debris from a killed/crashed run. Deleting one pattern but not the
        # class was called out in the follow-up audit (hundreds of dirs piled up).
        out_dir = os.path.join(ROOT, "output")
        try:
            for name in os.listdir(out_dir):
                if name.startswith("_frames_") or name.startswith("_audio_"):
                    shutil.rmtree(os.path.join(out_dir, name), ignore_errors=True)
        except OSError:
            pass

    def submit(self, proj, media_dir=None):
        with self._cond:
            queued = sum(1 for j in self.jobs if j.state == "queued")
            if queued >= MAX_QUEUED:
                raise QueueFull("render queue is full (%d waiting) \u2014 cancel one or wait" % queued)
            # prune old finished jobs so self.jobs stays bounded (audit #3).
            # NOTE (audit Bug E): a live worker may still hold its Job object —
            # that's safe: pruning only rebinds the list, the Job itself stays
            # referenced by the worker and keeps updating state normally.
            self.jobs = [j for j in self.jobs
                         if j.state not in ("done", "error", "canceled")][-KEEP_FINISHED:]
            j = Job(proj, media_dir or ROOT)
            self.jobs.append(j)
        self._pending.put(j)
        with self._cond:
            self._cond.notify_all()
        return j

    def cancel(self, job_id):
        """Cancel a queued job outright; flag a running one so its frame loop
        aborts at the next frame boundary."""
        with self._cond:
            for j in self.jobs:
                if j.id == job_id:
                    if j.state == "queued":
                        j.state = "canceled"
                        j.error = "canceled before start"
                        self._cond.notify_all()
                        return True
                    if j.state in ("frames", "encode", "audio", "mux"):
                        j.cancel_requested = True
                        self._cond.notify_all()
                        return True
                    return False
        return False

    def wait_change(self, timeout=1.0):
        """Block until a job state changes \u2014 websocket push instead of 0.5s poll."""
        with self._cond:
            self._cond.wait(timeout=timeout)

    def _worker_loop(self):
        while True:
            j = self._pending.get()
            if j.state == "canceled":      # canceled while still queued
                continue
            self.current = j
            try:
                self._run(j)
            except BaseException as e:     # NEVER let one job kill the worker thread
                j.state = "error"          # (SystemExit et al. escape `except Exception`)
                j.error = "%s: %s" % (type(e).__name__, e)
            finally:
                self.current = None
                with self._cond:
                    self._cond.notify_all()

    def _run(self, j):
        frames_dir = None
        audio_dir = None
        try:
            name = j.name + "_" + j.id[:6]
            out_dir = os.path.join(ROOT, "output")
            frames_dir = os.path.join(out_dir, "_frames_%s" % name)
            audio_dir = os.path.join(out_dir, "_audio_%s" % name)
            shutil.rmtree(frames_dir, ignore_errors=True)   # fresh start; never reuse stale/empty dirs
            os.makedirs(frames_dir, exist_ok=True)
            eng = Engine(j.proj, media_dir=j.media_dir)
            j.state = "frames"
            with self._cond:
                self._cond.notify_all()
            jobs = max(1, min(8, os.cpu_count() or 1))
            if jobs > 1 and j.frames_total >= 60:
                # parallel frame render in the app too (audit #5): same chunked
                # mp.Pool shape as render_cli. Progress updates per chunk.
                import multiprocessing as mp
                proj_path = os.path.join(ROOT, "projects", "_queue_%s.json" % j.id)
                with open(proj_path, "w", encoding="utf-8") as fh:
                    json.dump(j.proj, fh)
                try:
                    # fixed small chunks (not total/jobs): a 45-frame chunk left the
                    # progress bar at 0% until ~8 big jumps (audit Bug C). Grain is
                    # seeded per frame index (random.Random(idx*7919)), so chunk size
                    # never changes output pixels — only progress granularity.
                    chunk = 8
                    ranges = [(a, min(a + chunk, j.frames_total), frames_dir)
                              for a in range(0, j.frames_total, chunk)]
                    done_acc = 0
                    with mp.Pool(jobs, initializer=_frame_worker_init,
                                 initargs=(proj_path, j.media_dir)) as pool:
                        for cnt in pool.imap_unordered(_frame_chunk, ranges):
                            done_acc += cnt
                            j.frames_done = done_acc
                            if j.cancel_requested:
                                # Bug D (frames phase): terminate then fall through
                                # to the post-loop cancel check below, which sets
                                # state and lets `finally` remove the partial frames.
                                pool.terminate()
                                break
                finally:
                    try:
                        os.remove(proj_path)
                    except OSError:
                        pass
            else:
                for idx in range(j.frames_total):
                    if j.cancel_requested:
                        j.state = "canceled"
                        j.error = "canceled at frame %d/%d" % (idx, j.frames_total)
                        shutil.rmtree(frames_dir, ignore_errors=True)
                        return
                    # PNG intermediates: JPEG q92 -> crf 19 was lossy-then-lossy (audit #4)
                    eng.compose_frame(idx).save(os.path.join(frames_dir, "f_%04d.png" % idx))
                    j.frames_done = idx + 1
            if j.cancel_requested:
                j.state = "canceled"
                j.error = "canceled before encode"
                shutil.rmtree(frames_dir, ignore_errors=True)
                return
            j.state = "encode"
            if j.cancel_requested:
                j.state = "canceled"
                j.error = "canceled before audio/encode"
                return
            out_mp4 = os.path.join(out_dir, "%s.mp4" % name)
            wav = A.build_audio(j.proj, media_dir=j.media_dir, scratch=audio_dir)
            if j.cancel_requested:
                # Bug D: cancel honors phase boundaries — encode itself is not
                # interruptible (ffmpeg mid-run), but we never *start* it.
                j.state = "canceled"
                j.error = "canceled before ffmpeg encode"
                return
            j.state = "mux"
            cmd = ["ffmpeg", "-y", "-framerate", str(eng.FPS),
                   "-i", os.path.join(frames_dir, "f_%04d.png"),
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
        finally:
            # audit Bug A: every exit path (error, cancel, done) removes scratch dirs.
            # the success path already rmtree'd frames; ignore_errors keeps that cheap.
            if frames_dir:
                shutil.rmtree(frames_dir, ignore_errors=True)
            if audio_dir:
                shutil.rmtree(audio_dir, ignore_errors=True)

    def snapshot(self):
        with self._lock:
            return [j.snapshot() for j in self.jobs[-12:]]


QUEUE = Queue()
