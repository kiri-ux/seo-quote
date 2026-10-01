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

# A HIDDEN MARKET WHOSE LOOKUP FAILS IS NAMED, not read as zero demand.
def reno_down(path, payload, **kw):
    loc = (payload or [{}])[0].get("location_name", "")
    if loc.startswith("Reno") or loc.startswith("Nevada"):
        raise RuntimeError("40202 rate limit")
    return fake_post(path, payload, **kw)
app.dfs_post = reno_down
with app.app.test_request_context("/"):
    app.ads_volume_cache_clear()
    part = app.off_grid_volume(SVC, SHOWN, ALL, "")
check("a failed market is named", "Reno, NV" in (part["error"] or ""), True)
check("the others still count", part["volume"], (300 + 200) + (30 + 20))
app.dfs_post = fake_post

# THE REFINE ENDPOINT FORWARDS THEM. It names the keys it returns, and leaving
# these off is why the first two fixes did nothing live.
src = open(os.path.join(os.path.dirname(app.__file__), "app.py")).read()
api = src[src.index("def api_refine"):]
api = api[:api.index("\n@app.route")]
for k in ("off_grid_markets", "off_grid_volume", "off_grid_error", "off_grid_probes"):
    check(f"api_refine forwards {k}", f'"{k}": s1.get("{k}")' in api, True)

# THE PROBES MEASURE THEIR MARKETS. Phrased the way the grid phrases a city,
# so recommend_addons matches each one back to its market and five markets
# read as five measured, not two.
HIDDEN = ["Palm Springs, CA", "Reno, NV", "Salinas, CA"]
with app.app.test_request_context("/"):
    pg = app.build_grid([{"service": "injury lawyer", "tier": "ultra"}],
                        HIDDEN, "", prepicked=True)
probe_rows = [{"kw": x["keyword"], "pos": None} for x in pg["ultra"]]
table = [{"kw": "injury lawyer seattle wa", "pos": None},
         {"kw": "injury lawyer las vegas nv", "pos": None}]
with app.app.test_request_context("/"):
    before = app.recommend_addons(ALL, "", table)
    after = app.recommend_addons(ALL, "", table + probe_rows)
check("without probes, two markets measured", before["measured"], 2)
check("with probes, all five", after["measured"], 5)

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
