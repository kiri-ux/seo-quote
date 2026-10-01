"""A state entered in the State field is statewide and targets the state.

"Washington" read "Single city" and "Not on the map: Washington", and every
lookup was sent to "Washington,Washington,United States", which is not a
place. (2026-10-01, Kiri)
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

with app.app.test_request_context("/"):
    check("full name", app.loc_string(["Washington"], "Washington"), "Washington,United States")
    check("abbreviation", app.loc_string(["WA"], "WA"), "Washington,United States")
    check("no state param", app.loc_string(["Texas"], ""), "Texas,United States")
    check("a city is still a city", app.loc_string(["Seattle, WA"], ""),
          "Seattle,Washington,United States")
    check("new york, ny is the city", app.loc_string(["New York, NY"], ""),
          "New York,New York,United States")

with app.app.test_client() as c:
    g = c.post("/api/geo_scope", json={"markets": ["Washington"], "state": "Washington",
                                       "states": ["Washington"]}).get_json()
    check("statewide", g["band"], "statewide")
    check("not unplaced", g["unplaced"], [])
    two = c.post("/api/geo_scope", json={"markets": ["Washington", "Oregon"],
                                         "states": ["Washington", "Oregon"]}).get_json()
    check("two states", (two["band"], two["reason"]), ("statewide", "2 states."))
    city = c.post("/api/geo_scope", json={"markets": ["Seattle, WA"]}).get_json()
    check("cities unchanged", city["band"], "single_city")

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
