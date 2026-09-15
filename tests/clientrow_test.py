"""ONE CLIENT IS ONE ROW, AND IT HOLDS AS MANY QUOTES AS IT NEEDS.

Sage Dental with an SEO quote and an ORM quote is one row with both chips.
Drainify with four saved SEO quotes is one row carrying four. Planner, partner
and status belong to the client, not to whichever quote was saved last.
(2026-09-15, Kiri)
"""
import importlib.util
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
spec = importlib.util.spec_from_file_location("app", os.path.join(SRCDIR, "app.py"))
app = importlib.util.module_from_spec(spec)
sys.modules["app"] = app
spec.loader.exec_module(app)

bad = 0


def check(name, got, want):
    global bad
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name
          + ("" if ok else f"  got {got!r} want {want!r}"))
    if not ok:
        bad += 1


SEO = [
    {"id": 1, "name": "Drainify UK", "client": "Drainify", "strategy": "Core SEO + AI Search",
     "updated_at": "2026-09-17T10:00:00", "base": 5450},
    {"id": 2, "name": "Drainify IE", "client": "Drainify", "strategy": "Core SEO",
     "updated_at": "2026-09-17T09:00:00", "base": 4950},
    {"id": 3, "name": "Sage implants", "client": "Sage Dental", "strategy": "Core SEO",
     "updated_at": "2026-09-16T12:00:00", "base": 5450},
]
REP = [
    {"id": 9, "name": "Sage reputation", "client": "Sage Dental",
     "strategy": "Reactive + Proactive", "updated_at": "2026-09-16T13:00:00", "base": 3100},
    {"id": 10, "name": "Ski Barn reviews", "client": "Ski Barn", "strategy": "Reactive",
     "updated_at": "2026-09-15T08:00:00", "base": 2100},
]
META = {"Sage Dental": {"planner": "Stacy", "partner": "Bay Area Digital Solutions",
                        "status": "Ready for SSG Review", "order_no": "56305"}}

rows = app.group_by_client(SEO, REP, META)
by = {r["client"]: r for r in rows}

check("one row per client", sorted(by), ["Drainify", "Sage Dental", "Ski Barn"])
check("two products merge onto the client",
      (by["Sage Dental"]["seo"], by["Sage Dental"]["orm"]), (1, 1))
check("a client can hold many quotes of one product", by["Drainify"]["seo"], 2)
check("every quote is listed under the client", len(by["Drainify"]["quotes"]), 2)
check("strategies come off the quotes", by["Sage Dental"]["ormStrat"],
      ["Reactive", "Proactive"])
check("and are de-duplicated", by["Drainify"]["seoStrat"], ["Core SEO", "AI Search"])
check("client meta wins over the quote", by["Sage Dental"]["planner"], "Stacy")
check("order number comes from the client", by["Sage Dental"]["order"], "56305")
check("partner comes from the client", by["Sage Dental"]["partner"],
      "Bay Area Digital Solutions")
check("a client with no meta still has a planner", by["Ski Barn"]["planner"], "Kiri")
check("and a status", by["Ski Barn"]["status"], "Pending")
check("built is the newest quote on the client", by["Drainify"]["built"], "2026-09-17")
check("newest client first", [r["client"] for r in rows],
      ["Drainify", "Sage Dental", "Ski Barn"])

# a quote saved without a client is still reachable
check("no client is its own row",
      app.group_by_client([{"id": 4, "name": "One off", "client": "",
                            "updated_at": "2026-01-01T00:00:00"}], [])[0]["client"],
      "One off")

# the endpoint says plainly when there is no database
app.app.config["TESTING"] = True
c = app.app.test_client()
r = c.get("/api/adtini/clients").get_json()
if app.storage.enabled():
    check("endpoint reports enabled", r["enabled"], True)
else:
    check("no database is reported, not crashed", (r["enabled"], r["clients"]), (False, []))
    check("a meta write without a database says so",
          c.post("/api/adtini/client_meta", json={"client": "X", "planner": "Kiri"}).status_code,
          400)

print(f"\n{'FAILED' if bad else 'PASSED'} — {bad} failed")
raise SystemExit(1 if bad else 0)
