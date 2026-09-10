"""TWO DOCUMENTS, AND ONLY ONE OF THEM EXISTED.

Most reputation conversations are only about the rating -- "we are 4.4 and we
want 4.5" -- and the only document the rep tool could produce was the full ORM
quote. The review analysis is now its own download, shaped on the Ski Barn
analysis that was written by hand in September 2026.

The star maths is checked against that hand-written document, because it is the
one place the right answers are already known. (2026-09-10, Kiri)
"""
import importlib.util
import io
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
import rep_docx as R      # noqa: E402
import rep_pricing        # noqa: E402

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# The four New Jersey locations, exactly as the hand-written analysis had them,
# and as the live pull returns them: depth 200, sorted lowest rating first, so
# Paramus and Wayne are truncated and still fully known below 5 stars.
SKI_BARN = [
    {"title": "Paramus", "profile_reviews": 619, "profile_rating": 4.4,
     "neg_1": 44, "neg_2": 14, "weak_3": 31, "pos_4": 94, "pos_5": 17,
     "complete": False},
    {"title": "Lawrence Township", "profile_reviews": 252,
     "profile_rating": 4.4, "neg_1": 20, "neg_2": 8, "weak_3": 12,
     "pos_4": 30, "pos_5": 182, "complete": True},
    {"title": "Wayne", "profile_reviews": 486, "profile_rating": 4.7,
     "neg_1": 11, "neg_2": 8, "weak_3": 20, "pos_4": 51, "pos_5": 110,
     "complete": False},
    {"title": "Shrewsbury", "profile_reviews": 186, "profile_rating": 4.4,
     "neg_1": 18, "neg_2": 1, "weak_3": 9, "pos_4": 20, "pos_5": 138,
     "complete": True},
]

print("\nTHE BUCKETS ARE EXACT EVEN WHEN THE PULL IS NOT")
b, exact = R.star_buckets(SKI_BARN[0])
check("Paramus is truncated", SKI_BARN[0]["complete"], False)
check("and still exact, because the pull reached the 5s", exact, True)
check("with the distribution the analysis had",
      [b["5"], b["4"], b["3"], b["2"], b["1"]], [436, 94, 31, 14, 44])
check("and the totals agree", b["total"], 619)

print("\nAND THE AVERAGES MATCH THE HAND-WRITTEN ANALYSIS")
for loc, want in zip(SKI_BARN, (4.40, 4.37, 4.67, 4.39)):
    bb, _ = R.star_buckets(loc)
    check(loc["title"], round(R._avg(bb), 2), want)

print("\nSO DO THE REMOVAL SCENARIOS")
for loc, k, proj in ((SKI_BARN[0], 10, 4.452), (SKI_BARN[1], 6, 4.455),
                     (SKI_BARN[2], 10, 4.750), (SKI_BARN[3], 4, 4.467)):
    r = R.removal_range(loc)
    check(f"{loc['title']} removals", r["remove"], k)
    check(f"{loc['title']} projected", round(r["projected_avg"], 3), proj)
    check(f"{loc['title']} is a number, not a range", r["exact"], True)

print("\nGOOGLE ROUNDS HALF UP, AND 4.75 IS 4.8")
check("4.75 displays as 4.8", R._tier(4.75), 4.8)
check("4.749 displays as 4.7", R._tier(4.749), 4.7)
check("4.4499 displays as 4.4", R._tier(4.4499), 4.4)

print("\nA PULL THAT NEVER REACHED THE 5s GIVES A RANGE, NOT A GUESS")
deep = {"title": "Big", "profile_reviews": 2000, "profile_rating": 4.4,
        "neg_1": 120, "neg_2": 40, "weak_3": 40, "pos_4": 0, "pos_5": 0,
        "complete": False}
_, ex = R.star_buckets(deep)
check("not exact", ex, False)
rr = R.removal_range(deep)
check("and reported as a span", rr["remove_max"] > rr["remove"], True)
check("marked inexact", rr["exact"], False)

print("\nA PERFECT PROFILE HAS NOWHERE TO GO")
check("5.0 returns nothing",
      R.removal_range({"profile_reviews": 10, "profile_rating": 5.0,
                       "neg_1": 0, "neg_2": 0, "weak_3": 0,
                       "pos_4": 0, "pos_5": 10, "complete": True}), None)
check("and neither does a profile with no one-stars",
      R.removal_range({"profile_reviews": 20, "profile_rating": 4.4,
                       "neg_1": 0, "neg_2": 4, "weak_3": 4,
                       "pos_4": 4, "pos_5": 8, "complete": True}), None)

try:
    import docx
except ImportError:
    print("\npython-docx not installed here — document checks skipped")
    print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
    sys.exit(1 if FAIL else 0)

client = app.app.test_client()


