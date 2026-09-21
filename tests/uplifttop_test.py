"""THE TOP OF THE RANKING LADDER, AND WHAT THE UPLIFT APPLIES TO.

Two changes on 2026-09-21, and they only work together.

The ladder stopped at 80%+, which put a client with footholds on a few terms
and one with nothing anywhere on the same rung. Ranking coverage is the
strongest signal in the recorded book -- Spearman +0.59 against the gap, ahead
of the adder, volume and page-one occupancy -- and every client the bench has
the tool under-quoting sits at 90-100%.

The uplift could not be sized for them while it multiplied the volume add,
because then the same reading was worth a different amount of money to every
client: 18% of a base carrying $2,000 of volume is nothing like 18% of a bare
anchor. It also charged one fact twice, since vol_add_ramp already scales the
volume add by the same percentage. So the uplift comes off the volume add, and
the rung can be sized on the fact it describes.

What this file guards: the clients that must not move, the clients that must,
and the cliff -- because a step function on a percentage quantised by the term
count is exactly the hard gate vol_add_ramp was built to remove.
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

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


def base(nr, vol=0, band="contiguous_region", **kw):
    return app.stage4_price(band, kw.pop("adder", 0), False, 0, 35.0,
                            pct_not_ranking=float(nr), total_volume=vol,
                            **kw)["client_tiers"]["base"]


print("\nTHE RUNG SEPARATES CLIENTS THE OLD TOP LUMPED TOGETHER")
check("80% and 100% no longer price the same", base(80) == base(100), False)
check("and the ladder runs the right way",
      base(80) < base(85) < base(90) < base(95) <= base(100), True)
# Amare and Nob Hill are both at 80 and both already right. The boundary is
# what keeps them still, so it is checked rather than assumed.
check("nothing at 80 moves, which is where Amare and Nob Hill sit",
      app._tier_uplift(80.0, app.CFG["zero_ranking_tiers"]), 7)
check("and nothing below it moves either",
      [app._tier_uplift(v, app.CFG["zero_ranking_tiers"]) for v in (0, 30, 49, 65)],
      [0, 0, 0, 4])

print("\nTHE UPLIFT IS OFF THE VOLUME ADD")
# vol_add_ramp already scales the volume add from nothing at 40% not ranking to
# the whole of it at 100%. Multiplying that by the uplift charges the same
# reading twice.
lo, hi = base(100, vol=0), base(100, vol=60000)
add = app._volume_dollar_add(60000, app.CFG["vol_free_below"],
                             app.CFG["volume_brackets"])
add = min(add, app.CFG["volume_add_cap"])
# The volume money arrives at cost and is marked up, but it is NOT uplifted --
# so the difference between the two quotes is the add through the margin alone.
check("volume money is not multiplied by the uplift",
      abs((hi - lo) - round(add / 0.65 / 50) * 50) <= 100, True)
check("a client with no volume is unaffected by the rule",
      base(100, vol=0) > base(80, vol=0), True)

print("\nWHAT IT COSTS, SAID OUT LOUD")
# A client between 65 and 80 with heavy volume prices LOWER than it did. No
# quote in the book has that shape, so this is reasoned rather than fitted --
# pinned here so the first one that turns up is checked against it.
# It was $5,800 when the uplift multiplied the volume add too.
check("65-80% with heavy volume prices lower", base(80, vol=135000), 5650)
check("and the same client with no volume does not move at all",
      base(80, vol=0), 3100)

print("\nTHE CLIFF IS THE THING TO WATCH")
# The percentage is quantised by however many terms got measured: on a 25-term
# list each term is four points. A step function on it is a hard gate, which is
# what vol_add_ramp exists to have removed.


def swing(n_terms, vol=133860):
    def at(k):
        return app.stage4_price("contiguous_region", 0, False, 0, 35.0,
                                pct_not_ranking=round((1 - k / n_terms) * 100),
                                total_volume=vol)["handoff"]["package"]["base"]
    return max(abs(at(k) - at(k - 1)) for k in range(1, n_terms + 1))


check("no step in the ladder is worth more than 4 points",
      max(a[1] - b[1] for a, b in
          zip(app.CFG["zero_ranking_tiers"], app.CFG["zero_ranking_tiers"][1:])), 4)
check("one keyword still moves a 25-term quote by at most $400",
      swing(25) <= 400, True)
check("and a ten-term list is no coarser than it was", swing(10), 850)

print("\nTHE BENCH, WHICH IS WHAT IT WAS FITTED ON")
spec2 = importlib.util.spec_from_file_location(
    "pb", os.path.join(SRCDIR, "tools", "pricebench.py"))
pb = importlib.util.module_from_spec(spec2)
sys.modules["pb"] = pb
spec2.loader.exec_module(pb)
got = {d["name"]: pb.quote(d)[0]["base"] for d in pb.BENCH}
check("MPG lands on the price he sent", got["MPG Gummies"], 3950)
check("Skidmore comes within $100", abs(got["Skidmore Studio"] - 3950) <= 100, True)
check("Cota Vera closes most of its gap, and not all of it",
      4250 - got["Cota Vera"], 300)
check("Amare does not move", got["Amare Homes"], 3550)
check("and the floor clients do not move",
      [got[n] for n in ("Visit Central PA", "Junk Bee Gone",
                        "Keller Builds", "Red Shoes")], [2950] * 4)

print("\nTHE STEP IS FLAT IN DOLLARS ABOVE THE FLOOR")
# His step as a share of the base FALLS as the base rises -- 28% at $4,250, 24%
# at $5,450, 19% at $6,950 -- so a percentage cannot describe it. In dollars it
# sits still: every premium step in the book is $1,200-$1,700, median $1,300.


def step_of(nr, vol=0, band="contiguous_region", adder=0):
    t = app.stage4_price(band, adder, False, 0, 35.0, pct_not_ranking=float(nr),
                         total_volume=vol)["client_tiers"]
    return t["intermediate"] - t["base"], t["advanced"] - t["intermediate"]


check("the step is the same size on both rungs",
      len(set(step_of(100, vol=60000))), 1)
check("a premium client steps $1,300", step_of(100, vol=60000)[0], 1300)
check("and so does a much bigger one, because it is capped",
      step_of(100, vol=600000)[0], 1300)
# The three clients sitting exactly on a $1,000 step are what the flat floor is
# for, and the lift-off point has to clear them with room rather than by a
# rounding step. 0.36 scores the same and holds only because 1850 x 0.36 rounds
# to exactly 650.
check("a floor client still steps $1,000", step_of(5)[0], 1000)
check("with room under the lift-off, not a rounding step",
      app.CFG["tier_step_pct_of_base"] * 1850 < app.CFG["tier_step_flat"], True)
check("and the cap is the median premium step he sends",
      round(app.CFG["tier_step_cap"] / 0.65 / 50) * 50, 1300)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
