"""A town USPS spells with a space ("Mc Coy") still places in its own state.

Build Smart Institute (Q-100244): "McCoy, VA" missed the Virginia index, fell
through to the one national "mccoy" (McCoy TX, 1,189 miles from Roanoke) and
was quoted as a $3,330 add-on market. It is 35 miles from Roanoke, inside the
region. (2026-11-06, Kiri)
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

hub = app.city_coords("Roanoke, VA")
mc = app.city_coords("McCoy, VA")
check("mccoy.places", bool(mc), True)
check("mccoy.inVirginia", mc and round(app.miles_between(hub, mc)) < 60, True)
check("typedState.noNationalGuess", app.city_coords("Nowhereville, VA"), None)
check("mtUnion.stillPlaces", bool(app.city_coords("Mt. Union, PA")), True)

TOWNS = ["Roanoke, VA", "Salem, VA", "Blacksburg, VA", "Christiansburg, VA",
         "McCoy, VA"]
with app.app.test_request_context("/"):
    r = app.recommend_addons(TOWNS, "VA", [], band="contiguous_region",
                             main="Roanoke, VA")
    check("buildSmart.noAddon", r["suggested"], 0)

print(f"ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
