"""THE DECK IS THE QUOTE, SLIDE BY SLIDE.

The proposal document is the letter; the adtini product slides are what the
partner presents, and they were being rebuilt by hand from the product deck
every time -- which is where a Website Audit section reaches a client who
never bought one, and an AI Search price reaches one who is only buying Core
SEO.

So every slide here is checked against what the quote carries: the strategies
that were sold and no others, the keyword slide only for the search
strategies, the audit slide only for the audit, and on the pricing slide the
AI Search line and the add-on market box only when the quote holds them.
(2026-09-19, Kiri)
"""
import importlib.util
import io
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
import seo_pptx as P      # noqa: E402
from pptx import Presentation      # noqa: E402

FAIL, CHECKS = [], []
TITLE_LINE = "Search Engine Optimization+"


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


TERMS = ["apartments for rent san diego ca", "homes for sale san diego ca",
         "luxury apartments san diego ca", "homes for rent san diego ca",
         "new homes san diego ca", "studio apartments san diego ca"]
KW = {"ultra": [{"kw": TERMS[0]}, {"kw": TERMS[1]}],
      "competitive": [{"kw": TERMS[2]}, {"kw": TERMS[3]}],
      "long_tail": [{"kw": TERMS[4]}, {"kw": TERMS[5]}],
      "all": [{"kw": t} for t in TERMS]}


def quote(strategy, ai=True, addon=3, term=12):
    p = app.stage4_price("single_city", 550, False, addon, 35,
                         pct_not_ranking=100, total_volume=9220,
                         ai_search=ai, core_seo=True)
    return {"brand": "Escaya", "order_no": "44973", "strategy": strategy,
            "kw": KW,
            "table": [{"kw": TERMS[0], "pos": 3}, {"kw": TERMS[1], "pos": None}],
            "pricing": dict(p, addon_markets=addon, min_term_months=term,
                            client_addon_per_market=p.get(
                                "client_addon_per_market")),
            "serp": {"bytes": None}}


def deck(d):
    return Presentation(P.build_proposal_pptx(d))


def slides(prs):
    """Each slide as one flat string, which is how a reader meets it."""
    out = []
    for s in prs.slides:
        parts = []
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                parts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    parts += [c.text for c in row.cells]
        out.append(" · ".join(parts))
    return out


print("\nEVERYTHING SOLD, AND NOTHING ELSE")
# AI Search and Website Audit are never sold together (2026-10-26, Kiri), so
# the widest quote is Core SEO with the audit.
full = slides(deck(quote("Core SEO, Website Audit", ai=False)))
check("five slides on the full quote", len(full), 5)
check("the product and its SERP first",
      TITLE_LINE in full[0] and "Your SEO Campaign Will Include:" in full[0],
      True)
check("a capture that was never taken says so",
      "No SERP captured" in full[0], True)
check("strategy details second", "Strategy Details" in full[1], True)
check("with both strategies on it",
      all(s + ":" in full[1] for s in ("Core SEO", "Website Audit")), True)
# AN AUDIT QUOTE LEADS WITH THE AUDIT, then the tiers, then the keywords.
# (2026-10-26, Kiri)
check("audit details third", "Audit Details" in full[2], True)
check("product details fourth", "Product Details" in full[3], True)
check("and the keyword details last", "Keyword Details" in full[4], True)

print("\nA STRATEGY THAT WAS NOT SOLD IS NOT IN THE DECK")
core = slides(deck(quote("Core SEO", ai=False, addon=0, term=6)))
check("no audit slide", any("Audit Details" in s for s in core), False)
check("and no audit line on the strategy slide",
      "Website Audit:" in core[1], False)
check("nor an AI Search line", "AI Search:" in core[1], False)
check("the keyword slide stays, because SEO was sold",
      any("Keyword Details" in s for s in core), True)
check("and comes before pricing on a non-audit quote",
      "Keyword Details" in core[2] and "Product Details" in core[-1], True)

