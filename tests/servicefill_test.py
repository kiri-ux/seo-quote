"""A short services-axis list is topped up with the towns the axis dropped, so
adding seeds can't shrink the list. Texoma: 15 terms in Sherman alone after a
ninth seed flipped the axis. (2026-10-05, Kiri)
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

ev = {"dropped_cities": ["Denison, TX", "Ardmore, OK"]}
g = app.fill_short_services(["Sherman, TX"], 15, ev)
check("short.toppedUp", g, ["Sherman, TX", "Denison, TX"])
check("short.recorded", ev.get("filled_cities"), ["Denison, TX"])

ev = {"dropped_cities": ["Denison, TX", "Ardmore, OK"]}
check("veryShort.moreTowns", app.fill_short_services(["Sherman, TX"], 8, ev),
      ["Sherman, TX", "Denison, TX", "Ardmore, OK"])

ev = {"dropped_cities": ["Denison, TX"]}
check("full.untouched", app.fill_short_services(["Sherman, TX"], 28, ev), ["Sherman, TX"])
check("full.notRecorded", "filled_cities" in ev, False)

ev = {"dropped_cities": ["Denison, TX"]}
check("phrasesStayLast", app.fill_short_services(["Sherman, TX", "texoma"], 10, ev),
      ["Sherman, TX", "Denison, TX", "texoma"])

check("noSpare", app.fill_short_services(["Sherman, TX"], 5, {}), ["Sherman, TX"])

src = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
check("build.usesIt", "grid_cities = fill_short_services(grid_cities, len(services), axis_ev)" in src, True)
check("build.measuresThem", "cities = cities + [c for c in (axis_ev.get(\"filled_cities\") or [])" in src, True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
