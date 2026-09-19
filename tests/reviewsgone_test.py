"""THE REVIEW PULL HAD THE BUG THE RANK CHECK ALREADY FIXED.

DataForSEO wrote to Kiri again about "multiple occurrences of the Task Not Found
error (40401)". rankings_collect was fixed on 2026-09-04; reviews_collect was
written the same way and never was. It caught every raised exception and filed
it as "pending: poll again", and the browser re-sends every pending id twelve
times at five-second intervals -- so one dead task is twelve failed calls per
scan, and a ten-location DSO is a hundred and twenty.

The trap that makes it fire on a healthy account: a completed pull with an empty
result, a location with nothing to return. That read CONSUMED the task, so the
second ask is a guaranteed 40401 and every ask after it.

Queued is transient. Gone is permanent. They cannot share a branch.
(2026-09-19, Kiri)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")

import requests

import rep_scan

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


def _review(v):
    return {"rating": {"value": v}}


BEHAVIOUR = {
    # 40401 as an HTTP 404 -- what dfs_post raises on an expired task.
    "dead": "http404",
    # 40401 inside an HTTP 200 body, the way the rate limit arrives.
    "dead-in-body": "body40401",
    # Completed, nothing to return. The read spent the task.
    "empty": "empty",
    # Still in Google's queue. This one fills in by itself.
    "queued": "queued",
    # "Task Handed." under a 20000 with no result. Still working, NOT spent --
    # calling this gone drops a location's whole star split to save one call.
    "handed": "handed",
    # A read timeout: transient, and worth asking again.
    "flaky": "timeout",
    "good": "good",
}

CALLS = []


def fake_post(path, payload, timeout=None, method="POST", retries=1):
    CALLS.append(path)
    tid = path.rsplit("/", 1)[-1]
    beh = BEHAVIOUR[tid]
    if beh == "http404":
        e = requests.HTTPError("404 Client Error")
        e.response = _Resp(404)
        raise e
    if beh == "timeout":
        raise requests.Timeout("read timeout")
    if beh == "body40401":
        return {"tasks": [{"status_code": 40401,
                           "status_message": "Task Not Found.",
                           "result": None}]}
    if beh == "empty":
        return {"tasks": [{"status_code": 20000, "status_message": "Ok.",
                           "data": {"tag": "p-empty"}, "result": [None]}]}
    if beh == "handed":
        return {"tasks": [{"status_code": 20000, "status_message": "Task Handed.",
                           "result": None}]}
    if beh == "queued":
        return {"tasks": [{"status_code": 40602, "status_message": "Task In Queue.",
                           "result": None}]}
    return {"tasks": [{
        "status_code": 20000, "status_message": "Ok.",
        "data": {"tag": "p-good"},
        "result": [{"title": "Bright Dental Co", "reviews_count": 6,
                    "rating": {"value": 3.4},
                    "items": [_review(1), _review(1), _review(2), _review(3),
                              _review(4), _review(5)]}],
    }]}


rep_scan.init(fake_post)

print("reviews_collect sorts a dead task from a slow one")
out = rep_scan.reviews_collect(list(BEHAVIOUR))
# .get, so a regression reports the check that broke rather than a traceback.
GONE = out.get("gone", [])

check("gone.expiredTask", "dead" in GONE, True)
check("gone.fortyFourOhOneInTheBody", "dead-in-body" in GONE, True)
check("gone.readAndEmptyIsSpent", "empty" in GONE, True)
check("pending.stillInTheQueue", "queued" in out["pending"], True)
check("pending.aTimeoutIsWorthAnotherAsk", "flaky" in out["pending"], True)
check("pending.twentyThousandCanStillMeanWorking", "handed" in out["pending"], True)
check("gone.handedIsNotSpent", "handed" in GONE, False)
check("done.theGoodOneLands", [d["id"] for d in out["done"]], ["good"])

# The whole point: a gone task must not come back in the list the browser
# re-sends, or the poll asks for it twelve more times.
check("goneIsNotPending", [t for t in GONE if t in out["pending"]], [])
check("pendingHoldsOnlyTheTransient", sorted(out["pending"]),
      ["flaky", "handed", "queued"])
check("goneIsNotDone", [t for t in GONE
                        if t in [d["id"] for d in out["done"]]], [])

print("the counts still come out of a good pull")
g = out["done"][0]
check("counts.oneStar", g["neg_1"], 2)
check("counts.twoStar", g["neg_2"], 1)
check("counts.flagged", g["neg_1_2"], 3)
check("counts.weakThree", g["weak_3"], 1)
check("counts.fourAndFive", (g["pos_4"], g["pos_5"]), (1, 1))
check("counts.wholeProfile", g["complete"], True)
check("counts.notTruncated", g["truncated"], False)
check("totals.negatives", out["total_negatives"], 3)
check("totals.weak", out["total_weak"], 1)

print("the second round asks only for what is still coming")
CALLS.clear()
rep_scan.reviews_collect(out["pending"])
check("secondRound.asksForTheTransientOnly", len(CALLS), 3)
check("secondRound.neverAsksForADeadTask",
      [p for p in CALLS if p.rsplit("/", 1)[-1] in GONE], [])

print()
print("PASS %d/%d" % (len(CHECKS) - len(FAIL), len(CHECKS)))
sys.exit(1 if FAIL else 0)
