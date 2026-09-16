"""EVERY MODEL CALL IS TIMED, UNDER THE NAME OF THE PASS THAT MADE IT.

A 133s build reported "refine 129.6s (search_volume.live 18.5s)" and nothing
about the other 110s: the nine functions that post to the model each call
requests.post directly and none of them marked the time. The one URL they all
share is wrapped, labelled by the calling function. Anything else passes
through untouched.
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

import requests

FAIL = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


calls = []


class _Resp:
    status_code = 200
    def json(self): return {}


def fake_post(url, *a, **kw):
    calls.append(url)
    return _Resp()


app._requests_post = fake_post

# The wrapper is what requests.post now is, everywhere in the process.
check("requests.post is the wrapper", requests.post is app._post, True)


def claude_probe():
    return requests.post("https://api.anthropic.com/v1/messages", data="{}")


def _claude_other_inner():
    return requests.post("https://api.anthropic.com/v1/messages", data="{}")


with app.app.test_request_context("/api/refine"):
    app._t_start()
    claude_probe()
    _claude_other_inner()
    requests.post("https://api.dataforseo.com/v3/x", data="{}")
    marks = list(app._T.marks)

check("underlying post reached, three times", len(calls), 3)
check("model calls marked by caller", [m[0] for m in marks],
      ["claude_probe", "claude_other"])
check("durations are ints", all(isinstance(m[1], int) for m in marks), True)

# The pass that used to time itself by hand is no longer counted twice.
src = open(SRC).read()
check("industry_services has no hand timer",
      't_mark("claude_industry_services"' in src, False)

# Every model function still reaches the API through the timed route: no
# site imports its own copy of post.
import re
sites = re.findall(r"^\s*(?:resp = )?requests\.post\(\s*\n?\s*\"https://api\.anthropic\.com",
                   src, re.M)
check("every model site posts through requests.post (13 found)", len(sites) >= 9, True)
check("only the wrapper calls the saved original", src.count("_requests_post("), 2)

# A mark recorded on a pool worker lands on the request that spawned it.
import time as _t
with app.app.test_request_context("/api/refine"):
    app._t_start()
    def worker(i):
        t0 = _t.time()
        app.t_mark("worker.%d" % i, t0)
        return i
    with app.ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(worker, range(3)))
        futs = [ex.submit(worker, 10 + i) for i in range(2)]
        [f.result() for f in futs]
    got = sorted(m[0] for m in app._T.marks)
check("pool marks reach the request", got,
      ["worker.0", "worker.1", "worker.10", "worker.11", "worker.2"])
check("the executor the build uses is the carrying one",
      app.ThreadPoolExecutor.__module__ == "app", True)

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ok all")
sys.exit(1 if FAIL else 0)
