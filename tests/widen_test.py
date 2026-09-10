"""FORTY DICTIONARY WORDS AND A LIST THAT WAS 87% ONE WRONG TERM.

Two faults, one build. drainify.io's keywords_for_site profile came back as a
dictionary -- `vict` 301,000, `note note` 165,000, `meta`, `manifest`, `modus
operandi`, `reverso context`, `copacetic` -- and every one of them walked past
the relevance filter, because site terms were exempted from it as "on-topic by
construction". They filled the Ultra Competitive column ahead of every real
term.

Underneath that, the real list measured 680/mo, of which `drain manholes` was
590 -- a term a homeowner searches and a company buying survey software does
not. Widening to the aisle the buyer actually shops in (field service
management, job management) took it to 1,500/mo of buyer demand.

Both were found by hand. This is the pair of rules that finds them.
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


SEEDS = ["drain survey software", "sewer inspection software", "cctv drain survey"]
DICT_TERMS = ["vict", "note note", "meta", "manifest", "modus operandi",
              "reverso context", "copacetic", "esperance", "apropos", "sic",
              "inflationation", "perpend", "alterate", "provisal", "intigent"]


def run_pool(ideas, site):
    """Drive the real filter in stage1_keyword_list with the calls stubbed."""
    app.dfs_post = lambda path, payload, **k: {"tasks": [{"result": [
        {"keyword": kw, "search_volume": v} for kw, v in ideas]}]}
    app.fetch_suggestions = lambda *a, **k: []
    app.fetch_keywords_for_site = lambda *a, **k: [
        {"keyword": kw, "volume": v} for kw, v in site]
    s1 = app.stage1_keyword_list(SEEDS, [], "", "Drainify", "drainify.io", "")
    return s1


print("\nA DICTIONARY IS NOT THIS CLIENT'S SUBJECT")
s1 = run_pool(
    ideas=[("drain survey software", 10), ("sewer inspection software", 10)],
    site=[(t, 300000 - i * 1000) for i, t in enumerate(DICT_TERMS)]
      + [("cctv drain survey software", 90)])
pool_kw = {r["keyword"] for r in s1["pool"]}
check("no dictionary term reaches the pool",
      sorted(pool_kw & set(DICT_TERMS)), [])
check("every one is counted out", s1["site_dropped_n"], len(DICT_TERMS))
check("a real site term survives",
      "cctv drain survey software" in pool_kw, True)
check("and the seeds do",
      "drain survey software" in pool_kw, True)

print("\nTHE HIGHEST-VOLUME TERM DOES NOT WIN BY BEING HIGHEST")
# 301,000 against 10. Without the rule these lead every bucket.
tops = [r["keyword"] for r in s1["ultra"]]
check("nothing from the dictionary leads the list",
      sorted(set(tops) & set(DICT_TERMS)), [])

print("\nA WORD LIFTED OUT OF A SEED IS NOT A KEYWORD")
# `field` measured 27,100 -- 98% of the list -- and led Ultra Competitive for a
# company selling drain-survey software, because "drainage field service
# management software" is a seed and the ideas call returns its parts.
FIELD_SEEDS = ["drainage field service management software",
               "sewer inspection software", "cctv drain survey"]
app.dfs_post = lambda path, payload, **k: {"tasks": [{"result": [
    {"keyword": "field", "search_volume": 27100},
    {"keyword": "software", "search_volume": 90500},
    {"keyword": "drainage", "search_volume": 14800},
    {"keyword": "sewer inspection software", "search_volume": 10},
    {"keyword": "drainage field service management software", "search_volume": 20},
]}]}
app.fetch_suggestions = lambda *a, **k: []
app.fetch_keywords_for_site = lambda *a, **k: []
f1 = app.stage1_keyword_list(FIELD_SEEDS, [], "", "Drainify", "drainify.io", "")
f_kw = {r["keyword"] for r in f1["pool"]}
check("the bare modifier is gone", "field" in f_kw, False)
check("so is every other seed word",
      sorted(f_kw & {"software", "drainage"}), [])
check("counted out", f1["fragments_dropped_n"], 3)
check("the whole seed survives",
      "drainage field service management software" in f_kw, True)
check("and the real term does", "sewer inspection software" in f_kw, True)

# A one-word focus term is the client's own choice and stays.
app.dfs_post = lambda path, payload, **k: {"tasks": [{"result": [
    {"keyword": "plumber", "search_volume": 60500},
    {"keyword": "emergency", "search_volume": 40500},
    {"keyword": "emergency plumber", "search_volume": 8100},
]}]}
f2 = app.stage1_keyword_list(["plumber", "emergency plumber"], [], "", "Acme", "", "")
f2_kw = {r["keyword"] for r in f2["pool"]}
check("a seeded single word stays", "plumber" in f2_kw, True)
check("an unseeded one does not", "emergency" in f2_kw, False)

print("\nA SHORT WORD IS NOT A MATCH")
# "sic" shares no substantive token; "survey" does. The filter is on words of
# four letters or more precisely so that "is"/"to" cannot carry a term through.
check("min token length is configured", app.CFG["site_term_min_token"], 4)

print("\nTHIN, AND THIN BECAUSE ONE TERM CARRIES IT")
before = app.widen_offer([
    {"kw": "drain manholes", "vol": 590}, {"kw": "cctv drain survey report", "vol": 40},
    {"kw": "pipeline inspection software", "vol": 20},
    {"kw": "sewer inspection software", "vol": 10},
    {"kw": "sewer crawler", "vol": 10}, {"kw": "drain survey software", "vol": 10},
    {"kw": "cctv survey software", "vol": 0}])
check("it offers", before["show"], True)
check("it names the number", before["total"], 680)
check("it names the term carrying it", before["top"], "drain manholes")
check("and says so plainly", before["fact"],
      "680/mo across 6 measured terms. drain manholes is 87% of it.")

after = app.widen_offer([
    {"kw": "field service management software", "vol": 880},
    {"kw": "job management software", "vol": 480},
    {"kw": "cctv drain survey report", "vol": 40},
    {"kw": "inspection reporting software", "vol": 20},
    {"kw": "pipeline inspection software", "vol": 20},
    {"kw": "pipe inspection software", "vol": 20},
    {"kw": "sewer inspection software", "vol": 10},
    {"kw": "drain survey software", "vol": 10},
    {"kw": "asset inspection software", "vol": 10},
    {"kw": "sewer crawler", "vol": 10}])
check("still thin after widening", after["total"], 1500)
check("but no longer one term's list", after["fact"],
      "1,500/mo across 10 measured terms.")

print("\nA HEALTHY LIST IS LEFT ALONE")
healthy = app.widen_offer([{"kw": "personal injury lawyer", "vol": 9900},
                           {"kw": "car accident lawyer", "vol": 6600},
                           {"kw": "truck accident attorney", "vol": 2400}])
check("no offer", healthy["show"], False)

print("\nNOTHING MEASURED IS ITS OWN CASE")
none = app.widen_offer([{"kw": "x", "vol": 0}, {"kw": "y", "vol": 0}])
check("offered", none["show"], True)
check("stated", none["fact"], "No term on the list returned volume.")
check("no division by zero", none["top_share"], 0.0)
check("no rows at all", app.widen_offer([])["show"], True)

print("\nWITHOUT A KEY IT RETURNS NOTHING RATHER THAN GUESSING")
_k = os.environ.pop("ANTHROPIC_API_KEY", None)
check("no terms", app.widen_vocabulary(SEEDS, "", "", "", []), [])
if _k:
    os.environ["ANTHROPIC_API_KEY"] = _k
check("and no seeds returns nothing",
      app.widen_vocabulary([], "x", "", "", []), [])

print("\nTHE ENDPOINT IS WIRED")
c = app.app.test_client()
app.widen_vocabulary = lambda *a, **k: ["field service management software",
                                        "job management software",
                                        "crew scheduling software"]
app.fetch_exact_volume = lambda kws, *a, **k: {
    "field service management software": 880, "job management software": 480}
r = c.post("/api/widen", json={"keywords": SEEDS, "domain": "drainify.io"})
d = r.get_json()
check("200", r.status_code, 200)
check("strongest first", [x["kw"] for x in d["terms"]],
      ["field service management software", "job management software",
       "crew scheduling software"])
check("measured count", d["measured"], 2)
check("volume added", d["added_volume"], 1360)
check("an unmeasured candidate still shows", d["terms"][2]["vol"], 0)
r2 = c.post("/api/widen", json={"keywords": []})
check("no seeds is a 400", r2.status_code, 400)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
