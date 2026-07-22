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

# Domain -> recommended tactic for the SERP threat table. Review counts in
# the removal quote are GOOGLE Business reviews only; these third-party pages
# route to other tactics (Visions precedent: complaint boards / Reddit /
# Trustpilot pages can be removed at the PAGE level via Website Removal).
ROUTES = [
    (("yelp.", "glassdoor.", "indeed.", "bbb.",
      "facebook.", "instagram.", "x.com", "twitter.", "tiktok.",
      "linkedin."), "suppression"),
    (("trustpilot.", "complaintsboard.", "pissedconsumer.", "scampulse.",
      "ripoffreport.", "gripeo.", "reddit.", "quora."), "site removal"),
]

def route_tactic(domain, owned=False, forum=False, rating=None):
    if owned:
        return "owned \u2014 boost"
    # Sentiment gate: a third-party result showing a strong rating is an
    # asset working in the client's favor \u2014 suppressing it would bury
    # the brand's own good reviews. Leave it (and let it help push down
    # the actual negatives).
    if rating is not None and rating >= 4.0:
        return "positive \u2014 leave"
    d = (domain or "").lower()
    for prefixes, tactic in ROUTES:
        if any(p in d for p in prefixes):
            return tactic
    return "site removal" if forum else "suppression"


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
    organic, related, forums, pasf = [], [], [], []
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
                "tactic": route_tactic(_domain(it.get("domain")),
                                       bool(own) and own == _domain(it.get("domain")),
                                       rating=rat.get("value") or _rating_from_text(
                                           it.get("description"), it.get("title"))),
            })
        elif t in ("discussions_and_forums", "found_on_web"):
            for el in (it.get("items") or [])[:6]:
                dom = _domain(el.get("domain") or el.get("source"))
                forums.append({
                    "pos": it.get("rank_absolute"),
                    "domain": dom,
                    "title": el.get("title"),
                    "tactic": route_tactic(dom, forum=True),
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
        elif t == "people_also_search":
            pasf += [x for x in (it.get("items") or []) if isinstance(x, str)][:8]
    neg_related = [x for x in related
                   if any(m in x.lower() for m in NEG_MODIFIERS)]
    neg_pasf = [x for x in pasf if any(m in x.lower() for m in NEG_MODIFIERS)]
    ai_negative = [m for m in NEG_MODIFIERS if m in ai_text.lower()]
    owned_top10 = sum(1 for o in organic if o["owned"])
    return {"query": kw, "organic": organic[:10], "forums": forums,
            "ai_overview": ai_text, "ai_negative": ai_negative,
            "related": related, "negative_related": neg_related,
            "pasf": pasf, "negative_pasf": neg_pasf,
            "owned_in_top10": owned_top10}


def scan_autocomplete(brand):
    """Auto-suggest for the brand and '{brand} reviews' — negative flags.
    Uses client=gws-wiz (the actual Google search-box client; the DFS default
    returns a thinner set). Terms that come back empty get a fallback pass:
    trailing-space (next-word suggestions, matching Brendan's screenshots)
    then last-char-trimmed prefix. Extra calls only fire for empty terms."""
    kws = [brand.lower(), f"{brand} reviews".lower()]

    def _pull(keywords):
        payload = [{"keyword": k, "location_code": 2840, "language_code": "en",
                    "client": "gws-wiz"} for k in keywords]
        data = _post("/serp/google/autocomplete/live/advanced", payload,
                     timeout=30)
        res = {}
        for task in data.get("tasks") or []:
            kw = ((task.get("data") or {}).get("keyword") or "")
            sugg = []
            for block in task.get("result") or []:
                for it in (block or {}).get("items") or []:
                    if it.get("type") == "autocomplete" and it.get("suggestion"):
                        sugg.append(it["suggestion"])
            res[kw] = sugg
        return res

    out = {}
    try:
        first = _pull(kws)
        for k in kws:
            out[k] = {"suggestions": first.get(k, []) or first.get(k.strip(), [])}
        # fallback pass for empties: "kw " (next-word) then "kw"[:-1] (prefix)
        empties = [k for k in kws if not out[k]["suggestions"]]
        if empties:
            variants = {}
            for k in empties:
                variants[k + " "] = (k, "next-word")
                variants[k[:-1]] = (k, "prefix")
            fb = _pull(list(variants.keys()))
            for vkey, sugg in fb.items():
                orig, how = variants.get(vkey) or variants.get(vkey.strip(), (None, None))
                if orig and sugg and not out[orig]["suggestions"]:
                    # keep only suggestions still about the original term
                    keep = [x for x in sugg if orig.split()[0] in x.lower()]
                    if keep:
                        out[orig]["suggestions"] = keep
                        out[orig]["via"] = how
        for k in kws:
            out[k]["negative"] = [x for x in out[k]["suggestions"]
                                  if any(m in x.lower() for m in NEG_MODIFIERS)]
    except Exception as e:
        for k in kws:
            out.setdefault(k, {"error": str(e)})
    return out


# ---------------------------------------------------------------- locations
def scan_locations(brand, limit=200, domain=None):
    """Google Business location discovery via the Business Listings database
    (instant, no scrape). Tries the `title` search field, filter fallbacks,
    and — when the client website is known — a domain match, which finds the
    listing even when its name differs from the client name."""
    dom = (domain or "").lower().strip()
    dom = re.sub(r"^https?://", "", dom).split("/")[0].replace("www.", "")
    attempts = [
        {"title": brand, "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.title()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{brand.lower()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
    ]
    if dom:
        attempts += [
            {"filters": [["domain", "=", dom]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
            {"filters": [["url", "like", f"%{dom}%"]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
        ]
    last_err = None
    b_tokens = [w for w in brand.lower().split() if len(w) > 1]
    for payload in attempts:
        via_domain = payload.pop("_via_domain", False)
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
                # Title searches must contain the brand tokens; domain matches
                # skip that gate — a name mismatch is exactly what they solve.
                if not via_domain and not all(tok in title.lower() for tok in b_tokens):
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
                        "strategy": "domain" if via_domain
                                    else ("title" if "title" in payload else "filter")}
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
                vals = [((i.get("rating") or {}).get("value") or 5) for i in items]
                n1 = sum(1 for v in vals if v <= 1)
                n2 = sum(1 for v in vals if v == 2)
                n12 = n1 + n2
                n3 = sum(1 for v in vals if v == 3)
                done.append({
                    "id": tid,
                    "place_id": (task.get("data") or {}).get("tag"),
                    "title": res.get("title"),
                    "profile_rating": (res.get("rating") or {}).get("value"),
                    "profile_reviews": res.get("reviews_count"),
                    "pulled": len(items),
                    "neg_1": n1, "neg_2": n2, "neg_1_2": n12, "weak_3": n3,
                    "truncated": n12 >= len(items) and len(items) > 0,
                })
            else:
                pending.append(tid)
        except Exception:
            pending.append(tid)
    return {"done": done, "pending": pending,
            "total_negatives": sum(d["neg_1_2"] for d in done),
            "total_weak": sum(d["weak_3"] for d in done)}
