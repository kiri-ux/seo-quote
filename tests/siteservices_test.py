"""THEIR SITE'S PROPOSALS ARE MEASURED, LIKE EVERYONE ELSE'S.

The industry pass measured and floored what it proposed; the site pass handed
over the whole service menu unmeasured, and at fourteen open slots every line
of it became a seed. Now each proposal carries its volume and the response
names the floor, so the browser can hold every source to the same bar.
"""
import importlib.util
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
SRC = os.path.join(SRCDIR, "app.py")
spec = importlib.util.spec_from_file_location("app", SRC)
app = importlib.util.module_from_spec(spec)
sys.modules["app"] = app
spec.loader.exec_module(app)

FAIL = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


asked = {}


def fake_volume(terms, markets, state, national=False):
    asked["terms"] = list(terms)
    asked["markets"] = list(markets)
    asked["national"] = national
    return ({"allergy shots": 0, "ear tube surgery": 40, "earwax removal": 10}, {}, "")


app.fetch_local_volume = fake_volume
app.claude_menu_to_terms = lambda *a, **k: {}
app._split_proposal_kinds = lambda items, d, dom, **k: (items, [])
app.CFG["expand_min_volume"] = 20

with app.app.test_client() as c:
    r = c.post("/api/site_services", json={
        "domain": "", "pasted": "Allergy Shots\nEar Tube Surgery\nEarwax Removal",
        "geo_values": ["Oxford, MS", "Grenada, MS"], "state": "Mississippi",
        "seeds": ["hearing aids"]})
    body = r.get_json()

check("200", r.status_code, 200)
vol = {x["term"]: x.get("volume") for x in body.get("services", [])}
check("each proposal carries its volume",
      vol, {"allergy shots": 0, "ear tube surgery": 40, "earwax removal": 10})
check("measured in the quoted markets", asked["markets"], ["Oxford, MS", "Grenada, MS"])
check("locally, not nationally", asked["national"], False)
check("the floor is named", body.get("floor"), 20)

# No markets: measured nationally, still measured.
with app.app.test_client() as c:
    r = c.post("/api/site_services", json={
        "domain": "", "pasted": "Ear Tube Surgery", "geo_values": [], "state": ""})
check("no markets: national read", asked["national"], True)
check("no markets: still measured",
      [x.get("volume") for x in r.get_json()["services"]], [40])

# A volume read that fails leaves the proposals in, at zero, rather than
# taking the whole source down.
def broken(*a, **k):
    raise RuntimeError("40202 rate limit")
app.fetch_local_volume = broken
with app.app.test_client() as c:
    r = c.post("/api/site_services", json={
        "domain": "", "pasted": "Ear Tube Surgery", "geo_values": ["Oxford, MS"], "state": "MS"})
check("volume failure: proposals kept at zero",
      [x.get("volume") for x in r.get_json()["services"]], [0])

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ok all")
sys.exit(1 if FAIL else 0)
