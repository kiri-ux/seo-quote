"""A HAND-QUOTED CARD IS THREE NUMBERS AND THE OVERRIDE SET ONE.

Kiri, 2026-09-17: "it's unclear how to manually change the three package prices
based on these override fields."

It was unclear because it could not be done. "Override partner Core SEO" sets
the hard base and the ladder then steps at 38% of it, so entering the partner
cost behind Brendan's Seascape entry price of $6,950 produced
$6,950 / $9,550 / $12,200 against the $8,250 / $9,950 he wrote. The one field
that exists to reproduce a hand-quoted card could not reproduce one, and there
was no second field to reach for.

The step is the second number. The third follows from it -- every ladder in his
book is evenly spaced, and the ones that are not (Seascape steps $1,300 then
$1,700) are not reachable by any setting the pricer has, which is a separate
question from being able to set the step at all.

Partner dollars, like every other override on that screen, because the panel
says so at the top: "Every dollar here is partner hard cost; client price is
cost / (1 - markup)."
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
    a = dict(band="single_city", adder=0, zero_ranking=False, addon_markets=0,
             markup_pct=35, pct_not_ranking=100, total_volume=51690)
    a.update(kw)
    return app.stage4_price(**a)


# ---------------------------------------------- the reported case
# $4,500 partner is the cost behind Brendan's $6,950 at a 35% margin.
was = price(base_override=4500)
check("the base override still lands his entry price",
      was["handoff"]["package"]["base"], 6950)
check("and on its own it overshoots the rest",
      [was["handoff"]["package"][k] for k in ("intermediate", "advanced")],
      [9550, 12200])

now = price(base_override=4500, step_override=850)
check("the step override reaches his intermediate",
      now["handoff"]["package"]["intermediate"], 8250)
check("without moving the base he set",
      now["handoff"]["package"]["base"], 6950)
# HIS LADDER IS NOT EVEN ($1,300 then $1,700) AND THIS ONE IS. Pinned so the
# gap is a recorded fact rather than a surprise in a room: the advanced tier
# lands $400 under his, and no setting closes that without a third field.
check("the ladder it builds is evenly spaced",
      now["handoff"]["package"]["advanced"] - now["handoff"]["package"]["intermediate"],
      now["handoff"]["package"]["intermediate"] - now["handoff"]["package"]["base"])

# ---------------------------------------------- it is partner dollars
check("the step is partner dollars, not client",
      price(base_override=4500, step_override=850)["step"], 850)
check("and rounds to $50 like every other override",
      price(base_override=4500, step_override=838)["step"], 850)

# ---------------------------------------------- and it stands alone
# Overriding the step without the base is a legitimate quote: the formula found
# the right entry price and the wrong spread.
alone = price(step_override=600)
check("the step can be set without the base",
      alone["step"], 600)
check("and the formula still sets the base",
      alone["handoff"]["package"]["base"], price()["handoff"]["package"]["base"])
check("it is reported as manual", alone["manual_step"], True)
check("and an untouched ladder is not", price()["manual_step"], False)
check("nor is a base-only override", price(base_override=4500)["manual_step"], False)

# ---------------------------------------------- the formula figure is kept
# An override replaces a component, so calibration has to keep what the formula
# would have said or it compares a human's number against itself.
check("a step override records the formula price too",
      bool(price(step_override=600).get("formula")), True)
check("and that record is the unoverridden ladder",
      price(step_override=600)["formula"]["client_tiers"],
      price()["handoff"]["core_seo_price"])

# ---------------------------------------------- wiring
check("the route reads it off the payload",
      'step_override=d.get("step_override")' in SOURCE, True)
check("the panel offers the field",
      "['ov_step','Override partner step per tier','number','formula']" in UI, True)
check("the builder sends it", "step_override: r.cfg.ov_step || ''" in UI, True)
check("and the run sheet names it when it was used",
      "cfg.ov_step && `Step ${money(cfg.ov_step)}/tier`" in UI, True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
