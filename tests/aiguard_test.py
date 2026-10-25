"""IS THE AI OVERVIEW ABOUT THIS CLIENT.

The deck prints Google's AI Overview word for word. Nothing checked that it
named the client, so a same-name company's answer would have printed as
theirs. It now has to name them, and a page one that is mostly another
company's drops it. Markdown and citation markers are taken out; nothing is
reworded. (2026-10-25, Kiri)
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


check("markdown, links and citations come out, words stay",
      rep_scan.clean_ai_text("**Wheeler Digital** is an agency [1]. "
                             "See [their site](https://x.com) https://y.com"),
      "Wheeler Digital is an agency. See their site")
names = rep_scan.ai_names_client
check("the name, any punctuation", (
    names("Wheeler-Digital is an agency", "Wheeler Digital LLC"),
    names("Cisney & O'Donnell handle claims", "Cisney & O'Donnell PA"),
    names("see wheelerdigital.com", "Acme", "https://wheelerdigital.com")),
    (True, True, True))
check("another company sharing a word is not them",
      names("Sage Grouse habitat", "Sage Dental"), False)
check("a word inside a longer word is not them",
      names("Sagedentalia is a plant", "Sage Dental"), False)


def org(pos, domain, title):
    return {"type": "organic", "rank_group": pos, "domain": domain,
            "url": "https://%s/" % domain, "title": title, "description": ""}


AI = {"type": "ai_overview", "items": [{"text": ""}]}
PAGE = []


def fake_post(path, tasks, timeout=None):
    return {"tasks": [{"result": [{"items": PAGE}]}]}


rep_scan.init(fake_post)


def scan(ai, page):
    PAGE[:] = page + [dict(AI, items=[{"text": ai}])]
    return rep_scan.scan_serp("Sage Dental", "sagedental.com")["ai_overview"]


OURS = [org(1, "sagedental.com", "Sage Dental | Dentist"),
        org(2, "yelp.com", "Sage Dental Reviews - Yelp")]
check("an overview that names them prints",
      scan("Sage Dental has mixed **reviews** [2].", OURS),
      "Sage Dental has mixed reviews.")
check("one that never names them is dropped",
      scan("This dental office has mixed reviews.", OURS), "")
THEIRS = [org(i, "other%d.com" % i, "Sage Dental Studio Boise %d" % i)
          for i in range(1, 6)]
check("a page one that is mostly another company's drops it",
      scan("Sage Dental Studio has mixed reviews.", THEIRS), "")

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
