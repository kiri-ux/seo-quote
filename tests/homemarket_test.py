"""A 10/MO NOISE READING MUST NOT OUTRANK THE CLIENT'S OWN MARKET.

ENT Consultants of North MS, 2026-09-16. entoxford.com, eight markets. The
market probe reads geo-suffixed text -- "hearing aids greenwood ms" -- which in
a small town is noise at Google's 10/mo floor. Greenwood came back 10, Oxford 0.

That mattered far more than it looks. -scored is the FIRST key in the ranking
and home_rank is the third, so a single 10 outranked the client's own town. The
services axis then collapses the grid to cities[:1], and that one city sets the
grid suffix, the rank-check location AND the price -- so an Oxford practice was
built and priced entirely on Greenwood. Measured demand fell 230/mo to 100/mo
and both 50/mo near-me terms went with it. The grid's own lookup, which asks for
the bare service in the city's location rather than the suffixed phrase, had
Oxford at 30 for the head term the whole time.

The guard for this already existed and was too narrow: `not any(scored.values())`
only fires when EVERY market reads zero. Ranking now asks a separate question --
did anything clear axis_city_volume_floor, the number choose_grid_axis already
uses to decide whether a market carries demand. `nothing_measured` keeps its own
meaning, because choose_build_markets reads it to decide whether to WIDEN the
market search, and a weak 3/mo reading is still a reason to go looking.
"""
import importlib.util
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
SRC = os.path.join(SRCDIR, "app.py")
spec = importlib.util.spec_from_file_location("app", SRC)
app = importlib.util.module_from_spec(spec)
sys.modules["app"] = app
spec.loader.exec_module(app)

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


HOME = "ENT Consultants of North MS entoxford.com"
MARKETS = ["oxford, ms", "grenada, ms", "batesville, ms", "greenwood, ms",
           "lexington, ms", "hernando, ms", "cleveland, ms", "indianola, ms"]
FLOOR = int(app.CFG.get("axis_city_volume_floor", 20))


def probe(scores):
    """Run pick_grid_cities with the market probe answering `scores`.

    Patches the one provider call rather than the ranking, so the shipped
    selection path is what gets exercised.
    """
    def fake_post(path, payload, *a, **kw):
        kws = (payload[0] or {}).get("keywords") or []
        items = []
        for k in kws:
            v = 0
            for city, sc in scores.items():
                bare = city.split(",")[0].strip().lower()
                if bare in str(k).lower():
                    v = sc
                    break
            items.append({"keyword": k, "search_volume": v})
        return {"tasks": [{"status_code": 20000, "result": items}]}

    real = app.dfs_post
    app.dfs_post = fake_post
    try:
        exp = {}
        out = app.pick_grid_cities(list(MARKETS), "MS", 5, probe_term="hearing aids",
                                   explain=exp, home_hint=HOME)
        return out, exp
    finally:
        app.dfs_post = real


# ------------------------------------------------- the client's own market
check("Oxford is recognised as the home market",
      app.home_market_rank("oxford, ms", "MS", HOME), 0)
check("and the others are not",
      [app.home_market_rank(c, "MS", HOME) for c in MARKETS if not c.startswith("oxford")],
      [1] * 7)

# ------------------------------------------------- the reported failure
# Greenwood 10, everything else 0. Under the old all-zero test this ranked
# Greenwood first and the quote was built on it.
out, exp = probe({"greenwood, ms": 10})
check("a lone 10/mo reading is not enough to rank on",
      exp.get("ranked_on_demand"), False)
check("so the home market leads, not the noisy one", out[0], "oxford, ms")
check("and Greenwood is not the primary market", out[0] != "greenwood, ms", True)

# Every market at the 10/mo floor -- the shape these thin markets actually take.
out, exp = probe({c: 10 for c in MARKETS})
check("a floor-wide tie is not enough to rank on",
      exp.get("ranked_on_demand"), False)
check("and the home market leads it", out[0], "oxford, ms")

