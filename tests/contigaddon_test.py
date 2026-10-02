"""A contiguous region is one campaign, so it recommends no add-on markets.

Texoma Dentures: sixteen towns around Sherman, TX across TX and OK, ranking in
3 of 12. Counting each town it didn't rank in as a new market, plus the
two-state rule, recommended 15 add-ons at $2,850 on a 930/mo quote.
(2026-10-02, Kiri)
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

TOWNS = ["Sherman, TX", "Denison, TX", "Pottsboro, TX", "Gainesville, TX",
         "Durant, OK", "Ardmore, OK", "Madill, OK", "Calera, OK"]
ROWS = [{"kw": f"dentist {m.split(',')[0].lower()} {m.split(', ')[1].lower()}",
         "pos": 5 if i < 2 else "Not Found"} for i, m in enumerate(TOWNS)]

with app.app.test_request_context("/"):
    split = app.recommend_addons(TOWNS, "", ROWS, band="non_contiguous_region")
    check("nonContiguous.stillSplits", split["suggested"] > 0, True)
    one = app.recommend_addons(TOWNS, "", ROWS, band="contiguous_region")
    check("contiguous.nearbyNoAddons", one["suggested"], 0)
    check("contiguous.confident", one["confident"], True)
    check("contiguous.says", "contiguous region" in one["basis"], True)
    none = app.recommend_addons(TOWNS, "", ROWS)
    check("noBand.unchanged", none["suggested"], split["suggested"])
    c = app.app.test_client()
    r = c.post("/api/addon_suggestion", json={"geo_values": TOWNS, "table": ROWS,
                                               "band": "contiguous_region"})
    check("route.readsBand", (r.get_json() or {}).get("suggested"), 0)

    # FAR TOWNS ARE ADD-ONS. Texoma from Sherman: Paris 62, Antlers 70.
    TEX = ["Sherman, TX", "Denison, TX", "Durant, OK", "Ardmore, OK",
           "Paris, TX", "Antlers, OK", "Brookston, TX"]
    far = app.recommend_addons(TEX, "", [], band="contiguous_region")
    check("far.counted", far["suggested"], 2)
    check("far.named", sorted(far["markets_absent"]), ["Antlers, OK", "Paris, TX"])
    check("far.basis", "over 60 miles from Sherman, TX" in far["basis"], True)
    ranked = app.recommend_addons(TEX, "", [{"kw": "dentist paris tx", "pos": 4}],
                                  band="contiguous_region")
    check("far.rankingThereIsCovered", ranked["markets_absent"], ["Antlers, OK"])
    paged = app.recommend_addons(TEX, "", [], band="contiguous_region",
                                 site_locations=["antlers"])
    check("far.locationPageIsCovered", paged["markets_absent"], ["Paris, TX"])
    hub = app.recommend_addons(TEX, "", [], band="contiguous_region", main="Paris, TX")
    check("far.measuredFromMain", "from Paris, TX" in hub["basis"], True)
    r = c.post("/api/addon_suggestion", json={"geo_values": TEX, "table": [],
                                               "band": "contiguous_region",
                                               "main": "Sherman, TX"})
    check("route.far", (r.get_json() or {}).get("suggested"), 2)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
