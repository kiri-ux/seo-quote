"""A lost capture task is terminal, however the message arrives.

It came back as HTTP 200 with "Task Not Found" in the body rather than a 404,
so the poll spent three minutes asking about a task that no longer existed --
which is what an instance restart mid-capture leaves behind.
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
check("notFound.isGone", r.get("gone"), True)
check("notFound.notReady", r.get("ready"), False)
check("notFound.saysWhy", "no longer exists" in str(r.get("error")), True)

# By message alone, without the code.
r2 = fetch({"status_code": 20000, "status_message": "Task Not Found.", "result": None})
check("byMessage.isGone", r2.get("gone"), True)

# Still rendering is NOT gone -- the poll has to keep going.
r3 = fetch({"status_code": 20100, "status_message": "Task In Queue.", "result": None})
check("inQueue.notGone", bool(r3.get("gone")), False)
check("inQueue.carriesStatus", r3.get("status"), "Task In Queue.")
check("inQueue.notReady", r3.get("ready"), False)

r4 = fetch({"status_code": 20000, "status_message": "Task Handed.", "result": None})
check("handed.notGone", bool(r4.get("gone")), False)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
