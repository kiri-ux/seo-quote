"""A proposal's shape: few Ultra, more Competitive, most Long Tail.

King and Prince Seafood read 10 Ultra / 2 Competitive / 2 Long Tail, with
10/mo terms labelled "ultra competitive" and four near-me rows riding their
service's tier. (2026-10-02, Kiri)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
os.environ.pop("ANTHROPIC_API_KEY", None)
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

SEEDS = ["seafood supplier", "seafood wholesaler", "seafood distributor",
         "frozen seafood supplier", "wholesale seafood", "fish supplier",
         "shrimp supplier", "frozen fish supplier", "restaurant seafood supplier",
         "food service distributor"]
VOL = {s: 1000 - i * 90 for i, s in enumerate(SEEDS)}

def fake(path, payload, **kw):
    t = (payload or [{}])[0]
    if "search_volume" in path:
        out = []
        for k in t.get("keywords") or []:
            base = k.replace(" near me", "")
            v = VOL.get(base, 0)
            out.append({"keyword": k, "search_volume": (10 if k.endswith("near me") else v),
                        "location_code": 1})
        return {"tasks": [{"status_code": 20000, "result": out}]}
    return {"tasks": [{"status_code": 20000, "result": []}]}
app.dfs_post = fake
app.fetch_site_pages = lambda *a, **k: []

with app.app.test_client() as c:
    kw = c.post("/api/keywords", json={"keywords": SEEDS, "geo_values": ["Washington"],
                                       "state": "Washington", "brand": "KP",
                                       "geo_scope": "statewide"}).get_json()
    r = c.post("/api/refine", json={"keywords": SEEDS, "geo_values": ["Washington"],
                                    "state": "Washington", "brand": "KP",
                                    "geo_scope": "statewide", "ultra": kw.get("ultra"),
                                    "competitive": kw.get("competitive"),
                                    "long_tail": kw.get("long_tail")}).get_json()
n = {t: len(r.get(t) or []) for t in ("ultra", "competitive", "long_tail")}
svc_n = lambda t: len({x["kw"].replace(" near me", "") for x in r.get(t) or []
                       if not x["kw"].endswith("near me")})
total = sum(svc_n(t) for t in n)
print(n, total)
check("ultra is the smallest share", svc_n("ultra") <= max(1, round(total * 0.2)), True)
check("long tail is the largest", svc_n("long_tail") >= svc_n("competitive"), True)
near = [x for t in n for x in (r.get(t) or []) if x["kw"].endswith("near me")]
check("a 10/mo near-me row is not ultra",
      any(x in (r.get("ultra") or []) for x in near), False)
top = (r.get("ultra") or [{}])[0].get("kw", "")
check("the biggest term leads ultra", top.startswith("seafood supplier"), True)
print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