audit = slides(deck(quote("Website Audit", ai=False, addon=0)))
# AN AUDIT QUOTE CARRIES THE FULL CAMPAIGN TOO, for if they buy it after.
# (2026-10-15, Kiri)
check("an audit quote keeps the keyword slide",
      any("Keyword Details" in s for s in audit), True)
check("and the audit slide",
      any("Audit Details" in s for s in audit), True)
_aud = next(s for s in audit if "Audit Details" in s)
_apr = next(s for s in audit if "Product Details" in s)
check("the audit slide shows the one-time fee",
      "One-Time Fee: $2,950" in _aud, True)
check("the pricing slide carries the banner instead",
      "Three Tiers from Audit to SEO Campaign" in _apr
      and "One-Time Fee" not in _apr, True)
check("with the credit note",
      "credited back on your first month" in _apr, True)
check("and the campaign tiers under it",
      "Intermediate Campaign" in _apr, True)
check("an audit-only quote drops the months cell",
      "Months Running" in _apr, False)
check("but keeps the budget", "Monthly Budget (Intermediate)" in _apr, True)
check("a Core SEO + audit quote keeps the months cell",
      "Months Running" in full[3], True)
check("no fee on a quote that did not sell the audit",
      any("One-Time Fee" in s or "Three Tiers from Audit" in s
          for s in slides(deck(quote("Core SEO", ai=False)))), False)
# WEBSITE AUDIT IS NEVER SOLD WITH AI SEARCH. (2026-10-26, Kiri)
_aiaud = slides(deck(quote("Core SEO, AI Search, Website Audit")))
check("an AI Search quote drops the audit",
      any("Audit Details" in s or "Three Tiers from Audit" in s
          or "Website Audit:" in s for s in _aiaud), False)
check("and no audit fee is priced with AI Search",
      app.stage4_price("single_city", 0, False, ai_search=True,
                       website_audit=True)["handoff"]["website_audit_fee"], 0)

print("\nTHE AUDIT FEE")
_a = app.stage4_price("single_city", 0, False, website_audit=True)
check("$2,950 at 35%", _a["website_audit"]["fee"], 2950)
check("sent to the IO when sold", _a["handoff"]["website_audit_fee"], 2950)
check("partner cost sent", _a["handoff"]["partner_website_audit_cost"], 1917.5)
check("not in Package $", _a["handoff"]["package"], _a["client_tiers"])
# The planner can overwrite the rate-card partner fee. (2026-10-28, Kiri)
_o = app.stage4_price("single_city", 0, False, website_audit=True,
                      audit_override=2275)
check("an overwritten partner fee is sent", _o["handoff"]["partner_website_audit_cost"], 2275)
check("and the client fee follows it", _o["handoff"]["website_audit_fee"], 3500)
check("the route reads the override",
      'audit_override=d.get("audit_override")' in open(SRC, encoding="utf-8").read(), True)
check("zero on the IO when not sold",
      app.stage4_price("single_city", 0, False)["handoff"]["website_audit_fee"], 0)
check("moves with the margin",
      app.stage4_price("single_city", 0, False, markup_pct=20)
      ["website_audit"]["fee"], 2400)

print("\nTHE AI SEARCH PRICE ONLY WHEN IT IS IN THE QUOTE")
_q = quote("Core SEO, AI Search")
with_ai = slides(deck(_q))[-1]
# READ OFF THE QUOTE, NOT PINNED. These were hard-coded dollars, and a change
# to the ranking ladder -- which decides nothing about what the deck prints --
# failed five checks about layout. What is being tested is that the headline is
# both legs and the two named under it are its parts. (2026-09-21)
_pr = _q["pricing"]
_money = lambda v: "$" + format(int(v), ",")
_seo = _pr["client_tiers"]
_ai = _pr["ai_search"]["client_add"]
_both = _pr["ai_search"]["client_total"]
# THE HEADLINE IS WHAT THEY PAY. It was the Core SEO price with AI Search
# printed beside it, so the Monthly Budget above -- both legs -- matched no
# card on the slide.
check("the tier price is both legs together",
      f"{_money(_both['base'])} / month" in with_ai, True)
