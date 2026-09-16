"""A county market must be MEASURED in its seat, not in the county.

DataForSEO cannot target a US county. Sending one made the call fall back to
the widest area that resolved -- the United States -- so every keyword came
home marked "answered from a wider area" and the volume component priced on
almost nothing. The keyword wording already converted county -> seat; the
location string did not.
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
    L = lambda mk, st="Tennessee": app.loc_string(mk, st)

    # The four counties from the vein-clinic quote.
    check("knox.seat", L(["Knox County, TN"]), "Knoxville,Tennessee,United States")
    check("cumberland.seat", L(["Cumberland County, TN"]), "Crossville,Tennessee,United States")
    check("hamblen.seat", L(["Hamblen County, TN"]), "Morristown,Tennessee,United States")
    check("bradley.seat", L(["Bradley County, TN"]), "Cleveland,Tennessee,United States")

    # No county ever survives into a location string.
    for mk in (["Knox County, TN"], ["Cumberland County, TN", "Knox County, TN"],
               ["Hamblen County, TN"], ["Bradley County, TN"]):
        check(f"nocounty.{mk[0]}", "county" in L(mk).lower(), False)

    # A city is untouched.
    check("city.untouched", L(["Knoxville, TN"]), "Knoxville,Tennessee,United States")
    check("city.first", L(["Maryville, TN", "Knox County, TN"]),
          "Maryville,Tennessee,United States")

    # A county that is not a place stays as typed -- refusing to measure is
    # honest, inventing a seat is not.
    check("typo.passthrough", "Brandley" in L(["Brandley County, TN"]), True)

    # The keyword side must still name the seat too, so wording and location
    # cannot disagree.
    seats = app.county_cities("Knox County, TN", "Tennessee")
    check("wording.has.seat", "knoxville" in [str(x).lower() for x in seats], True)

    # Nationwide / no markets -> the state, then the country. Unchanged.
    check("empty.state", L([]), "Tennessee,United States")
    check("empty.country", L([], ""), "United States")

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
