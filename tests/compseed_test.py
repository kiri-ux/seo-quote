"""SEEDS FROM SOMEBODY ELSE'S SITE.

Drainify is a UK company entering the US. Every seed source the tool had starts
from the client -- their site, their focus terms, their own rankings -- and the
client's site is written in UK trade language. The US market calls the same work
sewer inspection, pipeline inspection and PACP coding, and not one of those
words appears anywhere on the client's site, so no amount of expanding the
client's own vocabulary reaches them. All eighteen terms came back with no US
volume and the quote fell to the anchor.

Their nine competitors use that vocabulary on every page and rank for it.
(2026-09-04, Kiri)
"""
import importlib.util
import json
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

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# What each competitor ranks for. "sewer inspection software" is held by three
# of them -- that is the category. "pipelogix login" is one vendor's own
# navigation. "wincan alternative" names a vendor too and is the opposite case.
RANKED = {
    "ariesindustries.com": [
        ("sewer inspection software", 20, 3),
        ("pipeline inspection software", 40, 7),
        ("pacp software", 90, 11),
    ],
    "pipelogix.com": [
        ("sewer inspection software", 20, 5),
        ("pacp software", 90, 2),
        ("pipelogix login", 300, 1),
    ],
    "sewerai.com": [
        ("sewer inspection software", 20, 9),
        ("pacp coding software", 30, 4),
        ("wincan alternative", 10, 6),
        ("drain survey software", 0, 60),
    ],
}


def fake_ranked(domain, markets=None, state="", limit=None):
    if domain == "broken.com":
        raise RuntimeError("40501 not found")
    rows = RANKED.get(domain)
    if rows is None:
        raise RuntimeError("no such domain")
    return [{"term": t, "bare": t, "position": p, "volume": v, "url": ""}
            for t, v, p in rows]


app.fetch_ranked_keywords = fake_ranked
client = app.app.test_client()


def call(**kw):
    r = client.post("/api/competitor_seeds", json=kw)
    return r.status_code, json.loads(r.data or b"{}")


print("\nIT READS THEM ALL AND POOLS WHAT THEY SHARE")
code, r = call(competitors=["https://ariesindustries.com/products/software/",
                            "www.pipelogix.com", "sewerai.com"],
               seeds=["drain survey"], brand="Drainify")
check("the call succeeds", code, 200)
check("three domains read", sorted(r["domains_read"]),
      ["ariesindustries.com", "pipelogix.com", "sewerai.com"])
terms = [k["term"] for k in r["keywords"]]
check("the shared term leads", terms[0], "sewer inspection software")
check("and it counts every competitor holding it",
      r["keywords"][0]["competitors"], 3)
check("the two-competitor term is next", terms[1], "pacp software")
check("shared terms are counted", r["shared"], 2)

print("\nTHE BEST POSITION ANY OF THEM HOLDS")
_pacp = [k for k in r["keywords"] if k["term"] == "pacp software"][0]
check("best, not last", _pacp["position"], 2)
check("volume is carried", _pacp["volume"], 90)

print("\nA VENDOR'S OWN NAME IS FLAGGED, NEVER DROPPED")
# "X login" is their navigation with nothing to win; "X alternative" is the
# comparison term a switch campaign is built on. The judgement is the planner's.
_by = {k["term"]: k for k in r["keywords"]}
check("their login page is still offered", "pipelogix login" in _by, True)
check("  and marked", _by["pipelogix login"]["vendor_terms"], ["pipelogix"])
check("the comparison term is offered", "wincan alternative" in _by, True)
check("an ordinary category term is not marked",
      _by["sewer inspection software"]["vendor_terms"], [])

print("\nWHAT IS ALREADY ON THE LIST IS NOT OFFERED AGAIN")
code, r2 = call(competitors=["sewerai.com"],
                seeds=["pacp coding software"], brand="Drainify")
check("the seeded term is gone",
      "pacp coding software" in [k["term"] for k in r2["keywords"]], False)
check("and it is counted", r2["already_seeded"], 1)

print("\nONE DEAD DOMAIN IS NOT A DEAD READ")
code, r3 = call(competitors=["ariesindustries.com", "broken.com"],
                seeds=[], brand="Drainify")
check("the good one still answers", code, 200)
check("the failure is named", r3["domains_failed"], ["broken.com"])
check("and its terms still arrive", len(r3["keywords"]) > 0, True)

print("\nNOTHING READABLE IS AN ERROR, NOT AN EMPTY ANSWER")
code, r4 = call(competitors=["broken.com"], seeds=[], brand="Drainify")
check("502, not 200", code, 502)
code, r5 = call(competitors=["not a domain", ""], seeds=[], brand="Drainify")
check("an unparseable entry is refused", code, 400)
check("and reported back", r5["unreadable"], ["not a domain"])

print("\nTHE CLIENT'S OWN NAME IS NOT A KEYWORD")
# Same matcher the client-side panel uses, so it behaves the same way here --
# INCLUDING its deliberate limit: a one-word brand is never filtered, because a
# single word that doubles as a service ("Amare", "Prime") would swallow the
# list. Asserted rather than assumed, so a change to that rule is caught here.
app.fetch_ranked_keywords = lambda d, m=None, s="", l=None: [
    {"term": "cisney o donnell", "bare": "cisney o donnell",
     "position": 1, "volume": 50, "url": ""},
    {"term": "sewer inspection software", "bare": "sewer inspection software",
     "position": 4, "volume": 20, "url": ""}]
code, r6 = call(competitors=["ariesindustries.com"], seeds=[],
                brand="Cisney & O'Donnell")
check("a two-word brand is cut",
      [k["term"] for k in r6["keywords"]], ["sewer inspection software"])
code, r7 = call(competitors=["ariesindustries.com"], seeds=[], brand="Drainify")
check("a one-word brand is deliberately not",
      "cisney o donnell" in [k["term"] for k in r7["keywords"]], True)
app.fetch_ranked_keywords = fake_ranked

print("\nTHE READ IS CAPPED")
check("domains are capped at the config value",
      int(app.CFG.get("competitor_seed_max_domains", 0)) > 0, True)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
