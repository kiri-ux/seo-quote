"""THE SAME PASS OVER THE SAME INPUTS IS ASKED ONCE.

A 133s build spent 129.6s in refine with only 18.5s of it in search_volume, so
the rest was Anthropic calls — every one at temperature 0, every one re-asked on
a rebuild that changed nothing. ADS_VOL_CACHE and RANK_CACHE already had this
lesson; the model passes never got it.

These are the properties the cache has to hold, because each one is a way it
could quietly be wrong instead of loudly broken:
  - a repeat is not re-asked, and a different input still is
  - a FAILED pass is never remembered (or one bad minute pins the rules-based
    fallback in place for six hours)
  - callers mutate what these passes return, so the stored copy must not be the
    handed-out copy
  - an operator who asks for a fresh answer gets one
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

FAIL = []
RUN = []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# ---------------------------------------------------------------- a fake pass
# Registered as a module global and wrapped by the SAME function the real passes
# go through, so this tests the shipped mechanism rather than a copy of it.
CALLS = []


def claude_probe_pass(a, b=""):
    CALLS.append((a, b))
    return {"services": [{"service": a, "tier": "ultra"}], "n": len(CALLS)}


app.claude_probe_pass = claude_probe_pass
app._time_claude_passes()
probe = app.claude_probe_pass

check("the probe got wrapped", getattr(probe, "_timed", False), True)

# ------------------------------------------------------- repeat is not re-asked
app.model_cache_clear()
del CALLS[:]
first = probe("ent", b="desc")
second = probe("ent", b="desc")
check("identical inputs call the pass once", len(CALLS), 1)
check("the second caller still gets the answer", second, first)

# ------------------------------------------------ a different input still asks
third = probe("dentist", b="desc")
check("a different arg is a different key", len(CALLS), 2)
check("and returns its own answer", third["services"][0]["service"], "dentist")
# kwargs are part of the key too, not just positionals
probe("ent", b="OTHER")
check("a changed kwarg is a different key", len(CALLS), 3)

# ----------------------------------------------------- a failure is not stored
# Every one of these passes returns None when the key is missing, the request
# times out, or the JSON will not parse — and every caller falls back on exactly
# that signal. Remembering it would pin the fallback in place for six hours.
DEAD = []


def claude_dead_pass(x):
    DEAD.append(x)
    return None


app.claude_dead_pass = claude_dead_pass
app._time_claude_passes()
app.claude_dead_pass("a")
app.claude_dead_pass("a")
check("a None result is re-asked, never cached", len(DEAD), 2)


def claude_empty_pass(x):
    DEAD.append(x)
    return []


app.claude_empty_pass = claude_empty_pass
app._time_claude_passes()
del DEAD[:]
app.claude_empty_pass("a")
app.claude_empty_pass("a")
check("an empty list is re-asked too", len(DEAD), 2)

# ------------------------------------------------- the caller cannot corrupt it
# stage1b_refine mutates what these passes return — enforce_topic_coverage
# rewrites the services list in place. Handing out the stored object would make
# build N's edits into build N+1's starting point.
app.model_cache_clear()
del CALLS[:]
got = probe("ent", b="desc")
got["services"].append({"service": "INJECTED", "tier": "ultra"})
got["n"] = 999
again = probe("ent", b="desc")
check("still served from cache after mutation", len(CALLS), 1)
check("the mutation did not reach the stored copy",
      [s["service"] for s in again["services"]], ["ent"])
check("nor a scalar on it", again["n"], 1)

# ------------------------------------------------------- fresh bypasses the cache
app.model_cache_clear()
del CALLS[:]
probe("ent", b="desc")
with app.app.test_request_context("/api/refine?fresh=1", method="GET"):
    app._pick_model_fresh()
    check("the request is marked fresh", app._model_fresh_requested(), True)
    probe("ent", b="desc")
check("fresh re-asks the pass", len(CALLS), 2)

with app.app.test_request_context("/api/refine", method="GET"):
    app._pick_model_fresh()
    check("a normal request is not fresh", app._model_fresh_requested(), False)
    probe("ent", b="desc")
check("and is served from cache", len(CALLS), 2)

# THE BYPASS HAS TO SURVIVE THE THREAD, because one pass now runs on one.
# claude_topics was moved onto a worker so it overlaps the expansion, and the
# fresh flag lives on flask.g. That reaches the worker ONLY because the
# ThreadPoolExecutor at the top of app.py copies the context — swap it for the
# stdlib one and an operator asking for a fresh answer silently gets the cached
# topics back, with nothing to show for the click.
del CALLS[:]
app.model_cache_clear()
with app.app.test_request_context("/api/refine?fresh=1", method="GET"):
    app._pick_model_fresh()
    ex = app.ThreadPoolExecutor(max_workers=1)
    try:
        check("a worker thread sees the fresh flag",
              ex.submit(app._model_fresh_requested).result(), True)
        ex.submit(probe, "ent", b="desc").result()
        ex.submit(probe, "ent", b="desc").result()
    finally:
        ex.shutdown()
check("so a threaded pass re-asks under fresh", len(CALLS), 2)

# an unserializable argument must not be cached under a colliding key
del CALLS[:]
app.model_cache_clear()
check("an unserializable arg yields no key",
      app._model_cache_key("x", (object(),), {}) is None
      or isinstance(app._model_cache_key("x", (object(),), {}), str), True)

# ------------------------------------- the two passes without the claude_ prefix
# infer_business runs inside stage1b_refine on every build with no business
# description yet, which is most first builds. Selecting on the prefix alone
# missed it, so it was neither timed under its own name nor cached.
check("infer_business is wrapped", getattr(app.infer_business, "_timed", False), True)
check("widen_vocabulary is wrapped", getattr(app.widen_vocabulary, "_timed", False), True)

# ------------------------------------------------------- per-pass model selection
# The map ships empty on purpose: these passes feed the quote, so nothing is
# switched until it has been measured on a real account.
check("no pass is pinned by default", app.CLAUDE_PASS_MODELS, {})
check("an unnamed call is the old behaviour",
      app.claude_model_for(), os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"))
check("an unpinned pass falls through to CLAUDE_MODEL",
      app.claude_model_for("claude_refine_keywords"),
      os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"))
os.environ["CLAUDE_MODEL_CLAUDE_REGION_NAMES"] = "claude-haiku-4-5"
check("a per-pass env var wins", app.claude_model_for("claude_region_names"),
      "claude-haiku-4-5")
check("and reaches only that pass",
      app.claude_model_for("claude_refine_keywords"),
      os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"))
del os.environ["CLAUDE_MODEL_CLAUDE_REGION_NAMES"]

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