check("with Core SEO named under it",
      f"Core SEO: {_money(_seo['base'])} / month" in with_ai, True)
check("and AI Search under that",
      f"AI Search: {_money(_ai['base'])} / month" in with_ai, True)
check("and the two named parts add up to the headline",
      _seo["base"] + _ai["base"], _both["base"])
check("and the AI lines in the tier list",
      "AI model brand optimization" in with_ai, True)
check("and what the AI money buys",
      "premium placements per month within AI search results" in with_ai, True)
check("no AI Search line without it", "AI Search:" in core[-1], False)
check("and no split at all, because there is nothing to split",
      "Core SEO: $" in core[-1], False)
check("and none of its bullets either",
      "AI model brand optimization" in core[-1], False)
# AI Search is only sold with Core SEO (2026-10-28), so a quote asking for it
# alone prices the pair and prints both lines.
solo = app.stage4_price("single_city", 550, False, 0, 35, pct_not_ranking=100,
                        total_volume=9220, ai_search=True, core_seo=False)
d = quote("AI Search")
d["pricing"] = dict(solo, addon_markets=0, min_term_months=12)
only_ai = slides(deck(d))[-1]
check("an AI-only quote prices the AI campaign", "/ month" in only_ai, True)
check("and carries the AI Search line under it",
      "AI Search: $" in only_ai, True)

print("\nADD-ON MARKETS ONLY WHEN THEY ARE ON THE QUOTE")
check("the count and the rate are printed",
      "# of Add-on Markets: 3" in with_ai.replace("\n", " ")
      or "# of Add-on Markets: 3" in slides(deck(quote(
          "Core SEO, AI Search")))[-1], True)
check("and neither is printed without them",
      "Add-on" in core[-1], False)

print("\nTHE NUMBERS ARE THE QUOTE'S OWN")
check("the term is the quote's", "12-month term" in with_ai, True)
check("a six-month quote says six", "6-month term" in core[-1], True)
# Monthly budget is the intermediate tier, which is the headline the tool
# prints everywhere else, times the term it is sold on.
_mid = _both["intermediate"]
check("the budget is the intermediate tier, and says so",
      f"Monthly Budget (Intermediate): {_money(_mid)}" in with_ai, True)
check("and the total is that across the term",
      f"Total Budget: {_money(_mid * 12)}" in with_ai, True)
# A FILE CANNOT BE SELECTED ON SCREEN, so the tier the budget came from is
# marked on its own card.
check("the tier is marked on its own card too", "Selected" in with_ai, True)
check("the budget equals that card",
      f"{_money(_mid)} / month" in with_ai, True)

print("\nTHE FLIGHT IS WHAT WAS TYPED ON THE FORM")
flight = dict(quote("Core SEO, AI Search"),
              start_date="2025-05-01", end_date="2025-10-31", months="")
dated = slides(deck(flight))[-1]
check("the dates print across the top",
      "05/01/2025 - 10/31/2025" in dated, True)
check("and the months are read off them", "Months Running: 6" in dated, True)
check("the total is the budget across those months",
      f"Total Budget: {_money(_mid * 6)}" in dated, True)
# Typed months win, and an end date is worked out from them.
typed = dict(quote("Core SEO, AI Search"), start_date="2025-05-01", months="3")
check("months typed by hand set the end date",
      "05/01/2025 - 08/01/2025" in slides(deck(typed))[-1], True)
check("with no dates at all it falls back to the term",
      "Months Running: 12" in with_ai, True)
check("and never prints a range it does not have",
      "/2025 -" in with_ai, False)

print("\nTHE AI LINES CARRY THE SPARKLE")
check("the AI tier line is marked with it",
      "\u2726" in with_ai, True)
check("and a quote without AI Search has none",
      "\u2726" in core[-1], False)

