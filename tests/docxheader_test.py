"""AN EM DASH STOPPED THE PROPOSAL DOWNLOADING.

    [WARNING] Invalid request from ip=10.195.190.9: Invalid HTTP Header:
    "'only 5 of 17 measured terms rank inside the first 5 pages - this client
    is starting close enough to scratch that the first rankings are 6-12+
    months out'"
    POST /api/proposal.docx HTTP/1.1" 400 0

X-Perf-Omitted carries the reason the performance section removed itself, and
that reason is prose written for a human. It contains an em dash, which is not
Latin-1, and gunicorn 22 refuses to send the response at all -- so the document
was built, and then thrown away, and the browser got a bare 400.

It only ever failed on quotes where the section omits itself WITH a reason,
which is why Drainify could never download and every performance-eligible quote
downloaded fine. (2026-09-09, Kiri)
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


REAL = ("only 5 of 17 measured terms rank inside the first 5 pages — this "
        "client is starting close enough to scratch that the first rankings "
        "are 6-12+ months out")

print("\nTHE LINE THAT BROKE IT")
out = app.ascii_header(REAL)
check("the em dash is gone", "—" in out, False)
check("and the sentence survives",
      out.startswith("only 5 of 17 measured terms rank inside the first 5 pages -"), True)
check("it encodes as latin-1, which is what a header must do",
      bool(out.encode("latin-1")), True)

print("\nEVERY OTHER WAY PROSE BREAKS A HEADER")
check("curly quotes", app.ascii_header("“pacp” ‘x’"), '"pacp" \'x\'')
check("ellipsis", app.ascii_header("waiting…"), "waiting...")
check("multiplication sign", app.ascii_header("7 × city"), "7 x city")
check("newlines collapse", app.ascii_header("a\r\nb\tc"), "a b c")
check("anything else is dropped, not raised",
      app.ascii_header("café 中文 ok"), "caf ok")
check("empty stays empty", app.ascii_header(""), "")
check("None stays empty", app.ascii_header(None), "")
check("it is capped", len(app.ascii_header("x" * 500)), 180)

print("\nTHE DOWNLOAD ITSELF")
try:
    import docx  # noqa: F401
    have_docx = True
except ImportError:
    have_docx = False

if not have_docx:
    print("  --   python-docx not installed here; endpoint check skipped")
else:
    client = app.app.test_client()
    terms = ["sewer inspection software", "pacp software", "sewer crawler"]
    payload = {
        "brand": "Drainify", "business_desc": "", "geo_values": [],
        "kw": {"all": [{"kw": t, "vol": 10} for t in terms],
               "ultra": [{"kw": t, "vol": 10} for t in terms],
               "competitive": [], "long_tail": [], "total_volume": 150},
        "table": [{"kw": t, "pos": 77} for t in terms],
        "signals": None,
        "pricing": {"client_tiers": {"base": 2950, "intermediate": 4000,
                                     "advanced": 5100},
                    "anchor": 1800, "markup_pct": 35, "addon_markets": 1,
                    "client_addon_per_market": {"base": 2655,
                                                "intermediate": 3600,
                                                "advanced": 4590},
                    "addon_discount_pct": 10, "min_term_months": 6,
                    "handoff": {}},
        "strategy": "Core SEO", "perf_on": None, "cpc": {}, "perf_extra": [],
        "perf_rows": [], "perf_override": {}, "practice_area": {},
        "state": "", "inputs": {"geo_values": []}, "serp": None}
    r = client.post("/api/proposal.docx", json=payload)
    check("the document is returned", r.status_code, 200)
    hdr = r.headers.get("X-Perf-Omitted") or ""
    check("and any reason it carries is header-safe",
          all(ord(c) < 128 for c in hdr), True)
    check("the file is a real docx", r.data[:2], b"PK")

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
