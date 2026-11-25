"""A NEAR-ME SEED IS THE BASE SERVICE, NOT A SERVICE OF ITS OWN.

Runza (Lincoln, NE): Expand proposed "fast food near me" and "drive thru near
me" as seeds. Kept whole they became services, crossed with the city ("fast
food near me lincoln ne") and summed into total_volume -- 14,800 + 720 of a
22,960 total, where no other near-me row counts. That bought the $450 volume
add; Brendan put the quote ~$750 too high. (2026-11-25, Kiri)
"""
import importlib.util
import os
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

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f"{name}: got {got!r}, want {want!r}")


cs = app.clean_seeds
check("near me cut to base", cs(["fast food near me"]), ["fast food"])
check("base already a seed folds", cs(["fast food", "fast food near me"]), ["fast food"])
check("other near-me wordings", cs(["urgent care nearby", "dentist near by",
                                    "pizza close to me", "tacos around me"]),
      ["urgent care", "dentist", "pizza", "tacos"])
check("bare near me dropped", cs(["near me", "burgers"]), ["burgers"])
check("hyphen and space fold, first kept",
      cs(["drive-thru", "drive thru near me", "drive thru"]), ["drive-thru"])
check("ordinary seeds untouched", cs(["burgers", "onion rings", "Shakes"]),
      ["burgers", "onion rings", "Shakes"])
check("word inside another word untouched", cs(["nearmeadow farms"]),
      ["nearmeadow farms"])

# Runza priced on its volume without the two near-me seeds and the double
# drive-thru: 22,960 -> 7,300, under the 10k line, $700 off the base.
before = app.stage4_price(band="single_city", adder=0, zero_ranking=False,
                          pct_not_ranking=100, total_volume=22960, site_debt=2)
after = app.stage4_price(band="single_city", adder=0, zero_ranking=False,
                         pct_not_ranking=100, total_volume=7300, site_debt=2)
check("runza before", before["client_tiers"]["base"], 4100)
check("runza after", after["client_tiers"]["base"], 3400)

if FAIL:
    print("FAIL nearmeseed_test")
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("ok nearmeseed_test")
