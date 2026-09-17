"""THE ORM BENCH HAS TO RUN, AND IT HAS TO STILL DESCRIBE rep_pricing.py.

rep_pricing.py is a calibration ledger written as comments -- every constant
names the invoice it reproduces (Vici's rate card, Sage, Tru North, Visions,
four Goldstone engagements, Hobart, Kim Anami). tools/pricebench.py gave the
SEO ledger a bench; tools/repbench.py is the ORM one.

A bench is only worth having if it breaks when the pricer changes. A tool that
silently stops matching the code it scores is worse than no tool, because it
keeps producing a table.
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location(
    "repbench", os.path.join(SRCDIR, "tools", "repbench.py"))
bench = importlib.util.module_from_spec(spec)
sys.modules["repbench"] = bench
spec.loader.exec_module(bench)

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# ---------------------------------------------- it runs
out = subprocess.run([sys.executable, "tools/repbench.py", "--quiet-gaps"],
                     capture_output=True, text=True, cwd=SRCDIR)
check("the bench runs clean", out.returncode, 0)
check("and prints a total", "total error" in out.stdout, True)
check("and every datapoint is in the table",
      all(d["name"][:38] in out.stdout for d in bench.BENCH), True)
check("every channel gets its own block",
      all(t in out.stdout for _, t in bench.CHANNELS), True)

# ---------------------------------------------- every row reprices
# A row whose call stopped working would print a table of zeros and look fine.
for d in bench.BENCH:
    got = d["f"]()
    check("%s reprices" % d["name"], isinstance(got, int) and got > 0, True)
check("every row cites its source", all(d.get("why") for d in bench.BENCH), True)

# ---------------------------------------------- and the scoring is real
by = {d["name"]: d for d in bench.BENCH}

# THE RATE CARD IS THE PRODUCT. Six published gross rates the hard-cost column
# has to rebuild at the default 35%. If any of these moves, the tool has
# stopped quoting the chart the client is looking at.
for name in ("Vici card 1-25", "Vici card 26-50", "Vici card 51-100",
             "Vici card 101-250", "Vici card 251-350", "Vici card 351-500"):
    check("%s is exact" % name, bench.score(by[name]["want"], by[name]["f"]()), 0)

# THE ONE KNOWN MISS. The hard-cost rewrite rounded each component base up to
# $50 and the drift landed on the client: Brendan sent $7,400, the tool quotes
# $7,550. Pinned at its real size so a change that fixes it fails this line
# loudly instead of passing quietly -- and so a change that makes it WORSE
# cannot hide behind a total.
sage = by["Sage Dental bundle @ 51,330/mo"]
check("the Sage bundle is still $150 over", bench.score(sage["want"], sage["f"]()), 150)
supp = by["Sage suppression alone @ 51,330/mo"]
check("and suppression on its own is still exact",
      bench.score(supp["want"], supp["f"]()), 0)

# A BAND SCORES ZERO ANYWHERE INSIDE IT, AND ITS EDGES ARE EDGES.
check("inside a band is zero", bench.score((4500, 5500), 5350), 0)
check("under a band is the distance to the floor", bench.score((4500, 5500), 4400), -100)
check("over a band is the distance to the cap", bench.score((4500, 5500), 5600), 100)
check("a bulk batch sits inside Brendan's own band",
      bench.score(by["bulk batch, ~15 pages"]["want"],
                  by["bulk batch, ~15 pages"]["f"]()), 0)

# THE ROUNDING FIX IS PINNED. $612.50 hard at 35% is $942.31; rounding to the
# NEAREST $5 printed $940 and realised 34.8% against a stated 35%.
off = by["off-card override $612.50 hard"]
check("an off-card review never lands under its own margin",
      612.50 / off["f"]() <= 0.65, True)
check("and it rounds up rather than to the nearest $5", off["f"](), 945)

# ---------------------------------------------- a patch actually moves it
raw = subprocess.run(
    [sys.executable, "tools/repbench.py", "--quiet-gaps",
     "--patch", json.dumps({"SEARCH_BUNDLE.supp_base": 1650})],
    capture_output=True, text=True, cwd=SRCDIR)
check("a patch prints a before and an after", raw.stdout.count("total error"), 3)
check("and it reaches a nested constant", "PATCHED CONFIG" in raw.stdout, True)
# supp hard 1650 + 9.75x51.33 = 2150.47 -> r50 2200; + as 2600 = 4800;
# 4800/0.65 = 7384.6 -> r50 7400. Which is exactly what Brendan sent.
check("$100 off the suppression base lands Sage on his number",
      "$7,400" in raw.stdout and "rows scored" in raw.stdout, True)
bench.apply_patch({"SEARCH_BUNDLE.supp_base": 1650})
check("and the bench agrees when the patch is applied in process",
      bench.score(sage["want"], sage["f"]()), 0)
bench.apply_patch({"SEARCH_BUNDLE.supp_base": 1750})
check("reverting puts it back", bench.score(sage["want"], sage["f"]()), 150)

# ---------------------------------------------- the gaps are named, not hidden
check("the superseded actuals are listed", len(bench.SUPERSEDED) > 0, True)
check("and each says why", all(d["why"] for d in bench.SUPERSEDED), True)
check("and each still shows what ships instead",
      all(isinstance(d["f"](), int) for d in bench.SUPERSEDED), True)
check("and none of them is scored",
      any(d["name"] == s["name"] for d in bench.BENCH for s in bench.SUPERSEDED),
      False)
check("the constants with no datapoint are listed", len(bench.UNPRICED) > 0, True)
check("and each says why", all(w for _, w in bench.UNPRICED), True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
