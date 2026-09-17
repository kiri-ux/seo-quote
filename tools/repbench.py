"""SCORE A REP-PRICING CHANGE AGAINST EVERY ORM FIGURE ANYONE ACTUALLY SENT.

    python3.12 tools/repbench.py
    python3.12 tools/repbench.py --patch '{"SEARCH_BUNDLE.supp_base": 1700}'
    python3.12 tools/repbench.py --patch @tools/proposals/<name>.json

rep_pricing.py is the same kind of document app.py is: a calibration ledger
written as comments, where every constant names the client it was fitted on and
the invoice it had to reproduce. tools/pricebench.py gave the SEO side of that
ledger a bench. This is the ORM side.

WHAT IS DIFFERENT HERE, AND WHY THE TOTAL AT THE BOTTOM MEANS LESS.

The SEO tool is ONE formula scored twelve times, so moving a constant moves
every client and a total error is the honest headline. ORM is a dozen separate
price channels that barely touch: review removals, page removals, the search
bundle, the shield, GEO. A constant usually drives exactly one row. So read the
PER-CHANNEL block, not the total -- a $5,000 miss on a $12,500 page removal and
a $5,000 miss on a $900 review are not the same event, and summing them says
they are.

SOME ACTUALS ARE BANDS, NOT NUMBERS. Brendan's July 2026 removal list quotes
"$4,500-$5,500 bulk, $7,500-$10,000 rack" -- a band is the datapoint, and a row
inside its band scores zero. Pretending a band is its midpoint would invent
precision he never gave.

AND SOME ACTUALS WERE DELIBERATELY LEFT BEHIND. The July 2026 recalibration
moved premium pages from Tru North's $7,500 to the Goldstone top-tier $12,500
on purpose. Those rows are listed under SUPERSEDED and are NOT scored: scoring
them would make every honest recalibration look like a regression.
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location(
    "rep_pricing", os.path.join(SRCDIR, "rep_pricing.py"))
rep = importlib.util.module_from_spec(spec)
sys.modules["rep_pricing"] = rep
spec.loader.exec_module(rep)


# --------------------------------------------------------------------------
# helpers -- each returns the ONE client-facing dollar figure the ledger
# records an actual for, so a bench row is a number against a number.
# --------------------------------------------------------------------------
def rev_unit(n, **kw):
    return rep.price_reviews(n, **kw)["unit"]


def art_unit(n=0, premium=0, **kw):
    lines = rep.price_articles(n, premium, **kw)
    return lines[0]["unit"]


def bundle(vol):
    return rep.price_search_bundle(vol)["total"]


def suppression(vol, tier="standard"):
    lines, _ = rep.price_search_protection(vol, True, False,
                                           suppression_tier=tier)
    return lines[0]["total"]


def guaranteed(n, per=None):
    lines, _ = rep.price_search_protection(0, False, True, as_mode="guaranteed",
                                           n_negatives=n,
                                           guaranteed_per_phrase=per)
    return lines[0]["total"]


def alt_engine(engine, which):
    lines, _ = rep.price_search_protection(
        0, False, which == "autosuggest", engine=engine,
        use_related=which == "related")
    return lines[0]["total"]


# --------------------------------------------------------------------------
# THE LEDGER. `want` is an int (an invoice figure) or a (lo, hi) band (a range
# Brendan quoted in words). `why` cites the comment in rep_pricing.py the row
# comes from, so a wrong input here is findable rather than arguable.
# --------------------------------------------------------------------------
BENCH = [
    # ---------------------------------------------------- review removals
    # The Vici chart IS the product -- six published gross rates that the
    # hard-cost column has to rebuild at the default 35%. If a margin or
    # rounding change moves any of these, the tool has stopped quoting the
    # rate card the client is looking at.
    dict(ch="reviews", name="Vici card 1-25", want=900, f=lambda: rev_unit(10),
         why="review_removal note: 'gross $900 / $850 / $800 / $750 / $700 / $650'"),
    dict(ch="reviews", name="Vici card 26-50", want=850, f=lambda: rev_unit(30),
         why="same chart"),
    dict(ch="reviews", name="Vici card 51-100", want=800, f=lambda: rev_unit(75),
         why="same chart"),
    dict(ch="reviews", name="Vici card 101-250", want=750, f=lambda: rev_unit(200),
         why="same chart"),
    dict(ch="reviews", name="Vici card 251-350", want=700, f=lambda: rev_unit(300),
         why="same chart"),
    dict(ch="reviews", name="Vici card 351-500", want=650, f=lambda: rev_unit(450),
         why="same chart"),
    # NOT A RATE CARD ROW -- THE ROUNDING FIX. $612.50 hard at 35% is $942.31.
    # Rounding to the NEAREST $5 printed $940 and realised 34.8% against a
    # stated 35%: the only figure in either tool that could land under its own
    # margin. Pinned so a later rounding change cannot quietly undo it.
    dict(ch="reviews", name="off-card override $612.50 hard", want=945,
         f=lambda: rev_unit(1, hard_override=612.50),
         why="r5 note (2026-08-28, Kiri): 'the quote showed $940, a realised "
             "margin of 34.8% against a stated 35%'"),

    # ------------------------------------------------------- page removals
    # Brendan's own words for his channel, as bands. A single page is rack; a
    # fifteen-page batch is the observed bulk run; 25+ is the Visions floor.
    dict(ch="pages", name="rack, 1 page (Goldstone repost)", want=7500,
         f=lambda: art_unit(1),
         why="article_removal note: 'rack rate $7,500-$10,000 per page', "
             "observed repost @ $7,500"),
    dict(ch="pages", name="bulk batch, ~15 pages", want=(4500, 5500),
         f=lambda: art_unit(15),
         why="article_removal note: 'observed bulk batch ~15 @ $4.5-5.5K'"),
    dict(ch="pages", name="Visions bulk floor, 25+ pages", want=4950,
         f=lambda: art_unit(25),
         why="article_removal note: 'Visions bulk floor'; whole-order brackets "
             "were his Visions Electronics actuals (2024)"),
    dict(ch="pages", name="top-tier news, premium", want=12500,
         f=lambda: art_unit(0, premium=1),
         why="premium_per: 'top-tier news actual (insurancenewsnet, Gannett "
             "in-depth -- Goldstone list July 2026)'"),

    # ---------------------------------------------------- search protection
    # THE ONE KNOWN MISS, AND THE REASON THIS FILE IS WORTH HAVING. The
    # hard-cost rewrite rounded each component base UP to $50 and the drift
    # landed on the client. The comment says +$150; the bench says it out loud
    # on every run instead of once in a block comment nobody re-reads.
    dict(ch="search", name="Sage Dental bundle @ 51,330/mo", want=7400,
         f=lambda: bundle(51330),
         why="SEARCH_BUNDLE note: 'the Sage actual (51,330/mo) now quotes "
             "$7,550 client at 35% vs Brendan's $7,400'"),
    dict(ch="search", name="Sage suppression alone @ 51,330/mo", want=3450,
         f=lambda: suppression(51330),
         why="suppression note: '$2,650 floor (his base campaign) + $15/1K "
             "still lands Sage's $3,450 exactly at 51,330/mo'"),
    dict(ch="search", name="Tru North base campaign (floor)", want=2650,
         f=lambda: suppression(0, "standard"),
         why="suppression note: 'Recalibrated July 2026 to the LOWER Tru North "
             "tier: $2,650 floor (his base campaign)'"),
    dict(ch="search", name="Tru North advanced tier", want=3650,
         f=lambda: suppression(0, "advanced"),
         why="tiers note: 'Steps are his exact +/-$1,000'"),
    dict(ch="search", name="Goldstone 2020 guaranteed, 2 phrases", want=8250,
         f=lambda: guaranteed(2),
         why="guaranteed_per_phrase: 'Goldstone 2020, 2 phrases' @ $4,125"),
    dict(ch="search", name="Goldstone 2021 guaranteed, 1 complex", want=9250,
         f=lambda: guaranteed(1, 9250),
         why="guaranteed note: '$9,250 (Goldstone 2021, 1 complex phrase) -- "
             "complexity-driven ... Editable per quote'"),
    dict(ch="search", name="Goldstone 2025 Bing auto-suggest", want=1500,
         f=lambda: alt_engine("bing", "autosuggest"),
         why="alt_engine_flat: 'Bing/DuckDuckGo are FLAT monthlies (Goldstone "
             "2025 actuals)'"),
    dict(ch="search", name="Goldstone 2025 DuckDuckGo related", want=1250,
         f=lambda: alt_engine("ddg", "related"),
         why="alt_engine_flat, same note"),

    # ---------------------------------------------------------- recurring
    dict(ch="monthly", name="Brand Shield, 1 location", want=3500,
         f=lambda: rep.price_shield(1)["total"],
         why="shield note: 'At 35%: $3,500 base + $700/extra location'"),
    dict(ch="monthly", name="Brand Shield, 3 locations", want=4900,
         f=lambda: rep.price_shield(3)["total"],
         why="same note: $3,500 + 2 x $700"),
    dict(ch="monthly", name="Sage GEO setup phase", want=4950,
         f=lambda: rep.price_geo("setup")["total"],
         why="GEO: 'Sage Digital Partner proposal actuals (Sept 2025): GEO "
             "$4,950/mo setup phase'"),
    dict(ch="monthly", name="Sage GEO scale phase", want=9950,
         f=lambda: rep.price_geo("scale")["total"],
         why="GEO, same note: '$9,950/mo scale phase'"),

    # ------------------------------------------- reference-only price cards
    # Priced by rep_pricing but not wired into build_rep_quote. Scored anyway:
    # they are still invoice figures, and a card nobody scores is a card that
    # drifts.
    dict(ch="reference", name="Kim Anami video (low actual)", want=4950,
         f=lambda: rep.price_video(1, 4950)["total"],
         why="price_video: 'Kim Anami actuals (2021): $4,950 + $6,250'"),
    dict(ch="reference", name="Kim Anami video (high actual)", want=6250,
         f=lambda: rep.price_video(1, 6250)["total"],
         why="same note"),
    dict(ch="reference", name="Kim Anami video (shipped default)",
         want=(4950, 6250), f=lambda: rep.price_video(1)["total"],
         why="price_video: 'midpoint $5,600 default' -- scored against the "
             "band the two actuals describe, not a midpoint invented here"),
    dict(ch="reference", name="Hobart premium placement", want=8000,
         f=lambda: rep.price_pr(premium=1)[0]["total"],
         why="PR: 'Hobart Wealth actuals (2021): PR pay-per-placement'"),
    dict(ch="reference", name="Hobart secondary placement", want=4500,
         f=lambda: rep.price_pr(secondary=1)[0]["total"], why="same note"),
    dict(ch="reference", name="Hobart press release", want=1500,
         f=lambda: rep.price_pr(releases=1)[0]["total"], why="same note"),
]

# Actuals the shipping config deliberately no longer reproduces. Shown, never
# scored -- otherwise a deliberate recalibration reads as a regression.
SUPERSEDED = [
    dict(name="Tru North premium page", was=7500,
         f=lambda: art_unit(0, premium=1),
         why="premium was Tru North's $7,500; July 2026 moved the premium "
             "channel to the Goldstone top-tier news actual"),
    dict(name="Visions small-order page", was=5950, f=lambda: art_unit(1),
         why="the Visions whole-order bracket started at $5,950; July 2026 "
             "found that bracket WAS the bulk rate (25+ order), so small "
             "orders now start at rack"),
    dict(name="Partner A review removal", was=450, f=lambda: rev_unit(10),
         why="Partner A ($450 flat) / Partner B ($650->$550) were client "
             "pricing in Brendan's Sage proposal; the Vici card replaced them "
             "and A/B is internal fulfillment routing only"),
]

# No datapoint exists. Listed so the gap is visible rather than implied by a
# number sitting in the config looking like every other number.
UNPRICED = [
    ("BBB remediation", "BBB_BRACKETS $650/$550/$450 are GUESSES -- Brendan's "
                        "note says 'tiers based on # of complaints' and "
                        "records no figure"),
    ("3-phrase inclusion", "SEARCH_BUNDLE/autosuggest included_negatives=3 is "
                           "an internal assumption; the Sage actual covered 2"),
    ("per_extra_negative", "$250/phrase beyond the inclusion is labelled GUESS "
                           "in the config"),
    ("article class bands", "classes[*].low/high/est are display keys set to "
                            "the channel band -- no class-specific actual "
                            "exists; every standard class prices off the "
                            "whole-order brackets"),
    ("internal cost %", "INTERNAL_COST_PCT 20% is a model of Vici delivery "
                        "cost, not an invoice; only reviews carry a confirmed "
                        "internal figure ($400/$300)"),
]

CHANNELS = [("reviews", "REVIEW REMOVALS"), ("pages", "PAGE REMOVALS"),
            ("search", "SEARCH PROTECTION"), ("monthly", "RECURRING BUNDLES"),
            ("reference", "REFERENCE CARDS (not wired into build_rep_quote)")]


def score(want, got):
    """Dollar error, signed the same way for a point and for a band: negative
    is under what he charged, positive is over. A band scores zero anywhere
    inside it, and its distance is measured from the edge that was missed."""
    if isinstance(want, tuple):
        lo, hi = want
        return 0 if lo <= got <= hi else (got - lo if got < lo else got - hi)
    return got - want


def fmt(want):
    return ("$%s-$%s" % (format(want[0], ","), format(want[1], ","))
            if isinstance(want, tuple) else "$%s" % format(want, ","))


def run(label):
    print("=" * 76)
    print(label)
    print("=" * 76)
    grand, misses = 0, []
    for ch, title in CHANNELS:
        rows = [d for d in BENCH if d["ch"] == ch]
        if not rows:
            continue
        print()
        print(title)
        print("%-38s %13s %11s %9s" % ("datapoint", "actual", "formula", "diff"))
        print("-" * 76)
        tot = 0
        for d in rows:
            got = d["f"]()
            e = score(d["want"], got)
            tot += abs(e)
            grand += abs(e)
            if e:
                misses.append((d["name"], e))
            print("%-38s %13s %11s %9s"
                  % (d["name"][:38], fmt(d["want"]), "$%s" % format(got, ","),
                     "%+d" % e if e else "ok"))
        vals = [v for d in rows for v in
                (d["want"] if isinstance(d["want"], tuple) else (d["want"],))]
        print("%-38s %13s %11s %9s"
              % ("channel spread $%s (%s-%s)"
                 % (format(max(vals) - min(vals), ","),
                    format(min(vals), ","), format(max(vals), ",")),
                 "", "", "$%s" % format(tot, ",")))
    print()
    print("-" * 76)
    print("rows scored          %d" % len(BENCH))
    print("exact                %d" % (len(BENCH) - len(misses)))
    print("total error          $%s   (READ THE PER-CHANNEL BLOCKS FIRST --"
          % format(grand, ","))
    print("                     these are separate price channels, not one ladder)")
    for n, e in misses:
        print("miss                 %-40s %+d" % (n, e))
    return grand


def resolve(path):
    """'REP_CFG.search_protection.suppression.base' -> (container, key).
    Dotted from a module-level name, so a patch key is the same string you
    would grep for in rep_pricing.py."""
    parts = path.split(".")
    obj = getattr(rep, parts[0])
    for p in parts[1:-1]:
        obj = obj[p]
    return obj, parts[-1]


def apply_patch(patch):
    for k, v in patch.items():
        if k.startswith("_"):
            continue            # a note to the reader, not a constant
        if "." not in k:
            setattr(rep, k, v)  # module-level scalar, e.g. ART_CAL_MARGIN
            continue
        obj, key = resolve(k)
        obj[key] = v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", default="",
                    help="dotted-path overrides as JSON, or @path to a JSON "
                         "file. e.g. '{\"SEARCH_BUNDLE.supp_base\": 1700}'")
    ap.add_argument("--quiet-gaps", action="store_true")
    a = ap.parse_args()

    before = run("SHIPPING CONFIG")
    if a.patch:
        raw = a.patch
        if raw.startswith("@"):
            raw = open(os.path.join(SRCDIR, raw[1:]), encoding="utf-8").read()
        patch = {k: v for k, v in json.loads(raw).items()
                 if not k.startswith("_")}
        print()
        print("patch: %s" % json.dumps(patch))
        apply_patch(patch)
        print()
        after = run("PATCHED CONFIG")
        print()
        print("total error  $%s -> $%s   (%+d)"
              % (format(before, ","), format(after, ","), after - before))
    if not a.quiet_gaps:
        print()
        print("SUPERSEDED -- real actuals the shipping config no longer "
              "reproduces, on purpose:")
        for d in SUPERSEDED:
            print("  %-26s was $%-7s now $%-7s  %s"
                  % (d["name"], format(d["was"], ","),
                     format(d["f"](), ","), d["why"]))
        print()
        print("UNPRICED -- constants with no datapoint behind them:")
        for n, why in UNPRICED:
            print("  %-22s %s" % (n, why))


if __name__ == "__main__":
    main()
