"""MAINTENANCE OUT, AND THE IO TOLD WHAT IT IS PRICING OFF.

Maintenance was priced everywhere -- a Search Protection maintenance phase at
54.4% of the active rate, phrase maintenance at $750, auto-suggest and related
maintenance at $2,150 -- and none of it is sold. It is gone from the pricer,
the config panel, the formula panel and the two Brendan copy strings that
promised it to the client.

Three things the IO never received. Search Protection (reactive) and the Brand
Shield (proactive) collapsed into a single Monthly Budget, so the form could
not tell which half of the money was which. And neither figure the two are
priced off -- brand search volume, location count -- went over at all, so a
repriced quote had no way to reach the same number.
"""
import importlib.util
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
sys.path.insert(0, HERE)
import rep_pricing as R          # noqa: E402
import rep_docx as D             # noqa: E402

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


SKI_BARN = {"campaign": "bundle", "margin_pct": 0.35,
            "search": {"bundle": True, "volume": 8000},
            "shield": {"locations": 4},
            "reviews": {"count": 26},
            "articles": {"standard": 2, "premium": 1}}
q = R.build_rep_quote(SKI_BARN)
h = q["handoff"]
names = [l["service"] for l in q["lines"]]

print("\nNOTHING ON THE QUOTE IS A MAINTENANCE LINE")
check("no maintenance service",
      [n for n in names if "aintenance" in n], [])
check("no maintenance kind",
      sorted({l["kind"] for l in q["lines"]}),
      ["monthly", "per_asset"])
check("the pricer is gone",
      hasattr(R, "price_search_bundle_maintenance"), False)
check("so is its ratio", "maintenance_pct" in R.SEARCH_BUNDLE, False)
check("monthly kinds are just monthly", R.MONTHLY_KINDS, ("monthly",))

print("\nEVERY TACTIC LOST ITS MAINTENANCE RATE")
sp = R.REP_CFG["search_protection"]
for tactic in ("autosuggest", "related"):
    keys = [k for k in sp[tactic] if "maintenance" in k]
    check("%s carries none" % tactic, keys, [])
check("no maintenance in any timeline",
      [v for v in (sp["autosuggest"]["timeline"], sp["related"]["timeline"],
                   sp["alt_engine_timeline"]) if "aintenance" in v], [])

print("\nAND THE DOCUMENT STOPPED PROMISING IT")
check("the rates line drops its second sentence",
      D.COPY["search_rates"],
      "We have a 85+% success rate at removal of negative results over a "
      "6 month period.")
check("the basis line keeps its reason",
      "ongoing work" in D.COPY["search_basis"], True)
check("and promises no maintenance",
      "aintenance" in D.COPY["search_basis"], False)

print("\nTHE TWO BUNDLES GO OVER SEPARATELY")
check("reactive", h["search_protection_monthly"], 6500)
check("proactive", h["brand_shield_monthly"], 5600)
check("and still sum to the budget",
      h["search_protection_monthly"] + h["brand_shield_monthly"],
      h["monthly_budget"])
check("which is the Ski Barn figure", h["monthly_budget"], 12100)

print("\nWITH WHAT EACH IS PRICED OFF")
check("brand search volume", h["search_volume"], 8000)
check("location count", h["locations"], 4)

print("\nREACTIVE ONLY SENDS A ZERO, NOT A MISSING KEY")
r1 = R.build_rep_quote({"campaign": "reactive", "margin_pct": 0.35,
                        "search": {"bundle": True, "volume": 8000}})["handoff"]
check("no shield money", r1["brand_shield_monthly"], 0)
check("search money stands", r1["search_protection_monthly"] > 0, True)
check("locations defaults to one", r1["locations"], 1)
check("strategy", r1["strategy"], ["Reactive"])

print("\nPROACTIVE ONLY IS THE MIRROR")
r2 = R.build_rep_quote({"campaign": "proactive", "margin_pct": 0.35,
                        "shield": {"locations": 4}})["handoff"]
check("no search money", r2["search_protection_monthly"], 0)
check("shield money stands", r2["brand_shield_monthly"], 5600)
check("volume is zero, not absent", r2["search_volume"], 0)

print("\nA REMOVALS-ONLY QUOTE HAS NO MONTHLY AT ALL")
r3 = R.build_rep_quote({"campaign": "reactive", "margin_pct": 0.35,
                        "reviews": {"count": 26}})["handoff"]
check("nothing recurring", r3["monthly_budget"], 0)
check("both bundles zero",
      (r3["search_protection_monthly"], r3["brand_shield_monthly"]), (0, 0))
check("the removals still went", r3["reviews_count"], 26)

print("\nTHE TWO BUNDLES CARRY THEIR BRANDING")
check("reactive line", [l["service"] for l in q["lines"] if "Search Protection" in l["service"]],
      ["Reactive \u00b7 Search Protection"])
check("proactive line", [l["service"] for l in q["lines"] if "Brand Shield" in l["service"]],
      ["Proactive \u00b7 Brand Shield"])
check("the shield detail is not its own name again",
      [l["detail"] for l in q["lines"] if "Brand Shield" in l["service"]],
      ["4 locations (+$700/extra location)"])
check("one location reads singular",
      R.build_rep_quote({"campaign": "proactive", "margin_pct": 0.35,
                         "shield": {"locations": 1}})["lines"][0]["detail"],
      "1 location")

