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

# ------------------------------------- AND THE OTHER EXPANSION, WHICH I MISSED
# There are TWO expansion prompts and they are reached from different screens.
# claude_expand_services is stage1b_refine's, on the SEO quote's refine path.
# claude_industry_services is /api/expand_services, which is what the adtini
# Keyword Builder's Expand button calls — and that is the screen Brendan's ENT
# list came off. Putting the rule in one of them fixed the path nobody was
# looking at. Both are asserted here so the next person cannot repeat it.
rule7 = ""
m7 = re.search(r"^7\. THE PRACTITIONER.*?(?=\nReturn ONLY JSON)", SOURCE, re.S | re.M)
if m7:
    rule7 = m7.group(0)

check("the gap-finder has a practitioner rule too", bool(rule7), True)
check("it is reachable from /api/expand_services",
      "claude_industry_services(" in SOURCE
      and "def api_expand_services" in SOURCE, True)
for term in ("ENT", "audiologist", "dentist", "plumber"):
    check("gap-finder rule names %r" % term, term in rule7, True)

# Two of that prompt's own rules would otherwise suppress these, so the rule has
# to say so explicitly: rule 1 forbids synonyms (an abbreviation reads as one)
# and rule 3 allows only services the business sells (a job title does not read
# as a service). Naming them is the whole reason the rule works there.
check("it overrides the synonym rule", "NOT caught by rule 1" in rule7, True)
check("it overrides the services-only rule",
      "NOT excluded by rule 3" in rule7, True)
check("it defers to the client's-own-noun rule", "Rule 5 still applies" in rule7, True)
check("a retailer is exempted here too",
      "retailer" in rule7 and "Do not invent one" in rule7, True)

# Both prompts are built by real calls with no key, so a rule that does not
# survive its f-string fails here rather than in front of a partner.
saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
check("gap-finder returns nothing without a key",
      app.claude_industry_services("ENT Consultants", "entoxford.com", "Medical",
                                   "An ENT practice", [], ["hearing aids"], "oxford, ms"),
      [])
if saved_key is not None:
    os.environ["ANTHROPIC_API_KEY"] = saved_key

# The floor is the other thing that can hide a good term in a thin market: ENT
# in Oxford MS may genuinely measure under it. Editable per quote, which is the
# lever if the practitioner terms come back measured but withheld.
check("the gap floor is per-quote editable",
      '("expand_min_volume", int)' in SOURCE, True)

# ------------------------------- VOLUME LIVES IN THE GENERAL TERMS (2026-09-16)
# Rule 7 asked for "at least TWO practitioner terms" and the model read the floor
# as a target: on the live ENT quote it returned ONE (otolaryngologist -- the
# clinically correct word almost nobody types) and spent the other twenty slots
# on procedures, because six of the seven rules asked for service lines. The
# quota was the wrong instrument. The ordering principle is the right one, and it
# is simpler: the biggest terms are the most general ones.
ask = ""
ma = re.search(r"Name up to \{n\} ADDITIONAL.*?(?=\nRules:)", SOURCE, re.S)
if ma:
    ask = ma.group(0)

# Prompt text is hard-wrapped, so a phrase can straddle a newline. Collapse
# whitespace before looking for one, or the test pins the line breaks too.
flat = lambda t: re.sub(r"\s+", " ", t)
ASK = flat(ask)
SRCF = flat(SOURCE)

check("the ask is framed on search volume", bool(ask) and "SEARCH VOLUME" in ASK, True)
check("it is no longer a request for service lines a business sells",
      "ADDITIONAL service lines a business of this type sells" not in SOURCE, True)
check("general beats specific is stated", "GENERAL TERMS" in ASK, True)
check("with the ENT case", "nasal polyp removal" in ASK, True)
for pair in ("dentist", "plumber", "personal injury lawyer"):
    check("and generalises past medicine: %r" % pair, pair in ASK, True)
check("a specific still earns a slot when people search it by name",
      "wisdom teeth removal" in ASK, True)
check("and not merely for being on a services page",
      "services page" in ASK, True)
check("the failure mode is named", "smallest terms" in ASK, True)

# Rule 4 is the ordering rule. It used to sort by how often a job is PERFORMED,
# which is not the same question and is why narrow procedures led the answer.
check("rule 4 orders by expected search volume",
      "4. Order by EXPECTED SEARCH VOLUME" in SOURCE, True)
