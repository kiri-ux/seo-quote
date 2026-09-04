"""THE WARNING HAS TO TRAVEL WITH THE NUMBER.

Step 1 said "these terms have no demand -- 90/mo total. Volume contributes $0."
Step 4, three sections lower, printed $2,950 with nothing beside it, and that is
the number anyone reads. Every demand signal on Drainify was at zero, so the
price was the nationwide anchor plus a $50 competition adder -- a floor, not a
measurement of that client. Two clients in completely different markets price
identically there and nothing on the price card says so. (2026-09-04, Kiri)

The line is drawn at "could not be measured", NOT at "low". vol_free_below is
10,000 -- the point where volume stops ADDING money -- and a perfectly ordinary
local contractor sits under it. Firing there would make the warning noise.
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


def price(**kw):
    args = dict(band="nationwide", adder=50, zero_ranking=False, addon_markets=0,
                markup=35.0, total_volume=90, pct_not_ranking=19.0,
                national_demand=True)
    args.update(kw)
    return app.stage4_price(args["band"], args["adder"], args["zero_ranking"],
                            args["addon_markets"], args["markup"],
                            pct_not_ranking=args["pct_not_ranking"],
                            total_volume=args["total_volume"],
                            national_demand=args["national_demand"],
                            base_override=args.get("base_override"))


print("\nDRAINIFY: NOTHING MEASURED, SO SAY SO")
p = price()
check("the list could not be measured", p["no_demand"], True)
check("volume added nothing", p["price_basis"]["volume_add"], 0)
check("and 81% ranking means no uplift either",
      p["price_basis"]["zero_ranking_uplift_pct"], 0)
check("the adder is the only live component",
      p["price_basis"]["competitive_adder"], 50)
check("the basis carries the total it judged on",
      p["price_basis"]["total_volume"], 90)

print("\nTHE PRICE REALLY IS THE ANCHOR PLUS THE ADDER")
check("base = anchor + adder",
      p["base"], p["price_basis"]["anchor"] + p["price_basis"]["competitive_adder"])

print("\nA LOW-VOLUME CLIENT IS NOT AN UNMEASURED ONE")
# 6,000/mo is under vol_free_below (10,000) so it adds no money -- and it is a
# completely ordinary local quote. The warning must not fire on it.
lo = price(total_volume=6000, band="contiguous_region", national_demand=False)
check("volume still adds nothing", lo["price_basis"]["volume_add"], 0)
check("but the list was measured", lo["no_demand"], False)
check("right at the line is measured",
      price(total_volume=int(app.CFG["price_no_demand_below"]))["no_demand"], False)
check("one below it is not",
      price(total_volume=int(app.CFG["price_no_demand_below"]) - 1)["no_demand"], True)

print("\nNOT MEASURED YET IS NOT ZERO")
# A quote priced before step 1 has a total carries None, which is a different
# state from "measured and empty" and must not raise the warning.
check("no reading at all stays quiet", price(total_volume=None)["no_demand"], False)

print("\nAN OVERRIDE IS A HUMAN DECIDING, NOT THE FORMULA GUESSING")
ov = price(base_override=4200)
check("the override silences it", ov["no_demand"], False)
check("and the basis says a human set it",
      ov["price_basis"]["manual_base"], True)

print("\nA REAL DEMAND SIGNAL SILENCES IT")
big = price(total_volume=24000, pct_not_ranking=90.0)
check("volume contributes", big["price_basis"]["volume_add"] > 0, True)
check("the uplift contributes",
      big["price_basis"]["zero_ranking_uplift_pct"] > 0, True)
check("and nothing is flagged", big["no_demand"], False)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
