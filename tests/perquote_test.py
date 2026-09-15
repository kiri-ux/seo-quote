"""ONE QUOTE'S TUNING STAYS ON ONE QUOTE.

The config panel used to write the running session, so a markup or anchor
edited while pricing Sage Dental repriced whatever the next planner quoted.
A `cfg` object on the payload applies for that request and is put back after.
(2026-09-15, Kiri)
"""
import copy
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


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name
          + ("" if ok else f"  got {got!r} want {want!r}"))
    return 0 if ok else 1


bad = 0
before = copy.deepcopy(app.CFG)

# --- the overlay applies, then reverts -----------------------------------
with app.cfg_overlay({"geo_anchor": {"single_city": 9999},
                      "cpc_adder_cap": "1500"}) as clean:
    bad += check("anchor inside", app.CFG["geo_anchor"]["single_city"], 9999)
    bad += check("cap inside", app.CFG["cpc_adder_cap"], 1500)
    bad += check("only what changed", sorted(clean), ["cpc_adder_cap", "geo_anchor"])
bad += check("anchor restored", app.CFG["geo_anchor"]["single_city"],
             before["geo_anchor"]["single_city"])
bad += check("cap restored", app.CFG["cpc_adder_cap"], before["cpc_adder_cap"])
bad += check("nothing else moved", app.CFG, before)

# --- an empty or absent overlay is a no-op ------------------------------
with app.cfg_overlay({}) as clean:
    bad += check("empty overlay", clean, {})
with app.cfg_overlay(None) as clean:
    bad += check("no overlay", clean, {})

# --- a bad value is refused BEFORE anything is swapped ------------------
try:
    with app.cfg_overlay({"cpc_adder_cap": "not a number"}):
        bad += check("should not enter", True, False)
except (ValueError, TypeError):
    pass
bad += check("refused overlay left CFG alone", app.CFG, before)

# --- tiers and brackets coerce the same way as the session panel --------
with app.cfg_overlay({"zero_ranking_tiers": [[50, 2], [80, 7]],
                      "volume_brackets": [[20000, None, 0.04], [10000, 20000, 0.07]]}):
    bad += check("tiers sorted high to low",
                 app.CFG["zero_ranking_tiers"], [[80.0, 7.0], [50.0, 2.0]])
    bad += check("brackets sorted low to high, open top kept",
                 app.CFG["volume_brackets"], [[10000.0, 20000.0, 0.07], [20000.0, None, 0.04]])

# --- and it reaches the pricer through the endpoint ----------------------
app.app.config["TESTING"] = True
c = app.app.test_client()
body = {"band": "single_city", "adder": 0, "markup_pct": 0.35,
        "pct_not_ranking": 0, "total_volume": 0}
plain = c.post("/api/price", json=body).get_json()
tuned = c.post("/api/price", json=dict(body, cfg={"geo_anchor": {"single_city": 4000}})).get_json()
after = c.post("/api/price", json=body).get_json()
bad += check("the overlay moved the price", tuned["base"] != plain["base"], True)
bad += check("the next quote is back on the file", after["base"], plain["base"])
bad += check("session untouched by a quote", app.CFG, before)

print(f"\n{'FAILED' if bad else 'PASSED'} — {bad} failed")
raise SystemExit(1 if bad else 0)
