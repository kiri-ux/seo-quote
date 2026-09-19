"""TWENTY-FIVE REFUSALS PER CAPTURE, AND NOW ON EVERY ORM QUOTE TOO.

/serp/screenshot renders from a COMPLETED organic task, so every poll before
Google answers is a 40401 in DataForSEO's logs. The poll ran every three seconds
through 75 seconds of patience, which is twenty-five of them per capture -- and
since the reputation quote started capturing itself (2026-09-17) that runs on
every ORM quote as well as every SEO one. DataForSEO wrote to Kiri about it.

tasks_ready is free and does not collect anything, so it can be asked first.
task_get CANNOT be used for this: it drops the task, which would leave the
screenshot with nothing to render from.

It is a gate, not a gatekeeper. Unreadable list, or a caller that has already
waited out the grace window, and the screenshot call goes out as it always did.
(2026-09-19, Kiri)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")

import app

FAIL, CHECKS = [], []


def check(label, got, want):
    ok = got == want
    CHECKS.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


c = app.app.test_client()
SHOT = "/serp/screenshot"


def _forget():
    """A fresh process: nothing seen, nothing cached."""
    getattr(app, "_SERP_READY_SEEN", set()).clear()
    getattr(app, "_SERP_READY_FIRST", {}).clear()
    cache = getattr(app, "_SERP_READY_CACHE", {})
    cache["at"] = 0.0
    cache["ids"] = frozenset()


def _wire(ready_ids, raises=False):
    """Returns the list the screenshot endpoint's calls land in."""
    posted = []

    def fake_get(path, timeout=None):
        if raises:
            raise RuntimeError("tasks_ready unavailable")
        if "tasks_ready" in path:
            return {"tasks": [{"result": [{"id": i} for i in ready_ids]}]}
        return {"tasks": [{}]}

    def fake_post(path, payload=None, **kw):
        posted.append(path)
        # The shape an early ask actually gets back.
        return {"tasks": [{"status_code": 40401,
                           "status_message": "Task Not Found.", "result": None}]}

    app.dfs_get = fake_get
    app.dfs_post = fake_post
    return posted


def fetch(waited=0):
    return c.post("/api/serp_fetch",
                  json={"task_id": "t1", "keyword": "x", "waited": waited}).get_json()


print("a task that has not finished is not asked for")
_forget()
posted = _wire(ready_ids=["someone-elses-task"])
r = fetch()
check("stillRunning.screenshotNeverCalled", [p for p in posted if p == SHOT], [])
check("stillRunning.notReady", r.get("ready"), False)
check("stillRunning.saysQueued", r.get("queued"), True)
# post() throws on any body carrying an "error" key, so the poll must keep going.
check("stillRunning.notAnErrorBody", "error" in r, False)
check("stillRunning.notCalledGone", bool(r.get("gone")), False)
check("stillRunning.carriesAStatus", r.get("status"), "Task In Queue.")

print("a finished task goes straight through")
_forget()
posted = _wire(ready_ids=["t1"])
fetch()
check("finished.screenshotCalled", [p for p in posted if p == SHOT], [SHOT])

print("once seen finished, it stays finished")
# The render can take the id off the ready list, and asking twice must not turn
# a finished task back into a pending one.
posted = _wire(ready_ids=[])
fetch()
check("seenOnce.stillGoesThrough", [p for p in posted if p == SHOT], [SHOT])

print("the gate opens rather than blocking the capture")
_forget()
posted = _wire(ready_ids=[], raises=True)
fetch()
check("readyUnreadable.fallsThrough", [p for p in posted if p == SHOT], [SHOT])

_forget()
posted = _wire(ready_ids=["someone-elses-task"])
fetch(waited=getattr(app, "_SERP_READY_GRACE", 90) + 1)
check("pastTheGrace.fallsThrough", [p for p in posted if p == SHOT], [SHOT])

_forget()
posted = _wire(ready_ids=["someone-elses-task"])
fetch(waited=getattr(app, "_SERP_READY_GRACE", 90) - 1)
check("insideTheGrace.stillGated", [p for p in posted if p == SHOT], [])

print("the gate lets go on its own clock, whatever the page says")
# A cached copy of the old page sends no `waited` at all.
_forget()
posted = _wire(ready_ids=["someone-elses-task"])
app._SERP_READY_FIRST["t1"] = 0.0          # first held back at the epoch
c.post("/api/serp_fetch", json={"task_id": "t1", "keyword": "x"})
check("agedOut.fallsThroughWithNoWaited", [p for p in posted if p == SHOT], [SHOT])

print("concurrent captures share one read of the list")
_forget()
reads = []

def counting_get(path, timeout=None):
    reads.append(path)
    return {"tasks": [{"result": []}]}

app.dfs_get = counting_get
app.dfs_post = lambda path, payload=None, **kw: {"tasks": [{}]}
for _ in range(4):
    fetch()
check("cache.oneReadNotFour", len(reads), 1)

print()
print("PASS %d/%d" % (len(CHECKS) - len(FAIL), len(CHECKS)))
sys.exit(1 if FAIL else 0)
