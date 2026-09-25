"""WHOSE LOCATIONS ARE THESE.

A brand scan of "City Heating and Air" (cityheatandair.com) came back with 45
Google locations: City Air Experts, Twin City Heating Air and Electric Blaine,
HEP Heating Johnson City, Queen City Heating, Military City Air. Different
companies in different states. The review pull then ran on all 45 and the quote
priced 130 flagged reviews belonging to other people's businesses.

Two things were wrong and both are here.

  1. The domain attempts ran LAST. A listing pointing at the client's own
     website is the client; a listing whose name contains the client's words is
     a guess. The guesses ran first and never came back empty, so the identity
     match never fired.

  2. The name gate asked whether every token appeared ANYWHERE in the title, in
     any order, as a substring. "city", "heating", "and", "air" are all inside
     "Twin City Heating Air and Electric Blaine" -- and inside most HVAC
     company names in America.
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


def listing(title, reviews=10, pid=None):
    return {"title": title, "place_id": pid or title[:6],
            "rating": {"value": 4.1, "votes_count": reviews}}


# The eight the real scan led with, worst first for the pull.
BY_NAME = [
    listing("City Air Experts Heating and Cooling", 1045),
    listing("Twin City Heating Air and Electric Blaine", 648),
    listing("HEP Heating and Air Johnson City South", 571),
    listing("Green City Heating and Air Conditioning", 546),
    listing("Queen City Heating and Air Conditioning", 432),
    listing("Military City Air Conditioning and Heating", 376),
    listing("River City Heating and Air", 274),
    listing("City Heating and Air", 88, pid="theirs"),
]
# What the client's own domain returns: one listing, under another name.
BY_DOMAIN = [listing("City Heat and Air LLC", 88, pid="theirs")]


def fake(items_for):
    """items_for(payload) -> the listing rows that query returns."""
    seen = []

    def _post(path, payload, timeout=None, method=None):
        seen.append(payload[0])
        return {"tasks": [{"status_code": 20000,
                           "result": [{"items": items_for(payload[0])}]}]}
    return _post, seen


def is_domain_query(p):
    f = p.get("filters") or []
    return bool(f) and f[0][0] in ("domain", "url")


# ------------------------------------------------- the domain match is tried
# first, and it is the one that answers
_post, seen = fake(lambda p: BY_DOMAIN if is_domain_query(p) else BY_NAME)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air", domain="https://www.cityheatandair.com/")
check("the client's own website is asked first", is_domain_query(seen[0]), True)
check("and it is what answers", r["strategy"], "domain")
check("one location, not forty-five", len(r["locations"]), 1)
check("and it is theirs", [l["place_id"] for l in r["locations"]], ["theirs"])
check("a name mismatch does not disqualify a domain match",
      r["locations"][0]["title"], "City Heat and Air LLC")
check("no name search was spent at all", len(seen), 1)

# ------------------------------------------------- with no domain, the name
# gate has to carry it, and a phrase is not four loose words
_post, seen = fake(lambda p: BY_NAME)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air")
kept = [l["title"] for l in r["locations"]]
check("the name search is what runs", r["strategy"], "title")
check("their own listing survives", "City Heating and Air" in kept, True)
for junk in ("City Air Experts Heating and Cooling",
             "Twin City Heating Air and Electric Blaine",
             "HEP Heating and Air Johnson City South",
             "Military City Air Conditioning and Heating"):
    check("dropped: %s" % junk, junk in kept, False)
# HONEST ABOUT WHAT THE GATE CANNOT DO. These three carry the brand as a
# contiguous phrase, so no name rule reaches them -- which is the whole reason
# the domain runs first. Pinned so nobody reads this test as "solved".
check("a phrase gate cannot separate these three",
      sorted(t for t in kept if t != "City Heating and Air"),
      ["Green City Heating and Air Conditioning",
       "Queen City Heating and Air Conditioning",
       "River City Heating and Air"])

# ------------------------------------------------- the old gate kept all eight
old_gate = [t for t in (l["title"] for l in BY_NAME)
            if all(tok in t.lower()
                   for tok in "city heating and air".split())]
check("the gate this replaced kept every one of them", len(old_gate), 8)

# ------------------------------------------------- short brands stand down
# "Hot Tubs Etc." style punctuation still matches, and a brand too short to be
# a useful key does not empty the panel.
_post, seen = fake(lambda p: [listing("Hot Tubs Etc.", 30), listing("Bullfrog Spas", 90)])
rep_scan.init(_post)
r = rep_scan.scan_locations("Hot Tubs Etc")
check("punctuation does not break the phrase match",
      [l["title"] for l in r["locations"]], ["Hot Tubs Etc."])

_post, seen = fake(lambda p: [listing("Zed", 5), listing("Anything", 5)])
rep_scan.init(_post)
r = rep_scan.scan_locations("Zed")
check("a brand too short to key on does not empty the panel",
      len(r["locations"]), 2)

# ------------------------------------------------- domain empty -> fall back
_post, seen = fake(lambda p: [] if is_domain_query(p) else BY_NAME)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air", domain="cityheatandair.com")
check("an empty domain match falls through to the name search",
      r["strategy"], "title")
check("and the name gate still applies there",
      "City Air Experts Heating and Cooling" in [l["title"] for l in r["locations"]],
      False)

# ------------------------------------------------- and the same brand name
# does the same damage to the TERM universe
#
# Search Protection is priced off total brand volume. classify_term asked only
# whether the brand appeared anywhere in the term, so this client's universe
# came back 3,190/mo -- of which 480 was theirs and 2,710 belonged to seven
# other companies with "city", "heating" and "air" in their names.
BRAND = "City Heating and Air"
THEIRS = ["city heating and air",
          "city heating and air reviews",
          "city heating and air complaints",
          "is city heating and air legit",
          "reviews for city heating and air",
          "city heating and air conditioning"]
SOMEBODY_ELSE = ["holy city heating and air", "river city heating and air",
                 "bold city heating and air", "twin city heating and air",
                 "forest city heating and air", "central city heating and air",
                 "queen city heating and air conditioning"]
for t in THEIRS:
    check("theirs: %s" % t, rep_scan.classify_term(t, BRAND) is not None, True)
for t in SOMEBODY_ELSE:
    check("not theirs: %s" % t, rep_scan.classify_term(t, BRAND), None)
check("the modifier still decides the class",
      [rep_scan.classify_term(t, BRAND) for t in
       ("city heating and air", "city heating and air reviews",
        "city heating and air lawsuit")],
      ["neutral", "watch", "negative"])
# WHAT COMES AFTER THE BRAND IS LEFT ALONE. Google lists this very client as
# "City Heating & Air Conditioning", so a trailing word is not a different
# company.
check("a trailing word does not disqualify a term",
      rep_scan.classify_term("city heating and air conditioning", BRAND), "neutral")

# and the volume that reaches the quote is only theirs
_post, seen = fake(lambda p: [])


def term_post(path, payload, timeout=None):
    if "keywords_for_keywords" in path:
        rows = [{"keyword": t, "search_volume": v} for t, v in
                [("holy city heating and air", 590), ("city heating and air", 480),
                 ("river city heating and air", 390), ("bold city heating and air", 260),
                 ("twin city heating and air", 260), ("forest city heating and air", 260),
                 ("queen city heating and air conditioning", 170),
                 ("central city heating and air", 110)]]
        return {"tasks": [{"result": rows}]}
    raise RuntimeError("probe not stubbed")


rep_scan.init(term_post)
out = rep_scan.scan_terms(BRAND)
check("the brand universe is 480/mo, not 3,190", out["total_volume"], 480)
check("and it is one term", len(out["terms"]), 1)
check("the seven other companies are gone",
      [t["term"] for t in out["terms"]], ["city heating and air"])

# ------------------------------------------------- PAGE ONE STARTS AT ONE
# rank_absolute counts every element on the page -- ads, the local pack, the AI
# overview, image strips -- so the first organic result came back as #6 and a
# top-10 pull read "Page one: 6 through 14". Nobody can tell whether that is
# page one. app.py's own rank check already prefers rank_group.
def serp_post(path, payload, timeout=None):
    return {"tasks": [{"result": [{"items": [
        {"type": "organic", "rank_group": 1, "rank_absolute": 6,
         "domain": "ripoffreport.com", "url": "https://r/1", "title": "City Heating and Air reviews"},
        {"type": "organic", "rank_group": 2, "rank_absolute": 7,
         "domain": "yelp.com", "url": "https://y/2", "title": "City Heating and Air reviews"},
        {"type": "organic", "rank_group": 9, "rank_absolute": 14,
         "domain": "angi.com", "url": "https://a/3", "title": "City Heating and Air reviews"},
        {"type": "discussions_and_forums", "rank_absolute": 11,
         "items": [{"domain": "reddit.com", "url": "https://x", "title": "City Heating and Air reviews"}]},
    ]}]}]}


rep_scan.init(serp_post)
sr = rep_scan.scan_serp("City Heating and Air", "cityheatandair.com")
check("page one is numbered by organic rank",
      [o["pos"] for o in sr["organic"]], [1, 2, 9])
check("not by absolute position on the page",
      [o["pos"] for o in sr["organic"]] != [6, 7, 14], True)
# A FORUM BLOCK HAS NO ORGANIC RANK OF ITS OWN, so absolute is the only
# reading there and stays.
check("a forum block keeps its position on the page",
      [f["pos"] for f in sr["forums"]], [11])

# ------------------------------------------- PAGE ONE FOR THE NAME, NOT THE WORD
# "seascape reviews" came back all MSC Seascape, a cruise ship, and each page
# was tagged and priced as Seascape, Inc's. (2026-09-25)
def ship_post(path, payload, timeout=None):
    return {"tasks": [{"result": [{"items": [
        {"type": "organic", "rank_group": 1, "domain": "cruisecritic.com",
         "url": "https://c/1", "title": "MSC Seascape Review"},
        {"type": "organic", "rank_group": 2, "domain": "yelp.com",
         "url": "https://y/2", "title": "Seascape Inc - Los Alamitos - Yelp"},
        {"type": "organic", "rank_group": 3, "domain": "seascapeinc.com",
         "url": "https://seascapeinc.com", "title": "Home"},
        {"type": "discussions_and_forums", "rank_absolute": 9,
         "items": [{"domain": "reddit.com", "url": "https://x",
                    "title": "MSC Seascape : r/MSCCruises"}]},
    ]}]}]}


rep_scan.init(ship_post)
sr = rep_scan.scan_serp("Seascape, Inc", "seascapeinc.com")
check("a page about somebody else's Seascape is not page one",
      [o["domain"] for o in sr["organic"]], ["yelp.com", "seascapeinc.com"])
check("nor is their reddit thread", sr["forums"], [])
check("both are kept aside, not lost",
      [o["url"] for o in sr["off_brand_results"]], ["https://c/1", "https://x"])
# ...and the scan offers a narrower term: 2 of 4 results were the ship.
check("the scan suggests the name with its legal tail",
      sr["suggested_query"], "seascape inc")
sr = rep_scan.scan_serp("Seascape", "seascapeinc.com",
                        location="Los Alamitos,California,United States")
check("or the name plus their city", sr["suggested_query"],
      "seascape los alamitos")
sr = rep_scan.scan_serp("Seascape, Inc", "seascapeinc.com", query="seascape inc",
                        location="Los Alamitos,California,United States")
check("still wrong: the next term, not the one just searched",
      sr["suggested_query"], "seascape los alamitos")
sr = rep_scan.scan_serp("Seascape, Inc", "seascapeinc.com", query="seascape inc los alamitos",
                        tried=["seascape inc", "seascape los alamitos"],
                        location="Los Alamitos,California,United States")
check("and nothing once every term is spent", sr["suggested_query"], "")

# ------------------------------------------------ A NAME IS NOT A COMPANY
# "seascape inc reviews" was SeaScape Lawn Care, Inc in Coventry, RI: same
# name, other state, other domain. The client's listing is Los Alamitos, CA.
# (2026-09-25)
lawn_asked = []
def lawn_post(path, payload, timeout=None):
    lawn_asked.append(payload[0])
    return {"tasks": [{"result": [{"items": [
        {"type": "organic", "rank_group": 1, "domain": "seascapeinc.net",
         "url": "https://seascapeinc.net", "title": "Frozen Seafood Supplier - Seascape Inc"},
        {"type": "organic", "rank_group": 2, "domain": "indeed.com", "url": "https://i",
         "title": "SeaScape Lawn Care Inc Employee Reviews in Coventry, RI"},
        {"type": "organic", "rank_group": 3, "domain": "seascapeinc.com",
         "url": "https://seascapeinc.com", "title": "Home - SeaScape, Inc."},
        {"type": "organic", "rank_group": 4, "domain": "facebook.com", "url": "https://f",
         "title": "SeaScape | Coventry RI"},
        {"type": "organic", "rank_group": 5, "domain": "yelp.com", "url": "https://y",
         "title": "Seascape Inc - Los Alamitos, CA - Yelp"},
        # Names no state: known only by the words the other company uses.
        {"type": "organic", "rank_group": 6, "domain": "yelp.com", "url": "https://y2",
         "title": "SeaScape - Lawn Services"},
        {"type": "organic", "rank_group": 7, "domain": "simplyhired.com", "url": "https://s",
         "title": "SeaScape Lawn Care Inc Employment and Reviews"},
        # A title cut short still reads as an address.
        {"type": "organic", "rank_group": 8, "domain": "glassdoor.com", "url": "https://g",
         "title": "Working at SeaScape, Inc in Coventry, RI..."},
    ]}]}]}


rep_scan.init(lawn_post)
sr = rep_scan.scan_serp("Seascape, Inc", "https://www.seascapeinc.net/",
                        query="seascape inc",
                        home="10571 Calle Lee #137, Los Alamitos, CA 90720")
check("searched from their town when the order is nationwide",
      lawn_asked[-1].get("location_name"), "Los Alamitos,California,United States")
check("the other state's company and its lookalike domain are set aside",
      [o["domain"] for o in sr["organic"]], ["seascapeinc.net", "yelp.com"])
check("and the note can say where", sr["searched_from"],
      "Los Alamitos,California,United States")
sr = rep_scan.scan_serp("Seascape, Inc", "https://www.seascapeinc.net/",
                        query="seascape inc",
                        location="Denver,Colorado,United States",
                        home="10571 Calle Lee #137, Los Alamitos, CA 90720")
check("a market on the order still wins",
      lawn_asked[-1].get("location_name"), "Denver,Colorado,United States")

# ----------------------------------------------- THE PLANNER'S SEARCH TERM
# A typed term is searched as typed: "seascape inc" keeps its "inc", where the
# brand alone would search "seascape". (2026-09-25)
asked = []
def q_post(path, payload, timeout=None):
    asked.append((path, payload[0]))
    if "keywords_for_keywords" in path:
        return {"tasks": [{"result": [
            {"keyword": "seascape inc", "search_volume": 90},
            {"keyword": "seascape cruise", "search_volume": 40000},
            {"keyword": "seascape inc reviews", "search_volume": 20}]}]}
    return {"tasks": [{"result": [{"items": []}]}]}


rep_scan.init(q_post)
rep_scan.scan_serp("Seascape, Inc", "seascapeinc.com", query="Seascape Inc")
check("the SERP searches the typed term", asked[-1][1]["keyword"],
      "seascape inc reviews")
rep_scan.scan_serp("Seascape, Inc", "seascapeinc.com")
check("blank searches the brand", asked[-1][1]["keyword"], "seascape reviews")
out = rep_scan.scan_terms("Seascape, Inc", query="seascape inc")
check("the term universe is seeded on it",
      [p["keywords"] for x, p in asked if "keywords_for_keywords" in x][-1],
      ["seascape inc"])
check("and only phrases carrying it count",
      sorted(t["term"] for t in out["terms"]),
      ["seascape inc", "seascape inc reviews"])
try:
    rep_scan.scan_autocomplete("Seascape, Inc", query="seascape inc")
except Exception:
    pass
check("auto-suggest asks after it too",
      any(p.get("keyword") == "seascape inc" for x, p in asked
          if "autocomplete" in x), True)

# ------------------------------------------------- A NAME MATCH IN THEIR TOWN
# The domain match is identity and needs no help. The name fallback is a guess,
# and a brand made of common words still collects Green City, Queen City and
# River City after the phrase gate -- all of them real companies, none of them
# in Knoxville.
IN_AND_OUT = [
    listing("City Heating and Air", 88, pid="theirs"),
    listing("Green City Heating and Air Conditioning", 546, pid="g"),
    listing("River City Heating and Air", 274, pid="r"),
]
IN_AND_OUT[0]["address"] = "3111 NW Park Dr, Knoxville, TN 37921"
IN_AND_OUT[1]["address"] = "8898 Hwy 99, Seattle, WA 98103"
IN_AND_OUT[2]["address"] = "1200 Front St, Memphis, TN 38103"

_post, seen = fake(lambda p: IN_AND_OUT)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air",
                            location="Knoxville,Tennessee,United States")
check("only the listings in their market survive a name match",
      [l["place_id"] for l in r["locations"]], ["theirs"])
check("and the panel says the market did it", r["strategy"], "title+market")

# WRONG MARKET, OR THEY TRADE ELSEWHERE: the unfiltered list stands rather
# than nothing, and `strategy` says which.
_post, seen = fake(lambda p: IN_AND_OUT)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air",
                            location="Boise,Idaho,United States")
check("a market that matches nothing does not empty the panel",
      len(r["locations"]), 3)
check("and it says so", r["strategy"], "title")

# A DOMAIN MATCH IS IDENTITY, so the market does not narrow it.
_post, seen = fake(lambda p: BY_DOMAIN if is_domain_query(p) else IN_AND_OUT)
rep_scan.init(_post)
r = rep_scan.scan_locations("City Heating and Air", domain="cityheatandair.com",
                            location="Boise,Idaho,United States")
check("the website match is not second-guessed by the market",
      r["strategy"], "domain")
check("and it is still their listing", len(r["locations"]), 1)

# ------------------------------------------------- THE SCAN ASKS FROM THE
# CLIENT'S MARKET
#
# Every scan call was hardcoded to location_code 2840, the whole country, so
# the Geographic Targeting Areas on the form did nothing -- and a Knoxville
# client's page one came back with HVAC companies in Charlotte, Tucson and
# Blaine, which were then counted as theirs and priced for removal.
seen_payloads = []


def where_post(path, payload, timeout=None):
    seen_payloads.append((path, payload[0]))
    return {"tasks": [{"result": [{"items": []}]}]}


rep_scan.init(where_post)
rep_scan.scan_serp("City Heating and Air", "cityheatandair.com",
                   location="Knoxville,Tennessee,United States")
check("the SERP is pulled from the client's market",
      seen_payloads[-1][1].get("location_name"), "Knoxville,Tennessee,United States")
check("and not from the whole country",
      "location_code" in seen_payloads[-1][1], False)

rep_scan.scan_serp("City Heating and Air", "cityheatandair.com")
check("with no market on the order it falls back to the US",
      seen_payloads[-1][1].get("location_code"), 2840)

rep_scan.init(where_post)
try:
    rep_scan.scan_autocomplete("City Heating and Air",
                               location="Knoxville,Tennessee,United States")
except Exception:
    pass
check("auto-suggest asks from the same market",
      any(p.get("location_name") == "Knoxville,Tennessee,United States"
          for _, p in seen_payloads if "autocomplete" in _), True)

# A BRAND'S OWN DEMAND IS NOT LOCAL. The term universe stays national: whoever
# is looking for this brand is looking wherever they are, and the Search
# Protection bases were fitted on national volume (Sage at 51,330/mo).
seen_payloads.clear()
rep_scan.init(where_post)
try:
    rep_scan.scan_terms("City Heating and Air")
except Exception:
    pass
check("the term universe stays national",
      seen_payloads[0][1].get("location_code"), 2840)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
