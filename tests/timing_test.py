"""WHERE THE TIME GOES.

"Keyword generation takes so long" cannot be acted on from a guess: a build is
six rounds of calls to a paid service whose latency we do not control. Every
API response now carries its own duration and the provider calls it waited on,
so a slow build reads as a list of what it waited for.
"""
import sys, os, time
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

c = app.app.test_client()

# Every /api/ response is timed.
r = c.post("/api/geo_scope", json={"markets": ["Oxford, MS"], "state": "MS"})
check("header.present", "X-Elapsed-Ms" in r.headers, True)
check("header.isANumber", str(r.headers.get("X-Elapsed-Ms", "")).isdigit(), True)
body = r.get_json()
check("body.carriesIt", isinstance(body.get("_ms"), int), True)
check("body.keepsItsOwnKeys", body.get("band"), "single_city")

# A page is NOT timed -- this is for the pipeline, not the shell.
r2 = c.get("/adtini")
check("pages.untouched", "X-Elapsed-Ms" in r2.headers, False)

# Provider calls are attributed by endpoint.
calls = []
def fake_post(path, payload, **kw):
    calls.append(path)
    time.sleep(0.05)
    return {"tasks": [{"status_code": 20000, "result": []}]}
app.dfs_post = app.dfs_post  # keep the timed wrapper
app._dfs_post_inner = lambda path, payload, **kw: (calls.append(path),
                                                   time.sleep(0.05),
                                                   {"tasks": [{"status_code": 20000,
                                                               "result": []}]})[-1]
with app.app.test_request_context("/api/x"):
    app._t_start()
    app.dfs_post("/keywords_data/google_ads/search_volume/live", [{}])
    app.dfs_post("/serp/google/organic/live/regular", [{}])
    marks = dict(getattr(app._T, "marks", []))
check("marks.bothRecorded", len(marks), 2)
check("marks.keyedByEndpoint",
      "keywords_data.google_ads.search_volume.live" in marks, True)
check("marks.haveDurations", all(v >= 40 for v in marks.values()), True)
check("marks.calledThrough", len(calls), 2)

# The timing never breaks a response.
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app.py"), encoding="utf-8").read()
check("timing.isBestEffort", src.count("except Exception:\n        pass") >= 1, True)
check("timing.wrapsProviderCalls", "_dfs_post_inner" in src, True)
check("timing.wrapsTheCrawl", "_fetch_site_pages_inner" in src, True)
check("timing.wrapsTheModel", "_claude_industry_services_inner" in src, True)

# And the builder prints it.
ui = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "adtini.html"), encoding="utf-8").read()
check("ui.collects", "TIMING.push" in ui, True)
check("ui.printsIt", "timingLine()" in ui, True)
check("ui.resetsPerBuild", "timingReset();" in ui, True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
