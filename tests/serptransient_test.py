"""40101 INTERNAL SE SERVER ERROR IS DATAFORSEO'S BACKEND, NOT A FAILED CHECK.

Cisney & O'Donnell, live: "No gap found in 7 terms checked · 5 did not answer ·
40101: Internal SE Server Error." Five of twelve probes never reached Google,
and the panel reported a finding about the client from what was left.

The error arrives HTTP 200 with the problem inside the task, so the transport
retry in _serp_one -- which only catches dfs_post RAISING -- never saw it, and
a keyword died on one attempt. The same error is what leaves "—" cells in a
finished rank check.

The 40501 ladder MOVES location. This one stays put and asks again.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


OK = {"tasks": [{"status_code": 20000,
                 "result": [{"items": [
                     {"type": "organic", "rank_absolute": 4,
                      "domain": "cisneyremodeling.com"}]}]}]}


def task_err(code, msg):
    return {"tasks": [{"status_code": code, "status_message": msg,
                       "result": None}]}


def run(replies):
    """Serve `replies` in order; returns (result_or_error, calls_made)."""
    seen = []
    real, real_sleep = app.dfs_post, app.time.sleep
    app.time.sleep = lambda *a, **k: None

    def fake(path, payload, timeout=None, **kw):
        seen.append((payload[0]["keyword"], payload[0]["location_name"]))
        return replies[min(len(seen) - 1, len(replies) - 1)]
    app.dfs_post = fake
    try:
        try:
            out = app._serp_one("deck builder huntingdon pa",
                                "cisneyremodeling.com", ["Huntingdon, PA"],
                                "PA", "Cisney & O'Donnell", 100,
                                deadline=app.time.time() + 25)
        except Exception as e:                            # noqa: BLE001
            out = ("ERROR", str(e))
        return out, seen
    finally:
        app.dfs_post, app.time.sleep = real, real_sleep


# ---------------------------------------------- the transient resolves
SE_ERR = task_err(40101, "Internal SE Server Error.")
out, seen = run([SE_ERR, OK])
check("a 40101 is asked again, not reported as a failure",
      out[0] if isinstance(out, tuple) and out[0] != "ERROR" else out, 4)
check("and it took a second call at the same location",
      [x[1] for x in seen], [seen[0][1], seen[0][1]])

# ---------------------------------------------- it does not ask forever
out, seen = run([SE_ERR])
check("a 40101 that never clears is still an error",
      isinstance(out, tuple) and out[0] == "ERROR", True)
check("and the error carries the reason", "40101" in str(out[1]), True)
# 1 original + serp_retry_transient resubmits.
check("and it is bounded", len(seen),
      1 + int(app.CFG.get("serp_retry_transient", 2)))

# ---------------------------------------------- A BAD REQUEST IS NOT RETRIED
# 40501 is an unusable location: the ladder MOVES rather than asking the same
# question again, and a 404xx is not coming back however many times you ask.
out, seen = run([task_err(40400, "Not Found.")])
check("a 404xx is not resubmitted", len(seen), 1)

# 40501 walks the ladder: same keyword, a DIFFERENT location each time.
out, seen = run([task_err(40501, "Invalid Field: 'location_name'.")])
check("a 40501 moves instead of repeating",
      len(seen) > 1 and len({x[1] for x in seen}) == len(seen), True)

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
