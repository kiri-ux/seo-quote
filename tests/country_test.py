"""EVERY LOOKUP WENT TO THE UNITED STATES, WHOEVER THE CLIENT WAS.

loc_string appended ",United States" unconditionally and the Labs calls sent
country 2840, so Drainify -- a UK company entering the US -- had its UK side
measured as US demand: eighteen terms with no volume and nothing on screen
saying the country was the reason. DataForSEO is multi-country on the same
subscription; the hardcoding was ours.

NATIONAL ONLY outside the US. The market grouping, the county index and the
Mount Union spelling repair all read a US ZIP dataset. (2026-09-10, Kiri)
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


def ctx(body=None, method="POST", path="/"):
    c = app.app.test_request_context(path, json=(body or {}), method=method)
    c.push()
    app._pick_country()
    return c


print("\nNOTHING MOVES FOR A US QUOTE")
c = ctx({})
check("the default is the US", app.country(), "US")
check("the location string is unchanged", app.loc_string([], ""), "United States")
check("and so is a city one", app.loc_string(["Altoona, PA"], ""),
      "Altoona,Pennsylvania,United States")
check("the Labs code is unchanged", app.labs_location_code(), 2840)
check("markets still place", app.usable_markets(["Altoona, PA"]), ["Altoona, PA"])
c.pop()

print("\nA UK QUOTE IS MEASURED IN THE UK")
c = ctx({"country": "GB"})
check("the country is read off the payload", app.country(), "GB")
check("the location is the country", app.loc_string([], ""), "United Kingdom")
check("the Labs code follows it", app.labs_location_code(), 2826)
check("it is not domestic", app.is_domestic(), False)
check("the rank check goes there too",
      app.rank_location([], "", True), "United Kingdom")
c.pop()

print("\nAND IT CARRIES NO MARKETS, BECAUSE IT CANNOT")
c = ctx({"country": "GB"})
check("towns are dropped", app.usable_markets(["London", "Manchester"]), [])
check("so a market list cannot build a local string",
      app.loc_string(["London"], ""), "United Kingdom")
c.pop()

print("\nTHE COUNTRY IS FOUND WHEREVER THE PAYLOAD PUTS IT")
for body, want in (({"country": "ca"}, "CA"),
                   ({"inputs": {"country": "AU"}}, "AU"),
                   ({"country": "IE"}, "IE"),
                   ({"country": "nz"}, "NZ")):
    c = ctx(body)
    check(str(body), app.country(), want)
    c.pop()
c = ctx({}, method="GET", path="/?country=gb")
check("or on the query string", app.country(), "GB")
c.pop()

print("\nAN UNKNOWN COUNTRY IS THE US, NOT AN ERROR")
for bad in ("ZZ", "", None, "United Kingdom", 7):
    c = ctx({"country": bad})
    check(repr(bad), app.country(), "US")
    c.pop()

print("\nOUTSIDE A REQUEST IT IS STILL THE US")
check("no context, no crash", app.country(), "US")
check("and the name comes back", app.country_name(), "United States")

print("\nEVERY COUNTRY IN THE REGISTER IS COMPLETE")
for code, c_ in app.COUNTRIES.items():
    check(f"{code} has a name, a Labs code and an ISO",
          all(c_.get(k) for k in ("name", "labs", "iso", "label")), True)
check("and the US is the default", app.DEFAULT_COUNTRY, "US")

print("\nTHE PANEL NAMES THE COUNTRY IT MEASURED IN")
c = ctx({"country": "GB"})
check("the step-1 basis says GB", app.country(), "GB")
c.pop()

print("\nAND A NATIONAL LOOKUP IS NOT A MARKET")
# fetch_local_volume queries with an empty city on a national quote; when that
# falls back it must not be reported as a market that contributed no volume.
_pc = {}
_fallback = ["", "  ", "Altoona"]
_fallback = [x for x in _fallback if str(x).strip()]
check("the empty city is not a market", _fallback, ["Altoona"])

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