check("and says general before specific",
      "General before specific, every time." in SRCF, True)
check("the old purchase-frequency ordering is gone",
      "Order by how commonly the service is bought" not in SOURCE, True)

# Both practitioner rules must say LEAD, not fill a quota -- in the gap-finder
# and in stage1b_refine's expansion.
check("the gap-finder rule says they lead",
      "Under rule 4 these LEAD the answer" in SRCF, True)
check("the refine-path rule says they lead too",
      "so they LEAD: at least one belongs in" in SRCF, True)
check("neither reads as a quota",
      SRCF.count("not a quota") >= 2, True)
check("and the observed failure is written down",
      SRCF.count("followed by twenty procedures") == 2, True)
check("the old floor-as-target wording is gone",
      "At least TWO practitioner terms" not in SOURCE, True)

# ------------------------------------ THE PARSER ATE THE ANSWER (2026-09-16)
# Rule 7 asks for ENT, audiologist, dentist, plumber. The gap-finder's own parse
# then required 2-5 words, so every single-word term was discarded before
# volume, before the floor, before the fold. On the real ENT quote the ONLY
# practitioner term that survived was "ear nose and throat doctor" — because it
# happened to be five words. The rule worked; the parser deleted its output.
GATE = lambda t: bool(app.clean_kw(app.strip_placeholders(t.lower())).strip()) \
    and 0 < len(app.clean_kw(app.strip_placeholders(t.lower())).strip().split()) <= 5
for one in ("ENT", "audiologist", "dentist", "plumber", "electrician"):
    check("a one-word practitioner noun survives the parse: %r" % one, GATE(one), True)
check("multi-word still survives", GATE("ear nose and throat doctor"), True)
check("six words is still too many", GATE("a b c d e f"), False)

# ------------------------------ AN INITIALISM IS A HEAD TERM, NOT A FRAGMENT
# fold_proposals folds a one-token term into a longer seed containing it, which
# is right for "junk" inside "junk removal" and wrong for "ENT" inside
# "pediatric ENT care" — structurally identical, semantically opposite. Code
# cannot read the difference from tokens, so the parse records the model's own
# capitalisation before .lower() destroys it and the caller passes it through.
ENT_SEEDS = ["hearing aids", "pediatric ent care", "pediatric ent surgery",
             "tonsillectomy", "chronic sinusitis treatment"]
MK = ["oxford, ms", "grenada, ms"]

kept_no, folded_no = app.fold_proposals(
    ["ent", "audiologist"], seeds=ENT_SEEDS, markets=MK, state="MS")
check("without the exemption ENT is folded away", "ent" in folded_no, True)

kept_yes, _ = app.fold_proposals(
    ["ent", "audiologist", "ear nose and throat doctor", "hearing doctor"],
    seeds=ENT_SEEDS, markets=MK, state="MS", keep_bare=["ent"])
check("with it ENT survives", "ent" in kept_yes, True)
check("and the spelled-out form survives beside it",
      "ear nose and throat doctor" in kept_yes, True)
check("audiologist is unaffected either way", "audiologist" in kept_yes, True)

# BOTH REGRESSIONS. The guard exists because of these two; the exemption must
# not reach either. Nothing is passed as keep_bare, which is the normal case.
_k, _f = app.fold_proposals(["junk", "junk removal", "haul away junk"],
                            seeds=["junk removal"], markets=[], state="")
check("junk still folds against its own seed", "junk" in _f, True)

_k2, _f2 = app.fold_proposals(
    ["ski jackets", "boys ski jackets", "girls ski jackets", "ski pants",
     "boys ski pants"], seeds=[], markets=[], state="")
check("Ski Barn near-duplicates still collapse", _k2, ["ski jackets", "ski pants"])
check("and their qualified forms are what went",
      _f2, ["boys ski jackets", "girls ski jackets", "boys ski pants"])

# The flag itself is set from the model's raw casing, not guessed downstream.
check("the parse records an initialism",
      'bool(re.fullmatch(r"[A-Z]{2,5}", rawt))' in SOURCE, True)
check("and the route passes it to the fold",
      'keep_bare=[c["term"] for c in cands' in SOURCE, True)

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
