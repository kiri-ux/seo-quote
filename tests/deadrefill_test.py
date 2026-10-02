"""Zero-search slots are refilled from the market, not left in the proposal.

King and Prince Seafood came back with eleven of twenty-one terms at zero
searches: phrasings the build proposed that nobody types, kept because the
swap only drew on the client's eight seeds. (2026-10-02, Kiri)
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

LOCAL = {"seafood supplier": 400, "wholesale seafood": 300, "seafood wholesale": 0}
def fake_vol(terms, markets, state, national=False, cap=None):
    return ({t: LOCAL.get(t, 0) for t in terms},
            {("seattle", t): LOCAL.get(t, 0) for t in terms}, None)
app.fetch_local_volume = fake_vol

SERVICES = [{"service": "seafood distributor", "tier": "ultra"},
            {"service": "b2b battered fish and veggies", "tier": "competitive"},
            {"service": "frozen battered shrimp supplier", "tier": "long_tail"},
            {"service": "beer battered shrimp supplier", "tier": "long_tail"},
            {"service": "crispy battered shrimp wholesale", "tier": "long_tail"}]
VOLS = {"seafood distributor": 120}
POOL = [{"keyword": "seafood supplier", "volume": 900},
        {"keyword": "wholesale seafood", "volume": 800},
        {"keyword": "seafood wholesale", "volume": 700},
        {"keyword": "fish market", "volume": 50}, {"keyword": "fish fry", "volume": 40},
        {"keyword": "fish sticks", "volume": 30}]
with app.app.test_request_context("/"):
    svcs, rep, nv, npc = app.refill_dead_services(
        SERVICES, VOLS, ["seafood distributor", "b2b battered fish and veggies"],
        POOL, {app._seed_stem(w) for w in ["seafood", "supplier", "wholesale",
                                           "battered", "shrimp"]},
        ["Seattle, WA"], "WA", "King and Prince Seafood", ["Seattle, WA"])
names = [x["service"] for x in svcs]
check("the client's own zero term stays", "b2b battered fish and veggies" in names, True)
check("a measured term of the same kind comes in", "seafood supplier" in names, True)
check("one of a different kind does not", "wholesale seafood" in names, False)
check("a candidate with no local volume does not", "seafood wholesale" in names, False)
check("one dead slot refilled, the others kept", len(rep), 1)
check("list size holds", len(svcs), len(SERVICES))
check("tiers inherited", {x["tier"] for x in svcs if x["service"] in nv}, {"long_tail"})
check("its volume comes back", nv, {"seafood supplier": 400})
check("and their per-city figures", ("seattle", "seafood supplier") in npc, True)
with app.app.test_request_context("/"):
    same, rep2, _, _ = app.refill_dead_services(
        SERVICES, VOLS, [], [], [], ["Seattle, WA"], "WA", "", ["Seattle, WA"])
check("no pool, nothing changes", (same, rep2), (SERVICES, []))
# THE SAME KIND OF TERM. A supplier slot is not refilled with a diner's search.
LOCAL.update({"seafood restaurants": 8100, "seafood boil": 210,
              "frozen seafood supplier": 90})
POOL2 = [{"keyword": "seafood restaurants", "volume": 9000},
         {"keyword": "seafood boil", "volume": 8000},
         {"keyword": "frozen seafood supplier", "volume": 7000},
         {"keyword": "fish market", "volume": 50}, {"keyword": "fish fry", "volume": 40},
         {"keyword": "fish sticks", "volume": 30}]
with app.app.test_request_context("/"):
    svcs2, rep2b, _, _ = app.refill_dead_services(
        SERVICES, VOLS, ["seafood distributor", "b2b battered fish and veggies"],
        POOL2, {app._seed_stem(w) for w in ["seafood", "supplier", "restaurants",
                                            "boil", "frozen", "battered", "shrimp"]},
        ["Seattle, WA"], "WA", "King and Prince Seafood", ["Seattle, WA"])
names2 = [x["service"] for x in svcs2]
check("a diner's search never fills a supplier slot",
      any(n in names2 for n in ("seafood restaurants", "seafood boil")), False)
check("a supplier term does", "frozen seafood supplier" in names2, True)
check("one slot refilled, the rest keep their terms", len(rep2b), 1)

# THE CLIENT'S TABLE leaves out zero-volume terms, down to a floor.
import seo_pptx
rows = [{"kw": f"t{i}", "vol": (100 if i < 10 else 0)} for i in range(21)]
out = seo_pptx.drop_zero_volume(rows, min_rows=15)
check("zero rows dropped to the floor", len(out), 15)
check("every measured row kept", sum(1 for x in out if x["vol"]) , 10)
check("order kept", [x["kw"] for x in out][:3], ["t0", "t1", "t2"])
full = [{"kw": "a", "vol": 5}, {"kw": "b", "vol": 0}]
check("enough measured rows: all zeros go",
      seo_pptx.drop_zero_volume([{"kw": str(i), "vol": 9} for i in range(20)] + full,
                                min_rows=15)[-1]["kw"], "a")

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
