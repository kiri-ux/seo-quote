"""VALOR ROOFING'S EXPAND CAME BACK WEIRD.

Knoxville TN, seeds "roofing" and "asphalt roofs". Every seed Expand added came
off what roofingbyvalor.com ranks for, and the ranked phrases kept their place:
"knoxville roofing company", "knoxville tn roofer", "roofer in" (the city cut
off the end, the preposition left), "roofing maryville", "sevierville roofers".
Their own sister names got through too: "valor restoration", "valor home
services reviews". And the footer summed "roofing near me" (720) that the
header leaves out: 630/mo vs 1,350/mo on one list. (2026-11-25, Kiri)
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


M, S = ["Knoxville, TN"], "Tennessee"
g = lambda t: app.ranked_term_geo(t, M, S)
check("leading city comes out", g("knoxville roofing company"), ("roofing company", ""))
check("city + state code", g("knoxville tn roofer"), ("roofer", ""))
check("city + state name", g("knoxville tennessee roofers"), ("roofers", ""))
check("no dangling preposition", g("roofer in knoxville tn"), ("roofer", ""))
check("trailing city still works", g("metal roofing knoxville"), ("metal roofing", ""))
check("another TN town is flagged", g("roofing companies maryville")[1], "maryville")
check("another TN town, leading", g("sevierville roofers")[1], "sevierville")

nb = lambda t: app.names_brand_word(t, "Valor Roofing", "https://roofingbyvalor.com/",
                                    ["roofing", "asphalt roofs"])
check("sister name is their name", nb("valor restoration"), True)
check("name + reviews is their name", nb("valor home services reviews"), True)
check("a service is not", nb("roofing contractor"), False)
check("trade word in a name stays a service",
      app.names_brand_word("gutter guards", "Gutter Pros", "gutterpros.com",
                           ["gutter cleaning", "Home - Gutters"]),
      False)
check("a city in the name is not the name",
      app.names_brand_word("denver dentist", "Denver Dental Group",
                           "denverdentalgroup.com", ["dental"]), False)

ROWS = ["knoxville roofing company", "roofing company knoxville", "roofer in knoxville tn",
        "roofing maryville", "valor restoration", "roofing contractor"]
app.fetch_ranked_keywords = lambda dom, markets, state, lim=None: [
    dict(zip(("term", "bare", "elsewhere"), (t,) + app.ranked_term_geo(t, markets, state)),
         position=5, volume=50, url="") for t in ROWS]
app.claude_seed_kinds = lambda terms, *a, **k: {}
c = app.app.test_client()
got = c.post("/api/ranked_keywords", json={
    "domain": "https://roofingbyvalor.com/", "brand": "Valor Roofing",
    "seeds": ["roofing", "asphalt roofs"], "geo_values": M}).get_json()
check("only clean services come back", [k["bare"] for k in got["keywords"]],
      ["roofing company", "roofer", "roofing contractor"])
check("other town reported", got["other_markets"], ["maryville"])
check("sister name reported", "valor restoration" in got["brand_terms"], True)

w = app.widen_offer([{"kw": "knoxville roofing company", "vol": 390},
                     {"kw": "roofing near me", "vol": 720},
                     {"kw": "roofing knoxville tn", "vol": 210},
                     {"kw": "asphalt roofs knoxville tn", "vol": 10}])
check("footer leaves near-me out like the header", w["total"], 610)

print("\n%d/%d passed" % (len(CHECKS) - len(FAIL), len(CHECKS)))
sys.exit(1 if FAIL else 0)
