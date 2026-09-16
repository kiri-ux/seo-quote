"""WHY THE LIST IS THE SIZE IT IS.

Ten seeds and nine markets produced ten terms, all in Oxford, and nothing on
screen said the build had measured those nine markets and decided the term
budget was better spent on services. The rule is Brendan's own; the silence
was ours.
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

DELTA = [("Oxford, MS", 90)] + [(c, 10) for c in (
    "Grenada, MS Batesville, MS Cleveland, MS Greenwood, MS Indianola, MS "
    "Lexington, MS Hernando, MS Clarksdale, MS").split(" MS ")]

# One market with demand -> the budget goes to services, and the evidence says so.
axis, why, ev = app.choose_grid_axis(DELTA, 10)
check("one.axis", axis, "services")
check("one.countsTheMarkets", ev.get("cities_scored"), 9)
check("one.countsWhatCarries", ev.get("cities_with_demand"), 1)
check("one.explains", bool(why), True)

# More than one -> geography earns it and the seeds repeat.
many = [(c, 200) for c in ("Oxford, MS", "Grenada, MS", "Cleveland, MS")]
axis2, why2, ev2 = app.choose_grid_axis(many, 10)
check("many.axis", axis2, "geography")
check("many.countsThem", ev2.get("cities_with_demand"), 3)

# Two markets, one of them at Google's floor: still services.
axis3, _w, ev3 = app.choose_grid_axis([("Oxford, MS", 90), ("Grenada, MS", 10)], 10)
check("floorDoesNotCount", axis3, "services")

# The planner can overrule it, and the measured verdict is kept beside it.
axis4, _w4, ev4 = app.choose_grid_axis(DELTA, 10, forced="geography")
check("forced.wins", axis4, "geography")
check("forced.saysSo", ev4.get("by_hand"), True)

# The request carries the override through to the decision, and the answer
# comes back with the list -- otherwise the toggle is a button that does nothing
# and the reason is invisible.
src = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
check("request.carriesTheOverride", 'grid_axis=(d.get("grid_axis") or "")' in src, True)
check("response.carriesTheVerdict",
      '"grid_axis": {"axis": axis, "reason": axis_reason, "evidence": axis_ev}' in src, True)
check("refine.carriesItToo", '"grid_axis": s1.get("grid_axis") or {}' in src, True)

# And the builder shows it, with a way to overrule it.
ui = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "templates", "adtini.html"), encoding="utf-8").read()
check("ui.sendsTheOverride", "grid_axis: d.axis" in ui, True)
check("ui.hasTheToggle", 'id="kbAxis"' in ui, True)
check("ui.showsTheReason", 'kbAxisNote' in ui, True)
check("ui.namesTheMarketCount", "carry measurable demand" in ui, True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