print("\nTHE KEYWORD SLIDE IS THE LIST, NOT A SAMPLE OF IT")
kw_slide = slides(deck(quote("Core SEO")))[2]
for t in TERMS:
    check("carries " + t, t in kw_slide, True)
check("with the rank the check found", " 3 " in " " + kw_slide + " ", True)
check("and says so when it found none", "Not Found" in kw_slide, True)
check("the tiers are named",
      all(x in kw_slide for x in ("Ultra-Competitive", "Competitive",
                                  "Long-Tail")), True)
# LONGER THAN A SLIDE IS MORE SLIDES. A table cut to fit quotes a smaller
# engagement than the one being sold.
many = quote("Core SEO")
many["kw"] = dict(KW, all=[{"kw": "term %d" % i} for i in range(30)])
check("thirty terms run onto a second slide",
      sum("Keyword Details" in s for s in slides(deck(many))), 3)

print("\nA CHIP CAN CARRY TWO STRATEGIES")
# The form offers the pair as one chip, "Core SEO + AI Search", and reading
# the field on commas alone matched neither: a real quote came back with the
# product slide and the prices and nothing in between. (2026-09-19, Kiri)
pair = slides(deck(quote("Core SEO + AI Search")))
check("both are read off one chip",
      sorted(P._strategies({"strategy": "Core SEO + AI Search"})),
      ["AI Search", "Core SEO"])
check("a list of chips reads the same",
      sorted(P._strategies({"strategy": ["Core SEO + AI Search"]})),
      ["AI Search", "Core SEO"])
check("so the strategy slide is there",
      any("Strategy Details" in s for s in pair), True)
check("and the keyword slide with it",
      any("Keyword Details" in s for s in pair), True)
check("with both strategies on the strategy slide",
      "Core SEO:" in pair[1] and "AI Search:" in pair[1], True)

print("\nTHE LOGO IS A FILE, NOT A WORD")
check("the deck never sets the name in type",
      any("adtini" in s for s in pair), False)

print("\nTHE MAIN MARKET AND THE ADD-ONS ARE NAMED")
named = quote("Core SEO, AI Search")
named.update(main_market="Seattle, WA",
             addon_market_names=["Las Vegas, NV", "Reno, NV"])
price_slide = slides(deck(named))[-1]
check("the main market is on the pricing slide",
      "Main Market: Seattle, WA" in price_slide, True)
check("and the add-ons with it",
      "Add-on Markets: Las Vegas, NV, Reno, NV" in price_slide, True)
check("a quote with no add-ons names no market",
      "Main Market" in slides(deck(dict(quote("Core SEO", addon=0),
                                        main_market="Seattle, WA")))[-1], False)

print("\nAND IT COMES BACK AS A FILE")
app.app.config["TESTING"] = True
client = app.app.test_client()
r = client.post("/api/proposal.pptx", json=quote("Core SEO, AI Search"))
check("the endpoint answers", r.status_code, 200)
check("with a deck", r.data[:2], b"PK")
check("named for the client",
      "Escaya_44973.pptx" in r.headers.get("Content-Disposition", ""), True)
check("and it opens", len(Presentation(io.BytesIO(r.data)).slides) > 0, True)

print("\nTHE PROPOSAL DOCUMENT")
from docx import Document      # noqa: E402
def _doc_text(q):
    _d = Document(app.build_proposal_docx(q))
    return "\n".join([x.text for x in _d.paragraphs]
                     + [c.text for t in _d.tables for r in t.rows
                        for c in r.cells])
_ad = _doc_text(quote("Website Audit", ai=False, addon=0))
check("an audit quote prints the one-time fee",
      "One-time fee: $2,950 (sites under 1,000 total pages)" in _ad, True)
check("and the campaign options", "Option 2: Intermediate SEO Campaign" in _ad,
      True)
check("no audit section on a Core SEO quote",
      "One-time fee" in _doc_text(quote("Core SEO", ai=False)), False)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
