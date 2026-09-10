"""ADDING DEMAND MADE THE QUOTE SMALLER.

Drainify's UK list measured 1,500/mo across ten terms. Eight measured terms
were added to Product / Vertical Focus -- 32 focus terms against a 20-service
grid -- and the rebuild came back at 840/mo across fourteen. The largest term
on the quote, `field service management software` at 880/mo, was gone.

Nothing rejected it. enforce_seed_services filled the grid from
clean[:max_services] IN ENTRY ORDER, so the eight newest terms sat at the end
of the list and the terms past slot twenty were dropped on typing order --
several of which measured nothing at all, and kept their slots because they had
been typed first.

Demand decides the slots now, and only when the list overflows: a list that
fits keeps the operator's order, and the tiering that follows from it.
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


# Typed in this order. The two that measure are typed LAST, exactly as they were
# when they came out of the widen panel.
SEEDS = ["cctv survey software", "drain survey", "manhole inspections",
         "drainage report automation", "sewer inspection software",
         "sewer crawler", "job management software",
         "field service management software"]
VOLS = {"cctv survey software": 0, "drain survey": 0, "manhole inspections": 0,
        "drainage report automation": 0, "sewer inspection software": 10,
        "sewer crawler": 10, "job management software": 480,
        "field service management software": 880}


def run(cap, seeds=SEEDS, vols=VOLS, services=None):
    return app.enforce_seed_services(services or [], seeds, cap, [], "", None,
                                     volumes=vols)


print("\nTHE LARGEST TERM ON THE QUOTE KEEPS ITS SLOT")
out, used, total, over = run(4)
names = [x["service"] for x in out]
check("the 880 term is in", "field service management software" in names, True)
check("so is the 480", "job management software" in names, True)
check("demand order", names,
      ["field service management software", "job management software",
       "sewer inspection software", "sewer crawler"])
check("nothing unmeasured took a slot",
      sorted(set(names) & {"cctv survey software", "drain survey"}), [])
check("the grid is full", used, 4)
check("the total is the focus list", total, 8)

print("\nWHAT LOST ITS SLOT IS NAMED")
check("four over capacity", len(over), 4)
check("and they are the unmeasured ones", sorted(over),
      ["cctv survey software", "drain survey", "drainage report automation",
       "manhole inspections"])

print("\nTHE STRONGEST TERM LEADS THE TIERS")
tiers = {x["service"]: x["tier"] for x in out}
check("880 is ultra", tiers["field service management software"], "ultra")
check("10 is long tail", tiers["sewer crawler"], "long_tail")

print("\nA LIST THAT FITS IS LEFT ALONE")
# Reordering a list that fits would move terms between tiers for no reason.
out2, _, _, over2 = run(20)
check("entry order preserved", [x["service"] for x in out2], SEEDS)
check("nothing over capacity", over2, [])

print("\nWITHOUT VOLUMES IT IS THE OLD BEHAVIOUR, NOT A CRASH")
out3, _, _, over3 = app.enforce_seed_services([], SEEDS, 3, [], "", None)
check("entry order", [x["service"] for x in out3], SEEDS[:3])
check("still reports the overflow", len(over3), 5)
out4, _, _, _ = app.enforce_seed_services([], SEEDS, 3, [], "", None, volumes={})
check("an empty map is the same", [x["service"] for x in out4], SEEDS[:3])

print("\nEDGES")
check("no seeds", app.enforce_seed_services([], [], 5, [], "", None)[1:], (0, 0, []))
_o, _u, _t, _ov = app.enforce_seed_services([], SEEDS, 0, [], "", None, volumes=VOLS)
check("a zero cap does not reorder or drop", _ov, [])
check("exactly at capacity keeps order",
      [x["service"] for x in run(8)[0]], SEEDS)

print("\nTHE NAME A SEED TAKES IS THE NAME ITS VOLUME IS KEYED ON")
# The volume map and the slot list have to agree, or ranking is silently random.
check("shared normaliser",
      app.seed_service_name("  CCTV Survey Software  ", [], ""),
      "cctv survey software")
check("the market comes off",
      app.seed_service_name("drain survey london", ["london"], ""),
      "drain survey")

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
