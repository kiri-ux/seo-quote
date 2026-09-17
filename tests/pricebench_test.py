"""THE BENCH HAS TO RUN, AND IT HAS TO STILL DESCRIBE THIS CODE.

app.py's config block is a calibration ledger written as comments: every
constant names the client it was fitted on and the quote it had to reproduce.
The ledger cites a pricebench.py that was never in the repository, so a change
to a constant meant re-reading two hundred lines of comment and taking the
author's word for the fit -- which is how volume_add_cap came to saturate at
20,000/mo with nobody noticing until a 51,690/mo client was quoted $3,150 under.

The bench is only worth having if it breaks when the pricer changes. A tool that
silently stops matching the code it scores is worse than no tool, because it
keeps producing a table.
"""
import importlib.util
import json
import os
import subprocess
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location(
    "pricebench", os.path.join(SRCDIR, "tools", "pricebench.py"))
bench = importlib.util.module_from_spec(spec)
sys.modules["pricebench"] = bench
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
out = subprocess.run([sys.executable, "tools/pricebench.py", "--quiet-gaps"],
                     capture_output=True, text=True, cwd=SRCDIR)
check("the bench runs clean", out.returncode, 0)
check("and prints a total", "total error" in out.stdout, True)
check("and every client is in the table",
      all(d["name"] in out.stdout for d in bench.BENCH), True)

# ---------------------------------------------- every row is repriceable
# A row whose inputs stopped working would print a table of zeros and look fine.
for d in bench.BENCH:
    got, adder = bench.quote(d)
    check("%s reprices" % d["name"], sorted(got), ["advanced", "base", "intermediate"])
    check("  and lands above the floor", got["base"] > 1000, True)

# ---------------------------------------------- and the scoring is real
# The two the ledger claims are exact must still be exact, and the one it says
# is $3,150 under must still be under -- otherwise the bench is describing a
# different pricer from the one shipping.
by = {d["name"]: d for d in bench.BENCH}
for name in ("Visit Central PA", "Keller Builds", "Red Shoes"):
    got, _ = bench.quote(by[name])
    check("%s is still an exact ladder" % name,
          [got[t] for t in bench.TIERS], list(by[name]["actual"]))

# AND THE ONE THE RESHAPE WAS FOR. Seascape was $3,150 under at the old
# constants; the 2026-09-17 volume curve brings it inside $150 of the base
# Brendan wrote. Pinned as a range, not a number, because the point is that the
# shipping curve reaches him -- if a later change drops it back to $3,800 this
# has to fail rather than quietly print a table.
sea, _ = bench.quote(by["Seascape Inc"])
want = by["Seascape Inc"]["actual"][0]
check("Seascape lands within $500 of his base at the shipping constants",
      abs(sea["base"] - want) <= 500, True)
check("and not at the old capped price", sea["base"] > 4000, True)

# ---------------------------------------------- a patch actually moves it
raw = subprocess.run([sys.executable, "tools/pricebench.py", "--quiet-gaps",
                      "--patch", json.dumps({"volume_add_cap": 2500})],
                     capture_output=True, text=True, cwd=SRCDIR).stdout
check("a patch prints a before and an after", raw.count("total error"), 3)
# THE OLD CURVE IS KEPT AS A PATCH, NOT AS A COMMENT. Reverting the reshape, or
# showing anyone what it changed, is one command.
prev = json.load(open(os.path.join(
    SRCDIR, "tools", "proposals", "pre_seascape_volume.json")))
check("the pre-change curve is on file", isinstance(prev, dict), True)
check("and it is the curve that shipped before",
      prev["volume_add_cap"], 450)
check("which is not the curve that ships now",
      bench.app.CFG["volume_add_cap"] != prev["volume_add_cap"], True)
back = subprocess.run([sys.executable, "tools/pricebench.py", "--quiet-gaps",
                       "--patch", "@tools/proposals/pre_seascape_volume.json"],
                      capture_output=True, text=True, cwd=SRCDIR)
check("and running it puts Seascape back where it was", back.returncode, 0)
check("at the old total error", "$15,515" in back.stdout, True)

# ---------------------------------------------- the gap is named, not hidden
check("the clients it cannot reconstruct are listed",
      len(bench.UNRECONSTRUCTIBLE) > 0, True)
check("and each says why", all(w for _, w in bench.UNRECONSTRUCTIBLE), True)
# Every bench row cites the line of app.py its inputs came from, so a wrong
# input is findable rather than arguable.
check("every bench row cites its source",
      all(d.get("why") for d in bench.BENCH), True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