# Nothing at all, which the old test did catch. Must not regress.
out, exp = probe({})
check("all-zero is not enough to rank on", exp.get("ranked_on_demand"), False)
# nothing_measured answers a DIFFERENT question -- whether to widen the market
# search -- and must keep its own meaning. A 3/mo reading is weak evidence but
# still a reason to go looking at more markets.
check("and all-zero is also nothing measured", exp.get("nothing_measured"), True)
check("and still leads with the home market", out[0], "oxford, ms")

# ------------------------------------------------- a real reading still wins
# This is the other half: a market that genuinely clears the floor beats the
# home market on merit. The fix must not pin every quote to the client's town.
out, exp = probe({"greenwood, ms": 90})
check("a reading above the floor IS enough to rank on",
      exp.get("ranked_on_demand"), True)
check("and it outranks the home market on merit", out[0], "greenwood, ms")

out, exp = probe({"greenwood, ms": 90, "oxford, ms": 140})
check("the biggest real reading wins", out[0], "oxford, ms")
check("scored markets are ranked, not just the top one",
      out[1], "greenwood, ms")

# The floor used is the one that already answers this question elsewhere.
check("the floor is axis_city_volume_floor", exp.get("measure_floor"), FLOOR)
out, exp = probe({"greenwood, ms": FLOOR - 1})
check("one below the floor does not rank", exp.get("ranked_on_demand"), False)
check("but it still counts as measured, so a widen can happen",
      exp.get("nothing_measured"), False)
out, exp = probe({"greenwood, ms": FLOOR})
check("exactly the floor ranks", exp.get("ranked_on_demand"), True)

# ------------------------------------- END TO END, WHICH IS WHERE IT GOT OUT
# The checks above drive pick_grid_cities with one value per city, so they never
# exercise the thing that actually broke: `scored` SUMS a market's probe terms.
# Six seeds of pure 10/mo noise sum to 60 and clear a floor of 20 with no real
# reading behind them, and the first version of this fix compared the floor
# against that sum. It passed every test above and changed nothing in
# production. So the floor is compared against the PEAK term, and this drives
# choose_build_markets, which is the call the build actually makes.
SEEDS = ["hearing aids", "pediatric ent care", "pediatric ent surgery",
         "tonsillectomy", "chronic sinusitis treatment",
         "minimally-invasive sinus procedures"]


def build(fn):
    real = app.dfs_post
    app.dfs_post = lambda path, payload, *a, **kw: {"tasks": [{
        "status_code": 20000,
        "result": [{"keyword": k, "search_volume": fn(str(k).lower())}
                   for k in ((payload[0] or {}).get("keywords") or [])]}]}
    try:
        return app.choose_build_markets(list(MARKETS), "MS", SEEDS, HOME)
    finally:
        app.dfs_post = real


cities, pick = build(lambda k: 10 if "greenwood" in k else 0)
check("e2e: six noise terms do not add up to a measurement",
      pick.get("ranked_on_demand"), False)
check("e2e: the home market leads", cities[0], "oxford, ms")

cities, pick = build(lambda k: 10)
check("e2e: a floor-wide tie still does not rank",
      pick.get("ranked_on_demand"), False)
check("e2e: home market leads that too", cities[0], "oxford, ms")

cities, pick = build(lambda k: 0)
check("e2e: a dead probe leads with the home market", cities[0], "oxford, ms")

# The other direction, which matters just as much: a market with genuine demand
# must still beat the client's own town.
cities, pick = build(lambda k: 90 if "greenwood" in k else 0)
check("e2e: a real reading ranks", pick.get("ranked_on_demand"), True)
check("e2e: and outranks the home market", cities[0], "greenwood, ms")

cities, pick = build(lambda k: 140 if "oxford" in k else (90 if "greenwood" in k else 0))
check("e2e: the biggest real reading wins", cities[0], "oxford, ms")

# One strong term must not be hidden by five thin ones sharing the market.
cities, pick = build(lambda k: (90 if "hearing aids" in k else 10) if "greenwood" in k else 0)
check("e2e: one genuinely strong term is enough to rank a market",
      pick.get("ranked_on_demand"), True)
check("e2e: and that market leads", cities[0], "greenwood, ms")

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
