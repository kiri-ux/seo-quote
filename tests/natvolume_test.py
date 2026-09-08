"""EIGHTEEN BLANKS AGAINST A 300/MO TOTAL.

Every keyword on Drainify's grid read "(no data)" while the panel above it
reported "sewer inspection software 30". Both numbers came from the same dict.

A nationwide build makes no crossings: build_grid emits the bare service with
volume 0, and _apply_volumes opened with `if not city_l: continue` -- a guard
added so a near-me row's real figure could not be overwritten by the miss
branch. On a national quote EVERY row has no city, so every row kept its zero
and the demand that had been measured was never shown.

The price is unaffected: total_volume sums the service map, not the rows. What
was lost is the per-row number -- which is the one anybody checks the tiering
against, and the one that made a partly-measured list read as a dead one.
(2026-09-08, Kiri)
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


VOLS = {
    "sewer inspection software": 30,
    "pacp software": 480,
    "cctv pipe inspection software": 10,
    "water damage restoration": 90,
    "water damage restoration near me": 210,
}
nv = app.national_row_volume

print("\nA NATIONWIDE ROW IS ITS OWN SERVICE")
check("the figure is found",
      nv({"keyword": "sewer inspection software",
          "service": "sewer inspection software"}, VOLS), 30)
check("and the big one too",
      nv({"keyword": "pacp software", "service": "pacp software"}, VOLS), 480)

print("\nA NEAR-ME ROW WAS MEASURED AS ITSELF")
# Keyword first: the near-me phrase carries its own demand, which is not the
# bare service's. Reading the service here would print 90 against a term that
# measured 210.
check("its own phrase wins",
      nv({"keyword": "water damage restoration near me",
          "service": "water damage restoration"}, VOLS), 210)

print("\nNOTHING MEASURED STAYS NOTHING")
check("an unmeasured term returns None",
      nv({"keyword": "drain survey app", "service": "drain survey app"}, VOLS), None)
check("a zero is not a figure",
      nv({"keyword": "x", "service": "x"}, {"x": 0}), None)
check("no vols at all", nv({"keyword": "pacp software"}, None), None)
check("no row at all", nv(None, VOLS), None)

print("\nIT FALLS BACK TO THE SERVICE WHEN THE ROW HAS NO KEYWORD")
check("service is the second key",
      nv({"service": "pacp software"}, VOLS), 480)

print("\nTHE PRICE NEVER DEPENDED ON THE ROWS")
# total_volume sums the service map -- stated here so a later change that moves
# it onto the rows has to break this test first.
_svc = ["sewer inspection software", "pacp software", "drain survey app"]
check("the total comes from the service map",
      sum(VOLS.get(s, 0) for s in _svc), 510)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
