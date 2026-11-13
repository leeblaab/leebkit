import json, hashlib, os, sys
sys.path.insert(0, '.')
from core.engine import Engine
proj = json.load(open('samples/promo_v12.json'))
proj['width'], proj['height'] = 1080, 1920
eng = Engine(proj, media_dir='samples/media')
out = {}
for idx in range(eng.N):
    if idx % 10: continue
    out["f%04d" % idx] = hashlib.sha256(eng.compose_frame(idx).tobytes()).hexdigest()[:16]
base = json.load(open('tests/golden/hashes-linux.json'))['frames']['promo_v12_1080x1920']
drift = sorted(k for k,v in out.items() if base.get(k) != v)
print("PROBE frames=%d drift=%d" % (len(out), len(drift)))
for k in drift[:6]: print("  drift:", k, "now", out[k], "base", base.get(k))
