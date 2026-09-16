"""The per-minute pacing bucket is per endpoint family.

Google Ads LIVE endpoints are capped at 12 requests a minute by DataForSEO.
Everything else, SERP included, is capped at 2000. One shared bucket held SERP
to the Google Ads limit, so a rank check of eleven keywords could not finish
inside a request budget and its tail came back as failures.
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app as m

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1; print("  ok  ", name)
    else:
        fail += 1; print("  FAIL", name, "got", repr(got), "want", repr(want))

fam = m._dfs_family
check("volumeIsAdsLive", fam("/keywords_data/google_ads/search_volume/live"), "ads_live")
check("adsTaskIsNot",    fam("/keywords_data/google_ads/search_volume/task_post"), "other")
check("serpLiveIsOther", fam("/serp/google/organic/live/regular"), "other")
check("serpTaskIsOther", fam("/serp/google/organic/task_post"), "other")
check("screenshotOther", fam("/serp/screenshot"), "other")
check("onpageOther",     fam("/on_page/content_parsing/live"), "other")
check("blankOther",      fam(""), "other")

check("adsCapIsTwelveSafe", m.CFG["dfs_calls_per_minute"] <= 12, True)
check("otherCapIsBigger",
      m.CFG["dfs_calls_per_minute_other"] > m.CFG["dfs_calls_per_minute"], True)
check("otherCapUnderProviderLimit", m.CFG["dfs_calls_per_minute_other"] <= 2000, True)

# The buckets do not share timestamps: filling the Ads one must not slow SERP.
m._DFS_BUCKETS.clear()
for _ in range(m.CFG["dfs_calls_per_minute"]):
    m._dfs_take_slot("/keywords_data/google_ads/search_volume/live")
check("adsBucketFilled", len(m._DFS_BUCKETS["ads_live"]), m.CFG["dfs_calls_per_minute"])

t0 = time.time()
for _ in range(20):
    m._dfs_take_slot("/serp/google/organic/live/regular")
check("twentySerpCallsDidNotWait", time.time() - t0 < 1.0, True)
check("serpBucketIsItsOwn", len(m._DFS_BUCKETS["other"]), 20)

# A full bucket still blocks — the pacing is not simply gone.
m._DFS_BUCKETS.clear()
m.CFG["dfs_calls_per_minute_other"] = 2
m._dfs_take_slot("/serp/google/organic/live/regular")
m._dfs_take_slot("/serp/google/organic/live/regular")
held = {"done": False}
def third():
    m._dfs_take_slot("/serp/google/organic/live/regular")
    held["done"] = True
th = threading.Thread(target=third, daemon=True); th.start(); th.join(1.5)
check("fullBucketStillBlocks", held["done"], False)
m.CFG["dfs_calls_per_minute_other"] = 300
m._DFS_BUCKETS.clear()

# Zero still disables pacing for that family only.
m.CFG["dfs_calls_per_minute_other"] = 0
t0 = time.time()
for _ in range(500):
    m._dfs_take_slot("/serp/google/organic/live/regular")
check("zeroDisablesPacing", time.time() - t0 < 1.0, True)
check("zeroRecordsNothing", m._DFS_BUCKETS.get("other", []), [])
m.CFG["dfs_calls_per_minute_other"] = 300

check("workersRaised", m.CFG["rank_check_workers"] >= 10, True)
check("workersUnderProviderLimit", m.CFG["rank_check_workers"] <= 30, True)

print(f"\n{ok + fail} checks, {fail} failed")
sys.exit(1 if fail else 0)
