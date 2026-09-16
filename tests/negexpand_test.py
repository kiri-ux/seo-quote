"""A NEGATIVE THE PLANNER TYPED HAS TO REACH THE EXPANSION, NOT JUST THE BUILD.

ENT Consultants of North MS, 2026-09-16: "allergy" was in the negative terms and
the Expand button proposed "allergy testing" and "allergy doctor" anyway.

Negatives were applied in exactly one place -- drop_negative_services, inside
stage1b_refine, on the BUILD path. The expand route never read them, the
gap-finder had no parameter for them, and the prompt never mentioned them.

And it compounds, which is the part that makes it worse than a missed filter.
Expand adds its proposals as SEED chips, and drop_negative_services deliberately
never touches seeds -- "a focus term that trips a negative is reported on the
panel and kept", because the planner's own list is not the tool's to overrule.
So a negated term proposed by the tool laundered itself into the one place the
negative filter will not look.

Checked in code as well as in the prompt: a prompt rule is not a guarantee, and
this is a rule the planner typed by hand.
"""
import importlib.util
import json
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

SOURCE = open(SRC, encoding="utf-8").read()
UI = open(os.path.join(SRCDIR, "templates", "adtini.html"), encoding="utf-8").read()

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


PROMPT = {}


def gap(returns, negatives):
    """Run the gap-finder with the model answering `returns`."""
    def fake(url, *a, **kw):
        if "anthropic" in str(url):
            PROMPT["text"] = json.loads(kw["data"])["messages"][0]["content"]

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text", "text": json.dumps(
                    {"services": [{"term": t, "why": "x"} for t in returns]})}]}
        return R()

    real_post, real_key = app.requests.post, os.environ.get("ANTHROPIC_API_KEY")
    app.requests.post = fake
    os.environ["ANTHROPIC_API_KEY"] = "x"
    try:
        out = app.claude_industry_services(
            brand="ENT Consultants", domain="entoxford.com", industry="Medical",
            business_desc="An ENT practice", site_pages=[],
            seeds=["hearing aids", "tonsillectomy"], geo="oxford, ms",
            negatives=negatives)
        return [c["term"] for c in out]
    finally:
        app.requests.post = real_post
        if real_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = real_key


# ---------------------------------------------- the reported case
MODEL_SAID = ["allergy testing", "allergy doctor", "allergy treatment",
              "ear tube surgery", "ent"]
kept = gap(MODEL_SAID, ["allergy"])
check("every allergy term is dropped",
      [t for t in kept if "allergy" in t], [])
check("and the rest survive", kept, ["ear tube surgery", "ent"])

# ---------------------------------------------- the prompt is told too
# Dropping them silently wastes the slots: the model spends three of its
# twenty-two on terms that are thrown away. Telling it recovers them.
check("the prompt names the exclusions",
      "THE PLANNER HAS RULED THESE OUT" in PROMPT.get("text", ""), True)
check("and lists the actual negative",
      "wording: allergy" in PROMPT.get("text", ""), True)
check("and says why, so they are not read as gaps to fill",
      "not gaps to fill" in PROMPT.get("text", ""), True)

# No negatives means no such block -- an empty rule is noise in a prompt.
gap(["ent"], [])
check("no negatives, no block",
      "THE PLANNER HAS RULED THESE OUT" in PROMPT.get("text", ""), False)

# ---------------------------------------------- whole words, never fragments
# The same matcher the build uses, so the two cannot disagree about what a
# negative excludes. negative_hit's own docstring: negating "carrier" must not
# take "career", "auto" must not take "automotive".
check("a negative matches a whole word", app.negative_hit("allergy testing", ["allergy"]),
      "allergy")
check("and not a fragment", app.negative_hit("allegory writing", ["allergy"]), "")
check("a multi-word negative matches as a phrase",
      app.negative_hit("workers comp lawyer", ["workers comp"]), "workers comp")
check("and does not fire on one of its words",
      app.negative_hit("workers rights lawyer", ["workers comp"]), "")
kept = gap(["automotive repair", "auto insurance"], ["auto"])
check("the gap-finder uses that same matcher",
      kept, ["automotive repair"])

# ---------------------------------------------- the route passes them on
check("the expand route reads negatives off the payload",
      'negatives = [str(x).strip() for x in (d.get("negatives") or [])' in SOURCE, True)
check("and hands them to the gap-finder",
      "negatives=negatives)" in SOURCE, True)

# ---------------------------------------------- and the browser sends them
# Three passes feed the seed box and only one is the gap-finder; a term the
# client ranks for, or names on their own site, can trip a negative too.
check("the expand payload carries negatives",
      "negatives: (d.negatives || []).slice()," in UI, True)
check("and all three sources are filtered where they merge",
      "|| tripsNegative(term)) return;" in UI, True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
