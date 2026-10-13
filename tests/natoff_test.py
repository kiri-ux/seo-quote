"""A planner's No on Price on national demand sticks.

"Online Sales" as a goal priced on national demand, and every rebuild flipped
the switch back to Yes, so the client's own geo could not be quoted.
(2026-10-13, Kiri)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

r = app.resolve_national_demand
mk = ["Dothan, AL"]
# The goal still sets the starting value.
check("goal.on", r(band="single_city", markets=mk, goal="Online Sales")[0], True)
# A planner's No wins over the goal.
check("off.goal", r(band="single_city", markets=mk, goal="Online Sales", off=True),
      (False, "manual: off"))
# And over a product-brand industry with no markets.
check("off.industry", r(industry="retail - general / e-commerce", band="single_city",
                        off=True)[0], False)
# A nationwide geo scope is still nationwide: there is no local geo to price.
check("off.nationwide", r(band="nationwide", goal="Online Sales", off=True)[0], True)

# Pricing honors it too: the anchor stays on the client's band.
p_on = app.stage4_price("single_city", 0, False, goal="Online Sales")
p_off = app.stage4_price("single_city", 0, False, goal="Online Sales", national_off=True)
check("price.differs", p_on.get("national_demand") != p_off.get("national_demand")
      or p_on.get("monthly") != p_off.get("monthly"), True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
