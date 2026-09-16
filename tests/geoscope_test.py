"""The geo band is read off the markets, not off which checkbox is ticked.

Three cities on the Whidbey Island quote read "Single city" -- and the band is
the PRICING ANCHOR, so that was a wrong price wearing a wrong caption.
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
def band(markets, state="", national=False):
    return c.post("/api/geo_scope", json={"markets": markets, "state": state,
                                          "national_demand": national}).get_json()

check("one.city", band(["Knoxville, TN"], "TN")["band"], "single_city")
check("one.reason", "One market" in band(["Knoxville, TN"], "TN")["reason"], True)

# Two cities in different states do not touch.
far = band(["Knoxville, TN", "Miami, FL"])
check("far.apart", far["band"], "non_contiguous_region")
check("far.saysWhy", "do not touch" in far["reason"], True)

# Neighbouring towns are one region.
near = band(["Knoxville, TN", "Maryville, TN", "Alcoa, TN"], "TN")
check("near.oneRegion", near["band"] in ("contiguous_region", "single_city"), True)
check("near.notThreeCities", near["band"] != "non_contiguous_region", True)

# No markets is national, however the request is phrased.
check("empty.national", band([])["band"], "nationwide")
check("flag.national", band(["Knoxville, TN"], "TN", True)["band"], "nationwide")

# A market the map cannot place is said out loud rather than silently
# collapsing to the cheapest anchor at high confidence.
unk = band(["Whidbey Island, WA", "Fidalgo Island, WA", "Anacortes, WA"], "WA")
check("unplaceable.notConfident", unk["confidence"] != "high", True)
check("unplaceable.saysSo", "Could not place" in unk["reason"], True)
check("unplaceable.countsMarkets", unk["markets"], 3)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
