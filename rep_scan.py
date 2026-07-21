"""
Reputation Management — brand scan engine.

Automates Brendan's diagnostic section: brand term universe with negative-
modifier volumes, SERP threat table for "{brand} reviews" with owned-asset
tagging, related-searches + auto-suggest flags, Google location discovery,
and review-level negative counting (worst-first pull, so counting negatives
costs cents even on a 100-location DSO).

Dependency-injected: app.py calls init(dfs_post) at import so this module
never imports app (avoids the circular).

DFS cost notes (July 2026 pricing):
  keywords_for_keywords live ......... ~$0.05 / call
  SERP organic live advanced ......... ~$0.002 / call
  SERP autocomplete live ............. ~$0.002 / call
  business_listings search live ...... ~$0.002 / call (database, instant)
  google/reviews task (priority 2) ... $0.0015 per 10 reviews, ~1 min
Sort worst-first + depth 200/location => full Sage-scale negative count ~$3-4.
"""

_post = None                      # injected dfs_post(path, payload, ...)

def init(dfs_post):
    global _post
    _post = dfs_post


# ---------------------------------------------------------------- negatives
NEG_MODIFIERS = {
    "lawsuit", "lawsuits", "complaint", "complaints", "scam", "scams",
    "fraud", "ripoff", "rip-off", "sue", "sued", "suing", "settlement",
    "class action", "recall", "arrest", "arrested", "controversy",
    "scandal", "investigation", "warning", "problem", "problems",
    "horror", "worst", "avoid", "shut down", "closing", "bankrupt",
    "bankruptcy", "bbb",
}
WATCH_MODIFIERS = {"reviews", "review", "legit", "rating", "ratings",
                   "is it good", "safe"}

def classify_term(term, brand):
    t = term.lower()
    b = brand.lower()
    if b not in t:
        return None                       # not a brand term
    rest = t.replace(b, " ")
    for m in NEG_MODIFIERS:
        if m in rest:
            return "negative"
    for m in WATCH_MODIFIERS:
        if m in rest:
            return "watch"
    return "neutral"


def scan_terms(brand):
    """Brand term universe via keywords_for_keywords (US national).
    Returns terms classified neutral/watch/negative with volumes."""
    payload = [{"keywords": [brand.lower()], "location_code": 2840,
                "language_code": "en", "sort_by": "search_volume"}]
    data = _post("/keywords_data/google_ads/keywords_for_keywords/live",
                 payload, timeout=90)
    rows = []
    for it in (data["tasks"][0]["result"] or []):
        kw = (it.get("keyword") or "").lower()
        vol = it.get("search_volume") or 0
        cls = classify_term(kw, brand)
        if cls:
            rows.append({"term": kw, "volume": vol, "class": cls})
    rows.sort(key=lambda r: -r["volume"])
    tot = {c: sum(r["volume"] for r in rows if r["class"] == c)
           for c in ("neutral", "watch", "negative")}
    return {"terms": rows[:120],
            "total_volume": sum(tot.values()),
            "negative_volume": tot["negative"],
            "watch_volume": tot["watch"]}


# --------------------------------------------------------------------- serp
def _domain(d):
    d = (d or "").lower()
    return d[4:] if d.startswith("www.") else d

def scan_serp(brand, domain=""):
    """Top-10 for '{brand} reviews' + related searches, with owned tagging
    and ratings where Google surfaces them (review-site snippets)."""
    kw = f"{brand} reviews".lower()
    payload = [{"keyword": kw, "location_code": 2840,
                "language_code": "en", "depth": 10}]
    data = _post("/serp/google/organic/live/advanced", payload, timeout=60)
    own = _domain(domain)
    organic, related = [], []
    for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
        t = it.get("type")
        if t == "organic":
            rat = (it.get("rating") or {})
            organic.append({
                "pos": it.get("rank_absolute"),
                "title": it.get("title"),
                "domain": _domain(it.get("domain")),
                "rating": rat.get("value"),
                "votes": rat.get("votes_count"),
                "owned": bool(own) and own in _domain(it.get("domain")),
            })
        elif t == "related_searches":
            related = [s for s in (it.get("items") or []) if s][:10]
    neg_related = [s for s in related
                   if any(m in s.lower() for m in NEG_MODIFIERS)]
    owned_top10 = sum(1 for o in organic if o["owned"])
    return {"query": kw, "organic": organic[:10], "related": related,
            "negative_related": neg_related, "owned_in_top10": owned_top10}


