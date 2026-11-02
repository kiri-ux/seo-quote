"""WHAT A SITE RANKS FOR IS NOT WHAT IT SELLS.

Vici Media's Expand came back with sixteen suggestions off their own rankings,
every one a blog topic: "builtwith.com", "cookies on mobile phones", "why are
you looking at my search history". The ranked source skipped the "is this a
service they sell?" check the site-menu terms go through. Metric names ("view
through") and their own name with filler ("vici marketing") got through too.
Matches the dev build. (2026-11-02, Kiri)
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


VICI = ["programmatic advertising", "ott advertising", "geofencing marketing",
        "digital advertising agency"]

# ---- brand filter: their name plus filler ----
b = app.is_brand_term
check("vici marketing is their own name", b("vici marketing", "Vici Media", VICI), True)
check("vici reviews is their own name", b("vici reviews", "Vici Media", VICI), True)
check("a service is not", b("programmatic advertising", "Vici Media", VICI), False)
check("filler alone is not", b("digital marketing", "Vici Media", VICI), False)
check("denver dental stays", b("denver dental", "Denver Dental Group",
                                 ["dental implants"]), False)

# ---- ranked source runs the service check ----
ROWS = [{"term": t, "bare": t, "position": 5, "volume": 50, "url": ""}
        for t in ["ctv advertising", "builtwith.com", "cookies on mobile phones"]]
app.fetch_ranked_keywords = lambda *a, **k: [dict(r) for r in ROWS]
app.claude_seed_kinds = lambda terms, *a, **k: {
    "builtwith.com": {"kind": "reference", "why": "a website"},
    "cookies on mobile phones": {"kind": "reference", "why": "a blog topic"}}
c = app.app.test_client()
got = c.post("/api/ranked_keywords", json={"domain": "vicimediainc.com",
                                           "brand": "Vici Media", "seeds": VICI}).get_json()
check("only the service survives", [k["bare"] for k in got["keywords"]],
      ["ctv advertising"])
check("the rest are reported", sorted(x["term"] for x in got["not_services"]),
      ["builtwith.com", "cookies on mobile phones"])

# A blog-only site ranks for nothing but articles; that is not the classifier
# being broken, so nothing comes back.
app.claude_seed_kinds = lambda terms, *a, **k: {
    t: {"kind": "reference", "why": "blog"} for t in terms}
got = c.post("/api/ranked_keywords", json={"domain": "vicimediainc.com",
                                           "brand": "Vici Media", "seeds": VICI}).get_json()
check("all reference means none kept", got["keywords"], [])

# The ownership question still gets the raw set.
got = c.post("/api/ranked_keywords", json={"domain": "vicimediainc.com",
                                           "own": True}).get_json()
check("own skips the check", len(got["owned"]), 3)

print("\n%d/%d passed" % (len(CHECKS) - len(FAIL), len(CHECKS)))
sys.exit(1 if FAIL else 0)
