"""FIFTY-ONE DICTIONARY WORDS AND NO WAY TO SAY WHERE THEY CAME FROM.

A UK build put `vict` (301,000), `note note` (165,000), `modus operandi`,
`reverso context` and `copacetic` in the pool -- identical terms at identical
volumes across runs, unmoved by editing the seeds. Every guess at the cause was
a guess, because the row that carries the answer never reached the browser.

Each row is tagged at the point it enters the pool: "ideas" (Google Ads
keyword ideas), "suggest", "site" (the client's own domain), "geo", "gen",
"claude", "grid". Two places threw the tag away -- the /api/keywords response
shape, and /api/refine, which stamped every rebuilt row "build".
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


SRCTEXT = open(SRC, encoding="utf-8").read()

print("\nTHE BUILD RESPONSE CARRIES THE TAG")
# Both conv lambdas -- /api/keywords and /api/refine -- name "src".
check("both response shapes and the failure path name src",
      SRCTEXT.count('"src": r.get("src", "")'), 3)
check("the failure path names it too",
      '"src": r.get("src", ""), "origin": ""' in SRCTEXT, True)

print("\nTHE ROUND TRIP KEEPS IT")
check("no rebuilt row is stamped build",
      '"src": "build"' in SRCTEXT, False)
check("refine reads the posted tag",
      '"src": (x.get("src") or "")' in SRCTEXT, True)

print("\nEVERY POOL SOURCE STILL STAMPS ONE")
for tag in ("ideas", "suggest", "site", "geo", "gen", "claude", "grid"):
    check("%s is stamped" % tag, ('"src": "%s"' % tag) in SRCTEXT
          or ('r["src"] = "%s"' % tag) in SRCTEXT, True)

print("\nTHE BROWSER RENDERS IT")
IDX = open(os.path.join(SRCDIR, "templates", "index.html"), encoding="utf-8").read()
check("a label exists for every stamped source",
      all(("%s:" % t) in IDX.split("const SRC_LABEL={")[1].split("};")[0]
          for t in ("ideas", "suggest", "site", "geo", "gen", "claude", "grid")),
      True)
check("the chip calls it", "${volTag(x)}${srcTag(x)}" in IDX, True)
check("off unless asked for", "if(!ST.kwSrc) return '';" in IDX, True)
check("a hand-typed term says so", "src:'typed'" in IDX, True)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
