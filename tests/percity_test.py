"""Each market is probed on its OWN. The statewide figure is a per-city
fallback, not a decision to give up on the list.

Whidbey Island Electric read "14 answered from Washington statewide" and the
question was whether every city had been tried first.
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

CITIES = ["Whidbey Island, WA", "Anacortes, WA", "Fidalgo Island, WA"]
TERMS = ["electrical services"]
asked = []

def fake_post(path, payload, **kw):
    loc = (payload or [{}])[0].get("location_name", "")
    asked.append(loc)
    # Only Anacortes is a place Google carries.
    if "Anacortes" in loc:
        return {"tasks": [{"result": [{"keyword": "electrical services",
                                       "search_volume": 10,
                                       "location_code": 1027}]}]}
    if loc.startswith("Washington,"):
        return {"tasks": [{"result": [{"keyword": "electrical services",
                                       "search_volume": 480,
                                       "location_code": 21176}]}]}
    raise RuntimeError("40501 location_name not found")

app.dfs_post = fake_post
with app.app.test_request_context("/"):
    totals, per_city, err = app.fetch_local_volume(TERMS, CITIES, "WA")

# The third value is the panel's note, not an error: it names the markets that
# could not be targeted and says their figures are out of the pricing total.
check("note.namesWhidbey", "Whidbey Island" in (err or ""), True)
check("note.namesFidalgo", "Fidalgo Island" in (err or ""), True)
check("note.excludesThem", "EXCLUDED from the pricing total" in (err or ""), True)
check("note.doesNotNameAnacortes",
      "Anacortes" in (err or "").replace("Fidalgo Island, WA, Whidbey Island, WA", ""), False)

# EVERY CITY WAS ASKED FOR BY NAME before anything broader was tried.
for c in ("Whidbey Island", "Anacortes", "Fidalgo Island"):
    check(f"asked.{c}", any(c in a for a in asked), True)

# The broader call is the RETRY, so it comes after the city's own attempt.
first_whidbey = next(i for i, a in enumerate(asked) if "Whidbey Island" in a)
first_state = next((i for i, a in enumerate(asked) if a.startswith("Washington,")), None)
check("cityBeforeState", first_state is None or first_whidbey < first_state, True)

# The city that resolved keeps its own figure.
check("anacortes.own", per_city.get(("anacortes", "electrical services")), 10)

# The two that did not are marked as answered elsewhere...
fb = set(per_city.get("__fallback_cities__") or [])
check("whidbey.flagged", "whidbey island" in fb, True)
check("fidalgo.flagged", "fidalgo island" in fb, True)
check("anacortes.notFlagged", "anacortes" not in fb, True)

# ...and named, so the screen can say WHICH wider area answered.
locs = per_city.get("__city_locs__") or {}
check("whidbey.namedState",
      any("Washington" in str(v) for k, v in locs.items() if "Whidbey" in k), True)

# AND THE BORROWED FIGURE IS NOT IN THE PRICING TOTAL. A town's whole state is
# not that town's demand.
check("total.isTheRealOne", totals.get("electrical services"), 10)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
