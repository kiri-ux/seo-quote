"""A rank check must not fail because Google does not carry the market name.

Whidbey Island Electric read "0 of 3 measured terms ranking, 18 unmeasured",
and pressing Recheck ran the same unresolvable location and failed the same 18.
The volume probe has walked a location ladder since August; this one did not.
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

asked = []
def fake_post(path, payload, **kw):
    loc = (payload or [{}])[0].get("location_name", "")
    asked.append(loc)
    if "Whidbey Island" in loc or "Fidalgo Island" in loc:
        return {"tasks": [{"status_code": 40501,
                           "status_message": "location_name not found", "result": None}]}
    return {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"type": "organic", "rank_group": 3, "domain": "whidbeyislandelectric.com"}]}]}]}

app.dfs_post = fake_post
app._SERP_LOC_USED.clear()

with app.app.test_request_context("/"):
    # The market Google cannot place still gets a rank, from a wider area.
    pos, qs, doms = app._serp_one(
        "electrical services whidbey island wa", "whidbeyislandelectric.com",
        ["Whidbey Island, WA"], "WA", "Whidbey Island Electric", 100,
        deadline=__import__("time").time() + 30,
        loc_override="Whidbey Island,Washington,United States")
    # The parse of a position is another test's job; what matters here is that
    # the call was made somewhere that answers instead of raising.
    check("didNotRaise", True, True)
    check("triedTheCityFirst", "Whidbey Island" in asked[0], True)
    check("thenSomethingWider", len(asked) > 1, True)
    used = app._SERP_LOC_USED.get("electrical services whidbey island wa", "")
    check("usedIsNotTheCity", "Whidbey Island" in used, False)
    check("usedIsNamed", bool(used), True)

    # A market Google DOES carry is answered on the first call, unchanged.
    asked.clear()
    app._SERP_LOC_USED.clear()
    pos2, _q, _d = app._serp_one(
        "electrical services anacortes wa", "whidbeyislandelectric.com",
        ["Anacortes, WA"], "WA", "Whidbey Island Electric", 100,
        deadline=__import__("time").time() + 30,
        loc_override="Anacortes,Washington,United States")
    check("city.answeredFirst", len(asked), 1)
    check("city.notMarkedBorrowed",
          app._SERP_LOC_USED.get("electrical services anacortes wa"),
          "Anacortes,Washington,United States")

# A task error that is NOT about the location still raises.
def bad_post(path, payload, **kw):
    return {"tasks": [{"status_code": 40200, "status_message": "payment required",
                       "result": None}]}
app.dfs_post = bad_post
with app.app.test_request_context("/"):
    try:
        app._serp_one("x", "d.com", ["Anacortes, WA"], "WA", "b", 100,
                      deadline=__import__("time").time() + 30,
                      loc_override="Anacortes,Washington,United States")
        check("otherErrorsStillRaise", False, True)
    except RuntimeError as e:
        check("otherErrorsStillRaise", "40200" in str(e), True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
