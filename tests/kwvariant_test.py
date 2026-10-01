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
SEEDS = ["car accident attorney", "dog bite lawyer", "slip and fall lawyer",
         "premises liability lawyer", "truck accident lawyer"]
CPC_NOW = {"car accident attorney": 180.0, "dog bite lawyer": 40.0}
VOL = {"slip and fall lawyer": 160, "premises liability lawyer": 140,
       "truck accident lawyer": 900}
CPC = {"slip and fall lawyer": 60.0, "premises liability lawyer": 30.0,
       "truck accident lawyer": 200.0}
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
    lo = app.kw_variant("lower", ROWS, HEAD, POOL, MK, "", CPC_NOW, k=1, seeds=SEEDS,
                        levers={"adder": True, "volume": False})
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
    up = app.kw_variant("grow", ROWS, HEAD, POOL, MK, "", CPC_NOW, k=1, seeds=SEEDS)
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

# NOT A WORD THE CLIENT NEVER USED. Valero's first swap was "trust attorney";
# Alamo Biscuit's was "la popular bakery", a competitor.
VOL.update({"trust attorney": 100, "la popular bakery": 900, "best car accident lawyer": 300})
CPC.update({"trust attorney": 20.0, "la popular bakery": 1.0, "best car accident lawyer": 90.0})
POOL2 = [{"keyword": "trust attorney"}, {"keyword": "la popular bakery"},
         {"keyword": "best car accident lawyer"}]
with app.app.test_request_context("/"):
    g = app.kw_variant("lower", ROWS, HEAD, POOL2, MK, "", CPC_NOW, k=1, seeds=SEEDS,
                       levers={"adder": True, "volume": False})
check("an ungrounded term is never swapped in",
      [x["service"] for x in g["in"]], ["best car accident lawyer"])

# PRICED ON VOLUME: the biggest-volume head goes, whatever its click price.
R2 = [{"kw": "restaurant san antonio tx", "vol": 246000, "city": "san antonio", "tier": "ultra"},
      {"kw": "breakfast san antonio tx", "vol": 18100, "city": "san antonio", "tier": "ultra"},
      {"kw": "biscuits san antonio tx", "vol": 1000, "city": "san antonio", "tier": "long_tail"}]
VOL.update({"biscuit restaurant": 900, "breakfast tacos": 5000})
CPC.update({"biscuit restaurant": 2.0, "breakfast tacos": 1.5})
with app.app.test_request_context("/"):
    v = app.kw_variant("lower", R2, [r["kw"] for r in R2[:2]],
                       [{"keyword": "biscuit restaurant"}, {"keyword": "breakfast tacos"}],
                       ["San Antonio, TX"], "", {"restaurant": 0.8, "breakfast": 2.5}, k=1,
                       seeds=["restaurant", "breakfast", "biscuits", "tacos"],
                       levers={"adder": False, "volume": True})
check("volume lever: the biggest-volume head goes",
      [x["service"] for x in v["out"]], ["restaurant"])
check("volume lever: volume falls a lot", v["volume_delta"] < -200000, True)

# A PLACE NAME INSIDE A CANDIDATE IS NOT A NEW SERVICE. "san antonio bakery"
# and "bakery san antonio texas" are "bakery", already quoted.
VOL.update({"bakery": 22000, "pan dulce": 1600})
with app.app.test_request_context("/"):
    gg = app.kw_variant("lower", R2 + [{"kw": "bakery san antonio tx", "vol": 22200,
                                        "city": "san antonio", "tier": "ultra"}],
                        [r["kw"] for r in R2[:2]],
                        [{"keyword": "san antonio bakery"},
                         {"keyword": "bakery san antonio texas"},
                         {"keyword": "pan dulce san antonio"}],
                        ["San Antonio, TX"], "", {"restaurant": 0.8, "breakfast": 2.5},
                        k=1, seeds=["restaurant", "breakfast", "bakery", "pan dulce"],
                        levers={"adder": False, "volume": True})
check("a quoted service with a place name is not swapped in",
      [x["service"] for x in gg["in"]], ["pan dulce"])
check("no keyword carries the place twice",
      [r["kw"] for r in gg["rows"] if r["kw"].count("san antonio") > 1], [])

# NOT THEIR OWN NAME, AND NOT A QUOTED SERVICE WITH A PREPOSITION LEFT ON IT.
VOL.update({"biscuit company": 500, "bakery near": 400, "best panaderia": 300})
with app.app.test_request_context("/"):
    bn = app.kw_variant("lower", R2 + [{"kw": "bakery san antonio tx", "vol": 22200,
                                        "city": "san antonio", "tier": "ultra"}],
                        [r["kw"] for r in R2[:2]],
                        [{"keyword": "biscuit company"}, {"keyword": "bakery near san antonio"},
                         {"keyword": "best panaderia"}],
                        ["San Antonio, TX"], "", {"restaurant": 0.8}, k=1,
                        seeds=["restaurant", "breakfast", "bakery", "biscuits", "panaderia"],
                        brand="Alamo Biscuit Company & Panaderia",
                        levers={"adder": False, "volume": True})
check("their own name and a dangling preposition are not swapped in",
      [x["service"] for x in bn["in"]], ["best panaderia"])

# THE BUILD'S PER-SERVICE DEMAND is what the volume delta is measured in, not
# row sums: rows for a service can carry figures the total never held.
with app.app.test_request_context("/"):
    sv = app.kw_variant("lower", R2, [r["kw"] for r in R2[:2]],
                        [{"keyword": "biscuit restaurant"}], ["San Antonio, TX"], "",
                        {"restaurant": 0.8}, k=1,
                        seeds=["restaurant", "breakfast", "biscuits"],
                        levers={"adder": False, "volume": True},
                        service_volume={"restaurant": 100000, "breakfast": 18100})
check("volume delta off the build's service volume", sv["volume_delta"], 900 - 100000)

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
