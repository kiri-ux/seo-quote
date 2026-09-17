"""THE PAYLOAD THE PAGE SENDS, PRICED BY THE PRICER THAT SHIPS.

Three bugs in one quote, all the same shape: the page and the module agreed on
what a thing meant and disagreed on what it was called.

  * The page sent search.suppression. build_rep_quote gates Search Protection
    on search.bundle. So a Reactive quote came back "not on this quote" with a
    $0 monthly, however much brand volume the scan had measured.
  * The page read totals.removals_max and totals.total. The pricer returned
    one_time / monthly / per_asset. Both tiles printed a dash on every quote,
    and the saved record stored a one-time of 0.
  * Every stub in the browser tests had invented the missing keys, so all of
    it passed.

So this builds the payload the way generateOrm builds it and prices it with
the module that ships. No stubs on either side.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rep_pricing as R

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


def payload(strategy, **over):
    """What generateOrm posts to /api/rep_quote, key for key."""
    strat = set(strategy)
    d = dict(
        campaign=("bundle" if {"Proactive", "Reactive"} <= strat
                  else "proactive" if "Proactive" in strat else "reactive"),
        margin_pct=0.35,
        reviews={"count": over.get("reviews", 0)} if "Review Removals" in strat
                 else {"count": 0},
        articles=({"standard": over.get("std", 0), "premium": 0, "pages": []}
                  if "Site/Article Removals" in strat
                  else {"standard": 0, "premium": 0, "pages": []}),
        search={"volume": over.get("volume", 0),
                "bundle": "Reactive" in strat,
                "suppression": "Reactive" in strat,
                "autosuggest": False, "term_sets": 1, "pages": []},
        shield={"locations": over.get("locations", 1)},
        industry=over.get("industry", []),
        overrides={},
    )
    if "Proactive" not in strat:
        d["shield"]["enabled"] = False
    return d


# ---------------------------------------------- THE $0 QUOTE
# City Heating and Air as it was actually quoted: Reactive + Review Removals,
# 11 flagged reviews, 500/mo brand volume. It came back $0/mo.
q = R.build_rep_quote(payload(["Reactive", "Review Removals"], reviews=11, volume=500))
svc = [l["service"] for l in q["lines"]]
check("Reactive puts Search Protection on the quote",
      any("Search Protection" in x for x in svc), True)
check("and the monthly is not zero", q["totals"]["monthly"] > 0, True)
# At 500/mo the per-1K terms are pennies, so this is the two component bases:
# suppression 1750 and auto-suggest 2250, each CEIL50'd, = 4100 hard, and
# 4100/0.65 CEIL50'd = 6350 client. The SEARCH_BUNDLE floor of 3950 never
# binds, because the bases already clear it before any volume is added.
check("the floor never binds, the bases do", q["totals"]["monthly"], 6350)
check("the review removals are on it too",
      any("Review Removal" in x for x in svc), True)
check("at the rate card's 1-25 price", q["handoff"]["price_per_review_removal"], 900)

# ---------------------------------------------- THE TILES THAT PRINTED A DASH
check("removals_max is sent under the name the screen reads",
      q["totals"]["removals_max"], 11 * 900)
check("and it is the pay-on-success per-asset sum",
      q["totals"]["removals_max"], q["totals"]["per_asset"])
# There is deliberately no totals.total: a recurring monthly and a
# pay-on-success maximum do not add up to a number anyone can quote.
check("no single total is claimed", "total" in q["totals"], False)

# ---------------------------------------------- every strategy reaches a line
for strat, want in [
        (["Reactive"], "Search Protection"),
        (["Proactive"], "Brand Shield"),
        (["Review Removals"], "Review Removal"),
        (["Site/Article Removals"], "Website/Article Removals")]:
    p = payload(strat, reviews=4, std=2, volume=9000, locations=2)
    if "Proactive" in strat:
        p["shield"] = {"locations": 2, "enabled": True}
    got = [l["service"] for l in R.build_rep_quote(p)["lines"]]
    check("%s prices a line" % strat[0], any(want in x for x in got), True)
    check("  and only that one", len(got), 1)

# ---------------------------------------------- the strategy travels back
both = payload(["Reactive", "Proactive", "Review Removals", "Site/Article Removals"],
               reviews=4, std=2, volume=9000, locations=3)
both["shield"] = {"locations": 3, "enabled": True}
qb = R.build_rep_quote(both)
check("all four workstreams read back off the quote",
      sorted(qb["handoff"]["strategy"]),
      ["Proactive", "Reactive", "Review Removals", "Site/Article Removals"])
check("the two recurring bundles go over separately",
      qb["handoff"]["search_protection_monthly"] > 0
      and qb["handoff"]["brand_shield_monthly"] > 0, True)
check("and they add to the monthly budget",
      qb["handoff"]["search_protection_monthly"]
      + qb["handoff"]["brand_shield_monthly"], qb["handoff"]["monthly_budget"])

# ---------------------------------------------- industry rides along
check("industry is carried to the order form",
      R.build_rep_quote(payload(["Reactive"], volume=500,
                                industry=["Home Services - HVAC"]))["handoff"]["industry"],
      ["Home Services - HVAC"])

# ---------------------------------------------- volume moves the monthly
# The bundle is priced off brand volume, so the terms fix that cut City Heating
# and Air from 3,190/mo to 480 has to move this number.
lo = R.build_rep_quote(payload(["Reactive"], volume=480))["totals"]["monthly"]
hi = R.build_rep_quote(payload(["Reactive"], volume=51330))["totals"]["monthly"]
check("brand volume moves the Search Protection monthly", hi > lo, True)
check("and 51,330/mo is the Sage figure", hi, 7550)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
