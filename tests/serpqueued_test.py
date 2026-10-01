"""A capture whose task is still queued is not a dead task.

King and Prince Seafood: "no capture after 3 minutes ... Task Not Found". The
screenshot asked task_get whether the organic task was alive, read 40602 Task
In Queue (and 40401) as dead, and the page never asked for a fresh task.
(2026-10-01, Kiri)
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

app.dfs_post = lambda path, payload, **kw: {"tasks": [{"status_code": 40401,
                                                       "status_message": "Task Not Found."}]}
app._serp_gate_holds = lambda *a, **k: False
state = {"code": 40602}
app.dfs_get = lambda path, **kw: {"tasks": [{"status_code": state["code"],
                                            "status_message": "msg"}]}

def fetch():
    with app.app.test_client() as c:
        return c.post("/api/serp_fetch", json={"task_id": "t1", "waited": 120}).get_json()

for code in (40602, 40601, 40401):
    state["code"] = code
    r = fetch()
    check(f"{code} is waited on or requeued, not dead",
          (bool(r.get("notfound")), bool(r.get("taskerr"))), (True, False))
state["code"] = 40102
r = fetch()
check("a real task error is dead", bool(r.get("taskerr")), True)

print(f"PASS={ok} FAIL={fail}")
sys.exit(1 if fail else 0)
