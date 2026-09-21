"""A CLIENT NAME CARRIES ITS PAPERWORK AND A SEARCH BOX DOES NOT.

Cisney & O'Donnell PA scanned to "0/mo brand volume". Not a quiet market: the
name matching asked for the ENTERED name as a literal substring of the search
phrase, and no phrase anyone types ends in "pa". Every row DataForSEO returned
classified as a different company, the brand universe summed to zero, and
Search Protection priced off its floor instead of off measured demand.

Three layers were doing it, all off the same key:

  1. classify_term — the term universe, which IS the Search Volume field.
  2. names_client — the related-searches filter, which put both of that
     client's own phrases in the "they name a different company" box.
  3. scan_locations' title gate, which found nothing by name; only the domain
     attempt found their one listing.

And the seeds sent to DataForSEO carried the suffix too, so Google Ads was
asked to expand a phrase nobody searches before any filter even ran.

What must NOT come back: the 2026-09-17 protection against a brand made of
common words. "City Heating and Air" claimed seven other companies' volume and
a 6.6x overcharge. Loosening the key cannot loosen that gate.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rep_scan

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


BRAND = "Cisney & O'Donnell PA"
LISTED = "Cisney & O'Donnell Builders & Remodelers"
SITE = "https://cisneyremodeling.com"

# ------------------------------------------------- the core name comes out
check("the legal tail comes off the seed", rep_scan.brand_seed(BRAND),
      "Cisney & O'Donnell")
check("and the core is tokens, not a string",
      rep_scan.brand_core(BRAND), ["cisney", "and", "odonnell"])
check("a name with no tail is left alone",
      rep_scan.brand_seed("City Heating and Air"), "City Heating and Air")
check("periods in the suffix do not hide it",
      rep_scan.brand_seed("Cisney & O'Donnell, P.A."), "Cisney & O'Donnell,")
check("a LEADING suffix word is part of the name",
      rep_scan.brand_seed("PA Roofing"), "PA Roofing")
check("and a hyphenated one is not a suffix at all",
      rep_scan.brand_seed("Co-op Market"), "Co-op Market")

# ------------------------------------------------- their own terms are theirs
THEIRS = {
    "cisney & o'donnell": "neutral",
    "cisney and o'donnell": "neutral",
    "cisney odonnell": "neutral",
    "cisney & o'donnell pa": "neutral",
    "cisney o'donnell remodeling": "neutral",
    "cisney & o'donnell reviews": "watch",
    "cisney odonnell reviews": "watch",
    "is cisney odonnell legit": "watch",
    "reviews for cisney and odonnell": "watch",
    "cisney & o'donnell complaints": "negative",
    "cisney and odonnell lawsuit": "negative",
    # run together, the way a brand known from a URL gets typed
    "cisneyodonnell reviews": "watch",
}
for t, cls in THEIRS.items():
    check("theirs: %s" % t, rep_scan.classify_term(t, BRAND), cls)

check("somebody else is still somebody else",
      rep_scan.classify_term("bullfrog remodeling reviews", BRAND), None)

# ------------------------------------------------- and the volume adds up
def term_post(path, payload, timeout=None):
    if "keywords_for_keywords" in path:
        rows = [{"keyword": t, "search_volume": v} for t, v in
                [("cisney & o'donnell", 210),
                 ("cisney odonnell reviews", 70),
                 ("cisney and o'donnell remodeling", 40),
                 ("cisney & o'donnell complaints", 20),
                 ("odonnell construction", 590)]]     # a different company
        return {"tasks": [{"result": rows}]}
    raise RuntimeError("probe not stubbed")


rep_scan.init(term_post)
out = rep_scan.scan_terms(BRAND)
check("the brand universe is no longer zero", out["total_volume"], 340)
check("the negative phrase is counted as negative", out["negative_volume"], 20)
check("the watch phrase is counted as watch", out["watch_volume"], 70)
check("and the other company is not in it",
      "odonnell construction" in [t["term"] for t in out["terms"]], False)

# THE SEED IS A PHRASE SOMEBODY TYPES. keywords_for_keywords was asked to
# expand "cisney & o'donnell pa", and the probe asked after eight more
# variants of it.
seeds = []


def seed_post(path, payload, timeout=None):
    seeds.append((path, payload[0]))
    return {"tasks": [{"result": []}]}


rep_scan.init(seed_post)
rep_scan.scan_terms(BRAND)
check("the seed drops the legal tail",
      seeds[0][1]["keywords"], ["cisney & o'donnell"])
check("and so do the exact-match probes",
      all(p.startswith("cisney & o'donnell ") for p in seeds[1][1]["keywords"]),
      True)

# ------------------------------------------------- the related-searches filter
# Both of this client's own phrases were excluded as "a different company".
check("their own related search is theirs",
      rep_scan.names_client("cisney & o'donnell reviews", BRAND, SITE), True)
check("spelled out, still theirs",
      rep_scan.names_client("cisney and o'donnell complaints", BRAND, SITE), True)
check("a topical phrase about somebody else is not",
      rep_scan.names_client("bullfrog remodeling reviews", BRAND, SITE), False)
# The 2026-08-05 case this filter exists for.
check("a manufacturer's complaints phrase stays out",
      rep_scan.names_client("hot springs hot tub reviews complaints",
                            "Hot Tubs Etc."), False)
check("and the client's own stays in",
      rep_scan.names_client("hot tubs etc reviews", "Hot Tubs Etc."), True)
# NO USABLE KEY MEANS STAND DOWN, not empty the panel.
check("with nothing to match on the filter stands down",
      rep_scan.names_client("anything at all", "", ""), True)

# ------------------------------------------------- a listing tail, reconciled
# Adopting Google's title used to make this WORSE, not better: the gate wants
# the whole entered name inside the phrase, so the longer the name the fewer
# terms can ever match. The two names are reconciled on their common head.
check("the listing name alone still fails the old way",
      rep_scan.classify_term("cisney & o'donnell reviews", LISTED), None)
check("but the typed name corroborates the head",
      rep_scan.classify_term("cisney & o'donnell reviews", LISTED, alias=BRAND),
      "watch")
check("and it works whichever name is in the field",
      rep_scan.classify_term("cisney & o'donnell reviews", BRAND, alias=LISTED),
      "watch")
check("an unrelated second name does not loosen anything",
      rep_scan.classify_term("cisney & o'donnell reviews", LISTED,
                             alias="Smith Plumbing"), None)

# TWO SOURCES ARE THE WHOLE POINT. Trimming a tail off one name on its own
# hands "Denver Dental Group" the term "denver dental" -- a service in a city,
# the best keyword they could buy, and thousands a month of other people's
# volume priced as theirs.
check("a descriptor tail is NOT trimmed on one name's word",
      rep_scan.classify_term("denver dental", "Denver Dental Group"), None)
check("and a listing that agrees on the full name changes nothing",
      rep_scan.classify_term("denver dental", "Denver Dental Group",
                             alias="Denver Dental Group of Cherry Creek"), None)

# ------------------------------------------------- the 6.6x overcharge stays shut
BRAND2 = "City Heating and Air"
for t in ["holy city heating and air", "river city heating and air",
          "bold city heating and air", "twin city heating and air",
          "forest city heating and air", "central city heating and air",
          "queen city heating and air conditioning"]:
    check("not theirs: %s" % t, rep_scan.classify_term(t, BRAND2), None)
check("nor squashed into one token",
      rep_scan.classify_term("twincityheatingair", BRAND2), None)
check("their own term still is theirs",
      rep_scan.classify_term("city heating and air", BRAND2), "neutral")
check("and so is their own listing's wording",
      rep_scan.classify_term("city heating and air conditioning", BRAND2),
      "neutral")

# A ONE-WORD CORE has only its own length keeping it off a common word, so a
# short one falls back to the name as entered.
check("a short core does not swallow a common word",
      rep_scan.classify_term("abc trucking", "ABC LLC"), None)
check("a long one is a real brand and works",
      rep_scan.classify_term("cisney reviews", "Cisney LLC"), "watch")

# ------------------------------------------------- the listing-title gate
def listing(title, reviews=10, pid=None):
    return {"title": title, "place_id": pid or title[:6],
            "rating": {"value": 4.3, "votes_count": reviews}}


def loc_post(items):
    def _p(path, payload, timeout=None):
        p = payload[0]
        by_domain = any(f and f[0] in ("domain", "url")
                        for f in (p.get("filters") or []))
        return {"tasks": [{"status_code": 20000,
                           "result": [{"items": [] if by_domain else items}]}]}
    return _p


rep_scan.init(loc_post([listing(LISTED, 27, pid="theirs")]))
r = rep_scan.scan_locations(BRAND)
check("the listing is found by NAME now, not only by website",
      [l["place_id"] for l in r["locations"]], ["theirs"])
check("and the panel says the name did it", r["strategy"], "title")

# THE AMPERSAND USED TO FAIL ITS OWN GATE. _squash dropped "&" outright, so a
# client listed as "City Heating & Air" did not contain "cityheatingandair".
rep_scan.init(loc_post([listing("City Heating & Air", 88, pid="theirs")]))
r = rep_scan.scan_locations(BRAND2)
check("an ampersand listing matches its spelled-out name",
      [l["place_id"] for l in r["locations"]], ["theirs"])

# ...and the 45-location scan stays shut.
rep_scan.init(loc_post([
    listing("Twin City Heating Air and Electric Blaine", 648, pid="twin"),
    listing("City Air Experts Heating and Cooling", 1045, pid="experts"),
    listing("City Heating and Air", 88, pid="theirs"),
]))
r = rep_scan.scan_locations(BRAND2)
check("other people's listings still do not come back",
      [l["place_id"] for l in r["locations"]], ["theirs"])

# ------------------------------------------------- the SERP asks a real query
asked = []


def serp_post(path, payload, timeout=None):
    asked.append(((payload[0].get("keyword") or "")))
    return {"tasks": [{"result": [{"items": []}]}]}


rep_scan.init(serp_post)
rep_scan.scan_serp(BRAND, SITE)
check("page one is pulled for a query somebody runs",
      asked[0], "cisney & o'donnell reviews")

asked.clear()


def ac_post(path, payload, timeout=None):
    # Echo data.keyword the way DFS does, so the empty-term fallback pass
    # (which re-asks with a trailing space and a trimmed prefix) stays out of
    # what this check is reading.
    for p in payload:
        asked.append(p.get("keyword") or "")
    return {"tasks": [{"data": {"keyword": p.get("keyword")},
                       "result": [{"items": [
                           {"type": "autocomplete", "suggestion": "x"}]}]}
                      for p in payload]}


rep_scan.init(ac_post)
rep_scan.scan_autocomplete(BRAND)
check("and auto-suggest is typed the same way",
      asked, ["cisney & o'donnell", "cisney & o'donnell reviews"])

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