print("\nPARTNER COST FOR EVERY CLIENT FIGURE")
# The margin can change on the order form after the quote is built, and every
# client component rounds UP separately, so no client price divides back.
for c, pk in [("monthly_budget", "partner_monthly_cost"),
              ("search_protection_monthly", "partner_search_protection_monthly"),
              ("brand_shield_monthly", "partner_brand_shield_monthly"),
              ("price_per_review_removal", "partner_hard_cost_per_review"),
              ("price_per_standard_site_removal", "partner_hard_cost_per_standard_site"),
              ("price_per_premium_site_removal", "partner_hard_cost_per_premium_site")]:
    check("%s has a partner figure" % c, bool(h.get(pk)) and h[pk] > 0, True)
    check("  and it is below the client one", h[pk] < h[c], True)
check("reactive partner", h["partner_search_protection_monthly"], 4200)
check("proactive partner", h["partner_brand_shield_monthly"], 3600)
check("the two sum to the partner monthly",
      h["partner_search_protection_monthly"] + h["partner_brand_shield_monthly"],
      h["partner_monthly_cost"])
check("review removals at partner cost",
      h["partner_review_removals_total"], round(552.5 * 26, 2))
check("standard sites", h["partner_standard_sites_total"], 9750)
check("premium sites", h["partner_premium_sites_total"], 8125)

print("\nMARGIN DOLLARS, THE WAY THE SEO HANDOFF SENDS THEM")
# Client figures round UP and partner figures do not, so client x (1 - margin)
# does not return partner. The difference is stated instead of derived.
_md = h["margin_dollars"]
check("monthly", _md["monthly"],
      round(h["monthly_budget"] - h["partner_monthly_cost"], 2))
check("per asset", _md["per_asset"],
      round(q["totals"]["per_asset"]
            - (h["partner_review_removals_total"]
               + h["partner_standard_sites_total"]
               + h["partner_premium_sites_total"]), 2))
check("both positive", _md["monthly"] > 0 and _md["per_asset"] > 0, True)
check("and it is not the naive product",
      _md["monthly"] == round(h["monthly_budget"] * 0.35, 2), False)

print("\nA WORKSTREAM THAT IS NOT ON THE QUOTE SENDS ZERO, NOT A MISSING KEY")
_r = R.build_rep_quote({"campaign": "reactive", "margin_pct": 0.35,
                        "reviews": {"count": 5}})["handoff"]
for k in ("partner_search_protection_monthly", "partner_brand_shield_monthly",
          "partner_standard_sites_total", "partner_premium_sites_total"):
    check(k, _r[k], 0)
check("the review partner total still lands", _r["partner_review_removals_total"] > 0, True)

print("\nSTRATEGY IS FOUR VALUES, READ OFF THE QUOTE")
check("all four", h["strategy"],
      ["Review Removals", "Site/Article Removals", "Reactive", "Proactive"])
check("reviews alone",
      R.build_rep_quote({"campaign": "reactive", "margin_pct": 0.35,
                         "reviews": {"count": 26}})["handoff"]["strategy"],
      ["Review Removals"])
check("search alone",
      R.build_rep_quote({"campaign": "reactive", "margin_pct": 0.35,
                         "search": {"bundle": True, "volume": 8000}})["handoff"]["strategy"],
      ["Reactive"])
check("shield alone",
      R.build_rep_quote({"campaign": "proactive", "margin_pct": 0.35,
                         "shield": {"locations": 4}})["handoff"]["strategy"],
      ["Proactive"])
check("nothing selected", R.build_rep_quote({"campaign": "reactive"})["handoff"]["strategy"], [])

print("\nA REMOVAL CAN SIT BESIDE A BRAND SHIELD")
# It could not before: reviews and article removals were gated on the campaign
# word, so a proactive quote dropped them however many were flagged.
mix = R.build_rep_quote({"campaign": "proactive", "margin_pct": 0.35,
                         "shield": {"locations": 3}, "reviews": {"count": 10}})
check("both lines", [l["service"] for l in mix["lines"]],
      ["Negative Review Removals", "Proactive \u00b7 Brand Shield"])
check("and both strategies", mix["handoff"]["strategy"],
      ["Review Removals", "Proactive"])

print("\nNO PHASE SURVIVES")
check("the bundle block is gone", "bundle" in R.REP_CFG, False)
check("no bundle meta",
      R.build_rep_quote({"campaign": "bundle", "margin_pct": 0.35,
                         "shield": {"locations": 1}})["bundle_meta"], None)

print("\nONE SUCCESS RATE, AND THE DOCUMENT SAYS THE SAME")
# Three versions were in play: the tool's routing split (~100% priority,
# 40-50% bulk), a flat ~70%, and Brendan's split by review age. A client
# holding an SSG proposal can read his, so his is the one that ships.
_rev = [l for l in q["lines"] if l["service"] == "Negative Review Removals"][0]
check("stated once", [n for n in _rev["notes"] if "Success rate" in n],
      ["Success rate: ~60% on reviews newer than 6 months; ~50% on older ones."])
check("no routing split",
      [n for n in _rev["notes"] if "bulk routing" in n], [])
check("and no flat rate",
      [n for n in _rev["notes"] if "70%" in n], [])
check("the document carries the same split",
      D.COPY["reviews_rates"],
      "We have a roughly 60% success rate at removing reviews that are newer "
      "than 6 months old. We have a roughly 50% success rate at removing "
      "reviews which are older than 6 months.")

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
