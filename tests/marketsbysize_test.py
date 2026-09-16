"""TWELVE SEEDS, TWO MARKETS.

The grid measured up to five markets whatever the seed list looked like, then
cut SEEDS to fit them: twelve focus terms across five markets became seven
services, and five things the client sells never reached the quote. Every
market cost a volume read and a rank check per term.

Now the seeds decide how many markets: slots / seeds, rounded up, taken by
size off the ZIP index. The demand probe still runs on the chosen markets, and
widens to the whole list only when none of them measures. (2026-09-16)
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

FAIL = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


app.CFG["grid_max_services"] = 20
app.CFG["grid_max_cities"] = 5
app.CFG["axis_city_volume_floor"] = 20

# ---- the count: slots / seeds, rounded up, capped ---------------------------
for n, want in [(12, 2), (20, 1), (25, 1), (10, 2), (11, 2), (7, 3),
                (4, 5), (1, 5), (0, 5)]:
    check(f"markets_for_seeds({n})", app.markets_for_seeds(n), want)

# ---- the order: biggest first, home first, no call --------------------------
TOWNS = ["Farragut, TN", "Sevierville, TN", "Knoxville, TN", "Oak Ridge, TN",
         "Maryville, TN", "Morristown, TN", "Clinton, TN", "Knox County, TN"]
ST = "Tennessee"
by = app.markets_by_size(TOWNS, ST)
check("biggest first", by[0], "Knoxville, TN")
check("every town kept", sorted(by), sorted(TOWNS))
sizes = [app.city_size(c, ST) for c in by]
check("non-increasing", sizes == sorted(sizes, reverse=True), True)
check("home market leads whatever its size",
      app.markets_by_size(TOWNS, ST, "sevierville-junk.com")[0], "Sevierville, TN")
check("state name is not a market",
      app.markets_by_size(["Tennessee", "Knoxville, TN"], ST), ["Knoxville, TN"])

# ---- the pick, with the probe stubbed --------------------------------------
calls = []
VOL = {"fn": lambda kw: 100}


def fake_post(path, payload, **k):
    kws = list((payload or [{}])[0].get("keywords") or [])
    calls.append(kws)
    return {"tasks": [{"result": [{"keyword": kw, "search_volume": VOL["fn"](kw)}
                                  for kw in kws]}]}


app.dfs_post = fake_post
SEEDS = ["junk removal", "hauling", "commercial junk removal", "hoarding cleanup",
         "construction debris removal", "dumpster rental", "furniture removal",
         "appliance removal", "house cleanout", "estate cleanout", "demolition",
         "paper shredding"]

# Demand everywhere: the two biggest, one probe, and only they were asked about.
cities, pick = app.choose_build_markets(TOWNS, ST, SEEDS, "")
check("two markets for twelve seeds", len(cities), 2)
check("the two biggest", sorted(cities), sorted(by[:2]))
check("one probe", len(calls), 1)
two = [c.split(",")[0].lower() for c in by[:2]]
check("probe named only those two",
      all(any(t in kw for t in two) for kw in calls[0]), True)
check("probe ran (not the input-order fallback)", pick["method"] != "input order", True)
check("seed_markets", pick["seed_markets"], 2)
check("seeds", pick["seeds"], 12)
check("measured", pick["measured"], by[:2])
check("by_size names every market", [x[0] for x in pick["by_size"]], by)
check("not widened", "widened_from" in pick, False)

# Nothing measured anywhere: the probe reads geo-suffixed text, which in a
# small town is zero everywhere. That is not evidence for a different market,
# so the size order stands and no second probe is spent.
calls.clear()
VOL["fn"] = lambda kw: 0
cities, pick = app.choose_build_markets(TOWNS, ST, SEEDS, "")
check("zero probe: not widened", "widened_from" in pick, False)
check("zero probe: still the two biggest", sorted(cities), sorted(by[:2]))
# Two calls, not one: an all-zero client-term probe already falls back to
# the population proxy inside pick_grid_cities. What must NOT happen is a
# third, the widen re-probe of the whole list.
check("zero probe: no widen re-probe", len(calls), 2)
check("zero probe: says nothing measured", pick["nothing_measured"], True)

# Thin: the two biggest measure a little, under the floor; a smaller town
# measures a lot. That is evidence. Widened to the whole list under the old
# cap, and the town that measured leads.
calls.clear()
VOL["fn"] = lambda kw: 100 if "oak ridge" in kw else 3
cities, pick = app.choose_build_markets(TOWNS, ST, SEEDS, "")
check("widened from the two by size", pick.get("widened_from"), by[:2])
check("widen probed every market",
      all(any(c.split(",")[0].lower() in kw for kw in calls[-1]) for c in TOWNS
          if not app.county_key(c, ST)), True)
check("the market that measured leads", cities[0], "Oak Ridge, TN")
check("under the cap", len(cities) <= 5, True)
check("measured is the whole list", pick["measured"], by)
check("floor recorded", pick["floor"], 20)

# Fewer markets than the formula allows: all of them, and nothing to widen to.
calls.clear()
VOL["fn"] = lambda kw: 0
cities, pick = app.choose_build_markets(["Knoxville, TN"], ST, SEEDS, "")
check("one entered, one measured", cities, ["Knoxville, TN"])
check("nothing to widen to", "widened_from" in pick, False)

# No markets at all: same shape as before, nothing measured.
calls.clear()
cities, pick = app.choose_build_markets([], "", SEEDS, "")
check("no markets", cities, [])
check("seed_markets 0", pick["seed_markets"], 0)

# ---- the real-query rows: more of them, at the shared floor ----------------
check("near_me_terms", app.CFG["near_me_terms"], 8)
check("near_me_min_volume", app.CFG["near_me_min_volume"], 20)

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ok all")
sys.exit(1 if FAIL else 0)
