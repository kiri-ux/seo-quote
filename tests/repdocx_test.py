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
check("titled as a review analysis", "GOOGLE BUSINESS PROFILE REVIEW ANALYSIS" in t, True)
check("naming the client", "Ski Barn" in t, True)
check("with every location", all(l["title"] in t for l in SKI_BARN), True)
check("the star distribution", "5 ★ | 4 ★ | 3 ★ | 2 ★ | 1 ★" in t, True)
check("the scenarios", "Rating Improvement Scenarios" in t, True)
check("the rate card", "1-25 removals: $900 per review" in t, True)
check("and the whole-order rate for 30 removals", "$850 per review" in t, True)
check("no reputation management in it",
      any(w in t for w in ("Brand Shield", "Search Protection",
                           "Proactive", "monthly")), False)

print("\nTHE PROPOSAL DOCUMENT")
q = rep_pricing.build_rep_quote(
    {"campaign": "bundle", "brand": "Ski Barn", "margin_pct": 0.35,
     "reviews": {"count": 26}, "articles": {"standard": 2, "premium": 1},
     "search": {"volume": 8000, "bundle": True}, "shield": {"locations": 4}})
r2 = client.post("/api/rep_proposal.docx",
                 json={"brand": "Ski Barn", "campaign": "bundle", "quote": q})
check("it builds", r2.status_code, 200)
t2 = text_of(r2.data)
check("both phases", "Phase 1 — Reactive" in t2 and "Phase 2 — Proactive" in t2, True)
check("the review line", "Negative Review Removals" in t2, True)
check("the shield", "Proactive Brand Shield" in t2, True)
check("and the totals", "One-time and per-asset" in t2 and "Monthly" in t2, True)

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
