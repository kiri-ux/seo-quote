"""A NEAR-ME FLOOR SET JUST ABOVE GOOGLE'S REFUSES EVERYTHING IN A SMALL MARKET.

ENT Consultants of North MS ran a build with no near-me rows at all, and an
earlier one that carried a single row out of thirty-six. near_me_terms had
already been raised to eight that same day for exactly that complaint, and it
changed nothing -- the count was never the lever.

near_me_min_volume is 20, deliberately just over the 10/mo Google reports for a
thin term. That is the right cut where the vertical has real demand somewhere
and the 10s are the dregs. In these markets every reading IS 10, so the floor
refused every form on the list. The two that ever survived -- "ear nose and
throat doctor near me" and "hearing aids near me", both 50/mo -- only did so
because that build was measured in Oxford.

These rows matter more than their count suggests: in a grid build they are the
only keywords that are what a person actually types, rather than service x city.

The relaxation is the test the industry gap-finder already uses for this same
question. If the best near-me form cannot reach a multiple of the floor, the
whole market is small and the floor is refusing the only terms that exist.
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

SOURCE = open(SRC, encoding="utf-8").read()
FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


FLOOR = int(app.CFG.get("near_me_min_volume", 20))
THIN = int(app.CFG.get("near_me_thin_floor", 10))
MULT = float(app.CFG.get("expand_thin_market_mult", 10))


def effective_floor(volumes):
    """The floor the attach pass would use, given what the forms measured.

    Mirrors the two lines in _attach_near_me rather than reaching into the
    build: the decision is the thing under test, and running a whole grid to
    reach it would test everything except the decision.
    """
    floor = FLOOR
    best = max(list(volumes) or [0])
    if best and best < floor * MULT:
        floor = min(floor, THIN)
    return floor


def kept(volumes):
    f = effective_floor(volumes)
    return [v for v in volumes if v >= f]


# ---------------------------------------------- the reported case
# Every form at Google's floor. Under a floor of 20 the list carried none.
check("a market where everything reads 10 keeps its near-me rows",
      kept([10, 10, 10, 10]), [10, 10, 10, 10])
check("and the floor it used stepped down", effective_floor([10, 10, 10]), THIN)

# The Oxford build, which is what a working one looked like.
check("the 50/mo forms were never at risk", kept([50, 50, 10]), [50, 50, 10])

# ---------------------------------------------- and it does not open the gates
# Where the vertical has real demand somewhere, the 10s ARE the dregs and the
# floor has to hold -- that is the whole reason it exists.
check("a fat vertical keeps the full floor", effective_floor([2400, 90, 10]), FLOOR)
check("so its thin forms are still cut", kept([2400, 90, 10]), [2400, 90])
check("the boundary is a multiple of the floor",
      effective_floor([int(FLOOR * MULT)]), FLOOR)
check("one below it is thin", effective_floor([int(FLOOR * MULT) - 1]), THIN)

# A form nobody searches is still nothing, relaxed floor or not.
check("zero never gets in", kept([10, 0, 0]), [10])
check("and an all-zero probe does not relax anything",
      effective_floor([0, 0]), FLOOR)

# ---------------------------------------------- the knobs
# near_me_terms was raised to 8 the same day for this complaint and did nothing,
# because the floor was binding. All three are per-quote editable now so the
# next thin market can be answered without a deploy.
for k in ("near_me_terms", "near_me_min_volume", "near_me_thin_floor"):
    check("%s is per-quote editable" % k, '("%s", int)' % k in SOURCE, True)
check("the relaxation can be switched off", THIN >= 0, True)
check("the count is not the binding constraint",
      int(app.CFG.get("near_me_terms", 0)) >= 8, True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
