"""A COUNTY IS NOT A SINGLE CITY.

Seascape, Inc was entered as one market -- "San Diego County" -- and the builder
read back "Geo scope: Single city". San Diego County is 4,500 square miles and
3.3 million people, and single_city is the cheapest anchor there is, so this is
a wrong price and not a wrong caption. suggest_geo_scope's own docstring says as
much: "the band chooses the pricing anchor, so a wrong pick is a wrong price".

TWO SEPARATE HOLES, both from the same assumption -- that an entered market is
a city.

One county entered counted as one city and returned single_city without ever
asking what kind of place it named. The builder's client-side fallback had this
right (a ticked county box reads as a region); the server overruled it.

And a county has no coordinates of its own, so EVERY county market landed in
"could not place these on the map" and two counties returned no band at all. A
county's principal city is where it is, and the seats are already indexed for
the keyword build.

Placing a county at its seat then created a third thing to get right: the seat
is the county's MIDDLE. San Diego to Santa Ana is 86 miles and the two counties
share a border, so a city-sized join radius called them non-contiguous -- which
is a MORE expensive anchor than they earn. Each county end of a comparison gets
its own reach. (2026-09-17)
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

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


def band(markets, state=""):
    return app.suggest_geo_scope(markets, state).get("suggested") or ""


def anchor(b):
    return app.stage4_price(band=b, adder=0, zero_ranking=False, markup_pct=35,
                            pct_not_ranking=0, total_volume=4690)["anchor"]


# ---------------------------------------------- the reported case
check("one county is a region, not a city",
      band(["san diego county"], "CA"), "contiguous_region")
check("with the state written into the market",
      band(["San Diego County, CA"]), "contiguous_region")
check("and the reason says which fact decided it",
      "county" in app.suggest_geo_scope(["san diego county"], "CA")["reason"].lower(),
      True)
# WHAT THIS DOES AND DOES NOT COST TODAY. single_city and contiguous_region
# happen to share an anchor right now, so Seascape's own price does not move.
# The band is stored on the quote, drives the rest of the ladder, and is the
# thing the config tunes -- pinned here so that if the two anchors are ever
# separated (they were, and may be again) this is a price bug that shows up as
# a failure rather than as a quote.
check("the two bands are priced alike today",
      anchor("contiguous_region"), anchor("single_city"))
check("and a wider band is not cheaper",
      anchor("non_contiguous_region") >= anchor("single_city"), True)

# ---------------------------------------------- a city is still a city
check("one city is still one city", band(["san diego"], "CA"), "single_city")
check("and so is a city that merely sits in a county",
      band(["oxford"], "MS"), "single_city")
# "County Line Road" is not a county. The match is on the name's suffix, and
# then on the county index, so a road does not become a region.
check("two cities are read the way they always were",
      band(["oxford", "greenwood"], "MS"), "non_contiguous_region")

# ---------------------------------------------- counties reach the map at all
# Before this they all landed in "could not place", so two counties returned no
# band and the caller fell back to a guess.
check("two counties get a band", band(["san diego county", "orange county"], "CA") != "",
      True)
# ADJACENT COUNTIES ARE ONE REGION. Seat to seat is 86 miles and they share a
# border; a city-sized radius made them non-contiguous, which costs MORE.
check("and two that touch are one region",
      band(["san diego county", "orange county"], "CA"), "contiguous_region")
check("so are two more a county apart",
      band(["san diego county", "los angeles county"], "CA"), "contiguous_region")
# But the reach is a county's own size, not a licence. Counties at opposite ends
# of a state are still two regions.
check("counties across a state are still apart",
      band(["san diego county", "humboldt county"], "CA"), "non_contiguous_region")
check("the reach is per-quote editable",
      '("scope_county_reach_miles", float)' in open(SRC, encoding="utf-8").read()
      or "scope_county_reach_miles" in app.CFG, True)

# ---------------------------------------------- nothing else moved
check("national demand still wins outright",
      app.suggest_geo_scope(["san diego county"], "CA",
                            national_demand=True).get("suggested"), "nationwide")
check("and no markets is still no band", band([]), "")
check("an unplaceable market still says so",
      "could not place" in app.suggest_geo_scope(
          ["zzqqx county", "san diego"], "CA")["reason"].lower(), True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
