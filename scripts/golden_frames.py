#!/usr/bin/env python3
"""Golden-frame harness (v1.3 C1). Renders a fixed corpus deterministically and
writes SHA-256 per frame to tests/golden/hashes.json. Zero engine changes; this
is the safety net for C2-C4 refactors.

Corpus:
  - samples/promo_v12.json in all three formats (9:16, 1:1, 16:9): ALL frames
    on the linux push gate; sampled (--sample N) subset to keep CI fast.
  - tests/golden/kinds_corpus.json: ONE synthetic multi-shot project carrying
    every caption kind in separate shots (one Engine build), at fixed progress
    points, in leebdark + neonlight x all three formats.
End-to-end leg: one real ffmpeg encode -> ffprobe nb_frames (the sequence-read
layer that frame-level hashing cannot exercise).

Usage:  python scripts/golden_frames.py [--update] [--sample N]
Exit 0 = match; 1 = mismatch/drift report; 2 = baseline missing (--update).
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.engine import Engine  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden")
BASELINE = os.path.join(GOLDEN, "hashes.json")
MEDIA = os.path.join(ROOT, "samples", "media")
FORMATS = [(1080, 1920), (1080, 1080), (1920, 1080)]


def sha(img):
    return hashlib.sha256(img.tobytes()).hexdigest()[:16]


def build(proj_path, w, h, preset=None):
    proj = json.load(open(proj_path, encoding="utf-8"))
    proj["width"], proj["height"] = w, h
    if preset:
        proj["preset"] = preset
    return Engine(proj, media_dir=MEDIA)


def hash_all(eng, sample=0):
    """frame-index -> hash for every frame (or every `sample`-th)."""
    out = {}
    for idx in range(eng.N):
        if sample and idx % sample:
            continue
        out["f%04d" % idx] = sha(eng.compose_frame(idx))
    return out


def hash_points(eng, points_per_shot=3):
    """frame-index -> hash at fixed local-time points per shot."""
    out = {}
    for i, s in enumerate(eng.shots):
        t = float(s["t"])
        for frac in (0.25, 0.6, 0.92):
            idx = int(round((eng.starts[i] + t * frac) * eng.FPS))
            idx = min(idx, eng.N - 1)
            out["shot%d@%.2f" % (i, frac)] = sha(eng.compose_frame(idx))
    return out


def encode_leg():
    """Real ffmpeg sequence read: N PNGs -> mp4 must probe nb_frames == N."""
    proj = {"schema": 1, "name": "gencode", "target": 1.0, "fps": 24,
            "width": 320, "height": 320,
            "shots": [{"t": 1.0, "transition": "cut", "captions": [
                {"kind": "title_block", "at": 0.2, "text": "GOLDEN"}]}]}
    eng = Engine(proj, media_dir=MEDIA)
    n = eng.N
    tmp = tempfile.mkdtemp(prefix="golden_enc_")
    try:
        for idx in range(n):
            eng.compose_frame(idx).save(os.path.join(tmp, "f_%04d.png" % idx))
        mp4 = os.path.join(tmp, "out.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "24",
                        "-i", os.path.join(tmp, "f_%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4],
                       check=True)
        pr = subprocess.run(["ffprobe", "-v", "error", "-count_frames",
                             "-select_streams", "v:0",
                             "-show_entries", "stream=nb_read_frames",
                             "-of", "default=nw=1:nk=1", mp4],
                            capture_output=True, text=True)
        got = int(pr.stdout.strip())
        return got == n, "encode nb_read_frames=%d expected=%d" % (got, n)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def build_corpus(sample=0):
    corpus = {}
    promo = os.path.join(ROOT, "samples", "promo_v12.json")
    for w, h in FORMATS:
        eng = build(promo, w, h)
        corpus["promo_v12_%dx%d" % (w, h)] = hash_all(eng, sample)
    kinds = os.path.join(GOLDEN, "kinds_corpus.json")
    for preset in ("leebdark", "neonlight"):
        for w, h in FORMATS:
            eng = build(kinds, w, h, preset=preset)
            corpus["kinds_%s_%dx%d" % (preset, w, h)] = hash_points(eng)
    return corpus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--sample", type=int, default=0,
                    help="hash every Nth promo frame (CI push gate)")
    a = ap.parse_args()

    corpus = build_corpus(sample=a.sample)
    ok_enc, enc_msg = encode_leg()

    if a.update:
        json.dump({"meta": {"sample": a.sample}, "frames": corpus},
                  open(BASELINE, "w", encoding="utf-8"), indent=1, sort_keys=True)
        print("baseline written: %s (%d entries)" %
              (BASELINE, sum(len(v) for v in corpus.values())))
        return 0 if ok_enc else 1

    if not os.path.exists(BASELINE):
        print("no baseline at %s — run with --update first" % BASELINE)
        return 2
    base = json.load(open(BASELINE, encoding="utf-8"))["frames"]
    # compare only the keys this invocation produced (sampled runs subset-match)
    drift, missing = [], []
    for key, frames in corpus.items():
        ref = base.get(key)
        if ref is None:
            missing.append(key)
            continue
        for fk, hx in frames.items():
            if fk in ref and ref[fk] != hx:
                drift.append("%s/%s" % (key, fk))
            elif fk not in ref:
                missing.append("%s/%s" % (key, fk))
    print("encode leg: %s (%s)" % ("PASS" if ok_enc else "FAIL", enc_msg))
    if drift or missing:
        print("DRIFT %d frames, MISSING %d keys:" % (len(drift), len(missing)))
        for d in drift[:25]:
            print("  changed:", d)
        for m in missing[:10]:
            print("  missing:", m)
        return 1
    n = sum(len(v) for v in corpus.values())
    print("GOLDEN PASS (%d frames match, %s)" % (n, enc_msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
