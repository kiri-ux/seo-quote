"""THE PRACTITIONER TERMS, AND THE PASS THAT NO LONGER WAITS.

Brendan on ENT Consultants of North MS (Q-100244): the keyword list was all
ailment-based — "ear infection treatment", "hearing aids", "adenoid removal" —
and carried none of "ENT", "ear nose and throat doctor", "hearing doctor near
me", which are the terms with the highest volume in that market.

Rule 2b of the expansion prompt proved the gap on its own: its model answer for
a general dental practice is "family dentistry, cleanings, crowns, invisalign,
veneers, emergency" and never once says "dentist". The prompt only ever asked
what the business DOES.

A prompt rule is one delete away from being gone with nothing failing, so the
rule is asserted here. The second half of the file pins the ordering property
the topics pass now depends on.
"""
import importlib.util
import os
import re
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

SOURCE = open(SRC, encoding="utf-8").read()

FAIL = []
RUN = []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# ------------------------------------------------- the rule reaches the prompt
# Built by calling the real function with no API key: it returns None before it
# posts, so the prompt is constructed exactly as it would be for a live build
# and nothing is sent. That is the only way to prove the rule survives the
# f-string rather than merely existing somewhere in the file.
saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
check("no key means no call", app.claude_expand_services(
    ["ear infection treatment"], "An ENT practice", [], "ENT Consultants",
    "entnorthms.com", [], 20), None)
if saved_key is not None:
    os.environ["ANTHROPIC_API_KEY"] = saved_key

# The prompt text itself lives in the source; assert against the rule block.
rule = ""
m = re.search(r"^2w\..*?(?=^2h\.)", SOURCE, re.S | re.M)
if m:
    rule = m.group(0)

check("the practitioner rule is in the prompt", bool(rule), True)
check("it is stated as what they are, not what they do",
      "WHAT THEY ARE, NOT ONLY WHAT THEY DO" in rule, True)
check("it says these carry the highest volume",
      "HIGHEST volume" in rule, True)
for term in ("ENT", "ear nose and throat doctor", "audiologist"):
    check("names the ENT term %r" % term, term in rule, True)
check("carries the dentist case rule 2b missed", "dentist" in rule, True)
check("generalises past medicine (law)", "personal injury lawyer" in rule, True)
check("generalises past medicine (trades)", "plumber" in rule, True)
check("at least one practitioner term is ultra",
      "ULTRA tier" in rule, True)
check("abbreviation and spelled-out form are separate services",
      "ABBREVIATION" in rule, True)

# The near-me pass can only reach terms already in this list, which is why a
# missing practitioner term costs more than one slot: it also costs the
# "<practitioner> near me" form the operator expected to see.
check("the rule says these stay bare for the grid",
      'near me' in rule and 'grid adds the place' in rule, True)
check("and explains the near-me pass depends on it",
      "near-me pass" in rule, True)

# A guard against the obvious overcorrection: not every business is a profession.
check("a retailer is exempted", "retailer is a store" in rule, True)
check("and inventing a title is forbidden",
      "Do NOT invent a title" in rule, True)

# The existing near-me machinery is what turns these into the forms Brendan
# listed, so the rule is only useful while that pass is switched on.
check("near-me terms are still configured",
      int(app.CFG.get("near_me_terms") or 0) > 0, True)

# ------------------------------------------------- topics no longer wait
# claude_topics reads seeds, the business description and the brand. None is
# touched between the expansion and the point the answer is first needed, so it
# is submitted before claude_expand_services and collected at
# enforce_topic_coverage. Assert the order, because reverting it would cost the
# overlap silently — the build would just be slower.
body = SOURCE[SOURCE.index("def stage1b_refine"):]
body = body[:body.index("\ndef ")]
i_submit = body.find("_topic_pool.submit(claude_topics")
i_expand = body.find("services = claude_expand_services(")
i_collect = body.find("_topic_fut.result()")
i_enforce = body.find("enforce_topic_coverage(services")

check("topics is submitted inside stage1b_refine", i_submit > 0, True)
check("submitted BEFORE the expansion runs", 0 < i_submit < i_expand, True)
check("collected after the expansion", i_collect > i_expand, True)
check("and before the coverage guarantee needs it",
      0 < i_collect < i_enforce, True)
check("the pool is not left running", "_topic_pool.shutdown(wait=False)" in body, True)

# A raised pass used to escape stage1b_refine and cost the whole refine, which
# returns the UNREFINED list. Through a future it has to be caught here.
tail = body[i_collect - 400:i_collect + 400]
check("a failed topics pass falls back instead of sinking the build",
      "except Exception" in tail and "topic_clusters(topic_seeds)" in body, True)

# topic_seeds is computed once, at the submit site, so both users agree.
check("topic_seeds is computed once", body.count("topic_seeds = _buyable"), 1)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
