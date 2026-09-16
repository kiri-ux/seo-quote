"""The screenshot task must not be refused because Google does not carry the
market name. "the capture service took no task", over and over, was a 40501 on
"Whidbey Island,Washington,United States"."""
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

asked = []
def fake_post(path, payload, **kw):
    loc = (payload or [{}])[0].get("location_name", "")
    asked.append(loc)
    if "Whidbey Island" in loc:
        return {"tasks": [{"status_code": 40501,
                           "status_message": "location_name not found"}]}
    return {"tasks": [{"status_code": 20100, "id": "task-123"}]}

app.dfs_post = fake_post
c = app.app.test_client()
r = c.post("/api/serp_queue", json={"keyword": "electrical services whidbey island wa",
                                    "geo_values": ["Whidbey Island, WA"], "state": "WA",
                                    "device": "desktop"}).get_json()
check("gotATask", r.get("task_id"), "task-123")
check("triedTheMarketFirst", "Whidbey Island" in asked[0], True)
check("thenWider", len(asked) > 1, True)
check("saysItIsBorrowed", r.get("loc_scope"), "broader")
check("namesWhatWasCaptured", "Whidbey Island" in str(r.get("loc_used")), False)

# A market Google carries is queued on the first call, unmarked.
asked.clear()
r2 = c.post("/api/serp_queue", json={"keyword": "electrical services anacortes wa",
                                     "geo_values": ["Anacortes, WA"], "state": "WA"}).get_json()
check("city.oneCall", len(asked), 1)
check("city.notBorrowed", r2.get("loc_scope"), "")

# A refusal that is not about the location is reported, not retried elsewhere.
def broke(path, payload, **kw):
    asked.append((payload or [{}])[0].get("location_name", ""))
    return {"tasks": [{"status_code": 40200, "status_message": "payment required"}]}
app.dfs_post = broke
asked.clear()
r3 = c.post("/api/serp_queue", json={"keyword": "x", "geo_values": ["Anacortes, WA"],
                                     "state": "WA"})
check("otherRefusal.notRetried", len(asked), 1)
check("otherRefusal.reported", "payment required" in str(r3.get_json().get("error")), True)

print(f"ok={ok} failed={fail}")
sys.exit(1 if fail else 0)
