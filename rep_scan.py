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

import re

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


PROBE_MODIFIERS = ["lawsuit", "complaints", "scam", "fraud", "class action",
                   "settlement", "reviews", "legit"]

def scan_terms(brand):
    """Brand term universe via keywords_for_keywords (US national), PLUS an
    exact-match probe of the canonical negative/watch variants. KFK returns
    GROUPED volumes that merge close variants (the same quirk the SEO tool
    works around) — so '{brand} lawsuit' can vanish into the parent term and
    silently undercount negative volume. The probe re-pulls those terms from
    the Labs keyword database, which returns per-term exact volume."""
    b = brand.lower()
    payload = [{"keywords": [b], "location_code": 2840,
                "language_code": "en", "sort_by": "search_volume"}]
    data = _post("/keywords_data/google_ads/keywords_for_keywords/live",
                 payload, timeout=90)
    by_term = {}
    for it in (data["tasks"][0]["result"] or []):
        kw = (it.get("keyword") or "").lower()
        vol = it.get("search_volume") or 0
        cls = classify_term(kw, brand)
        if cls:
            by_term[kw] = {"term": kw, "volume": vol, "class": cls, "src": "kfk"}

    # exact-match probe: canonical variants + any flagged KFK terms
    probes = [f"{b} {m}" for m in PROBE_MODIFIERS]
    probes += [t for t, r in by_term.items() if r["class"] != "neutral"]
    probes = sorted(set(probes))
    try:
        pdata = _post("/dataforseo_labs/google/keyword_overview/live",
                      [{"keywords": probes, "location_code": 2840,
                        "language_code": "en"}], timeout=45)
        for block in (pdata["tasks"][0]["result"] or []):
            for it in (block.get("items") or []):
                kw = (it.get("keyword") or "").lower()
                vol = ((it.get("keyword_info") or {}).get("search_volume")) or 0
                cls = classify_term(kw, brand)
                if not cls:
                    continue
                # exact volume overrides the grouped KFK number
                by_term[kw] = {"term": kw, "volume": vol, "class": cls,
                               "src": "exact"}
    except Exception:
        pass                      # probe is enrichment — never fail the scan

    rows = sorted(by_term.values(), key=lambda r: -r["volume"])
    tot = {c: sum(r["volume"] for r in rows if r["class"] == c)
           for c in ("neutral", "watch", "negative")}
    return {"terms": rows[:120],
            "total_volume": sum(tot.values()),
            "negative_volume": tot["negative"],
            "watch_volume": tot["watch"]}


# --------------------------------------------------------------------- serp
def _domain(d):
    """Normalize a domain or full URL: strip scheme, path, query, port, www."""
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0]
    return d[4:] if d.startswith("www.") else d

def _rating_from_text(*texts):
    """Google rarely returns structured star snippets now — the rating usually
    lives in the description text ('average rating of 2.6 from 90 reviews',
    '1.4 / 5', 'Rated 3.1 out of 5'). Regex it out; None if absent."""
    pat = re.compile(
        r"(?:rated\s+|rating(?:\s+of)?[:\s]+|average rating of\s+)?"
        r"([0-5]\.\d)\s*(?:/\s*5|out of 5|stars?|\u2605|from\s+[\d,]+\s+reviews)",
        re.I)
    for t in texts:
        if not t:
            continue
        m = pat.search(t)
        if m:
            try:
                v = float(m.group(1))
                if 0 < v <= 5:
                    return v
            except ValueError:
                pass
    return None


