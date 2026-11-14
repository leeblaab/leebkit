"""C2 (v1.41) — S1 trust boundary: Host allowlist + WS Origin check.

Audit #1 S1: app.py binds 127.0.0.1 (good) but validated nothing about WHO
reaches it. A DNS-rebinding page in the user's own browser hits 127.0.0.1 with
a foreign Host header and rides the loopback trust straight into /api/render,
/api/upload, /api/projects. Fix: TrustedHostMiddleware (127.0.0.1/localhost/
[::1]) + reject foreign Origin on the /ws/progress handshake.

Starlette's TestClient sends Host "testserver" by default — every request here
sets an explicit Host so the gate is exercised, not bypassed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


try:
    from starlette.testclient import TestClient
except Exception as e:  # pragma: no cover
    print("SKIP (TestClient unavailable: %s)" % e)
    sys.exit(0)

import app as APP  # noqa: E402

HOSTS = {
    "loopback": {"host": "127.0.0.1:8735"},
    "localhost": {"host": "localhost:8735"},
    "rebound": {"host": "evil.example.com"},
    "attacker_ip": {"host": "93.184.216.34"},
}

c = TestClient(APP.app)

# --- Host allowlist -------------------------------------------------------
for label, hdrs in (("loopback", HOSTS["loopback"]), ("localhost", HOSTS["localhost"])):
    r = c.get("/api/meta", headers=hdrs)
    check("Host %s accepted (/api/meta 200)" % label, r.status_code == 200,
          "status=%d" % r.status_code)

for label, hdrs in (("rebound", HOSTS["rebound"]), ("attacker_ip", HOSTS["attacker_ip"])):
    r = c.get("/api/meta", headers=hdrs)
    check("Host %s rejected (400)" % label, r.status_code == 400,
          "status=%d" % r.status_code)

# the WRITE endpoints are what rebinding actually weaponizes — gate those too
for label, hdrs in (("rebound", HOSTS["rebound"]),):
    r = c.post("/api/project", json={"name": "c2probe", "project": {}},
               headers=hdrs)
    check("Host %s rejected on write path (400)" % label, r.status_code == 400,
          "status=%d body=%s" % (r.status_code, r.text[:80]))

# --- WS Origin ------------------------------------------------------------
# same-origin and no-Origin (non-browser client) must connect; a foreign
# browser Origin must be refused before accept.
try:
    with c.websocket_connect("/ws/progress", headers=HOSTS["loopback"]) as ws:
        msg = ws.receive_json()
    check("WS loopback Host, no Origin -> connects + snapshot", "jobs" in msg)
except Exception as e:
    check("WS loopback Host, no Origin -> connects + snapshot", False, repr(e))

try:
    with c.websocket_connect("/ws/progress", headers={**HOSTS["loopback"],
                                                      "origin": "http://evil.example.com"}) as ws:
        ws.receive_json()
    check("WS foreign Origin refused before accept", False, "connected anyway")
except Exception as e:
    # starlette raises WebSocketDisconnect/ProtocolError on a 1008 close
    check("WS foreign Origin refused before accept", True, type(e).__name__)

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
