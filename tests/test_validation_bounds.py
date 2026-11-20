# SPDX-License-Identifier: AGPL-3.0-only
"""B3 (v1.6) — validation bounds + friendly-error gates.

Audit #2 B3 fuzz found NO true bypass (hostile kind/y/n/w/t all rejected), but two
bounds gaps + error-message polish:
  - captions list had no upper cap (5000 accepted -> render-time/memory DoS surface)
  - colors accepted arbitrary nested dicts / non-list (no type gate)
  - None shot / string shots raised AttributeError instead of a readable ValueError
Gate: each hostile shape now raises ValueError with a readable message, and a
known-good project still validates (no regression).
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.engine import validate_project  # noqa: E402

BASE = json.load(open(os.path.join(ROOT, "samples", "promo_v12.json"), encoding="utf-8"))
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " " + detail))
    if not cond:
        FAILS.append(name)


def expect_valueerror(name, mut):
    p = copy.deepcopy(BASE)
    mut(p)
    try:
        validate_project(p)
        check(name, False, "accepted (no raise)")
    except ValueError as ex:
        check(name, True)
    except Exception as ex:
        check(name, False, "wrong exception %s: %s" % (type(ex).__name__, str(ex)[:60]))


# regression: known-good project still validates
try:
    validate_project(copy.deepcopy(BASE))
    check("known-good promo_v12 still validates", True)
except Exception as ex:
    check("known-good promo_v12 still validates", False, str(ex)[:80])

expect_valueerror("shots must be a list (string shots)",
                  lambda p: p.update(shots="abc"))
expect_valueerror("shot must be an object (None shot)",
                  lambda p: p["shots"].append(None))
expect_valueerror("caption count capped (5000)",
                  lambda p: p["shots"][0].update(
                      captions=[{"kind": "small", "text": "x"}] * 5000))
expect_valueerror("caption must be an object (None caption)",
                  lambda p: p["shots"][0].update(captions=[None]))
expect_valueerror("captions must be a list (string)",
                  lambda p: p["shots"][0].update(captions="nope"))
expect_valueerror("colors must be a list (nested dict)",
                  lambda p: p["shots"][0].update(
                      captions=[{"kind": "small", "text": "hi",
                                 "colors": {"x": {"y": None}}}]))
expect_valueerror("colors must be a list (bare string)",
                  lambda p: p["shots"][0].update(
                      captions=[{"kind": "small", "text": "hi", "colors": "accent"}]))
expect_valueerror("colors items must be strings",
                  lambda p: p["shots"][0].update(
                      captions=[{"kind": "small", "text": "hi", "colors": [None, 3]}]))

# a sane caption count + list-of-str colors still passes
p = copy.deepcopy(BASE)
p["shots"][0]["captions"] = [{"kind": "small", "text": "hi", "colors": ["accent", "white"]}]
try:
    validate_project(p)
    check("valid colors list + small caption count passes", True)
except Exception as ex:
    check("valid colors list + small caption count passes", False, str(ex)[:80])

print("\n%d FAIL(S)" % len(FAILS))
sys.exit(1 if FAILS else 0)
