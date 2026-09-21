"""SCORE A PRICING CHANGE AGAINST EVERY QUOTE BRENDAN ACTUALLY SENT.

    python3.12 tools/pricebench.py                 # current CFG
    python3.12 tools/pricebench.py --patch '{"volume_add_cap": 1200}'
    python3.12 tools/pricebench.py --patch @tools/proposals/seascape.json

app.py's config block is a calibration ledger written as comments: every
constant carries the client it was fitted on and the quote it had to reproduce.
The ledger cites a pricebench.py that was never in the repository, so any change
to a constant meant re-reading two hundred lines of comment and taking the
author's word for the fit. This is that bench, built back out of the ledger.

WHAT IS IN HERE AND WHAT IS NOT. Only datapoints whose INPUTS the ledger
records, alongside the price Brendan actually sent. Several more clients are
named in the comments with no inputs attached -- they are listed at the bottom
as unreconstructible rather than guessed at, because a bench with invented
inputs would score a change against this file instead of against his book.

READ THE SPREAD BEFORE READING THE ERRORS. Across BE's twelve proposals the
whole observed range of base prices is about $625. A change that improves one
client by $200 and moves four others by $150 has not improved anything.
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location("app", os.path.join(SRCDIR, "app.py"))
app = importlib.util.module_from_spec(spec)
sys.modules["app"] = app
spec.loader.exec_module(app)


# --------------------------------------------------------------------------
# THE LEDGER. `actual` is what Brendan sent. A tier of None is a price the
# comments do not record -- scored on the tiers that exist, never on a guess.
# `why` cites the line of app.py the inputs come from, so a wrong input here is
# findable rather than arguable.
# --------------------------------------------------------------------------
BENCH = [
    dict(name="Skidmore Studio", band="nationwide", adder=50, vol=24000, nr=90,
         actual=(3950, 5450, 6950),
         why="geo_anchor note: 'Skidmore (adder 50, vol 24k, 90% not ranking)'"),
    dict(name="MPG Gummies", band="nationwide", adder=0, vol=25000, nr=100,
         actual=(3950, 5450, 6950),
         why="geo_anchor note: 'MPG (adder 0, vol 25k+, 100% not ranking)'"),
    dict(name="Rockingham Insurance", band="contiguous_region", cpc=121.0,
         vol=0, nr=39, industry="Insurance - Carrier",
         actual=(5450, 6750, 7950),
         why="insurance card note: 'lands 5,450/6,750/8,050 vs his 5,450/6,750/7,950'"),
    dict(name="Media Venue", band="contiguous_region", adder=0, vol=0, nr=0,
         actual=(2925, 4040, 5150),
         why="anchor note: 'Brendan $2,925/$4,040/$5,150'; uplift note says the "
             "+18% came from footholds miscounted as not ranking, fixed by "
             "zero_ranking_top_n=100, so the honest input is ~0% not ranking"),
    # THE FLOOR-BOUND SIX. tier_step_flat was calibrated on exactly these: base
    # on the $2,950 floor, and the step is what the fit was scored on.
    dict(name="Nob Hill Dental", band="single_city", adder=0, vol=0, nr=80,
         actual=(2950, None, None),
         why="zero_ranking_tiers note: 'Nob Hill Dental at 80% not ranking ... "
             "quoted $2,950'"),
    dict(name="Visit Central PA", band="single_city", adder=0, vol=0, nr=5,
         actual=(2950, 3950, 4950),
         why="same note ('Visit Central PA at 5% were both quoted $2,950') plus "
             "tier_step_flat note: steps $1,000"),
    dict(name="Junk Bee Gone", band="single_city", adder=0, vol=0, nr=5,
         actual=(2950, 3850, 4750),
         why="zero_ranking_tiers note ('5% not ranking ... also $2,950') plus "
             "tier_step_flat note: 'steps ... $900 in one (Junk Bee Gone)'"),
    dict(name="Keller Builds", band="single_city", adder=0, vol=0, nr=25,
         actual=(2950, 3950, 4950),
         why="tier_step_flat note: floor base, steps $1,000"),
    # THE ONE AGGREGATOR-HELD PAGE ONE IN THE BOOK, and the quote
    # pageone_aggregator_add is fitted on. Same twenty terms, same one city, same
    # 80% not ranking as Nob Hill Dental directly above -- and $600 apart in what
    # Brendan sent. The only input that differs is who holds page one: Zillow,
    # Trulia, Redfin and Apartments.com here, five other Salem dentists there.
    # Reconstructible as of 2026-09-19 because the lever gives its page one a
    # place in the formula; before that it was cited in the back-measure only.
    dict(name="Amare Homes", band="single_city", adder=0, vol=0, nr=80,
         agg=0.86, agg_terms=20, actual=(3550, None, None),
         why="tier_step_flat note: 'Nob Hill and Amare Homes are both 20 terms, "
             "one city, 80% not ranking, and $600 apart'. The 0.86 share is "
             "RECONSTRUCTED from pageone_strength's note that its page one is "
             "Zillow, Trulia and Redfin -- the ledger records who, not how many "
             "slots. The lever is a threshold, so any share over the 0.50 cut "
             "prices identically and the exact figure is not load-bearing"),
    dict(name="Red Shoes", band="single_city", adder=0, vol=0, nr=23,
         actual=(2950, 3950, 4950),
         why="tier_step_flat note: floor base, steps $1,000"),
    # BRENDAN'S NEWEST, AND THE REASON THIS FILE EXISTS. A national commodity
    # distributor: nothing ranking at all, a $6.12 median bid across 13 bidders,
    # 51,690/mo. His three reasons map to the three levers that move a non-floor
    # quote, and all three are asleep or saturated on it. (2026-09-17)
    dict(name="Seascape Inc", band="contiguous_region", cpc=6.12, vol=51690,
         nr=100, actual=(6950, 8250, 9950),
         why="Brendan 2026-09-17: 'I would have quoted this as $6950 for entry, "
             "$8,250 for intermediate and $9,950 for advanced'"),
    # AND THE ONE THAT PROVES VOLUME IS NOT DEMAND. The largest raw volume in
    # the whole set, priced UNDER the statewide anchor because he already ranks.
    dict(name="Susquehanna River Valley VB", band="statewide", adder=0,
         vol=135000, nr=40, actual=(2950, None, None),
         why="vol_free_below note: '135k/mo ... Brendan priced it BELOW the "
             "statewide anchor ... ranks for 60% of its head terms'. The base "
             "is read off the statewide anchor less ~7%"),
]

# Named in the ledger with no inputs recorded. Listed so the gap is visible.
UNRECONSTRUCTIBLE = [
    ("Waytek", "CPC $60 and '+$500 total' are recorded; band, volume and "
               "ranking coverage are not"),
    ("PA Dental Excellence", "'$3,350 base, single-city Philadelphia, his "
                             "HIGHEST base' -- no adder, volume or coverage"),
    ("Serene Health", "reclassified out of the auto-fit ledger: priced off the "
                      "big-org card, not computed from keywords"),
    ("Ooten Law", "fitted the legal +$700 anchor add; its own inputs are not "
                  "written down"),
    ("NASSCO", "cited for scope and page-one strength, never for a price fit"),
    ("NPAIHB", "cited only in the page-one back-measure. $3,550 like Amare, "
               "but its page one is ihs.gov and Wikipedia -- not an aggregator "
               "lock-up, so the new lever does not explain it either"),
]

TIERS = ("base", "intermediate", "advanced")


def quote(d):
    """Reprice one bench client under whatever CFG is loaded."""
    adder = d.get("adder")
    if adder is None and d.get("cpc"):
        # The ledger records a CPC for some clients and a finished adder for
        # others. Run the same piecewise the quote would.
        cpc, C = float(d["cpc"]), app.CFG
        free = float(C.get("cpc_adder_free_below", 5.0))
        knee = float(C.get("cpc_adder_knee", 62.0))
        raw = 0.0 if cpc <= free else (
            min(cpc, knee) * float(C.get("cpc_adder_mult", 2.6))
            + max(0.0, cpc - knee) * float(C.get("cpc_adder_mult_high", 12.3)))
        adder = int(round(min(raw, float(C.get("cpc_adder_cap", 1300))) / 50.0) * 50)
    p = app.stage4_price(band=d["band"], adder=int(adder or 0), zero_ranking=False,
                         addon_markets=0, markup_pct=35,
                         pct_not_ranking=d.get("nr"),
                         total_volume=d.get("vol") or 0,
                         # Who holds page one. Absent on every client the
                         # back-measure has not read a SERP for, which prices as
                         # not measured rather than as no aggregators.
                         pageone_agg_share=d.get("agg"),
                         pageone_agg_terms=d.get("agg_terms"),
                         industry=d.get("industry", ""))
    return p["handoff"]["package"], adder


def run(label):
    rows, errs, worst = [], [], (0, "")
    for d in BENCH:
        got, adder = quote(d)
        cells, e = [], []
        for i, t in enumerate(TIERS):
            want = d["actual"][i]
            if want is None:
                cells.append("%7s" % "-")
                continue
            diff = got[t] - want
            e.append(abs(diff))
            errs.append(abs(diff))
            if abs(diff) > worst[0]:
                worst = (abs(diff), "%s %s" % (d["name"], t))
            cells.append("%7s" % ("%+d" % diff if diff else "0"))
        rows.append((d["name"], adder, got, d["actual"], cells, sum(e)))

    print("=" * 78)
    print(label)
    print("=" * 78)
    print("%-28s %6s  %-23s %-23s" % ("client", "adder", "quoted (B)", "formula"))
    print("-" * 78)
    for name, adder, got, actual, cells, _ in rows:
        a = "/".join(str(x) if x is not None else "-" for x in actual)
        f = "/".join(str(got[t]) for t in TIERS)
        print("%-28s %6s  %-23s %-23s %s" % (name, "$%d" % adder, a, f, " ".join(cells)))
    print("-" * 78)
    print("tiers scored        %d" % len(errs))
    print("total error         $%s" % format(sum(errs), ","))
    print("median tier error   $%s" % format(int(statistics.median(errs)) if errs else 0, ","))
    print("exact tiers         %d of %d" % (sum(1 for e in errs if e == 0), len(errs)))
    print("worst               $%d  (%s)" % worst)
    # THE NUMBER THAT DECIDES WHETHER AN IMPROVEMENT IS REAL.
    bases = [d["actual"][0] for d in BENCH if d["actual"][0]]
    print("his own base spread $%s   (%d clients, $%d-$%d)"
          % (format(max(bases) - min(bases), ","), len(bases), min(bases), max(bases)))
    return sum(errs), len(errs) - sum(1 for e in errs if e == 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", default="",
                    help='CFG overrides as JSON, or @path to a JSON file')
    ap.add_argument("--quiet-gaps", action="store_true")
    a = ap.parse_args()

    before, _ = run("CURRENT CFG")
    if a.patch:
        raw = a.patch
        if raw.startswith("@"):
            raw = open(os.path.join(SRCDIR, raw[1:]), encoding="utf-8").read()
        # A leading underscore is a note to the reader, not a constant.
        patch = {k: v for k, v in json.loads(raw).items() if not k.startswith("_")}
        print()
        print("patch: %s" % json.dumps(patch))
        app.CFG.update(patch)
        after, _ = run("PATCHED CFG")
        print()
        print("total error  $%s -> $%s   (%+d)"
              % (format(before, ","), format(after, ","), after - before))
    if not a.quiet_gaps:
        print()
        print("NOT IN THE BENCH -- named in the ledger, inputs not recorded:")
        for n, why in UNRECONSTRUCTIBLE:
            print("  %-24s %s" % (n, why))


if __name__ == "__main__":
    main()