def scan_serp(brand, domain=""):
    """Top-10 for '{brand} reviews': organic results (with ratings parsed from
    snippet text when Google omits star markup), the Reddit/forums block, the
    AI Overview, related searches — owned tagging against the client domain."""
    kw = f"{brand} reviews".lower()
    payload = [{"keyword": kw, "location_code": 2840,
                "language_code": "en", "depth": 10}]
    data = _post("/serp/google/organic/live/advanced", payload, timeout=45)
    own = _domain(domain)
    organic, related, forums = [], [], []
    ai_text = ""
    for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
        t = it.get("type")
        if t == "organic":
            rat = (it.get("rating") or {})
            organic.append({
                "pos": it.get("rank_absolute"),
                "title": it.get("title"),
                "domain": _domain(it.get("domain")),
                "snippet": (it.get("description") or "")[:200],
                "rating": rat.get("value") or _rating_from_text(
                    it.get("description"), it.get("title")),
                "votes": rat.get("votes_count"),
                "owned": bool(own) and own == _domain(it.get("domain")),
            })
        elif t in ("discussions_and_forums", "found_on_web"):
            for el in (it.get("items") or [])[:6]:
                forums.append({
                    "pos": it.get("rank_absolute"),
                    "domain": _domain(el.get("domain") or el.get("source")),
                    "title": el.get("title"),
                })
        elif t == "ai_overview":
            parts = []
            for el in (it.get("items") or []):
                for k in ("text", "title", "snippet"):
                    if el.get(k):
                        parts.append(el[k])
            if it.get("markdown"):
                parts.append(it["markdown"])
            ai_text = " ".join(parts)[:1200]
        elif t == "related_searches":
            related = [x for x in (it.get("items") or []) if x][:10]
    neg_related = [x for x in related
                   if any(m in x.lower() for m in NEG_MODIFIERS)]
    ai_negative = [m for m in NEG_MODIFIERS if m in ai_text.lower()]
    owned_top10 = sum(1 for o in organic if o["owned"])
    return {"query": kw, "organic": organic[:10], "forums": forums,
            "ai_overview": ai_text, "ai_negative": ai_negative,
            "related": related, "negative_related": neg_related,
            "owned_in_top10": owned_top10}


def scan_autocomplete(brand):
    """Auto-suggest for the brand and '{brand} reviews' — negative flags.
    Both keywords go in ONE DFS request (two tasks) to halve latency; this
    lives on its own endpoint so a slow autocomplete can't drag the SERP
    call past Render's ~100s proxy timeout."""
    kws = [brand.lower(), f"{brand} reviews".lower()]
    payload = [{"keyword": k, "location_code": 2840, "language_code": "en"}
               for k in kws]
    out = {}
    try:
        data = _post("/serp/google/autocomplete/live/advanced", payload,
                     timeout=30)
        for task in data.get("tasks") or []:
            kw = ((task.get("data") or {}).get("keyword") or "").lower()
            sugg = []
            for res in task.get("result") or []:
                for it in (res or {}).get("items") or []:
                    if it.get("type") == "autocomplete" and it.get("suggestion"):
                        sugg.append(it["suggestion"])
            out[kw] = {"suggestions": sugg,
                       "negative": [x for x in sugg
                                    if any(m in x.lower() for m in NEG_MODIFIERS)]}
    except Exception as e:
        for k in kws:
            out.setdefault(k, {"error": str(e)})
    return out


# ---------------------------------------------------------------- locations
def scan_locations(brand, limit=200):
    """Google Business location discovery via the Business Listings database
    (instant, no scrape). Uses the dedicated `title` search field, with a
    filter-based fallback; surfaces the DFS error instead of returning an
    empty list when the call itself failed."""
    attempts = [
        {"title": brand, "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.title()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.lower()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
    ]
    last_err = None
    b_tokens = [w for w in brand.lower().split() if len(w) > 1]
    for payload in attempts:
        try:
            data = _post("/business_data/business_listings/search/live",
                         [payload], timeout=90)
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") != 20000:
                last_err = task.get("status_message") or "unknown DFS error"
                continue
            items = ((task.get("result") or [{}])[0] or {}).get("items") or []
            locs = []
            for it in items:
                title = (it.get("title") or "")
                # keep only rows whose title actually contains the brand tokens
                if not all(tok in title.lower() for tok in b_tokens):
                    continue
                rat = it.get("rating") or {}
                locs.append({
                    "title": title,
                    "address": it.get("address"),
                    "place_id": it.get("place_id"),
                    "cid": it.get("cid"),
                    "rating": rat.get("value"),
                    "reviews": rat.get("votes_count") or 0,
                })
            if locs:
                return {"locations": locs,
                        "total_reviews": sum(l["reviews"] for l in locs),
                        "strategy": "title" if "title" in payload else "filter"}
        except Exception as e:
            last_err = str(e)
    if last_err:
        return {"locations": [], "total_reviews": 0,
                "error_detail": f"Listings lookup failed: {last_err}"}
    return {"locations": [], "total_reviews": 0}


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
