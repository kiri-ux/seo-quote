"""AI SEARCH CAN BE QUOTED ON ITS OWN.

Strategy offered three chips and one of them was "Core SEO + AI Search" -- a
single option naming two products, so AI Search could only ever be bought
bolted to Core SEO. There was no way to quote a client who wants the AI Search
work and nothing else. (2026-09-17)

Two things had to be true before the chip could be split.

THE CHIPS HAD TO REACH THE PRICE. They did not. The Strategy field fed the order
form, the proposal and the list column, and /api/price was never told, so an
adtini quote that said "Core SEO + AI Search" was priced as Core SEO and the AI
Search leg was a label with no money behind it.

AND A SOLO QUOTE HAD TO PRICE THE LEG, NOT THE PAIR. AI Search is a percentage
of the client's own Core SEO number, so that number is computed either way --
it is the BASIS. What changes is what is charged, and what Billing is handed:
a partner billed for a Core SEO campaign nobody bought is a real invoice, so
partner_hard_cost drops the leg too and margin_dollars follows it.

Old quotes are not touched: "Core SEO + AI Search" splits on " + " into the two
chips it names and joins again on save.
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

UI = open(os.path.join(SRCDIR, "templates", "adtini.html"), encoding="utf-8").read()
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
    return app.stage4_price(**args)["handoff"]


# ---------------------------------------------- the picker
check("AI Search is its own option", "AI Search" in app.STRATEGY_OPTIONS, True)
check("and the combined chip is gone",
      "Core SEO + AI Search" in app.STRATEGY_OPTIONS, False)
check("Core SEO still is one", "Core SEO" in app.STRATEGY_OPTIONS, True)
check("and so is the audit", "Website Audit" in app.STRATEGY_OPTIONS, True)

# ---------------------------------------------- the three shapes
core = price()
both = price(ai_search=True)
solo = price(ai_search=True, core_seo=False)

# The pair is what it always was: the two legs added together.
check("both chips price the pair",
      both["package"]["base"],
      core["package"]["base"] + both["ai_search_price"]["base"])
check("and Core SEO alone is unchanged by the split",
      core["package"], price(core_seo=True)["package"])

# THE WHOLE POINT. A solo quote charges the AI Search leg, not the pair.
check("AI Search alone charges the AI Search leg",
      solo["package"], both["ai_search_price"])
check("and not the pair", solo["package"]["base"] == both["package"]["base"], False)
check("nor the Core SEO figure",
      solo["package"]["base"] == core["package"]["base"], False)

# The basis is still reported, because the percentage is of something.
check("the Core SEO basis is still carried",
      solo["core_seo_price"], core["core_seo_price"])
check("and it is flagged as not sold", solo["core_seo_sold"], False)
check("while the pair is", both["core_seo_sold"], True)
check("and so is a Core SEO quote", core["core_seo_sold"], True)

# ---------------------------------------------- what Billing is handed
# A partner billed for a Core SEO campaign nobody bought is a real invoice.
check("Billing is not charged for the leg nobody bought",
      solo["partner_hard_cost"], solo["partner_ai_search_cost"])
check("and the Core SEO partner line is zero",
      set(solo["partner_core_seo_cost"].values()), {0})
check("the pair still bills both legs",
      both["partner_hard_cost"]["base"],
      both["partner_core_seo_cost"]["base"] + both["partner_ai_search_cost"]["base"])
# Package - Partner Hard Cost = Margin $, on every shape.
for name, h in (("Core SEO", core), ("both", both), ("AI Search alone", solo)):
    check("margin still reconciles on a %s quote" % name,
          {k: h["package"][k] - h["partner_hard_cost"][k] for k in h["package"]},
          h["margin_dollars"])

# ---------------------------------------------- the route, and old callers
check("the route reads it off the payload",
      'core_seo=bool(d.get("core_seo", True))' in open(SRC, encoding="utf-8").read(), True)
# Every caller that predates the split was quoting Core SEO, so absent is yes.
check("absent means Core SEO is being sold",
      price(ai_search=True)["core_seo_sold"], True)

# ---------------------------------------------- and the browser sends it
check("the builder sends what is being bought",
      "ai_search: hasStrategy(d, 'ai search')" in UI
      and "core_seo: hasStrategy(d, 'core seo')" in UI, True)
check("a stored quote still splits into chips",
      "String(i.strategy || 'Core SEO').split(' + ')" in UI, True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
