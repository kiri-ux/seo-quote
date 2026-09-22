"""THE MULTI-SITE DISCOUNT IS A CHECKBOX AND A LINE-ITEM COUNT.

1-9 line items 5% off, 10-25 10%, 26+ 15%. SEO: every client figure. ORM: the
monthly lines only -- removals stay at full rate. Partner cost never moves.
(2026-09-22, Kiri)
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
import rep_pricing as rp


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name
          + ("" if ok else f"  got {got!r} want {want!r}"))
    return 0 if ok else 1


bad = 0
for n, want in ((0, 0), (1, 5), (9, 5), (10, 10), (25, 10), (26, 15), (100, 15)):
    bad += check(f"{n} line items -> {want}%", rp.multisite_pct(n), want)

# ---- SEO
a = app.stage4_price("single_city", 200, False, 2, 35, ai_search=True)
b = app.stage4_price("single_city", 200, False, 2, 35, ai_search=True,
                     multisite_items=12)
for k in a["client_tiers"]:
    bad += check(f"SEO {k} tier 10% off", b["client_tiers"][k],
                 round(a["client_tiers"][k] * 0.9))
    bad += check(f"SEO {k} package 10% off", b["handoff"]["package"][k],
                 round(a["handoff"]["package"][k] * 0.9))
    bad += check(f"SEO {k} margin $ is package less partner",
                 b["handoff"]["margin_dollars"][k],
                 b["handoff"]["package"][k] - b["handoff"]["partner_hard_cost"][k])
bad += check("SEO partner cost unchanged", b["handoff"]["partner_hard_cost"],
             a["handoff"]["partner_hard_cost"])
bad += check("SEO handoff carries the rate", b["handoff"]["multisite_discount_pct"], 10)
bad += check("SEO handoff carries the count", b["handoff"]["multisite_line_items"], 12)
bad += check("SEO unticked is untouched", a["handoff"]["multisite_discount_pct"], 0)

with app.app.test_client() as c:
    req = {"band": "single_city", "adder": 200, "markup_pct": 35}
    off = c.post("/api/price", json=dict(req, multisite=False, multisite_items=30)).get_json()
    on = c.post("/api/price", json=dict(req, multisite=True, multisite_items=30)).get_json()
    bad += check("/api/price ignores the count when unticked",
                 off["multisite_discount_pct"], 0)
    bad += check("/api/price applies 15% when ticked", on["multisite_discount_pct"], 15)
    bad += check("/api/price base tier 15% off", on["client_tiers"]["base"],
                 round(off["client_tiers"]["base"] * 0.85))

# ---- ORM
p = {"campaign": "bundle", "margin_pct": .35, "reviews": {"count": 5},
     "articles": {"standard": 2, "premium": 0},
     "search": {"volume": 5000, "bundle": True},
     "shield": {"locations": 3, "enabled": True}}
q0 = rp.build_rep_quote(p)
q1 = rp.build_rep_quote(dict(p, multisite=True, multisite_items=30))
for l0, l1 in zip(q0["lines"], q1["lines"]):
    want = round(l0["total"] * 0.85) if l0["kind"] == "monthly" else l0["total"]
    bad += check(f"ORM {l0['service']}", l1["total"], want)
bad += check("ORM monthly budget 15% off", q1["handoff"]["monthly_budget"],
             sum(round(l["total"] * 0.85) for l in q0["lines"] if l["kind"] == "monthly"))
bad += check("ORM removal rate unchanged", q1["handoff"]["price_per_review_removal"],
             q0["handoff"]["price_per_review_removal"])
bad += check("ORM partner monthly unchanged", q1["handoff"]["partner_monthly_cost"],
             q0["handoff"]["partner_monthly_cost"])
bad += check("ORM handoff carries the rate", q1["handoff"]["multisite_discount_pct"], 15)
q2 = rp.build_rep_quote(dict(p, multisite=False, multisite_items=30))
bad += check("ORM unticked is untouched", q2["handoff"]["monthly_budget"],
             q0["handoff"]["monthly_budget"])

print(f"\n{'FAILED' if bad else 'PASSED'} — {bad} failed")
raise SystemExit(1 if bad else 0)
