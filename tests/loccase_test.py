"""THE PROVIDER'S LOCATION DATABASE IS TITLE CASE.

loc_string title-cased the STATE and passed the CITY through exactly as the
planner typed it. "knoxville, TN" on the form queued a capture against
"knoxville,Tennessee,United States" -- not a place in DataForSEO's database.
task_post accepts it and the task fails when it runs, and /serp/screenshot
answers 40401 for an errored task exactly as it does for one that never
existed, so the capture polled a dead id for three minutes and gave up.

This is not an ORM bug. Every SERP capture, rank check and keyword pull that
goes through loc_string had it, on any quote where the market was typed flat.
"""
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import app

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# ---------------------------------------------- however it was typed
for typed in ("knoxville, tn", "Knoxville, TN", "KNOXVILLE, TN"):
    check("%-16s resolves to one place" % typed,
          app.loc_string([typed], ""), "Knoxville,Tennessee,United States")

check("two words are both cased",
      app.loc_string(["boca raton, fl"], ""), "Boca Raton,Florida,United States")
check("and so is a city with punctuation",
      app.loc_string(["st. louis, mo"], ""), "St. Louis,Missouri,United States")

# A PROVIDER SPELLING THAT ALREADY CARRIES CAPITALS IS LEFT ALONE. .title()
# would turn McAllen into Mcallen, which is a different miss in the same place.
check("McAllen keeps its capital",
      app.loc_string(["McAllen, TX"], ""), "McAllen,Texas,United States")
check("DeSoto keeps its capital",
      app.loc_string(["DeSoto, TX"], ""), "DeSoto,Texas,United States")

# ---------------------------------------------- and the capture asks for it
seen = []


def fake_post(path, payload, **kw):
    seen.append((path, payload))
    raise RuntimeError("stop here")


app.dfs_post = fake_post
c = app.app.test_client()
c.post("/api/serp_queue", json={"keyword": "city heating and air reviews",
                                "geo_values": ["knoxville, tn"], "state": "TN",
                                "device": "desktop"})
check("the capture is queued against a place that exists",
      seen[0][1][0]["location_name"], "Knoxville,Tennessee,United States")
check("and it is the keyword the caller asked for",
      seen[0][1][0]["keyword"], "city heating and air reviews")

# no market on the order is the country, not a broken string
seen.clear()
c.post("/api/serp_queue", json={"keyword": "acme reviews", "geo_values": [],
                                "state": "", "device": "desktop"})
check("no market falls back to the country",
      seen[0][1][0]["location_name"], "United States")

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
