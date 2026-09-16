"""A measured keyword in a measured market is asked for once.

Google Ads LIVE is capped at 12 requests a minute and volume is asked per
market, so a build that measures eight markets spends most of its time waiting
on the pacing bucket -- and the propose-then-build gate makes the second press
re-measure the identical terms.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app as m

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1; print("  ok  ", name)
    else:
        fail += 1; print("  FAIL", name, "got", repr(got), "want", repr(want))

PATH = "/keywords_data/google_ads/search_volume/live"
CALLS = []

def fake(path, payload, timeout=None, method="POST", retries=1):
    CALLS.append((path, payload))
    kws = (payload[0].get("keywords") or []) if payload else []
    return {"tasks": [{"status_code": 20000,
                       "data": {"location_code": 9010, "location_name":
                                payload[0].get("location_name")},
                       "result": [{"keyword": k, "search_volume": 10 * (i + 1)}
                                  for i, k in enumerate(kws)]}]}

m._dfs_post_inner = fake

def vol(kws, loc):
    d = m.dfs_post(PATH, [{"keywords": list(kws), "location_name": loc,
                           "language_code": "en"}])
    rows = (d["tasks"][0]["result"] or [])
    return {str(r["keyword"]): r.get("search_volume") for r in rows}

m.ads_volume_cache_clear(); CALLS.clear()

a = vol(["hearing aids", "tonsillectomy"], "Oxford,Mississippi,United States")
check("firstPassAsks", len(CALLS), 1)
check("firstPassAnswers", a, {"hearing aids": 10, "tonsillectomy": 20})

b = vol(["hearing aids", "tonsillectomy"], "Oxford,Mississippi,United States")
check("secondPassAsksNothing", len(CALLS), 1)
check("secondPassSameNumbers", b, a)

# A different market is a different measurement.
vol(["hearing aids"], "Grenada,Mississippi,United States")
check("otherMarketIsItsOwn", len(CALLS), 2)

# A partly-cached list asks only for what is new.
CALLS.clear()
c = vol(["hearing aids", "tonsillectomy", "ear tube surgery"],
        "Oxford,Mississippi,United States")
check("onlyTheMissIsAsked", len(CALLS), 1)
check("askedJustTheNewOne", CALLS[0][1][0]["keywords"], ["ear tube surgery"])
check("mergedAnswerIsWhole", sorted(c), ["ear tube surgery", "hearing aids",
                                         "tonsillectomy"])
check("cachedValuesKept", c["hearing aids"], 10)
check("freshValueRead", c["ear tube surgery"], 10)

# The location code survives a fully cached answer.
d = m.dfs_post(PATH, [{"keywords": ["hearing aids"],
                       "location_name": "Oxford,Mississippi,United States",
                       "language_code": "en"}])
check("locationCodeKept", d["tasks"][0]["data"]["location_code"], 9010)
check("statusIsClean", d["tasks"][0]["status_code"], 20000)

# A KEYWORD WITH NO DEMAND IS REMEMBERED AS NO DEMAND, not re-asked forever.
def empty(path, payload, timeout=None, method="POST", retries=1):
    CALLS.append((path, payload))
    return {"tasks": [{"status_code": 20000, "data": {}, "result": []}]}
m._dfs_post_inner = empty
m.ads_volume_cache_clear(); CALLS.clear()
vol(["nothing here"], "Oxford,Mississippi,United States")
vol(["nothing here"], "Oxford,Mississippi,United States")
check("emptyAnswerCachedToo", len(CALLS), 1)

# A REFUSAL IS NOT A MEASUREMENT.
def refused(path, payload, timeout=None, method="POST", retries=1):
    CALLS.append((path, payload))
    return {"tasks": [{"status_code": 40202,
                       "status_message": "rate limit", "result": None}]}
m._dfs_post_inner = refused
m.ads_volume_cache_clear(); CALLS.clear()
m.dfs_post(PATH, [{"keywords": ["throttled"], "location_name": "X",
                   "language_code": "en"}])
m.dfs_post(PATH, [{"keywords": ["throttled"], "location_name": "X",
                   "language_code": "en"}])
check("refusalNotCached", len(CALLS), 2)

# Other endpoints are untouched.
m._dfs_post_inner = fake
CALLS.clear()
m.dfs_post("/serp/google/organic/live/regular",
           [{"keyword": "x", "location_name": "Y"}])
m.dfs_post("/serp/google/organic/live/regular",
           [{"keyword": "x", "location_name": "Y"}])
check("serpIsNotCachedHere", len(CALLS), 2)

# This endpoint is paced by the Google Ads cap, the others are not.
check("volumeIsTheCappedFamily", m._dfs_family(PATH), "ads_live")

print(f"\n{ok + fail} checks, {fail} failed")
sys.exit(1 if fail else 0)
