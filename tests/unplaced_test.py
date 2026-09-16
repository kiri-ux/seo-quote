"""A MARKET THE MAP CANNOT PLACE IS STILL BEING PRICED.

"Cleaveland, MS" and "Indianaola, MS" are misspellings. Every keyword naming
them borrowed its volume from a wider area, the scope line still read "high
confidence, 8 areas form one connected region", and nothing said which markets
were responsible.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

c = app.app.test_client()
MK = ["Oxford, MS", "Grenada, MS", "Batesville, MS", "Greenwood, MS",
      "Indianaola, MS", "Lexington, MS", "Hernando, MS", "Cleaveland, MS"]
r = c.post("/api/geo_scope", json={"markets": MK, "state": "MS"}).get_json()
un = {x["market"]: x["suggestion"] for x in (r.get("unplaced") or [])}

check("namesBoth", sorted(un), ["Cleaveland, MS", "Indianaola, MS"])
check("suggests.cleveland", un.get("Cleaveland, MS"), "Cleveland")
check("suggests.indianola", un.get("Indianaola, MS"), "Indianola")
check("leavesGoodOnesAlone", "Oxford, MS" in un, False)
check("greenwoodIsFine", "Greenwood, MS" in un, False)

# Spelled correctly, nothing is flagged.
good = [m.replace("Cleaveland", "Cleveland").replace("Indianaola", "Indianola")
        for m in MK]
r2 = c.post("/api/geo_scope", json={"markets": good, "state": "MS"}).get_json()
check("cleanRun.none", len(r2.get("unplaced") or []), 0)
check("cleanRun.stillABand", r2.get("band"), "contiguous_region")

# A name nothing is close to is reported without a guess rather than a wrong one.
r3 = c.post("/api/geo_scope",
            json={"markets": ["Oxford, MS", "Zzzqqx, MS"], "state": "MS"}).get_json()
un3 = {x["market"]: x["suggestion"] for x in (r3.get("unplaced") or [])}
check("nonsense.flagged", "Zzzqqx, MS" in un3, True)
check("nonsense.noWildGuess", un3.get("Zzzqqx, MS"), "")

# Nationwide has no markets to place.
r4 = c.post("/api/geo_scope", json={"markets": [], "state": ""}).get_json()
check("national.none", r4.get("unplaced") or [], [])

# And the builder shows it.
ui = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "adtini.html"), encoding="utf-8").read()
check("ui.hasTheLine", 'id="kbUnplaced"' in ui, True)
check("ui.saysWhatItMeans", "take demand from a wider area" in ui, True)
check("ui.offersTheSpelling", "did you mean" in ui, True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
