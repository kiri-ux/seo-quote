"""A CLICK PRICE NEEDS CLICKS.

Enerbase (Minot ND, single city, 120/mo, $42.88 median bid on 3 bids) took a
$100 CPC adder to $3,100. Brendan sent it at the $2,950 floor: "low search
volume in that market and it not being very competitive". Under
cpc_adder_min_demand a CPC-derived adder is not applied. (2026-10-05)
"""
import importlib.util
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location("app", os.path.join(SRCDIR, "app.py"))
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


def price(**kw):
    args = dict(adder=100, adder_basis="cpc", total_volume=120)
    args.update(kw)
    return app.stage4_price("single_city", args["adder"], False, 0, 35,
                            pct_not_ranking=58.0,
                            total_volume=args["total_volume"],
                            pageone_agg_share=0.26, pageone_agg_terms=19,
                            adder_basis=args["adder_basis"])


p = price()
check("Enerbase prices at the floor", p["client_tiers"]["base"], 2950)
check("adder not applied", p["competitive_adder"], 0)
check("the measured adder is reported", p["competitive_adder_waived"], 100)
check("the line is reported", p["competitive_adder_min_demand"], 500)

p = price(total_volume=600)
check("over the line the adder applies", p["competitive_adder"], 100)
check("nothing waived over the line", p["competitive_adder_waived"], 0)
check("and prices above the floor", p["client_tiers"]["base"], 3100)

p = price(total_volume=None)
check("unmeasured demand is not thin", p["competitive_adder"], 100)

p = price(adder_basis="kd")
check("a KD adder is untouched", p["competitive_adder"], 100)

p = price(adder_basis=None)
check("an adder with no basis is untouched", p["competitive_adder"], 100)

print("\n%d/%d passed" % (len(CHECKS) - len(FAIL), len(CHECKS)))
sys.exit(1 if FAIL else 0)
