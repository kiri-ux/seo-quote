""""UK,UNITED STATES" IS NOT A PLACE.

Drainify is a UK company entering the US, so the geo box held UK and United
States. loc_string appends ",United States" to every market unconditionally --
there is no country input anywhere in this tool -- so "UK" went out as the
location "UK,United States". Five rank lookups came back 40501 Invalid Field,
the volume read returned nothing for the entire grid, page one measured zero
incumbents, and the only thing on screen was an error naming a field.

The tool measures US demand on a US SERP. That is the honest answer and it has
to be the one on the panel. (2026-09-04, Kiri)
"""
import importlib.util
import json
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


print("\nA COUNTRY IS RECOGNISED FOR WHAT IT IS")
for g in ["UK", "uk", "United Kingdom", "England", "Great Britain", "GB",
          "Ireland", "Canada", "Australia", "Germany", "EMEA", "International"]:
    check(g, app.is_foreign_geo(g), True)

print("\nAND A REAL US MARKET IS NOT ONE")
for g in ["Altoona, PA", "New York City, NY", "Huntingdon County, PA",
          "Mount Union, PA", "Georgia", "Washington"]:
    check(g, app.is_foreign_geo(g), False)

print("\nIT NEVER REACHES A LOOKUP")
check("dropped from the measurable markets",
      app.usable_markets(["UK", "United States", "Altoona, PA"]), ["Altoona, PA"])
check("so the location string is not built from it",
      app.loc_string(["UK", "Altoona, PA"], ""), "Altoona,Pennsylvania,United States")
check("a UK-only campaign falls back to the country, not to nonsense",
      app.loc_string(["UK"], ""), "United States")
# The exact string the failing build sent.
check("the 40501 string is gone",
      "UK,United States" in [app.loc_string(["UK"], "")], False)

print("\nTHE PANEL SAYS SO RATHER THAN GOING QUIET")
client = app.app.test_client()
r = json.loads(client.post("/api/markets", json={
    "geo_values": ["UK", "United States", "Altoona, PA"],
    "state": "", "geo_scope": "nationwide"}).data)
check("the country is named back", r["foreign"], ["UK"])
check("it is not counted as a market", r["markets"], 1)
check("and it is not filed as a non-place — it IS a place",
      "UK" in (r.get("non_place") or []), False)
check("the US as a whole is still a non-place",
      r["non_place"], ["United States"])

print("\nNOTHING FOREIGN, NOTHING SAID")
r2 = json.loads(client.post("/api/markets", json={
    "geo_values": ["Altoona, PA", "Bedford, PA"], "state": "PA"}).data)
check("quiet on an ordinary quote", r2["foreign"], [])

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
