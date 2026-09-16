"""The proposal table is the keyword SET being proposed.

Left to itself the builder drops any term whose rank was not measured, because
"Not Found" is a positive claim about a term nobody checked. A 21-term quote
went out with three rows. The adtini tab asks for all of them.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

KW = {"ultra": [{"kw": "electrical services whidbey island wa", "vol": 480},
                {"kw": "electrical services anacortes wa", "vol": 10}],
      "competitive": [{"kw": "generator installation anacortes wa", "vol": 10}],
      "long_tail": [{"kw": "kohler generator installation anacortes wa", "vol": 0}]}
TABLE = [
    {"kw": "electrical services whidbey island wa", "pos": "—", "error": True},
    {"kw": "electrical services anacortes wa", "pos": "Not Found", "error": False},
    {"kw": "generator installation anacortes wa", "pos": 8, "error": False},
    # kohler... has no row at all: never checked.
]

# Default: unchecked terms stay out, as before.
d = {"kw": KW, "table": TABLE}
rows = app._proposal_rows(d)
check("default.skipsUnchecked", len(rows), 2)
check("default.noErroredTerm",
      any("whidbey" in r["kw"] for r in rows), False)

# all_keywords: every term, and an unchecked one reads Not Found.
d2 = {"kw": KW, "table": TABLE, "all_keywords": True}
rows2 = app._proposal_rows(d2)
check("all.everyTerm", len(rows2), 4)
by = {r["kw"]: r for r in rows2}
check("all.rankedKeepsItsNumber",
      by["generator installation anacortes wa"]["rank"], "8")
check("all.notFoundStays",
      by["electrical services anacortes wa"]["rank"], "Not Found")
# A check that failed, and one that never ran, are both outstanding -- not a
# claim that the client does not rank.
check("all.erroredReadsDash",
      by["electrical services whidbey island wa"]["rank"], "\u2014")
check("all.neverCheckedReadsDash",
      by["kohler generator installation anacortes wa"]["rank"], "\u2014")
check("all.realNotFoundIsKept",
      by["electrical services anacortes wa"]["rank"], "Not Found")
check("all.tierCarried",
      by["electrical services whidbey island wa"]["tier"], "Ultra Competitive")
check("all.volumeCarried",
      by["electrical services whidbey island wa"]["vol"], 480)
# Ranked first, as the table always read.
check("all.rankedFirst", rows2[0]["rank"], "8")

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
