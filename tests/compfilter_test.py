"""EVERYTHING THE RIVAL RANKS FOR IS NOT A SERVICE THIS CLIENT CAN SELL.

Reading six Huntingdon contractors for Cisney & O'Donnell returned, as things
to buy: masco sayre, web-don inc, home guide and american remodeling (their
NAMES), grass cutters, bush hogging, dog grooming and a roofing tax credit
(other trades those firms also run), epoxy floors in four wordings, and kitchen
remodeling in PITTSBURGH -- a service the grid would have quoted as "kitchen
remodel pittsburgh huntingdon pa".

Three filters, none of them a word list:

  the wrong trade        claude_seed_kinds already answers service / item /
                         other_business / reference per client with the
                         business in front of it.
  the wrong place        a geo in the position a geo is written in -- the last
                         word, or the one after in/near. Bath is a town in
                         Maine and "kitchen and bath showroom" is not about it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# What the six sites actually came back with.
RIVAL_ROWS = {
    "mcgraw-contracting.com": [
        ("masco sayre", 20), ("custom kitchen", 2400), ("bush hogging", 1000),
        ("kitchen remodel pittsburgh", 590), ("basement finishing", 90)],
    "ebendres.com": [
        ("grass cutters", 33100), ("web-don inc", 720), ("deck builder", 70),
        ("dog groomer within 20 mi", 480), ("home addition", 320)],
    "carusocabinet.com": [
        ("home guide", 2400), ("epoxy floor inside house", 1900),
        ("tax credit for a new roof", 480), ("custom kitchen", 2400),
        ("american remodeling", 720), ("kitchen and bath showroom", 140)],
}
SEEDS = ["contractor", "general contractor", "home remodel", "bathroom remodel",
         "kitchen remodel", "kitchen remodeling", "residential contractors"]
MARKETS = ["huntingdon county, pa", "blair county, pa", "huntingdon, pa",
           "altoona, pa"]

# The trade verdicts, as claude_seed_kinds answers them for a remodeler. A
# company NAME lands in other_business too, which is how the names that are not
# one of the six read domains are caught -- vendor_terms only knows the sites it
# was handed, and "web-don inc" is a fourth firm one of them ranks for.
KINDS = {
    "masco sayre": "other_business", "web-don inc": "other_business",
    "home guide": "other_business", "american remodeling": "other_business",
    "custom kitchen": "service", "basement finishing": "service",
    "deck builder": "service", "home addition": "service",
    "kitchen and bath showroom": "service",
    "kitchen remodel pittsburgh": "service",   # right trade, wrong place
    "bush hogging": "other_business", "grass cutters": "other_business",
    "dog groomer within 20 mi": "other_business",
    "epoxy floor inside house": "other_business",
    "tax credit for a new roof": "reference",
}


def run(kinds=KINDS):
    real_rk, real_kinds = app.fetch_ranked_keywords, app.claude_seed_kinds
    app.fetch_ranked_keywords = lambda dm, *a, **k: [
        {"bare": t, "term": t, "volume": v, "position": 5}
        for t, v in RIVAL_ROWS.get(dm, [])]
    app.claude_seed_kinds = lambda terms, *a, **k: {
        t: {"kind": kinds.get(t, "service"), "why": ""} for t in terms} if kinds else {}
    app.app.config["TESTING"] = True
    try:
        c = app.app.test_client()
        r = c.post("/api/competitor_seeds", json={
            "competitors": list(RIVAL_ROWS), "seeds": SEEDS,
            "brand": "Cisney & O'Donnell PA", "domain": "cisneyremodeling.com",
            "business_desc": "home remodeling contractor",
            "geo_values": MARKETS, "state": "PA"})
        return [x["term"] for x in (r.get_json() or {}).get("keywords", [])]
    finally:
        app.fetch_ranked_keywords, app.claude_seed_kinds = real_rk, real_kinds


terms = run()

# ---------------------------------------------- the rivals' own names
# The endpoint FLAGS these and returns them on purpose: "pipelogix alternative"
# is the comparison term a B2B campaign is built on, and which is which is a
# judgement about the campaign. The trade verdict catches them here, and the
# adtini panel drops anything still carrying a vendor flag -- see
# tests/compseeds_test.js.
for name in ("masco sayre", "web-don inc", "home guide", "american remodeling"):
    check("a rival's own name is not offered: %s" % name, name in terms, False)

# ---------------------------------------------- the wrong trade
for other in ("bush hogging", "grass cutters", "dog groomer within 20 mi",
              "epoxy floor inside house", "tax credit for a new roof"):
    check("another trade is not this client's: %s" % other, other in terms, False)

# ---------------------------------------------- the wrong place
check("the right service in the wrong city goes",
      "kitchen remodel pittsburgh" in terms, False)
# BATH IS A TOWN IN MAINE. Only a geo where a geo is written counts, or the
# client's own showroom term would go with it.
check("and a town name mid-phrase is not a geo",
      "kitchen and bath showroom" in terms, True)

# ---------------------------------------------- what survives is the point
check("the real gaps come through",
      sorted(terms), ["basement finishing", "custom kitchen", "deck builder",
                      "home addition", "kitchen and bath showroom"])

# ---------------------------------------------- AN UNAVAILABLE JUDGEMENT IS
# NOT A NEGATIVE ONE. claude_seed_kinds returns {} with no key, no network or
# bad JSON, and the list must survive that rather than empty itself.
blind = run(kinds=None)
check("no trade verdict keeps the list",
      "bush hogging" in blind and "custom kitchen" in blind, True)
# The deterministic two do not need the classifier: a read domain's own name,
# and a geo where a geo is written.
check("and the deterministic filters still run",
      ("kitchen remodel pittsburgh" in blind, "mcgraw contracting" in blind),
      (False, False))

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