def scan_autocomplete(brand):
    """Auto-suggest for the brand and '{brand} reviews' — negative flags."""
    out = {}
    for kw in (brand.lower(), f"{brand} reviews".lower()):
        payload = [{"keyword": kw, "location_code": 2840, "language_code": "en"}]
        try:
            data = _post("/serp/google/autocomplete/live/advanced",
                         payload, timeout=60)
            sugg = []
            for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
                if it.get("type") == "autocomplete":
                    s = it.get("suggestion")
                    if s:
                        sugg.append(s)
            out[kw] = {"suggestions": sugg,
                       "negative": [s for s in sugg
                                    if any(m in s.lower() for m in NEG_MODIFIERS)]}
        except Exception as e:
            out[kw] = {"error": str(e)}
    return out


# ---------------------------------------------------------------- locations
def scan_locations(brand, limit=200):
    """Google Business location discovery via the Business Listings database
    (instant, no scrape). Profile-level rating + review count per location."""
    payload = [{"filters": [["title", "like", f"%{brand.lower()}%"]],
                "limit": limit,
                "order_by": ["rating.votes_count,desc"]}]
    data = _post("/business_data/business_listings/search/live",
                 payload, timeout=90)
    locs = []
    for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
        rat = it.get("rating") or {}
        locs.append({
            "title": it.get("title"),
            "address": it.get("address"),
            "place_id": it.get("place_id"),
            "cid": it.get("cid"),
            "rating": rat.get("value"),
            "reviews": rat.get("votes_count") or 0,
        })
    return {"locations": locs,
            "total_reviews": sum(l["reviews"] for l in locs)}


# ------------------------------------------------------------- review pulls
def reviews_submit(place_ids, depth=200):
    """Queue worst-first review pulls (priority 2, ~1 min). Returns task ids.
    depth=200 => $0.03/location at priority pricing."""
    depth = max(10, min(4490, int(depth)))
    payload = [{"place_id": pid, "location_code": 2840, "language_code": "en",
                "depth": depth, "sort_by": "lowest_rating", "priority": 2,
                "tag": pid}
               for pid in place_ids]
    data = _post("/business_data/google/reviews/task_post", payload, timeout=60)
    tasks = []
    for t in data.get("tasks") or []:
        tasks.append({"id": t.get("id"),
                      "place_id": (t.get("data") or {}).get("tag"),
                      "ok": t.get("status_code") in (20000, 20100)})
    return {"tasks": tasks, "depth": depth}


def reviews_collect(task_ids):
    """Poll queued pulls. Counts 1-2 star (negative) and 3 star (weak) per
    task; flags when negatives hit the pull depth (=> more exist)."""
    done, pending = [], []
    for tid in task_ids:
        try:
            data = _post(f"/business_data/google/reviews/task_get/{tid}",
                         None, timeout=30, method="GET")
            task = (data.get("tasks") or [{}])[0]
            res = (task.get("result") or [None])[0]
            if task.get("status_code") == 20000 and res:
                items = res.get("items") or []
                n12 = sum(1 for i in items
                          if ((i.get("rating") or {}).get("value") or 5) <= 2)
                n3 = sum(1 for i in items
                         if ((i.get("rating") or {}).get("value") or 5) == 3)
                done.append({
                    "id": tid,
                    "place_id": (task.get("data") or {}).get("tag"),
                    "title": res.get("title"),
                    "profile_rating": (res.get("rating") or {}).get("value"),
                    "profile_reviews": res.get("reviews_count"),
                    "pulled": len(items),
                    "neg_1_2": n12, "weak_3": n3,
                    "truncated": n12 >= len(items) and len(items) > 0,
                })
            else:
                pending.append(tid)
        except Exception:
            pending.append(tid)
    return {"done": done, "pending": pending,
            "total_negatives": sum(d["neg_1_2"] for d in done),
            "total_weak": sum(d["weak_3"] for d in done)}
