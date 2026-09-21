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
# 2, not 1: unnamed is now the third tier, below a market the client at least
# serves. With no primary hint there is no middle tier to land in.
check("and the others are not",
      [app.home_market_rank(c, "MS", HOME) for c in MARKETS if not c.startswith("oxford")],
      [2] * 7)

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

# ------------- AND THE SIGNAL WAS BEING DESTROYED BY THE DATA MEANT TO HELP IT
# The panel finally showed the readings: Oxford 10, Greenwood 10, Grenada 10,
# Batesville 0, Hernando 0. A TIE, not Greenwood measuring higher -- so nothing
# above was wrong, and none of it mattered, because home_rank was not breaking
# the tie either.
#
# The hint handed to it is brand + domain PLUS every location scraped off the
# site and every service area entered. For a practice that lists the eight towns
# it covers, all eight matched and all eight ranked 0. The tiebreak meant to name
# the client's own market answered "all of them", the sort fell through to
# alphabetical, and g sorts before o.
PRIMARY = "ENT Consultants of North MS entoxford.com"
SERVED = PRIMARY + " Oxford Greenwood Batesville Grenada Hernando Cleveland"

check("the flagship is tier 0", app.home_market_rank("oxford, ms", "MS", SERVED, PRIMARY), 0)
check("a market they merely serve is tier 1",
      app.home_market_rank("greenwood, ms", "MS", SERVED, PRIMARY), 1)
check("and one they never name is tier 2",
      app.home_market_rank("tupelo, ms", "MS", SERVED, PRIMARY), 2)
# A served market still beats an unnamed one. The full hint is worth something;
# it is just not the flagship.
check("served still outranks unnamed",
      app.home_market_rank("greenwood, ms", "MS", SERVED, PRIMARY)
      < app.home_market_rank("tupelo, ms", "MS", SERVED, PRIMARY), True)
# The shipped bug, kept as a check so the collapse is visible if it returns.
check("one bag makes every served town look like home",
      [app.home_market_rank(c, "MS", SERVED) for c in ("oxford, ms", "greenwood, ms")],
      [0, 0])
# Callers that pass no primary hint keep the old two-tier behaviour.
check("no primary hint, no third tier",
      app.home_market_rank("tupelo, ms", "MS", SERVED), 2)
check("and the named one is still 0",
      app.home_market_rank("oxford, ms", "MS", SERVED), 0)

# End to end on the readings the panel actually printed.
TIE = {"oxford": 10, "greenwood": 10, "grenada": 10, "batesville": 0, "hernando": 0}
TIE_MK = ["oxford, ms", "greenwood, ms", "batesville, ms", "grenada, ms", "hernando, ms"]


def tie_build(primary):
    real = app.dfs_post
    app.dfs_post = lambda path, payload, *a, **kw: {"tasks": [{
        "status_code": 20000,
        "result": [{"keyword": k, "search_volume":
                    next((v for t, v in TIE.items() if t in str(k).lower()), 0)}
                   for k in ((payload[0] or {}).get("keywords") or [])]}]}
    try:
        return app.choose_build_markets(list(TIE_MK), "MS", SEEDS, SERVED,
                                        primary_hint=primary)[0]
    finally:
        app.dfs_post = real


check("e2e: the real tie resolves to the client's own town",
      tie_build(PRIMARY)[0], "oxford, ms")
check("e2e: and without the flagship it does not",
      tie_build("")[0] != "oxford, ms", True)

# ---------------------------------------------------------------- AND THE
# OTHER DOOR: NOT TRUSTING THE SCORES AT ALL.
#
# The fix above dropped the scores from the sort key whenever no single term
# cleared the floor, which left cty_rank, home_rank and then the NAME deciding.
# On a quote whose markets are all counties with no home match, the name is the
# only key left.
#
# Milligan Vein (milliganvein.com, four TN counties): Knox summed 70/mo and
# Bradley 10/mo, but Google floors a thin term at 10 so no single term cleared
# 20 -- and the whole quote was built, rank-checked and priced on BRADLEY,
# because b sorts before k. (2026-09-21)
VEIN = {"knox": 10, "cumberland": 0, "hamblen": 0, "bradley": 10}
VEIN_MK = ["knox county, tn", "cumberland county, tn", "hamblen county, tn",
           "bradley county, tn"]
# Seven thin terms in Knox, one in Bradley: 70/mo against 10/mo, and not one
# of them over the floor.
VEIN_SEEDS = ["vein clinic", "varicose vein specialist", "vascular ultrasound",
              "venous insufficiency", "vein doctor", "phlebologist",
              "phlebectomy"]


def vein_build(hint=""):
    real = app.dfs_post

    def fake(path, payload, *a, **kw):
        rows = []
        for k in ((payload[0] or {}).get("keywords") or []):
            s = str(k).lower()
            v = 0
            # Knox reads on every term; Bradley on one. Both at Google's floor.
            if "knox" in s:
                v = 10
            elif "bradley" in s and "vein clinic" in s:
                v = 10
            rows.append({"keyword": k, "search_volume": v})
        return {"tasks": [{"status_code": 20000, "result": rows}]}

    app.dfs_post = fake
    try:
        return app.choose_build_markets(list(VEIN_MK), "TN", VEIN_SEEDS,
                                        hint, primary_hint=hint)
    finally:
        app.dfs_post = real


picked, exp = vein_build()
check("the market with the demand is built on, not the first alphabetically",
      picked[0], "knox county, tn")
check("and b no longer sorts before k",
      picked[0] != "bradley county, tn", True)
# THE READING IS STILL REPORTED AS WEAK. Nothing cleared the floor, so the
# panel must not print this as a measured ranking.
check("nothing cleared the floor, and the panel is told so",
      exp.get("ranked_on_demand"), False)
# The scores are still carried for the panel to show, and the market that was
# built on is the one holding the biggest of them. (choose_build_markets probes
# a reduced term set, so the sum is whatever that set measures -- the property
# that matters is which market tops it, not the figure.)
_kept = dict(exp.get("kept") or {})
check("the scores are still carried for the panel to show",
      _kept.get("knox county, tn", 0) > 0, True)
check("and the market built on is the one holding the biggest",
      max(_kept, key=lambda c: _kept[c]), "knox county, tn")
# AND THE FLAGSHIP STILL OUTRANKS A SUM. This is what the ENT fix was for:
# Oxford at 0/mo beats Greenwood at 10/mo because it is the client's own town,
# and the sum sits BELOW home_rank on the key, not above it.
check("the client's own town still beats a bigger sum elsewhere",
      tie_build(PRIMARY)[0], "oxford, ms")

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
