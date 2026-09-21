"""THE VOLUME CURVE, AND THE PROMISE THAT COMES WITH RESHAPING IT.

2026-09-17, Brendan on Seascape, Inc: "I would have quoted this as $6950 for
entry, $8,250 for intermediate and $9,950 for advanced." The tool said
$3,800/$4,800/$5,800. Volume was the only lever that could reach him -- a $6.12
median bid earns $15.91 of competitive adder -- and volume_add_cap at $450
saturated at 20,000/mo, so 20k, 51k, 150k and 500k all added exactly the same
$450.

THE PROMISE: the reshape buys the top of the curve and touches nothing else.
Every client Brendan has already priced sits below 25,000/mo, and none of them
may move by a dollar.

Keeping that promise took two attempts. The first replaced the old rate AND the
cap with one low rate that hit $481 at 25k -- matching at the ends and sagging
in the middle, quietly cutting every 12,000-22,000/mo client by up to $193
partner, about $300 client. THE BENCH DID NOT CATCH IT, because no calibration
client sits in that band with demand still uncaptured, and a bench only sees the
clients in it. A sweep of the input space did, which is why this file sweeps
rather than spot-checks.

The old cap was a zero-rate bracket -- at $450 it bound from 16,410/mo up -- and
writing it out as one makes the promise exact instead of approximate.
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


# The curve exactly as it shipped before 2026-09-17, kept as the thing the
# promise is measured against. tools/proposals/pre_seascape_volume.json is the
# same numbers, for running the bench against.
WAS_CAP = 450
WAS_BRACKETS = [[10000, 20000, 0.0702], [20000, 35000, 0.0439],
                [35000, 50000, 0.0351], [50000, None, 0.0263]]
FREE = 10000


def add(vol, brackets, cap):
    return min(app._volume_dollar_add(vol, FREE, brackets), cap)


def now(vol):
    return add(vol, app.CFG["volume_brackets"], app.CFG["volume_add_cap"])


def was(vol):
    return add(vol, WAS_BRACKETS, WAS_CAP)


# ---------------------------------------------- the promise, swept
# Every $100 of volume from nothing to 25,000/mo, through the whole pricer --
# the quote is what was promised, not the float behind it. A spot check at the
# ends is exactly what missed the sag.
def priced(vol, brackets, cap, nr=100):
    keep = (app.CFG["volume_brackets"], app.CFG["volume_add_cap"])
    app.CFG["volume_brackets"], app.CFG["volume_add_cap"] = brackets, cap
    try:
        return app.stage4_price(band="contiguous_region", adder=0, zero_ranking=False,
                                markup_pct=35, pct_not_ranking=nr,
                                total_volume=vol)["handoff"]["package"]
    finally:
        app.CFG["volume_brackets"], app.CFG["volume_add_cap"] = keep


SHIPS = (app.CFG["volume_brackets"], app.CFG["volume_add_cap"])
drift = [v for v in range(0, 25001, 100)
         if priced(v, *SHIPS) != priced(v, WAS_BRACKETS, WAS_CAP)]
check("no quote at or below 25,000/mo moves by a dollar", drift[:5], [])
check("and that is 251 volumes checked, not three",
      len(range(0, 25001, 100)), 251)
# Checked at the coverage that makes the volume add bite hardest AND at the
# ramp's midpoint, where a fractional difference has the best chance of
# crossing a $50 rounding boundary.
drift50 = [v for v in range(0, 25001, 100)
           if priced(v, *SHIPS, nr=50) != priced(v, WAS_BRACKETS, WAS_CAP, nr=50)]
check("half-ramped clients do not move either", drift50[:5], [])

# ---------------------------------------------- and it only ever goes up
lower = [(v, was(v), now(v)) for v in range(0, 600001, 500) if now(v) < was(v)]
check("no volume anywhere adds less than it used to", lower[:5], [])

# ---------------------------------------------- the top of the curve moves
check("the free floor is untouched", (now(9999), now(10000)), (0, 0))
# Rounded up to the whole search, so the band closes a nickel over $450 rather
# than two cents under it -- the direction that cannot make anyone cheaper.
check("the old cap's knee is where it was", round(now(16411), 2), 450.05)
check("the flat stretch is still flat", now(18000), now(25000))
check("and sits on the old cap", round(now(25000)), 450)
# THE WHOLE POINT. Above the fitted range the curve is a curve again.
check("26,000 is the first volume that moves", now(26000) > was(26000), True)
check("and it keeps climbing", now(30000) < now(51690) < now(135000), True)
check("Seascape's own volume clears the old cap by a multiple",
      now(51690) > WAS_CAP * 4, True)
# It still has a ceiling: a freak volume cannot run away with the price.
check("the new cap still binds somewhere", now(10 ** 7), app.CFG["volume_add_cap"])

# ---------------------------------------------- monotonic, with no cliffs
vals = [now(v) for v in range(0, 300001, 250)]
check("the curve never goes backwards",
      all(b >= a for a, b in zip(vals, vals[1:])), True)
# A $900 jump between two adjacent clients is a number nobody can defend in a
# room; it is why vol_add_ramp exists rather than a hard gate at 50%.
steps = [b - a for a, b in zip(vals, vals[1:])]
check("and never jumps more than $50 between adjacent volumes",
      max(steps) <= 50, True)

# ---------------------------------------------- through the whole pricer
def base(vol, nr=100, band="contiguous_region"):
    return app.stage4_price(band=band, adder=0, zero_ranking=False, markup_pct=35,
                            pct_not_ranking=nr,
                            total_volume=vol)["handoff"]["package"]["base"]


check("Seascape lands on Brendan's entry price, within $150",
      abs(base(51690) - 6950) <= 150, True)
# WAS 3,800, AND THE VOLUME CURVE IS NOT WHAT MOVED IT (2026-09-21). This
# helper prices at 100% not ranking, which now draws the top zero-ranking rung
# (+18% where it used to be +7%) and no longer carries that uplift on the
# volume add at all. The volume component itself is unchanged -- the pure-curve
# checks above still pass on the same figures -- so the number is restated
# rather than the curve re-fitted.
check("and a 20,000/mo client is where the ranking ladder puts it",
      base(20000), 4100)
check("with the volume component itself untouched",
      round(app._volume_dollar_add(20000, app.CFG["vol_free_below"],
                                   app.CFG["volume_brackets"]), 2), 450.05)
# THE OTHER HIGH-VOLUME CLIENT IN THE BOOK POINTS THE OTHER WAY. Susquehanna is
# 135,000/mo and was quoted at the floor, because it already ranks for 60% of
# its head terms. vol_add_ramp is the whole reconciliation, and a steeper curve
# leans on it harder -- so it is checked here, not assumed.
check("a client that already ranks still pays nothing for volume",
      base(135000, nr=40), base(0, nr=40))
check("even at the very top of the curve",
      base(600000, nr=40), base(0, nr=40))
check("and the ramp still ramps rather than cliffing",
      base(51690, nr=40) < base(51690, nr=50) < base(51690, nr=60), True)

# ---------------------------------------------- the ramp, widened with it
# THE RAMP SMOOTHS A PERCENTAGE THAT IS QUANTISED BY THE TERM COUNT. On a
# 25-term list each term is four points, so "linear, no discontinuity" was only
# ever true of the percentage, not of the quote. At a $450 add that was worth
# $135 a keyword and nobody noticed. At $2,500 one term falling out of the top
# 100 moved Susquehanna $750 -- a bigger cliff than the hard gate the ramp was
# built to remove, arrived at from the other direction.
check("the ramp is wider than the add it now scales",
      app.CFG["vol_add_ramp"], [40, 100])


def swing(n_terms, vol=133860):
    """The most one keyword can move a quote, on a list of n measured terms."""
    def at(k):
        return app.stage4_price(band="contiguous_region", adder=0, zero_ranking=False,
                                markup_pct=35, pct_not_ranking=round((1 - k / n_terms) * 100),
                                total_volume=vol)["handoff"]["package"]["base"]
    return max(abs(at(k) - at(k - 1)) for k in range(1, n_terms + 1))


# The list lengths Brendan actually writes: his proposals run 20 to 99 terms.
check("one keyword moves a 25-term quote by at most $400", swing(25) <= 400, True)
check("and a 99-term quote by at most $350", swing(99) <= 350, True)
# A ten-term list is the worst case and is still the worst case -- it is just
# well under half what it was. Pinned so nobody reads the line above as "solved".
check("a ten-term list is still coarse, at $850", swing(10), 850)

# ---------------------------------------------- and the bottom end did not move
# THE BOTTOM OF THE RAMP IS A CALIBRATED DATAPOINT AND THE TOP NEVER WAS.
# Widening both ends (the first attempt, 30/80) pulled Susquehanna off the floor
# -- at 40% not ranking they stopped being free, $2,950 -> $3,950, a thousand
# over what Brendan quoted, breaking the one actual the whole "volume is
# opportunity, not demand" rule rests on. Nothing in the book sits between 60%
# and 100% not ranking, so stretching the top is free.
check("40% not ranking still pays nothing for volume",
      base(133860, nr=40), base(0, nr=40))
check("and 39% certainly does", base(133860, nr=39), base(0, nr=39))
check("full price needs a client ranking for nothing at all",
      base(133860, nr=100) > base(133860, nr=99), True)
check("90% not ranking is no longer the same as 100%",
      base(133860, nr=90) < base(133860, nr=100), True)

# ---------------------------------------------- the knobs stay editable
SOURCE = open(SRC, encoding="utf-8").read()
for k in ("volume_add_cap", "vol_free_below"):
    check("%s is per-quote editable" % k, k in SOURCE, True)
check("and so are the brackets", '"volume_brackets" in d' in SOURCE, True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