def text_of(data):
    d = docx.Document(io.BytesIO(data))
    out = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    for tb in d.tables:
        for row in tb.rows:
            out.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(out)


print("\nTHE REVIEW ANALYSIS DOCUMENT")
r = client.post("/api/rep_removals.docx",
                json={"brand": "Ski Barn", "region": "New Jersey Locations",
                      "locations": SKI_BARN, "margin_pct": 0.35})
check("it builds", r.status_code, 200)
check("it is a docx", r.data[:2], b"PK")
t = text_of(r.data)
check("it opens the way Sage's does", "Reputation Management:" in t, True)
check("with the areas line",
      "Ski Barn has several areas which require improvement from a "
      "reputational standpoint:" in t, True)
check("and the analysis named under it",
      "Google Business Profile review analysis" in t, True)
check("naming the client", "Ski Barn" in t, True)
check("with every location", all(l["title"] in t for l in SKI_BARN), True)
check("the star distribution", "5 ★ | 4 ★ | 3 ★ | 2 ★ | 1 ★" in t, True)
check("the scenarios", "Rating Improvement Scenarios" in t, True)
check("the ladder is written down the page, as Sage's is",
      "1 to 25 reviews: $900 per" in t, True)
check("every rung", all(f"{a} to {b} reviews:" in t for a, b in
      ((1, 25), (26, 50), (51, 100), (101, 250), (251, 350), (351, 500))), True)
check("and the whole-order rate for 30 removals", "$850 per review" in t, True)
check("no ORM services in it",
      any(w in t for w in ("Brand Shield", "Search Protection",
                           "Proactive", "Auto Suggest", "Related Searches")),
      False)
check("and no Partner A / Partner B — the rate card replaced them",
      "Partner A" in t or "Partner B" in t, False)

print("\nAND IT OPENS AND CLOSES THE WAY HIS OWN PROPOSALS DO")
check("the subject line",
      "Subject: Ski Barn - Reputation Management Proposal" in t, True)
check("the from line",
      "From: Brendan Egan, Aaron Peterson - Simple SEO Group" in t, True)
check("the IP notice", "remain the intellectual property of Simple SEO Group" in t, True)
check("his review wording, verbatim",
      "you, as the end client, can define which reviews you want removed" in t, True)
check("the success rates", "roughly 60% success rate" in t, True)
check("the pay-on-success terms",
      "payment is only due upon successful removal of the review from Google" in t, True)
check("the capacity note", "capacity to remove up to 500 reviews per month" in t, True)
check("next steps", "Proposal - Next Steps" in t, True)
check("and the footer", "1-888-918-1665 | info@SimpleSEOGroup.com" in t, True)

print("\nTHE PROPOSAL DOCUMENT")
q = rep_pricing.build_rep_quote(
    {"campaign": "bundle", "brand": "Ski Barn", "margin_pct": 0.35,
     "reviews": {"count": 26}, "articles": {"standard": 2, "premium": 1},
     "search": {"volume": 8000, "bundle": True}, "shield": {"locations": 4}})
r2 = client.post("/api/rep_proposal.docx",
                 json={"brand": "Ski Barn", "campaign": "bundle", "quote": q,
                       "margin_pct": 0.35})
check("it builds", r2.status_code, 200)
t2 = text_of(r2.data)
check("it opens as a proposal",
      "Subject: Ski Barn - Reputation Management Proposal" in t2, True)
check("the summary is his", "requesting information to assist in improving "
      "their online reputation" in t2, True)
check("website removals, his wording",
      "which to date has a 100% success rate" in t2, True)
check("with his pay-on-success terms",
      "payment is only due upon successful removal of the site from Google" in t2, True)
check("and his timeline", "average of 2-3 months to remove a site" in t2, True)
check("review removals, his wording", "roughly 50% success rate" in t2, True)
check("the search campaign is flagged as not performance-based",
      "not done on a performance basis" in t2, True)
check("the priced lines survive", "26 flagged reviews" in t2, True)
check("the shield", "Brand Shield" in t2, True)
check("the totals", "One-time and per-asset (pay on success)" in t2, True)
check("next steps", "new-client-registration-contract" in t2, True)
check("the rate card runs across the page there",
      "# Of Reviews Removed | 1-25 | 26-50 | 51-100 | 101-250 | 251-350 | 351-500"
      in t2, True)
check("and the footer", "SimpleSEOGroup.com/TOS" in t2, True)

print("\nAN EMPTY QUOTE SAYS SO RATHER THAN FAILING")
r3 = client.post("/api/rep_proposal.docx",
                 json={"brand": "Nobody", "campaign": "reactive",
                       "quote": {"lines": [], "totals": {}}})
check("still a document", r3.status_code, 200)
check("that says nothing is proposed",
      "Nothing is proposed" in text_of(r3.data), True)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
