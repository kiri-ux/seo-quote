""""Task Not Found" is a CONDITION, not a verdict.

/serp/screenshot renders from a COMPLETED organic task, so until Google answers
the id is genuinely not found -- the same 40401 an expired task gives. Calling
it terminal made the capture give up seconds after queueing. The endpoint
reports the condition and the caller, which knows how long it has waited,
decides.
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

c = app.app.test_client()
def fetch(task):
    app.dfs_post = lambda path, payload, **kw: {"tasks": [task]}
    return c.post("/api/serp_fetch", json={"task_id": "t1", "keyword": "x"}).get_json()

# The shape that actually arrived.
r = fetch({"status_code": 40401, "status_message": "Task Not Found.", "result": None})
check("notFound.reportsCondition", r.get("notfound"), True)
check("notFound.notReady", r.get("ready"), False)
check("notFound.doesNotCallItGone", bool(r.get("gone")), False)
# post() throws on any body carrying an "error" key, so this must not use it.
check("notFound.notAnErrorBody", "error" in r, False)
check("notFound.carriesTheMessage", "Task Not Found" in str(r.get("status")), True)

# By message alone, without the code.
r2 = fetch({"status_code": 20000, "status_message": "Task Not Found.", "result": None})
check("byMessage.reportsCondition", r2.get("notfound"), True)

# Still rendering is NOT gone -- the poll has to keep going.
r3 = fetch({"status_code": 20100, "status_message": "Task In Queue.", "result": None})
check("inQueue.notGone", bool(r3.get("gone")), False)
check("inQueue.notNotfound", bool(r3.get("notfound")), False)
check("inQueue.carriesStatus", r3.get("status"), "Task In Queue.")
check("inQueue.notReady", r3.get("ready"), False)

r4 = fetch({"status_code": 20000, "status_message": "Task Handed.", "result": None})
check("handed.notGone", bool(r4.get("gone")), False)
check("handed.notNotfound", bool(r4.get("notfound")), False)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
