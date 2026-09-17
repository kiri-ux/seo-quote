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

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
