"""WHO HOLDS PAGE ONE, AS OPPOSED TO HOW STRONG THEY ARE.

Nob Hill Dental and Amare Homes are identical on every number the formula reads
-- twenty terms, one city, 80% not ranking, no volume, no adder -- and Brendan
sent $2,950 and $3,550. The one thing that differs is who is on page one:
Zillow, Trulia, Redfin and Apartments.com for Amare, five other Salem dentists
for Nob Hill. pageone_aggregator_add is that difference, and this is the test
that it fires on one and not the other.

The alternative that was NOT taken is in the first section too: both clients
read 80% not ranking, so raising the zero-ranking ladder would have charged
both. A lever that cannot separate two clients priced $600 apart is not the
lever.
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


# Amare's page one, as pageone_strength's own note describes it, with a local
# realty site and the client's own Facebook page in the mix.
AMARE = [{"domain": "zillow.com", "appearances": 9},
         {"domain": "apartments.com", "appearances": 8},
         {"domain": "trulia.com", "appearances": 6},
         {"domain": "redfin.com", "appearances": 5},
         {"domain": "rent.com", "appearances": 4},
         {"domain": "santafeproperties.com", "appearances": 3},
         {"domain": "facebook.com", "appearances": 4},
         {"domain": "localrealty.com", "appearances": 2}]

# Nob Hill's: other dentists, with the Yelp and Healthgrades every local SERP
# carries. Real aggregators, nowhere near most of the page.
NOBHILL = [{"domain": "salemdental.com", "appearances": 7},
           {"domain": "willamettedental.com", "appearances": 6},
           {"domain": "yelp.com", "appearances": 5},
           {"domain": "capitoldentalcare.com", "appearances": 5},
           {"domain": "smilesalem.com", "appearances": 4},
           {"domain": "healthgrades.com", "appearances": 3}]


def price(rows, **kw):
    agg = app.pageone_aggregators(rows) if rows is not None else {"share": None,
                                                                  "terms": None}
    args = dict(band="single_city", adder=0, total_volume=0,
                pct_not_ranking=80.0)
    args.update(kw)
    return app.stage4_price(args["band"], args["adder"], False, 0, 35.0,
                            pct_not_ranking=args["pct_not_ranking"],
                            total_volume=args["total_volume"],
                            industry=args.get("industry", ""),
                            pageone_agg_share=agg["share"],
                            pageone_agg_terms=agg["terms"])


print("\nTHE TWO CLIENTS THE FORMULA COULD NOT TELL APART")
amare, nob = price(AMARE), price(NOBHILL)
check("Amare lands on the price Brendan sent",
      amare["client_tiers"]["base"], 3550)
check("Nob Hill does not move", nob["client_tiers"]["base"], 3100)
check("and the difference is the page-one component alone",
      amare["client_tiers"]["base"] - nob["client_tiers"]["base"], 450)
check("both read the same ranking coverage, which is the point",
      (amare["pct_not_ranking"], nob["pct_not_ranking"]), (80.0, 80.0))
check("Amare's add is the constant", amare["pageone_aggregator_add"], 300)
check("Nob Hill's is nothing", nob["pageone_aggregator_add"], 0)

print("\nTHE MEASUREMENT")
a = app.pageone_aggregators(AMARE)
n = app.pageone_aggregators(NOBHILL)
check("Amare's page one is aggregator-held", round(a["share"], 2), 0.86)
check("Nob Hill's is not", round(n["share"], 2), 0.27)
check("a social profile counts for nobody, either way",
      a["slots"], 9 + 8 + 6 + 5 + 4 + 3 + 2)
check("and the aggregators are named",
      a["domains"],
      ["apartments.com", "redfin.com", "rent.com", "trulia.com", "zillow.com"])
check("a subdomain of an aggregator is the aggregator",
      app._is_aggregator("biz.yelp.com"), True)
check("a domain that merely ends in the same letters is not",
      app._is_aggregator("notzillow.com"), False)

print("\nNOT MEASURED IS NOT ZERO")
blind = price(None)
check("an unread page one adds nothing",
      blind["pageone_aggregator_add"], 0)
check("and says so rather than reading as no aggregators",
      blind["pageone_aggregator_measured"], False)
check("the reason is on the quote",
      blind["pageone_aggregator_why"], "page one not measured")
check("a two-term read is too thin to fire",
      app.pageone_aggregator_add(1.0, 2)[0], 0)
check("three is the minimum", app.pageone_aggregator_add(1.0, 3)[0], 300)

print("\nTHE CAP IS WHY THE SHARE IS COUNTED BEFORE THE LIST IS CUT")
# serp_rival_cap sorts by appearances and keeps the top of the list, which is
# exactly the shape of an aggregator. A Yelp and a Healthgrades on most terms,
# and twenty local practices holding one slot each: a page one the client can
# win, and two thirds of it local -- until the cap throws the locals away.
counts = {"yelp.com": 8, "healthgrades.com": 5}
counts.update({f"dentist{i}.com": 1 for i in range(20)})
full = app.aggregators_from_counts(counts, 20)
capped = app.pageone_aggregators(
    sorted([{"domain": d, "appearances": c} for d, c in counts.items()],
           key=lambda r: -r["appearances"])[:3])
check("the honest share stays under the cut", full["share"] < 0.5, True)
check("the truncated one would have fired", capped["share"] >= 0.5, True)

print("\nA BIG-ORG CARD MUTES IT")
# hospital/telehealth/behavioral health price on the size of the organisation
# rather than on SERPs, and stacking a page-one premium on one is the
# double-count the insurance card already paid for.
hosp = price(AMARE, industry="Health Services - Hospital")
check("the add is zeroed", hosp["pageone_aggregator_add"], 0)
check("and the quote says why",
      "muted" in hosp["pageone_aggregator_why"], True)

print("\nA HAND-SET BASE IS THE WHOLE BASE")
manual = app.stage4_price("single_city", 0, False, 0, 35.0, pct_not_ranking=80.0,
                          total_volume=0, base_override=2500,
                          pageone_agg_share=0.86, pageone_agg_terms=20)
check("the add is not in the price", manual["base"], 2500)
check("and is not reported as though it were",
      manual["pageone_aggregator_add"], 0)


print("\nTHE CONSTANT IS THE REVERT")
_old = app.CFG["pageone_aggregator_add"]
try:
    app.CFG["pageone_aggregator_add"] = 0
    check("zero puts Amare back where it was",
          price(AMARE)["client_tiers"]["base"], 3100)
finally:
    app.CFG["pageone_aggregator_add"] = _old

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
