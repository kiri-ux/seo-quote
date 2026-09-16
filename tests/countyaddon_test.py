"""A county market is named by its SEAT in the keyword, so the add-on matcher
has to look for the seat as well as the county.

Matching "knox county" against "chronic venous insufficiency knoxville tn" found
nothing: four counties entered, "Rankings measured in only 0 markets", and the
add-on recommendation refused on a rank check that had in fact run -- next to a
tile reading "100% of 12 terms ranking".
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

ST = "Tennessee"
COUNTIES = ["Knox County, TN", "Cumberland County, TN",
            "Hamblen County, TN", "Bradley County, TN"]
# The list the builder actually produces: every phrase carries the SEAT.
SEAT_ROWS = [
    {"kw": "chronic venous insufficiency knoxville tn", "pos": 6},
    {"kw": "phlebectomy knoxville tn", "pos": "Not Found"},
    {"kw": "varicose vein treatment crossville tn", "pos": "Not Found"},
    {"kw": "vein clinic near me morristown tn", "pos": "Not Found"},
    {"kw": "sclerotherapy cleveland tn", "pos": "Not Found"},
]

with app.app.test_request_context("/"):
    out = app.recommend_addons(COUNTIES, ST, SEAT_ROWS)
    check("measured.allFour", out.get("measured"), 4)
    check("noRunStep3", "run step 3 first" in (out.get("basis") or ""), False)
    # One seat ranks, three do not -> three markets they are not in yet.
    check("covered.one", out.get("covered"), 1)

    # A county named as itself still matches -- the old path is not broken.
    county_rows = [{"kw": "vein clinic knox county tn", "pos": 4},
                   {"kw": "vein clinic cumberland county tn", "pos": "Not Found"},
                   {"kw": "vein clinic hamblen county tn", "pos": "Not Found"},
                   {"kw": "vein clinic bradley county tn", "pos": "Not Found"}]
    out2 = app.recommend_addons(COUNTIES, ST, county_rows)
    check("county.form.stillMatches", out2.get("measured"), 4)

    # Plain cities are untouched. Four of them, because three or fewer short
    # -circuit to one campaign before anything is measured.
    city_rows = [{"kw": "roof repair knoxville tn", "pos": 2},
                 {"kw": "roof repair maryville tn", "pos": "Not Found"},
                 {"kw": "roof repair alcoa tn", "pos": "Not Found"},
                 {"kw": "roof repair farragut tn", "pos": "Not Found"}]
    out3 = app.recommend_addons(
        ["Knoxville, TN", "Maryville, TN", "Alcoa, TN", "Farragut, TN"], ST, city_rows)
    check("cities.measured", out3.get("measured"), 4)
    check("cities.covered", out3.get("covered"), 1)

    # A seat that belongs to no entered county must not be credited.
    out4 = app.recommend_addons(["Knox County, TN", "Cumberland County, TN"], ST,
                                [{"kw": "vein clinic nashville tn", "pos": 3}])
    check("wrongCity.notCounted", out4.get("measured"), 0)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
