"""Every market the client gave counts toward demand, in the table or not.

Valero Law Group named five markets. The grid crossed Seattle and Las Vegas,
the volume pull only asked about those two, and Palm Springs, Reno and Salinas
added nothing to the price. (2026-10-01, Kiri)
"""
import sys, os
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

VOL = {"Seattle": 1000, "Las Vegas": 2000, "Palm Springs": 300, "Reno": 400,
       "Salinas": 200}
CODE = {"Seattle": 1, "Las Vegas": 2, "Palm Springs": 3, "Reno": 4, "Salinas": 5}
asked = []

def fake_post(path, payload, **kw):
    loc = (payload or [{}])[0].get("location_name", "")
    asked.append(loc)
    city = next((c for c in VOL if loc.startswith(c)), None)
    if not city:
        raise RuntimeError("40501 location_name not found")
    return {"tasks": [{"result": [
        {"keyword": "injury lawyer", "search_volume": VOL[city],
         "location_code": CODE[city]},
        {"keyword": "car accident attorney", "search_volume": VOL[city] // 10,
         "location_code": CODE[city]}]}]}

app.dfs_post = fake_post
SHOWN = ["Seattle, WA", "Las Vegas, NV"]
ALL = ["Palm Springs, CA", "Reno, NV", "Salinas, CA", "Seattle, WA", "Las Vegas, NV"]
SVC = ["injury lawyer", "car accident attorney"]

with app.app.test_request_context("/"):
    out = app.off_grid_volume(SVC, SHOWN, ALL, "")
check("the three hidden markets are named",
      sorted(out["markets"]), ["Palm Springs, CA", "Reno, NV", "Salinas, CA"])
check("their demand is counted", out["volume"], (300 + 400 + 200) + (30 + 40 + 20))
check("no error", out["error"], None)
check("every hidden market was asked about",
      all(any(a.startswith(c) for a in asked) for c in ("Palm Springs", "Reno", "Salinas")),
      True)

with app.app.test_request_context("/"):
    none = app.off_grid_volume(SVC, ALL, ALL, "")
check("nothing hidden, nothing added", (none["markets"], none["volume"]), ([], 0))

def broken(path, payload, **kw):
    raise RuntimeError("boom")
app.dfs_post = broken
with app.app.test_request_context("/"):
    app.ads_volume_cache_clear()
    bad = app.off_grid_volume(SVC, SHOWN, ALL, "")
check("a failed lookup adds nothing", bad["volume"], 0)
check("and says so", bool(bad["error"]), True)

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
