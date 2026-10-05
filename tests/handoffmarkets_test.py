"""THE PROPOSAL HANDOFF NAMES THE MAIN AND ADD-ON MARKETS.

The .docx and slides already print them (#64). adtini reads the same two
fields off /api/handoff and the saved quote's handoff. Empty on a quote with
no add-ons. (2026-10-05, Kiri)
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


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name
          + ("" if ok else f"  got {got!r} want {want!r}"))
    return 0 if ok else 1


fails = 0
m = app.handoff_meta({"main_market": " seattle wa ",
                      "addon_market_names": ["Las Vegas, NV", "", "Reno, NV"]})
fails += check("main market", m["main_market"], "seattle wa")
fails += check("add-on names", m["addon_market_names"], ["Las Vegas, NV", "Reno, NV"])

m = app.handoff_meta({})
fails += check("no add-ons: main empty", m["main_market"], "")
fails += check("no add-ons: names empty", m["addon_market_names"], [])

c = app.app.test_client()
r = c.post("/api/handoff", json={"main_market": "seattle wa",
                                 "addon_market_names": ["Reno, NV"]})
fails += check("api/handoff carries both", (r.get_json()["proposal"]["main_market"],
                                            r.get_json()["proposal"]["addon_market_names"]),
               ("seattle wa", ["Reno, NV"]))
sys.exit(1 if fails else 0)
