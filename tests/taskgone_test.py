"""A DEAD TASK POLLED THREE HUNDRED TIMES.

DataForSEO emailed Kiri about "multiple occurrences of the Task Not Found error
(40401)". It was this tool. A queued SERP task is dropped once its result has
been read and expires after that, so asking again returns 40401 as an HTTP 404
-- which dfs_post raises. rankings_collect caught every raised exception and
filed it as "pending: poll again", and the front end polls every 4 seconds for
240 seconds. Five dead tasks is 300 failed calls in a single run, and reopening
a saved quote and pressing Retry does it again with task IDs that are days old.

Queued is transient. Gone is permanent. They cannot share a branch.
(2026-09-04, Kiri)
"""
import importlib.util
import json
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

import requests

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


class _Resp:
    def __init__(self, code):
        self.status_code = code


CALLS = []


def fake_post(path, payload, timeout=None, method="POST", retries=1):
    CALLS.append(path)
    tid = path.rsplit("/", 1)[-1]
    if tid == "dead":                       # 40401 as an HTTP 404
        e = requests.HTTPError("404 Client Error")
        e.response = _Resp(404)
        raise e
    if tid == "dead-in-body":               # 40401 inside a 200
        return {"tasks": [{"status_code": 40401,
                           "status_message": "Task Not Found."}]}
    if tid == "slow":                       # genuinely still running
        return {"tasks": [{"status_code": 40602}]}
    if tid == "flaky":                      # a real transient
        raise requests.ConnectionError("read timed out")
    return {"tasks": [{"status_code": 20000, "result": [{"items": []}]}]}


app.dfs_post = fake_post
client = app.app.test_client()


def collect(tasks):
    del CALLS[:]
    r = client.post("/api/rankings_collect",
                    json={"tasks": tasks, "domain": "drainify.co.uk",
                          "brand": "Drainify"})
    return json.loads(r.data)


print("\nA TASK THAT NO LONGER EXISTS IS ANSWERED ONCE")
r = collect([{"kw": "pacp", "task_id": "dead"}])
check("it does not go back on the poll list", r["pending"], [])
check("it lands as a finished row", len(r["done"]), 1)
check("marked as an error", r["done"][0]["error"], True)
check("and marked as gone, not merely failed", r["done"][0].get("gone"), True)
check("one call, not sixty", len(CALLS), 1)

print("\nTHE SAME ANSWER INSIDE A 200 BODY")
r = collect([{"kw": "pacp", "task_id": "dead-in-body"}])
check("also gone", r["done"][0].get("gone"), True)
check("also not re-polled", r["pending"], [])

print("\nSTILL RUNNING IS STILL POLLED")
r = collect([{"kw": "pacp", "task_id": "slow"}])
check("queued stays pending", [t["task_id"] for t in r["pending"]], ["slow"])
check("and nothing is reported about it yet", r["done"], [])

print("\nAND A REAL TRANSIENT IS STILL RETRIED")
# A dropped connection says nothing about whether the task exists.
r = collect([{"kw": "pacp", "task_id": "flaky"}])
check("kept on the poll list", [t["task_id"] for t in r["pending"]], ["flaky"])

print("\nA MIXED BATCH IS SORTED CORRECTLY")
r = collect([{"kw": "a", "task_id": "dead"},
             {"kw": "b", "task_id": "slow"},
             {"kw": "c", "task_id": "live"}])
check("only the live one is polled again",
      [t["task_id"] for t in r["pending"]], ["slow"])
_by = {d["kw"]: d for d in r["done"]}
check("the dead one is closed out", _by["a"].get("gone"), True)
check("the good one landed", _by["c"]["error"], False)
check("and the slow one is not reported yet", "b" in _by, False)

print("\n%d checks, %d failed" % (len(CHECKS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all ok")
