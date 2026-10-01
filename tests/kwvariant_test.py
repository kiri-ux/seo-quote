"""A cheaper or bigger list without dropping a tier.

Partners trim a quote to a budget by picking less competitive or lower-volume
terms, and grow it by adding higher-volume ones. kw_variant swaps the priciest
head services for cheaper ones from the build's own pool, or adds the
biggest unused ones, crossed with the same markets. (2026-10-01, Kiri)
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

MK = ["Seattle, WA", "Las Vegas, NV"]
ROWS = [
    {"kw": "car accident attorney seattle", "vol": 210, "city": "seattle", "tier": "ultra"},
    {"kw": "car accident attorney las vegas nv", "vol": 880, "city": "las vegas", "tier": "ultra"},
    {"kw": "car accident attorney near me", "vol": 960, "city": "", "tier": "ultra"},
    {"kw": "dog bite lawyer seattle", "vol": 90, "city": "seattle", "tier": "competitive"},
    {"kw": "dog bite lawyer las vegas nv", "vol": 70, "city": "las vegas", "tier": "competitive"},
]
HEAD = [r["kw"] for r in ROWS]
POOL = [{"keyword": "slip and fall lawyer seattle", "volume": 70},
        {"keyword": "premises liability lawyer", "volume": 50},
        {"keyword": "truck accident lawyer", "volume": 300}]
CPC_NOW = {"car accident attorney": 180.0, "dog bite lawyer": 40.0}
VOL = {"slip and fall lawyer": 160, "premises liability lawyer": 140,
       "truck accident lawyer": 900}
CPC = {"slip and fall lawyer": 60.0, "premises liability lawyer": 30.0,
       "truck accident lawyer": 150.0}
heads_priced = []

def fake_vol(terms, markets, state, national=False, cap=None):
    return {t: VOL.get(t, 0) for t in terms}, {}, None

def fake_metrics(head, markets, state, national=False, industry=""):
    ks = [h["keyword"] for h in head]
    heads_priced.append(ks)
    cpc = {k: CPC.get(k, CPC_NOW.get(k, 0)) for k in ks}
    med = sorted(cpc.values())[len(cpc) // 2] if cpc else 0
    return {"cpc": cpc, "adder": int(med * 5)}

app.fetch_local_volume = fake_vol
app.stage3_metrics = fake_metrics

with app.app.test_request_context("/"):
    lo = app.kw_variant("lower", ROWS, HEAD, POOL, MK, "", CPC_NOW, k=1)
check("lower: no error", lo["error"], None)
check("lower: the priciest head service goes", [x["service"] for x in lo["out"]],
      ["car accident attorney"])
check("lower: replaced by the biggest cheaper candidate",
      [x["service"] for x in lo["in"]], ["slip and fall lawyer"])
kws = [r["kw"] for r in lo["rows"]]
check("lower: same markets, near me kept",
      sorted(k for k in kws if k.startswith("slip and fall lawyer")),
      ["slip and fall lawyer las vegas nv", "slip and fall lawyer near me",
       "slip and fall lawyer seattle"])
check("lower: the old service is gone", any("car accident" in k for k in kws), False)
check("lower: list size holds", len(lo["rows"]), len(ROWS))
check("lower: tier kept", {r["tier"] for r in lo["rows"] if "slip" in r["kw"]}, {"ultra"})
check("lower: volume drops", lo["volume_delta"] < 0, True)
check("lower: adder recomputed on the new head",
      "slip and fall lawyer" in heads_priced[-1] and "car accident attorney" not in heads_priced[-1],
      True)

heads_priced.clear()
with app.app.test_request_context("/"):
    up = app.kw_variant("grow", ROWS, HEAD, POOL, MK, "", CPC_NOW, k=1)
check("grow: no error", up["error"], None)
check("grow: the biggest unused term comes in", [x["service"] for x in up["in"]],
      ["truck accident lawyer"])
check("grow: nothing goes out", up["out"], [])
check("grow: crossed with the markets",
      sorted(r["kw"] for r in up["rows"] if r["kw"].startswith("truck")),
      ["truck accident lawyer las vegas nv", "truck accident lawyer near me",
       "truck accident lawyer seattle"])
check("grow: volume rises by its demand", up["volume_delta"], 900)

with app.app.test_request_context("/"):
    none = app.kw_variant("lower", ROWS, HEAD, [], MK, "", CPC_NOW)
check("no pool, says so", bool(none["error"]), True)

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
