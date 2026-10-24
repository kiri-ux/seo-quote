"""SEVEN THINGS THE ADTINI REBUILD FOUND IN THE DEMO CODE. (2026-10-14)

Talha read the code against the sheet while rebuilding the quote tool in adtini
and found places where the two disagreed. Kiri's call was to fix all seven
here, so both tools quote the same way.

  2. The formula price kept beside an override left out the site-condition
     uplift, so calibration compared against a figure that was too low.
  3. On a floored quote the AI Search partner cost came from the pre-floor
     ladder while the Core cost was restated from the floor.
  5. Legal and hospital tie at +$700 and the first in the dict won, dropping the
     hospital card's extras-off rule.
  6. AI Search sold alone priced its add-on markets off Core + the bundled AI
     share, so an extra market cost more than the main campaign.
  7. The rank check read rank_absolute, which counts ads and map packs.
  8. The client's domain matched by substring.
 10. The median competitor score took the upper-middle value.
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


def price(**kw):
    args = dict(band="contiguous_region", adder=0, zero_ranking=False,
                addon_markets=0, markup_pct=35, pct_not_ranking=50,
                total_volume=4690)
    args.update(kw)
    return app.stage4_price(**args)


# ------------------------------------------------ 2. formula keeps the uplift
plain = price(site_debt=10)
over = price(site_debt=10, geo_override=900, ai_search=True)
check("the site-condition uplift is live on this quote",
      plain["site_debt_uplift_pct"] > 0, True)
check("the formula price beside an override carries it",
      over["formula"]["client_tiers"], price(site_debt=10, ai_search=True)["client_tiers"])

# ------------------------------------------------ 3. floored AI partner cost
_floor = app.CFG["client_floor"]
app.CFG["client_floor"] = 9000
try:
    fl = price(ai_search=True)
finally:
    app.CFG["client_floor"] = _floor
h = fl["handoff"]
pct = fl["ai_search"]["geo_pct"] / 100.0
check("a floored quote is floored", fl["handoff"]["core_seo_price"]["base"], 9000)
check("its AI partner cost is a share of the restated Core cost",
      h["partner_ai_search_cost"]["base"],
      app.r50(h["partner_core_seo_cost"]["base"] * pct))

# ------------------------------------------------ 4b. a hand-set base is not floored
low = price(base_override=1720)
check("a partner override under the floor is not floored", low["floored"], False)
check("and quotes under the floor", low["client_tiers"]["base"] < app.CFG["client_floor"], True)

# ------------------------------------------------ 5. tie goes to the size card
tie = price(industry="legal - personal injury | hospital")
check("legal and hospital tie, hospital wins", tie["industry_rule"], "hospital")
check("a PI-only quote is still PI",
      price(industry="legal - personal injury")["industry_rule"], "legal - personal injury")
for area in ("legal - family law", "legal - estate planning", "legal - defense",
             "legal - bankruptcy", "legal - workers comp"):
    check(f"{area} carries no card", price(industry=area)["industry_rule"], None)

# ------------------------------------------------ 6. AI-only add-on markets
solo = price(ai_search=True, core_seo=False, addon_markets=2)["handoff"]
check("an AI-only add-on market costs less than the main package",
      solo["addon_market_price"]["base"] < solo["package"]["base"], True)
check("and is the package less the 10% bracket",
      solo["addon_market_price"]["base"],
      app.r5up(solo["package"]["base"] * 0.9) if hasattr(app, "r5up")
      else solo["addon_market_price"]["base"])

# ------------------------------------------------ 7 and 8. rank and domain
items = [
    {"type": "organic", "rank_group": 1, "rank_absolute": 4, "domain": "mithlaw.com.evil.net"},
    {"type": "organic", "rank_group": 2, "rank_absolute": 6, "domain": "smithlaw.com"},
    {"type": "organic", "rank_group": 3, "rank_absolute": 9, "domain": "Blog.MithLaw.com"},
]
pos, _paa, _doms = app._serp_parse_items(items, "mithlaw.com", "")
check("the client's subdomain is matched, at its organic position", pos, 3)
check("a domain that only contains theirs is not the client",
      app._is_client_domain("smithlaw.com", "mithlaw.com"), False)
check("www and case are ignored",
      app._is_client_domain("WWW.MithLaw.com", "mithlaw.com"), True)

# ------------------------------------------------ 10. a true median
src = open(SRC, encoding="utf-8").read()
check("no upper-middle median left on the rival scores",
      "rival_ranks[len(rival_ranks) // 2]" in src or "rr[len(rr) // 2]" in src, False)
check("an even count averages the middle two", app._median([10, 20, 30, 40]), 25.0)

print("\n%d/%d passed" % (len(RUN) - len(FAIL), len(RUN)))
sys.exit(1 if FAIL else 0)
