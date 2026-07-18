#!/usr/bin/env python3
"""
SSG / adtini — SEO Quote Tool (Render-ready Flask app)

Partner fills the product form -> backend runs the keyword pull, rank check,
and pricing formula against DataForSEO -> quote renders on screen with the full
staged breakdown for a human to review before sending.

ENV (set in Render dashboard -> Environment):
    DFS_LOGIN      DataForSEO account email
    DFS_PASSWORD   DataForSEO API password (from dashboard, not portal login)

Local run:
    pip install -r requirements.txt
    DFS_LOGIN=... DFS_PASSWORD=... python app.py
    -> http://localhost:5000
"""
import os, json, base64, statistics, time
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Flask, render_template, request, jsonify
import storage

app = Flask(__name__)
BASE = "https://api.dataforseo.com/v3"

# ---------------------------------------------------------------------------
# CONFIG — every tunable constant. Brendan-calibration items live here only.
# Spring ladder ($1,450–$4,250 by geo scope), per decision.
# ---------------------------------------------------------------------------
CFG = {
    # Geo dropdown (5 options) -> 4 price anchors.
    # Non-contiguous shares the $2,950 (multi-region) anchor with statewide.
    # HARD COST anchors = CEIL50(0.65 × former client anchor). All internal
    # calculations start from hard cost; client price = hard × (1 + markup).
    # HARD COST anchors = CEIL50(client anchor / 1.35). Client anchors blended
    # from the spring ladder uplifted toward the June ~$3,950 pricing. No floor —
    # the raised bases carry the new pricing level directly.
    "geo_anchor": {
        "single_city":          1650,
        "contiguous_region":    2350,
        "non_contiguous_region":2600,
        "statewide":            2600,
        "nationwide":           3150,
    },
    "competitive_adder": {0: 0, 1: 150, 2: 300},   # FLAT fallback (used when no bid data)
    "bid_score_breaks": [5.0, 15.0],          # <5->0, 5-15->1, >=15->2 (for the fallback)
    # --- CPC-scaled competitive adder ---
    # The competitive adder scales with the median top-of-page bid (CPC), because
    # CPC is the market's own measure of how valuable a click is: high-CPC verticals
    # (e.g. insurance ~$150) mean ranking organically replaces huge ad spend, so the
    # SEO is worth more. adder = median_cpc × cpc_adder_mult, rounded to $50, capped.
    # When there's NO bid data, fall back to the flat score buckets above.
    "cpc_adder_enabled": True,
    "cpc_adder_mult": 3.0,                     # $ of hard-cost adder per $1 of median CPC
    "cpc_adder_cap": 1500,                     # max adder (hard cost) so a freak CPC can't explode price
    "cpc_adder_free_below": 5.0,               # CPC at/below this adds nothing (normal-value clicks)
    "zero_ranking_bonus": 400,                # (legacy flat; superseded by tiers below)
    "default_markup_pct": 35,                 # client = hard × 1.35 ≈ original client price
    "zero_ranking_top_n": 20,
    "zero_ranking_frac": 0.10,
    # --- Brendan #5: TIERED zero-ranking. % of head terms NOT ranking in top-N
    # maps to a % uplift on the hard base. Each tier: [min_pct_not_ranking, uplift_pct].
    # Evaluated high-to-low; first threshold met wins. Replaces the flat bonus.
    # Calibrated against Serene Health (84% not ranking -> +14%, which with the
    # volume uplift reproduces the real $3,950/$5,450/$6,950 proposal).
    "zero_ranking_tiers": [
        [80, 14],   # 80%+ not ranking -> +14%
        [65, 9],    # 65-80% -> +9%
        [50, 5],    # 50-65% -> +5%
    ],
    # --- VOLUME-based pricing (fixed $ per additional search, declining marginal
    # rate, like tax brackets). Base price assumes a "normalized" volume up to
    # vol_free_below. Above that, each bracket adds $/search for volume WITHIN that
    # bracket; brackets stack. Each: [lo, hi, dollars_per_search]. Open-ended top
    # bracket uses hi = null. Added to the hard base. Admin-editable.
    # NOTE: rates are the lever to calibrate. Brendan's example used $0.50/search,
    # but that produces very large adds (a 15k client would gain ~$2,600 on the hard
    # base, roughly doubling the quote). These starting rates (~$0.05-0.08) keep a
    # normal-volume client near its real proposal while still escalating hard for
    # 100k+ clients. Tune live; no high-volume proposals exist to fit against.
    "vol_free_below": 10000,            # normalized: base already covers this
    "volume_brackets": [
        [10000, 20000, 0.08],
        [20000, 35000, 0.05],
        [35000, 50000, 0.04],
        [50000, None,  0.03],           # open-ended top bracket so it keeps escalating
    ],
    "step_ratio": 0.38,                       # June proposals: 38% step
    "client_floor": 0,                        # no floor — raised anchors carry pricing
    "addon_market_ratio": 0.42,
    "ultra_bucket_size": 3,
    "competitive_bucket_size": 6,
    "list_cap": 20,
    "rank_check_workers": 8,   # parallel SERP calls — avoids timeout on free Render
    # Long-tail sourcing
    "use_suggestions": True,           # pull keyword_suggestions for longer phrases
    "use_site_keywords": True,         # pull keywords_for_site from the client domain (Labs)
    "site_keywords_limit": 200,        # cap rows returned from keywords_for_site
    "longtail_min_words": 4,           # >= this many words qualifies as long-tail
    "longtail_prefixes": ["how","what","why","when","where","which","who","best",
                          "affordable","cheap","near","cost","top","is","can","do"],
    "longtail_target": 10,             # how many long-tails to keep in the list
    "rank_check_cap": 60,              # max keywords sent to the SERP rank check
    # --- GRID MODE (matches Brendan's proposals) -----------------------------
    # His keyword tables are a systematic SERVICE x CITY grid, with the tier
    # assigned to the SERVICE (every city inherits it): e.g. "auto insurance" is
    # Ultra-Competitive in all ten cities, "umbrella insurance" is Long Tail in
    # all ten. He does NOT use question-style long-tails (2 instances across 18
    # proposals), so the long-tail tier is just lower-competition services.
    "grid_mode": True,
    "grid_max_services": 4,            # services expanded from the seeds
    "grid_max_cities": 10,             # cities crossed against each service
    "grid_state_suffix": True,         # "auto insurance fairfax va" vs "... fairfax"
}

def r50(x):
    return int(round(x / 50.0) * 50)

def dfs_post(path, payload, timeout=120):
    login = os.environ.get("DFS_LOGIN", "")
    pw    = os.environ.get("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    resp = requests.post(BASE + path,
                         headers={"Authorization": f"Basic {token}",
                                  "Content-Type": "application/json"},
                         data=json.dumps(payload), timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def loc_string(markets, state):
    if markets and state:
        return f"{markets[0]},{state},United States"
    if markets:                       # city without state — still localizes
        return f"{markets[0]},United States"
    if state:
        return f"{state},United States"
    return "United States"

# City -> state auto-derivation. Covers major US metros + the cities in the
# sample proposals. Unknown cities fall back to "City,United States", which
# DataForSEO usually resolves to the largest match.
CITY_STATE = {
    "san diego":"California","chula vista":"California","el cajon":"California",
    "oceanside":"California","escondido":"California","bonita":"California","alpine":"California",
    "los angeles":"California","san francisco":"California","sacramento":"California",
    "san jose":"California","fresno":"California","long beach":"California","irvine":"California",
    "knoxville":"Tennessee","nashville":"Tennessee","memphis":"Tennessee",
    "farragut":"Tennessee","alcoa":"Tennessee","maryville":"Tennessee","louisville":"Tennessee",
    "hampton roads":"Virginia","norfolk":"Virginia","virginia beach":"Virginia",
    "chesapeake":"Virginia","newport news":"Virginia","hampton":"Virginia","richmond":"Virginia",
    "wichita":"Kansas","kansas city":"Missouri","topeka":"Kansas",
    "altoona":"Pennsylvania","state college":"Pennsylvania","hanover":"Pennsylvania",
    "harrisburg":"Pennsylvania","lancaster":"Pennsylvania","york":"Pennsylvania",
    "philadelphia":"Pennsylvania","pittsburgh":"Pennsylvania","bedford":"Pennsylvania",
    "lava hot springs":"Idaho","pocatello":"Idaho","boise":"Idaho","idaho falls":"Idaho",
    "anchorage":"Alaska","fairbanks":"Alaska","juneau":"Alaska",
    "new york":"New York","brooklyn":"New York","buffalo":"New York","albany":"New York",
    "chicago":"Illinois","houston":"Texas","dallas":"Texas","austin":"Texas",
    "san antonio":"Texas","phoenix":"Arizona","tucson":"Arizona","denver":"Colorado",
    "seattle":"Washington","portland":"Oregon","miami":"Florida","orlando":"Florida",
    "tampa":"Florida","atlanta":"Georgia","boston":"Massachusetts","detroit":"Michigan",
    "minneapolis":"Minnesota","charlotte":"North Carolina","raleigh":"North Carolina",
    "las vegas":"Nevada","salt lake city":"Utah","columbus":"Ohio","cleveland":"Ohio",
    "cincinnati":"Ohio","indianapolis":"Indiana","milwaukee":"Wisconsin","st louis":"Missouri",
}
def derive_state(markets, provided_state=""):
    """Return a state: use the partner's value if given, else look up the first
    market. Empty if unknown (loc_string then falls back to city,United States)."""
    if provided_state and provided_state.strip():
        return provided_state.strip()
    for mkt in markets:
        s = CITY_STATE.get(mkt.strip().lower())
        if s:
            return s
    return ""

def is_longtail(kw):
    """A keyword qualifies as long-tail if it's long or question/intent-shaped."""
    words = kw.split()
    if len(words) >= CFG["longtail_min_words"]:
        return True
    if words and words[0].lower() in CFG["longtail_prefixes"]:
        return True
    return False

def fetch_suggestions(seeds, markets, state):
    """keyword_suggestions returns queries CONTAINING the seed — structurally
    longer than keyword_ideas. Calls run in parallel; failures are non-fatal."""
    out = []
    if not CFG["use_suggestions"]:
        return out
    loc = loc_string(markets, state)

    def one(s):
        try:
            payload = [{"keyword": s, "location_name": loc,
                        "language_code": "en", "limit": 150}]
            data = dfs_post("/keywords_data/google_ads/keyword_suggestions/live", payload)
            res = (data["tasks"][0]["result"] or [])
            rows = []
            for block in res:
                for it in (block.get("items") or []):
                    kw = it.get("keyword")
                    if kw:
                        ki = it.get("keyword_info") or {}
                        rows.append({"keyword": kw, "volume": ki.get("search_volume") or 0})
            return rows
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=min(len(seeds), CFG["rank_check_workers"]) or 1) as ex:
        for rows in ex.map(one, seeds[:6]):
            out.extend(rows)
    return out

def fetch_keywords_for_site(domain, markets, state):
    """Labs 'Keywords For Site' — keywords relevant to the client's domain,
    derived from the site's content/category. Supplements partner seeds for
    established sites; returns little (harmlessly) for brand-new/zero-ranking
    sites, which is why it's additive, not a replacement. One call. Non-fatal."""
    if not CFG["use_site_keywords"] or not domain:
        return []
    dom = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    if not dom:
        return []
    try:
        # Labs endpoint: use numeric location_code (2840 = US), not location_name.
        payload = [{"target": dom, "location_code": 2840,
                    "language_code": "en", "limit": CFG["site_keywords_limit"]}]
        data = dfs_post("/dataforseo_labs/google/keywords_for_site/live", payload)
        res = (data["tasks"][0]["result"] or [])
        rows = []
        for block in res:
            for it in (block.get("items") or []):
                kw = it.get("keyword")
                if kw:
                    ki = it.get("keyword_info") or {}
                    rows.append({"keyword": kw, "volume": ki.get("search_volume") or 0})
        return rows
    except Exception:
        return []

def fetch_site_pages(domain, limit=30):
    """Pull the client's page structure as readable topics — the names of the
    pages they've built, which map directly to their service taxonomy and are
    strong SEO keyword fuel. Tries sitemap.xml first (fast, standard); falls back
    to the DataForSEO On-Page API if there's no usable sitemap. Returns a list of
    short topic strings. Non-fatal: [] on any failure."""
    if not domain:
        return []
    dom = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    if not dom:
        return []

    def slug_to_topic(url):
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else ""
        path = path.strip("/").split("?")[0].split("#")[0]
        if not path:
            return ""
        seg = [s for s in path.split("/") if s and not s.endswith((".xml", ".jpg", ".png", ".pdf", ".css", ".js"))]
        if not seg:
            return ""
        topic = seg[-1].replace("-", " ").replace("_", " ").replace(".html", "").strip()
        if len(topic) < 3 or topic.isdigit():
            return ""
        if topic.lower() in {"index", "home", "page", "blog", "category", "tag"}:
            return ""
        return topic

    pages, seen = [], set()
    import re
    deadline = time.time() + 5          # hard cap: sitemap work gets <= 5s total
    for sm in (f"https://{dom}/sitemap.xml", f"https://{dom}/sitemap_index.xml"):
        if time.time() > deadline:
            break
        try:
            r = requests.get(sm, timeout=5, headers={"User-Agent": "Mozilla/5.0 (SEO-quote-tool)"})
            if r.status_code != 200 or "<" not in r.text:
                continue
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, re.I)
            if locs and all(l.lower().endswith(".xml") for l in locs[:3]):
                child_locs = []
                for child in locs[:2]:          # at most 2 child sitemaps
                    if time.time() > deadline:
                        break
                    try:
                        cr = requests.get(child, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
                        child_locs += re.findall(r"<loc>\s*(.*?)\s*</loc>", cr.text, re.I)
                    except Exception:
                        pass
                locs = child_locs or locs
            for url in locs:
                t = slug_to_topic(url)
                if t and t.lower() not in seen:
                    seen.add(t.lower()); pages.append(t)
                if len(pages) >= limit:
                    break
            if pages:
                return pages[:limit]
        except Exception:
            continue

    # On-Page fallback only if we have time budget left
    if time.time() > deadline:
        return pages[:limit]
    try:
        payload = [{"url": f"https://{dom}", "max_crawl_pages": limit}]
        data = dfs_post("/on_page/instant_pages", payload)
        res = (data["tasks"][0]["result"] or [])
        for block in res:
            for it in (block.get("items") or []):
                t = slug_to_topic(it.get("url") or "")
                if t and t.lower() not in seen:
                    seen.add(t.lower()); pages.append(t)
        return pages[:limit]
    except Exception:
        return pages[:limit]


def fetch_local_volume(terms, markets, state):
    """Search volume for bare service terms AT THE CLIENT'S MARKET (not national).
    Uses the Google Ads endpoint because it accepts a location_name string, so we
    can scope to the actual city/state. National volume would be wildly larger
    than a local client's real addressable demand. Returns {term_lower: volume}."""
    if not terms:
        return {}
    try:
        payload = [{"keywords": [t.lower() for t in terms],
                    "location_name": loc_string(markets, state),
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        task0 = (data.get("tasks") or [{}])[0]
        items = task0.get("result") or []
        return {(it.get("keyword") or "").lower(): (it.get("search_volume") or 0)
                for it in items}
    except Exception:
        return {}


def fetch_exact_volume(keywords, markets, state):
    """Exact-match search volume. The Google Ads keywords_for_keywords endpoint
    we use to GENERATE terms returns GROUPED (broad) volumes that merge similar
    terms — which is why the numbers looked inflated/off. For the FINAL list we
    re-pull volume from the Labs keyword database, which returns per-term exact
    volume. Returns {keyword_lower: volume}. Non-fatal: {} on any failure."""
    if not keywords:
        return {}
    out = {}
    # Labs endpoint takes numeric location_code; use the city if known, else US.
    loc_code = 2840
    try:
        # batch up to 1000 per call
        for i in range(0, len(keywords), 1000):
            chunk = keywords[i:i+1000]
            payload = [{"keywords": [k.lower() for k in chunk],
                        "location_code": loc_code, "language_code": "en"}]
            data = dfs_post("/dataforseo_labs/google/keyword_overview/live", payload)
            res = (data["tasks"][0]["result"] or [])
            for block in res:
                for it in (block.get("items") or []):
                    kw = (it.get("keyword") or "").lower()
                    ki = it.get("keyword_info") or {}
                    if kw:
                        out[kw] = ki.get("search_volume") or 0
        return out
    except Exception:
        return {}

def infer_business(domain, seeds, site_terms):
    """Infer a short description of what the client's business does (and doesn't),
    from its domain + site keywords, so Claude can exclude off-target terms
    (e.g. 'medication' for a therapy practice that doesn't prescribe). Returns a
    short string, or '' if unavailable. Uses Claude; non-fatal."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not (domain or site_terms):
        return ""
    site_list = [s["keyword"] for s in site_terms][:40]
    prompt = f"""Based on this client's website and the keywords their site ranks for, write ONE sentence describing what the business does and, importantly, what related services it does NOT offer (for SEO targeting).

WEBSITE: {domain or "(none)"}
SERVICES/VERTICAL: {", ".join(seeds)}
KEYWORDS FROM THEIR SITE: {json.dumps(site_list, ensure_ascii=False)}

Example output: "A therapy and counseling practice providing talk therapy for mental health conditions; does NOT prescribe medication or offer psychiatric drug treatment."

Return ONLY the one-sentence description, no preamble."""
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 200, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=20)
        resp.raise_for_status()
        body = resp.json()
        return "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
    except Exception:
        return ""

STATE_ABBREV = {
    "alabama":"al","alaska":"ak","arizona":"az","arkansas":"ar","california":"ca",
    "colorado":"co","connecticut":"ct","delaware":"de","florida":"fl","georgia":"ga",
    "hawaii":"hi","idaho":"id","illinois":"il","indiana":"in","iowa":"ia","kansas":"ks",
    "kentucky":"ky","louisiana":"la","maine":"me","maryland":"md","massachusetts":"ma",
    "michigan":"mi","minnesota":"mn","mississippi":"ms","missouri":"mo","montana":"mt",
    "nebraska":"ne","nevada":"nv","new hampshire":"nh","new jersey":"nj","new mexico":"nm",
    "new york":"ny","north carolina":"nc","north dakota":"nd","ohio":"oh","oklahoma":"ok",
    "oregon":"or","pennsylvania":"pa","rhode island":"ri","south carolina":"sc",
    "south dakota":"sd","tennessee":"tn","texas":"tx","utah":"ut","vermont":"vt",
    "virginia":"va","washington":"wa","west virginia":"wv","wisconsin":"wi","wyoming":"wy",
}

def claude_expand_services(seeds, business_desc, site_pages, brand, domain,
                           candidates, max_services):
    """Expand the partner's seed terms into the SERVICE list a proposal would
    target, assigning a competitiveness TIER to each service (not to each
    keyword). This mirrors how the real proposals are built: 'auto insurance' is
    Ultra-Competitive in every city, 'umbrella insurance' is Long Tail in every
    city. Returns [{"service":..., "tier": "ultra"|"competitive"|"long_tail"}]
    or None on failure (caller falls back to the seeds themselves)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    pages = [p for p in (site_pages or [])][:40]
    cands = [c.get("keyword", c) if isinstance(c, dict) else c for c in (candidates or [])][:80]
    prompt = f"""You are an SEO strategist choosing which SERVICES a local business should target in a proposal.

BUSINESS: {business_desc or "(infer from the vertical, website and pages below)"}
SEED TERMS FROM THE PARTNER: {", ".join(seeds)}
WEBSITE: {domain or "(none)"}
BRAND (never include this in a service): {brand or "(none)"}

THEIR ACTUAL WEBSITE PAGES (their real service taxonomy):
{json.dumps(pages, ensure_ascii=False) if pages else "(none available)"}

KEYWORDS THE SEARCH API RETURNED FOR THIS BUSINESS (evidence of real demand):
{json.dumps(cands, ensure_ascii=False)}

TASK: choose exactly {max_services} SERVICES this business should target, and assign each a competitiveness tier.

RULES:
1. A SERVICE is a short, generic service phrase with NO city and NO brand — e.g. "auto insurance", "home insurance", "insurance agency", "umbrella insurance". It will be crossed with city names later, so do NOT include any location.
2. Only services this business actually offers. Exclude anything they don't do.
3. Spread across tiers so the proposal has all three. Aim for roughly:
   - 2 "ultra"        (the biggest, most competitive money terms)
   - 1 "competitive"  (solid mid-competition terms)
   - 1 "long_tail"    (a genuine but lower-competition service, e.g. a niche product line)
   Adjust the mix if {max_services} differs, but always include at least one long_tail and at least one ultra.
4. long_tail means a LOWER-COMPETITION SERVICE — never a question. Do NOT produce phrases starting with how/what/why/when/where.
5. Prefer the phrasing a customer would actually search.
6. TIER GUIDANCE — how these tiers are actually assigned in practice (insurance example):
   - ultra: the core high-demand money terms — "auto insurance", "car insurance", "home insurance", "insurance quotes"
   - competitive: solid mid-demand services — "homeowners insurance", "renters insurance", "insurance agency", "insurance company"
   - long_tail: niche or compound product lines with genuinely lower demand — "umbrella insurance", "home and auto insurance"
   Note that a mainstream service like "renters insurance" is COMPETITIVE, not long tail. Reserve long_tail for genuinely niche lines.

Return ONLY valid JSON, no prose:
{{"services": [{{"service": "auto insurance", "tier": "ultra"}}, {{"service": "umbrella insurance", "tier": "long_tail"}}]}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({
                "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 1000, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=30)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        out = []
        for s in parsed.get("services", []):
            svc = (s.get("service") or "").strip().lower()
            tier = (s.get("tier") or "competitive").strip().lower()
            if tier not in ("ultra", "competitive", "long_tail"):
                tier = "competitive"
            if svc:
                out.append({"service": svc, "tier": tier})
        return out[:max_services] or None
    except Exception:
        return None


def pick_grid_cities(markets, state, limit):
    """Choose WHICH cities go in the grid when more are supplied than the cap.
    Taking the first N by input order picks alphabetically-early villages over
    real metros (e.g. 'Augusta Springs' before 'Fairfax'). Instead, rank the
    supplied cities by how much search demand they actually carry, using a
    generic '<city>' population-proxy query, and keep the biggest.
    Falls back to input order if the lookup fails."""
    cities = [m.strip() for m in markets if m.strip()]
    # drop a market that is actually the state name — it isn't a city
    if state:
        cities = [c for c in cities if c.lower() != state.strip().lower()]
    if len(cities) <= limit:
        return cities
    try:
        probe = [f"insurance {c.lower()}" for c in cities][:700]
        payload = [{"keywords": probe,
                    "location_name": loc_string(cities, state),
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        items = (data.get("tasks") or [{}])[0].get("result") or []
        vol = {(it.get("keyword") or "").lower(): (it.get("search_volume") or 0)
               for it in items}
        ranked = sorted(cities,
                        key=lambda c: vol.get(f"insurance {c.lower()}", 0),
                        reverse=True)
        return ranked[:limit]
    except Exception:
        return cities[:limit]


def build_grid(services, markets, state):
    """Cross each SERVICE with each CITY, in the proposal format
    ('auto insurance fairfax va'). The tier comes from the service, so every
    city inherits it. Returns {ultra:[], competitive:[], long_tail:[]}."""
    cities = pick_grid_cities(markets, state, CFG["grid_max_cities"])
    suffix = ""
    if CFG.get("grid_state_suffix") and state:
        suffix = " " + STATE_ABBREV.get(state.strip().lower(), "")
        suffix = suffix.rstrip()
    buckets = {"ultra": [], "competitive": [], "long_tail": []}
    for s in services:
        svc, tier = s["service"], s["tier"]
        if not cities:                     # nationwide: no crossing
            buckets[tier].append({"keyword": svc, "volume": 0,
                                  "src": "grid", "origin": "added", "service": svc})
            continue
        for city in cities:
            c = city.strip().lower()
            # don't double-append the state if the "city" IS the state
            sfx = "" if (state and c == state.strip().lower()) else suffix
            buckets[tier].append({"keyword": f"{svc} {c}{sfx}".strip(),
                                  "volume": 0, "src": "grid",
                                  "origin": "added", "service": svc})
    return buckets


    """Claude pass over the API-generated candidates: removes junk/garbled/off-topic
    terms (using the business description to exclude irrelevant services), folds in
    site-related opportunities, buckets by difficulty, and tags each term's origin
    ('kept' from the candidates, or 'added' by Claude) so the UI can show what AI did.
    Non-fatal: returns None on no key / failure, so the caller falls back to rules."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    cand_terms = [c["keyword"] for c in candidates][:120]
    site_list  = [s["keyword"] for s in site_terms][:40]
    pages_list = [p for p in (site_pages or [])][:60]
    cand_lower = {c.lower() for c in cand_terms}
    mkt = ", ".join(markets) if markets else "national (no specific city)"
    biz = business_desc or "(NOT PROVIDED — infer it yourself from the vertical, website, pages, and site keywords below, and return it in the 'business' field)"
    pages_block = (json.dumps(pages_list, ensure_ascii=False) if pages_list
                   else "(no page structure available)")
    prompt = f"""You are an SEO strategist refining a keyword list for a client proposal. Be strict about relevance to THIS specific business.

WHAT THE BUSINESS DOES (and does not do): {biz}
CLIENT VERTICAL / SERVICES: {", ".join(seeds)}
TARGET MARKET(S): {mkt}
CLIENT BRAND (exclude any keyword containing this): {brand or "(none given)"}
CLIENT WEBSITE: {domain or "(none given)"}

THE CLIENT'S ACTUAL WEBSITE PAGES (their real service taxonomy — each page is a topic they offer and should rank for):
{pages_block}

CANDIDATE KEYWORDS (from a keyword API — contain junk, garbled terms, near-duplicates, and OFF-TARGET terms for services this business does not offer):
{json.dumps(cand_terms, ensure_ascii=False)}

KEYWORDS THE SITE ALREADY RANKS FOR:
{json.dumps(site_list, ensure_ascii=False)}

RULES:
1. EXCLUDE terms for services the business does NOT offer. (Example: a therapy practice that does not prescribe drugs should NOT have "medication", "prescription", or "over the counter" keywords.)
2. EXCLUDE garbled/nonsensical terms ("adhd and therapy", "add therapy" when the vertical is "adhd treatment"), near-duplicates, and brand terms.
3. KEEP real searches a prospective customer of THIS business would type.
4. USE THE WEBSITE PAGES as your primary guide to what this business actually offers. For each real service page, ensure there is a strong head keyword targeting it (geo-modified where local). ADD any the candidate list missed — these are high-priority SEO opportunities.
5. ADD other high-value keywords this business should target, consistent with their pages and services.
6. Keep the city modifier on local-intent terms where the market is local.
7. Bucket by ranking difficulty: "ultra" (hardest/highest value), "competitive" (moderate), "long_tail" (longer/question-style).
8. Do NOT invent search volumes. Only real, searchable terms.

Return ONLY valid JSON in exactly this shape. Each keyword item is [keyword, origin] where origin is "kept" or "added". The "business" field is your one-sentence read of what the business does and does not offer:
{{"business": "one sentence", "ultra": [["keyword","kept"], ...], "competitive": [["keyword","added"], ...], "long_tail": [["keyword","kept"], ...]}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({
                "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 2500,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }), timeout=30)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        def rows(key):
            out = []
            for item in parsed.get(key, []):
                if isinstance(item, list) and item:
                    kw = str(item[0]).strip()
                    origin = item[1] if len(item) > 1 else "kept"
                elif isinstance(item, str):
                    kw = item.strip(); origin = "kept"
                else:
                    continue
                if not kw:
                    continue
                # trust the model's tag but sanity-check against the candidate set
                if origin not in ("kept", "added"):
                    origin = "added" if kw.lower() not in cand_lower else "kept"
                out.append({"keyword": kw, "volume": 0, "src": "claude", "origin": origin})
            return out
        return {"ultra": rows("ultra"), "competitive": rows("competitive"),
                "long_tail": rows("long_tail"),
                "business": (parsed.get("business") or "").strip()}
    except Exception:
        return None



# ---------------------------------------------------------------------------
# STAGE 1 — keyword list
# ---------------------------------------------------------------------------
def stage1_keyword_list(seeds, markets, state, brand, domain="", business_desc=""):
    crossed = []
    for s in seeds:
        crossed.append(s)
        for m in markets:
            crossed.append(f"{s} {m}")
        if state:
            crossed.append(f"{s} {state}")

    payload = [{"keywords": crossed[:200],
                "location_name": loc_string(markets, state),
                "language_code": "en"}]
    data = dfs_post("/keywords_data/google_ads/keywords_for_keywords/live", payload)
    items = (data["tasks"][0]["result"] or [])
    raw = [{"keyword": it["keyword"], "volume": it.get("search_volume") or 0, "src": "ideas"}
           for it in items]

    # Add keyword_suggestions (longer, seed-containing phrases) into the pool
    for r in fetch_suggestions(seeds, markets, state):
        r["src"] = "suggest"; raw.append(r)
    # Add keywords_for_site (terms relevant to the client's domain) into the pool
    for r in fetch_keywords_for_site(domain, markets, state):
        r["src"] = "site"; raw.append(r)

    seed_tokens = {t.lower() for s in seeds for t in s.split()}
    brand_l = (brand or "").lower()
    # Connector words that signal a stitched-together / garbled phrase rather
    # than a real search query ("adhd and therapy", "treatment or counseling").
    CONNECTORS = {"and", "or", "&", "vs", "with"}
    def is_junk(kw):
        toks = kw.split()
        for i, t in enumerate(toks):
            if 0 < i < len(toks) - 1 and t in CONNECTORS:
                return True
        return False
    kept = []
    seen = set()
    for r in raw:
        kw = r["keyword"].lower()
        if kw in seen:
            continue
        seen.add(kw)
        if brand_l and brand_l in kw:
            continue
        if is_junk(kw):
            continue
        # Seed-token relevance filter applies to seed-derived sources only.
        # Site keywords come from the client's own domain and are on-topic by
        # construction, so they bypass it (but still drop the brand name above).
        if r.get("src") != "site" and seed_tokens and not (seed_tokens & set(kw.split())):
            continue
        kept.append(r)

    kept.sort(key=lambda r: r["volume"], reverse=True)
    with_vol = [r for r in kept if r["volume"] > 0]

    u, c = CFG["ultra_bucket_size"], CFG["competitive_bucket_size"]
    n_head = u + c

    if markets:
        # GEO-SCOPED: head terms are seed × market combinations ("adhd treatment
        # san diego") — the form the proposals actually use. We build these
        # directly from the crossing rather than relying on the API to return
        # them (it strips geo and inflates bare national terms). Volume is looked
        # up where available but NOT required, since local terms often report low
        # or zero volume in keyword tools yet are exactly what we rank/quote on.
        vol_lookup = {r["keyword"].lower(): r["volume"] for r in kept}
        geo_heads, seen_h = [], set()
        # (a) direct seed × market crossings
        seed_phrases = list(seeds)
        # (b) plus the API's related head terms, geo-modified — this is what gives
        # the proposal its variety ("adhd therapy san diego", "couples therapy
        # san diego") beyond the literal seeds. Drawn from the FULL candidate pool
        # (not volume-filtered) so sparse/niche verticals — where local terms
        # report little or no volume — still build a full list instead of
        # collapsing to the bare seeds. (This is the Versability case.)
        # Related expansion terms must share a SUBSTANTIVE seed token (length >= 4)
        # with the seeds. This drops loose API associations and garbled near-words
        # like "add therapy" (the seed was "adhd treatment" — "add" is only 3 chars
        # and isn't a seed word) while keeping real expansions ("adhd therapy").
        seed_long_tokens = {t.lower() for s in seeds for t in s.split() if len(t) >= 4}
        def shares_substantive_seed(kw):
            return bool(seed_long_tokens & set(kw.lower().split()))
        related = [r["keyword"] for r in kept
                   if not is_longtail(r["keyword"])
                   and not any(m.lower() in r["keyword"].lower() for m in markets)
                   and shares_substantive_seed(r["keyword"])]
        seed_phrases += related[:25]
        for s in seed_phrases:
            for m in markets:
                kw = f"{s} {m}".strip()
                kl = kw.lower()
                if kl in seen_h or (brand_l and brand_l in kl):
                    continue
                seen_h.add(kl)
                # rank these by the volume of their BARE form (local volume is
                # usually unreported, but bare volume signals term importance)
                bare_vol = vol_lookup.get(s.lower(), 0)
                geo_heads.append({"keyword": kw, "volume": bare_vol, "src": "geo"})
        # strongest terms first (by bare-form volume)
        geo_heads.sort(key=lambda r: r["volume"], reverse=True)
        # backfill with any remaining bare terms (volume or not) if still short
        bare_backfill = [r for r in kept if not is_longtail(r["keyword"])
                         and r["keyword"].lower() not in seen_h]
        head_ordered = geo_heads + bare_backfill
    else:
        # NATIONAL: no geo modifier; rank bare head terms by volume.
        head_ordered = [r for r in with_vol if not is_longtail(r["keyword"])]

    ultra       = head_ordered[:u]
    competitive = head_ordered[u:u + c]
    head_kws    = {r["keyword"] for r in ultra + competitive}

    # LONG-TAIL bucket: explicitly long / question-shaped phrases, deduped,
    # not already used as a head term. Longer phrases preferred.
    lt_candidates = [r for r in kept
                     if is_longtail(r["keyword"]) and r["keyword"] not in head_kws]
    # prefer more words, then higher volume
    lt_candidates.sort(key=lambda r: (len(r["keyword"].split()), r["volume"]), reverse=True)
    long_tail = lt_candidates[:CFG["longtail_target"]]

    # Backfill: if the API returned few real long-tails (common in local/niche
    # verticals), generate question-form long-tails from the seeds + market so
    # the bucket is never empty at Step 1. PAA harvested in Step 3 will add more.
    if len(long_tail) < CFG["longtail_target"]:
        seen_lt = {r["keyword"].lower() for r in long_tail} | {k.lower() for k in head_kws}
        mkt = markets[0] if markets else ""
        templates = ["how much does {s} cost{inm}", "best {s} near me",
                     "what to look for in {s}{inm}", "affordable {s} for adults{inm}",
                     "is {s} covered by insurance{inm}", "how to find a good {s}{inm}"]
        for s in seeds:
            for t in templates:
                if len(long_tail) >= CFG["longtail_target"]:
                    break
                kw = t.format(s=s, inm=(f" in {mkt}" if mkt else "")).strip()
                kl = kw.lower()
                if kl in seen_lt or (brand_l and brand_l in kl):
                    continue
                seen_lt.add(kl)
                long_tail.append({"keyword": kw, "volume": 0, "src": "gen"})

    # ---- Claude refinement pass (Option 2: API generates, Claude refines) ----
    site_terms = [r for r in raw if r.get("src") == "site"]
    # BUILD stops here (fast: keyword API + rules only). The Claude refinement and
    # exact-match volume run in a SEPARATE request (stage1b_refine) so neither
    # half can exceed the platform request timeout on heavy verticals.
    full = (ultra + competitive + long_tail)[:CFG["list_cap"]]
    fs = {r["keyword"] for r in full}
    return {
        "ultra":       [r for r in ultra if r["keyword"] in fs],
        "competitive": [r for r in competitive if r["keyword"] in fs],
        "long_tail":   [r for r in long_tail if r["keyword"] in fs],
        "head":        [r for r in (ultra + competitive) if r["keyword"] in fs],
        "all":         full,
        "refined_by_ai": False,
        "business_desc": "",
        "site_pages_found": 0,
        "site_terms":  [r["keyword"] for r in site_terms],   # passed to refine step
    }

def stage1b_refine(seeds, markets, state, brand, domain, business_desc,
                   ultra, competitive, long_tail, site_terms_kw):
    """Second half of Step 1, run as its own request: reads the sitemap, runs the
    Claude refinement pass, and re-pulls exact-match volume. Takes the raw buckets
    from stage1_keyword_list. Kept separate so a heavy Claude call can't time out
    the list build."""
    site_terms = [{"keyword": k} for k in (site_terms_kw or [])]
    site_pages = fetch_site_pages(domain)
    biz = business_desc.strip() if business_desc else ""

    # ---- GRID MODE: build a service x city grid like the real proposals -----
    if CFG.get("grid_mode"):
        cands = ultra + competitive + long_tail
        services = claude_expand_services(seeds, biz, site_pages, brand, domain,
                                          cands, CFG["grid_max_services"])
        if not services:
            # fall back to the partner's seeds, spread across tiers
            tiers = ["ultra", "ultra", "competitive", "long_tail"]
            services = [{"service": s.strip().lower(), "tier": tiers[min(i, 3)]}
                        for i, s in enumerate(seeds[:CFG["grid_max_services"]])]
        g = build_grid(services, markets, state)
        full = g["ultra"] + g["competitive"] + g["long_tail"]
        # Volume: look up the BARE service term AT THE CLIENT'S MARKET (the
        # geo-modified forms report ~0). The same figure is shown on each city
        # row for that service, so pricing must count it ONCE PER SERVICE — not
        # once per row — or a 10-city grid would inflate volume 10x.
        svc_names = list(dict.fromkeys([s["service"] for s in services]))
        vols = fetch_local_volume(svc_names, markets, state)
        for r in full:
            v = vols.get((r.get("service") or "").lower())
            if v is not None:
                r["volume"] = v
        service_volume = {s: vols.get(s.lower(), 0) for s in svc_names}
        return {
            "ultra": g["ultra"], "competitive": g["competitive"],
            "long_tail": g["long_tail"],
            "head": g["ultra"] + g["competitive"],
            "all": full,
            "refined_by_ai": True,
            "business_desc": biz,
            "site_pages_found": len(site_pages),
            "grid": True,
            "services": services,
            "service_volume": service_volume,
            "total_volume": sum(service_volume.values()),   # unique, not per-row
        }

    refined = claude_refine_keywords(seeds, markets, brand, domain,
                                     ultra + competitive + long_tail, site_terms,
                                     business_desc=biz, site_pages=site_pages)
    used_claude = False
    biz_out = biz
    if refined and (refined["ultra"] or refined["competitive"]):
        ultra       = refined["ultra"][:CFG["ultra_bucket_size"]] or ultra
        competitive = refined["competitive"][:CFG["competitive_bucket_size"]] or competitive
        if refined["long_tail"]:
            long_tail = refined["long_tail"][:CFG["longtail_target"]]
        used_claude = True
        biz_out = biz or refined.get("business", "")

    full = (ultra + competitive + long_tail)[:CFG["list_cap"]]

    exact = fetch_exact_volume([r["keyword"] for r in full], markets, state)
    if exact:
        for r in full:
            v = exact.get(r["keyword"].lower())
            if v is not None:
                r["volume"] = v

    fs = {r["keyword"] for r in full}
    return {
        "ultra":       [r for r in ultra if r["keyword"] in fs],
        "competitive": [r for r in competitive if r["keyword"] in fs],
        "long_tail":   [r for r in long_tail if r["keyword"] in fs],
        "head":        [r for r in (ultra + competitive) if r["keyword"] in fs],
        "all":         full,
        "refined_by_ai": used_claude,
        "business_desc": biz_out if used_claude else "",
        "site_pages_found": len(site_pages),
    }

# ---------------------------------------------------------------------------
# STAGE 3a — metrics -> competitive adder
# ---------------------------------------------------------------------------
def fetch_keyword_difficulty(kws, markets, state):
    """Labs bulk keyword difficulty (1-100 organic ranking difficulty). Separate
    call from the Google Ads bid data. Returns (kd_map, error_or_None) so the
    caller can surface why it's empty instead of silently failing."""
    if not kws:
        return {}, None
    try:
        # Labs endpoints want a numeric location_code, not location_name (which
        # the Google Ads endpoints use). 2840 = United States. Keyword difficulty
        # is a national-level organic metric, so country-level is appropriate.
        payload = [{"keywords": kws[:1000],
                    "location_code": 2840,
                    "language_code": "en"}]
        data = dfs_post("/dataforseo_labs/google/bulk_keyword_difficulty/live", payload)
        task = (data.get("tasks") or [{}])[0]
        # surface API-level errors (auth, plan, balance) explicitly
        if task.get("status_code") not in (20000, None) and not task.get("result"):
            return {}, f"{task.get('status_code')}: {task.get('status_message')}"
        res = task.get("result") or []
        kd = {}
        for block in res:
            for it in (block.get("items") or []):
                k = it.get("keyword")
                if k is None:
                    continue
                # difficulty can appear as a top-level field or nested
                v = it.get("keyword_difficulty")
                if v is None:
                    v = (it.get("keyword_properties") or {}).get("keyword_difficulty")
                if v is not None:
                    kd[k] = v
        return kd, None
    except requests.HTTPError as e:
        return {}, f"HTTP {e.response.status_code if e.response else '?'}"
    except Exception as e:
        return {}, str(e)[:80]

def _strip_markets(kw, markets):
    """Remove a trailing market modifier so we can look up bid/difficulty data,
    which the APIs key to the bare term ('adhd treatment'), not the geo form
    ('adhd treatment san diego')."""
    k = kw
    for m in sorted(markets, key=len, reverse=True):
        if m and k.lower().endswith(" " + m.lower()):
            k = k[: -(len(m) + 1)].strip()
            break
    return k

def stage3_metrics(head, markets, state):
    geo_kws = [r["keyword"] for r in head]
    if not geo_kws:
        return {"adder": 0, "median_score": 0, "bids": {}, "cpc": {}, "kd": {}}
    # Map each geo head term -> its bare form; query metrics on the bare forms
    # (which have real bid/difficulty data), then attribute results to both keys.
    bare_of = {g: _strip_markets(g, markets) for g in geo_kws}
    bare_unique = list(dict.fromkeys(bare_of.values()))

    payload = [{"keywords": bare_unique,
                "location_name": loc_string(markets, state),
                "language_code": "en"}]
    bid_err = None
    items = []
    try:
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        task0 = (data.get("tasks") or [{}])[0]
        # DataForSEO reports per-task problems in status_code/status_message even
        # on an HTTP 200, so surface those rather than silently returning nothing.
        if task0.get("status_code") not in (20000, None):
            bid_err = f"{task0.get('status_code')}: {task0.get('status_message')}"
        items = (task0.get("result") or [])
    except Exception as e:
        bid_err = str(e)
    bare_bid = {it["keyword"]: (it.get("high_top_of_page_bid") or 0) for it in items}
    bare_cpc = {it["keyword"]: (it.get("cpc") or it.get("high_top_of_page_bid") or 0) for it in items}
    bare_kd, kd_err = fetch_keyword_difficulty(bare_unique, markets, state)

    # Attribute to both the geo key (for the table) and the bare key.
    bids, cpc, kd = {}, {}, {}
    for g in geo_kws:
        b = bare_of[g]
        if bare_bid.get(b):  bids[g] = bare_bid[b]; bids[b] = bare_bid[b]
        if bare_cpc.get(b):  cpc[g]  = bare_cpc[b]; cpc[b]  = bare_cpc[b]
        if bare_kd.get(b) is not None: kd[g] = bare_kd[b]; kd[b] = bare_kd[b]

    kd_vals = [v for v in {bare_of[g]: kd.get(g) for g in geo_kws}.values()
               if isinstance(v, (int, float))]
    median_kd = int(statistics.median(kd_vals)) if kd_vals else None

    lo, hi = CFG["bid_score_breaks"]
    # Score only on head terms that returned bid data (don't let missing data
    # count as 0 and drag the median down).
    have_bid = [bids.get(g, 0) for g in geo_kws if bids.get(g, 0)]
    scores = [2 if b >= hi else 1 if b >= lo else 0 for b in have_bid]
    median_score = int(statistics.median(scores)) if scores else 0
    # Bid distribution so the panel can show what the score is derived from.
    # Use unique bare-term bids (the actual data points the score is built on).
    bid_vals = [v for v in bare_bid.values() if v]
    bid_stats = None
    if bid_vals:
        bid_stats = {"median": round(statistics.median(bid_vals), 2),
                     "min": round(min(bid_vals), 2),
                     "max": round(max(bid_vals), 2),
                     "n": len(bid_vals), "n_total": len(bare_unique)}
    # Competitive adder: prefer CPC-scaled (adder tracks median bid = click value),
    # fall back to the flat score buckets when there's no bid data to scale on.
    flat_adder = CFG["competitive_adder"][median_score]
    adder = flat_adder
    adder_basis = "flat"
    cpc_used = None
    if CFG.get("cpc_adder_enabled") and bid_stats and bid_stats["median"]:
        med_cpc = bid_stats["median"]
        cpc_used = med_cpc
        free = CFG.get("cpc_adder_free_below", 5.0)
        if med_cpc > free:
            raw = med_cpc * CFG.get("cpc_adder_mult", 3.0)
            capped = min(raw, CFG.get("cpc_adder_cap", 1500))
            adder = int(round(capped / 50.0) * 50)
            adder_basis = "cpc"
        else:
            adder = 0
            adder_basis = "cpc"
    return {"adder": adder, "adder_basis": adder_basis, "cpc_used": cpc_used,
            "flat_adder": flat_adder,
            "bid_error": bid_err,
            "bid_location": loc_string(markets, state),
            "bid_terms_queried": bare_unique[:8],
            "n_markets": len(markets),
            "median_score": median_score, "bids": bids, "cpc": cpc,
            "bid_stats": bid_stats, "breaks": [lo, hi],
            "kd": kd, "median_kd": median_kd, "kd_error": kd_err}

# ---------------------------------------------------------------------------
# STAGE 3b — rank check -> table + zero-ranking + PAA
# ---------------------------------------------------------------------------
def _serp_one(kw, domain_dom, markets, state, brand, top_n):
    """One keyword's SERP call. Returns (position_or_None, [paa questions]).
    Depth tracks top_n (not 100) and the timeout is short, so one slow lookup
    can't push the batch past the platform request limit. Retries once, because
    a transient failure would otherwise be recorded as 'Not Found' — which would
    wrongly inflate the not-ranking percentage that drives pricing."""
    depth = max(top_n, 10)
    payload = [{"keyword": kw, "location_name": loc_string(markets, state),
                "language_code": "en", "depth": depth}]
    last_err = None
    for attempt in range(2):
        try:
            data = dfs_post("/serp/google/organic/live/advanced", payload, timeout=20)
            break
        except Exception as e:
            last_err = e
            if attempt == 0:
                time.sleep(1)
    else:
        raise last_err
    res = (data["tasks"][0]["result"] or [{}])[0]
    items = res.get("items", []) or []
    pos, paa = None, []
    for it in items:
        if it.get("type") == "organic" and domain_dom and domain_dom in (it.get("domain") or ""):
            if pos is None:
                pos = it.get("rank_absolute")
        if it.get("type") == "people_also_ask":
            for el in it.get("items", []):
                q = el.get("title")
                if q and (brand or "").lower() not in q.lower():
                    paa.append(q)
    return pos, paa

def stage3_rankcheck(all_kws, domain, markets, state, brand):
    top_n = CFG["zero_ranking_top_n"]
    dom = (domain or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    # Cap the number of SERP calls to stay under the platform timeout.
    capped = all_kws[:CFG["rank_check_cap"]]
    kws = [r["keyword"] for r in capped]

    # Fire SERP calls in parallel; keep results aligned to input order.
    results = [None] * len(kws)
    with ThreadPoolExecutor(max_workers=CFG["rank_check_workers"]) as ex:
        futs = {ex.submit(_serp_one, kw, dom, markets, state, brand, top_n): i
                for i, kw in enumerate(kws)}
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = (None, [])   # one bad keyword shouldn't sink the quote

    table, paa, ranked = [], [], 0
    for kw, (pos, qs) in zip(kws, results):
        table.append({"keyword": kw, "position": pos})
        paa.extend(qs)
        if pos is not None and pos <= top_n:
            ranked += 1
    n = len(kws) or 1
    frac = ranked / n
    return {"table": table, "ranked": ranked, "frac": frac,
            "zero_ranking": frac < CFG["zero_ranking_frac"],
            "paa_pool": list(dict.fromkeys(paa))}

# ---------------------------------------------------------------------------
# STAGE 4 — pricing
# ---------------------------------------------------------------------------
def _tier_uplift(value, tiers):
    """Given a value and a list of [threshold, uplift_pct] sorted high-to-low,
    return the uplift_pct of the first threshold the value meets (else 0)."""
    for thresh, uplift in tiers:
        if value >= thresh:
            return uplift
    return 0

def _volume_dollar_add(total_volume, free_below, brackets):
    """Fixed $ added for search volume above a normalized baseline, using a
    declining marginal rate (tax-bracket style). Each bracket [lo, hi, rate]
    charges 'rate' $/search for the volume that falls within [lo, hi]; a hi of
    None means open-ended. Returns total $ added (0 if at/below the baseline)."""
    if not total_volume or total_volume <= free_below:
        return 0
    add = 0.0
    for b in brackets:
        lo, hi, rate = b[0], b[1], b[2]
        if total_volume > lo:
            top = total_volume if hi is None else min(total_volume, hi)
            band = max(0, top - lo)
            add += band * rate
    return add

def stage4_price(band, adder, zero_ranking, addon_markets=0, markup_pct=None,
                 pct_not_ranking=None, total_volume=None, base_override=None):
    if markup_pct is None:
        markup_pct = CFG["default_markup_pct"]
    m = 1.0 + (markup_pct / 100.0)
    anchor = CFG["geo_anchor"][band]                       # hard cost

    # --- volume-based add: fixed $ for volume above the normalized baseline ---
    vol_add = 0
    if total_volume is not None:
        vol_add = _volume_dollar_add(total_volume, CFG.get("vol_free_below", 10000),
                                     CFG.get("volume_brackets", []))

    # Base before % uplift = anchor + competitive adder + volume $ add.
    base_pre = anchor + adder + vol_add

    # --- tiered zero-ranking uplift (% of head terms not ranking) ---
    zr_uplift = 0
    if pct_not_ranking is not None:
        zr_uplift = _tier_uplift(pct_not_ranking, CFG.get("zero_ranking_tiers", []))
    elif zero_ranking:
        zr_uplift = CFG.get("zero_ranking_tiers", [[0, 0]])[0][1]

    # MANUAL OVERRIDE: set the hard base directly; the ladder recomputes from it.
    manual_base = base_override is not None and str(base_override) != ""
    if manual_base:
        base = r50(float(base_override))
        zr_uplift = 0; vol_add = 0
    else:
        base = r50(base_pre * (1.0 + zr_uplift / 100.0))

    step = r50(base * CFG["step_ratio"])
    hard = {"base": base, "intermediate": base + step, "advanced": base + 2*step}

    client_base = r50(base * m)
    floor = CFG.get("client_floor", 0)
    floored = False
    if floor and client_base < floor:
        client_base = floor
        floored = True
        cstep = r50(client_base * CFG["step_ratio"])
        client = {"base": client_base,
                  "intermediate": client_base + cstep,
                  "advanced": client_base + 2*cstep}
    else:
        client = {k: r50(v * m) for k, v in hard.items()}

    hard_addon   = {k: r50(v * CFG["addon_market_ratio"]) for k, v in hard.items()}
    client_addon = {k: r50(v * CFG["addon_market_ratio"]) for k, v in client.items()}
    return {"anchor": anchor, "base": base, "base_pre_uplift": base_pre, "step": step,
            "floored": floored, "client_floor": floor, "manual_base": manual_base,
            "zero_ranking_uplift_pct": zr_uplift, "volume_add": vol_add,
            "pct_not_ranking": pct_not_ranking, "total_volume": total_volume,
            "hard_tiers": hard, "client_tiers": client,
            "hard_addon_per_market": hard_addon, "client_addon_per_market": client_addon,
            "markup_pct": markup_pct, "addon_markets": addon_markets,
            "tiers": client, "addon_per_market": client_addon}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

def mock_pipeline(seeds, markets, state, domain, brand, band, addon):
    """Realistic sample data — no DataForSEO calls. Deterministic per input so
    the demo feels responsive to what the partner typed. Cannot time out."""
    market = markets[0] if markets else ""

    # Head terms: seed + market variants, descending volume
    head_terms = []
    for s in seeds:
        if market:
            head_terms.append(f"{s} {market}".strip())
        head_terms.append(s)
    seen = set(); head_terms = [h for h in head_terms if not (h in seen or seen.add(h))]
    ultra, comp = [], []
    for i, h in enumerate(head_terms):
        vol = max(40, 620 - i * 55)
        (ultra if i < 3 else comp).append({"kw": h, "vol": vol})
    comp = comp[:6]

    # Long-tail: question-shaped, longer phrases
    templates = ["how much does {s} cost in {m}", "best {s} near me",
                 "what to look for in {s} in {m}", "affordable {s} for adults in {m}",
                 "is {s} covered by insurance in {m}"]
    longtail = []
    for s in seeds:
        for t in templates:
            kw = t.format(s=s, m=market or "your area").replace("  ", " ").strip()
            longtail.append({"kw": kw, "vol": 0})
    longtail = longtail[:10]

    # Ranking table: mostly Not Found (zero-ranking demo), one ranked deep
    all_rows = ultra + comp + longtail
    table = []
    for i, r in enumerate(all_rows):
        pos = 54 if i == len(all_rows) - 1 else "Not Found"
        table.append({"kw": r["kw"], "pos": pos})
    ranked, total = 0, len(all_rows)   # 0 in top 50 -> zero-ranking fires
    zero_ranking = True
    adder, score = 300, 2              # hard-cost high-competition sample

    base = CFG["geo_anchor"][band] + adder + CFG["zero_ranking_bonus"]
    step = r50(base * CFG["step_ratio"])
    tiers = {"base": base, "intermediate": base + step, "advanced": base + 2*step}
    addon_per = {k: r50(v * CFG["addon_market_ratio"]) for k, v in tiers.items()}

    export_rows = (
        [{"kw": r["kw"], "rank": "Not Found", "comp": "Ultra Competitive"} for r in ultra] +
        [{"kw": r["kw"], "rank": "Not Found", "comp": "Competitive"} for r in comp] +
        [{"kw": r["kw"], "rank": "Not Found", "comp": "Long Tail"} for r in longtail])

    return {
        "demo": True,
        "stage1": {"ultra": ultra, "competitive": comp, "long_tail": longtail, "count": total},
        "stage3a": {"adder": adder, "score": score},
        "stage3b": {"ranked": ranked, "total": total, "frac": 0,
                    "zero_ranking": zero_ranking,
                    "paa": [r["kw"] for r in longtail[:6]], "table": table},
        "stage4": {"anchor": CFG["geo_anchor"][band], "adder": adder,
                   "zero_bonus": CFG["zero_ranking_bonus"], "base": base,
                   "step": step, "tiers": tiers, "addon_per_market": addon_per,
                   "addon_markets": addon, "band": band},
        "export_rows": export_rows,
    }

@app.route("/quote", methods=["POST"])
def quote():
    d = request.get_json(force=True)
    seeds   = [s.strip() for s in d.get("keywords", []) if s.strip()]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = (d.get("state") or "").strip()
    domain  = (d.get("domain") or "").strip()
    brand   = (d.get("brand") or "").strip()
    band    = d.get("geo_scope", "single_city")
    addon   = int(d.get("addon_markets", 0) or 0)

    if not seeds:
        return jsonify({"error": "At least one keyword/vertical is required."}), 400
    if band not in CFG["geo_anchor"]:
        return jsonify({"error": f"Unknown geo scope '{band}'."}), 400

    # DEMO_MODE: serve sample data instantly, no API calls, cannot time out.
    if DEMO_MODE:
        return jsonify(mock_pipeline(seeds, markets, state, domain, brand, band, addon))

    try:
        s1 = stage1_keyword_list(seeds, markets, state, brand)
        if not s1["all"]:
            return jsonify({"error": "No keywords returned — try broader seeds or check the market/state."}), 400
        m3 = stage3_metrics(s1["head"], markets, state)
        r3 = stage3_rankcheck(s1["all"], domain, markets, state, brand)
        p  = stage4_price(band, m3["adder"], r3["zero_ranking"], addon)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO request failed: {e}. Check DFS_LOGIN / DFS_PASSWORD, or set DEMO_MODE=1 to run on sample data."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}. Set DEMO_MODE=1 to run on sample data."}), 500

    # Fold PAA questions into the long-tail bucket (they're real long-tail queries
    # Google confirms users ask). Keep existing long-tails first, then top up with
    # PAA until we hit the target, deduping against everything already in the list.
    used = {r["keyword"].lower() for r in s1["ultra"] + s1["competitive"] + s1["long_tail"]}
    longtail = [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["long_tail"]]
    for q in r3["paa_pool"]:
        if len(longtail) >= CFG["longtail_target"]:
            break
        ql = q.lower()
        if ql not in used:
            used.add(ql)
            longtail.append({"kw": q, "vol": 0})   # PAA has no volume figure

    # Build the exportable keyword table: keyword / rank / competitiveness
    rank_map = {t["keyword"]: t["position"] for t in r3["table"]}
    def comp_label(kw, tier):
        return tier
    export_rows = []
    for r in s1["ultra"]:
        pos = rank_map.get(r["keyword"]); export_rows.append(
            {"kw": r["keyword"], "rank": pos if pos is not None else "Not Found", "comp": "Ultra Competitive"})
    for r in s1["competitive"]:
        pos = rank_map.get(r["keyword"]); export_rows.append(
            {"kw": r["keyword"], "rank": pos if pos is not None else "Not Found", "comp": "Competitive"})
    for lt in longtail:
        pos = rank_map.get(lt["kw"])
        export_rows.append(
            {"kw": lt["kw"], "rank": pos if pos is not None else "Not Found", "comp": "Long Tail"})

    return jsonify({
        "stage1": {
            "ultra":       [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["ultra"]],
            "competitive": [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["competitive"]],
            "long_tail":   longtail,
            "count": len(s1["all"]),
        },
        "stage3a": {"adder": m3["adder"], "score": m3["median_score"]},
        "stage3b": {
            "ranked": r3["ranked"], "total": len(s1["all"]),
            "frac": round(r3["frac"]*100), "zero_ranking": r3["zero_ranking"],
            "paa": r3["paa_pool"][:15],
            "table": [{"kw": t["keyword"],
                       "pos": (t["position"] if t["position"] is not None else "Not Found")}
                      for t in r3["table"]],
        },
        "stage4": {
            "anchor": p["anchor"], "adder": m3["adder"],
            "zero_bonus": CFG["zero_ranking_bonus"] if r3["zero_ranking"] else 0,
            "base": p["base"], "step": p["step"], "tiers": p["tiers"],
            "addon_per_market": p["addon_per_market"], "addon_markets": addon,
            "band": band,
        },
        "export_rows": export_rows,
    })

@app.route("/export.csv", methods=["POST"])
def export_csv():
    """Stateless CSV: frontend posts back the rows it already has."""
    import csv, io
    d = request.get_json(force=True)
    rows = d.get("rows", [])
    client = (d.get("client") or "client").replace(" ", "_")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Keyword", "Current Google Rank", "Competitiveness", "Est. CPC", "Keyword Difficulty"])
    for r in rows:
        cpc = r.get("cpc", "")
        cpc_str = f"${cpc:.2f}" if isinstance(cpc, (int, float)) and cpc else ""
        kd = r.get("kd", "")
        kd_str = f"{kd}/100" if isinstance(kd, (int, float)) else ""
        w.writerow([r.get("kw", ""), r.get("rank", ""), r.get("comp", ""), cpc_str, kd_str])
    from flask import Response
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={client}_keywords.csv"})

# ===========================================================================
# STEPPED LIVE ENDPOINTS — each is its own short request so nothing times out.
# The frontend calls them in sequence and holds state between steps.
# ===========================================================================

@app.route("/api/keywords", methods=["POST"])
def api_keywords():
    """Step 1 — build + bucket the keyword list. One ideas call + parallel suggestions."""
    d = request.get_json(force=True)
    seeds   = [s.strip() for s in d.get("keywords", []) if s.strip()]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    brand   = (d.get("brand") or "").strip()
    domain  = (d.get("domain") or "").strip()
    business_desc = (d.get("business_desc") or "").strip()
    if not seeds:
        return jsonify({"error": "At least one keyword/vertical is required."}), 400
    try:
        s1 = stage1_keyword_list(seeds, markets, state, brand, domain, business_desc)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}. Check funds / credentials."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500
    if not s1["all"]:
        return jsonify({"error": "No keywords returned — try broader seeds or check market/state."}), 400
    conv = lambda L: [{"kw": r["keyword"], "vol": r["volume"],
                       "origin": r.get("origin", "")} for r in L]
    resp = {
        "ultra": conv(s1["ultra"]), "competitive": conv(s1["competitive"]),
        "long_tail": conv(s1["long_tail"]), "head": conv(s1["head"]),
        "all": conv(s1["all"]), "refined_by_ai": s1.get("refined_by_ai", False),
        "business_desc": s1.get("business_desc", ""),
        "site_pages_found": s1.get("site_pages_found", 0),
        "site_terms": s1.get("site_terms", []),
    }
    # Thin-list guard: sparse/niche verticals or too few seeds produce a short
    # list. Flag it so the partner can add more seed terms for a fuller table.
    if len(s1["all"]) < 6 or len(s1["competitive"]) == 0:
        resp["thin_warning"] = ("Only a few keywords came back — this vertical may "
            "be low-volume, or try adding more seed terms (e.g. related services) "
            "for a fuller keyword table like the proposals.")
    return jsonify(resp)

@app.route("/api/refine", methods=["POST"])
def api_refine():
    """Step 1b — AI refinement + exact-match volume, run as a SEPARATE request so
    a heavy Claude call can't time out the list build. Takes the buckets the build
    step returned (plus any user edits) and returns the refined, volume-corrected
    list. Non-fatal: on any failure, returns the input list unchanged so the flow
    continues with the rules-based buckets."""
    d = request.get_json(force=True)
    seeds   = [s.strip() for s in d.get("keywords", []) if s.strip()]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    brand   = (d.get("brand") or "").strip()
    domain  = (d.get("domain") or "").strip()
    business_desc = (d.get("business_desc") or "").strip()
    site_terms_kw = d.get("site_terms", [])
    # rebuild bucket rows from what the frontend sends back (kw + vol)
    def rows(key):
        return [{"keyword": x["kw"], "volume": x.get("vol", 0), "src": "build"}
                for x in d.get(key, []) if x.get("kw")]
    ultra, competitive, long_tail = rows("ultra"), rows("competitive"), rows("long_tail")
    try:
        s1 = stage1b_refine(seeds, markets, state, brand, domain, business_desc,
                            ultra, competitive, long_tail, site_terms_kw)
    except Exception as e:
        # graceful: hand back the unrefined list so the pipeline still works
        conv0 = lambda L: [{"kw": r["keyword"], "vol": r["volume"], "origin": ""} for r in L]
        return jsonify({"ultra": conv0(ultra), "competitive": conv0(competitive),
                        "long_tail": conv0(long_tail),
                        "head": conv0(ultra + competitive),
                        "all": conv0(ultra + competitive + long_tail),
                        "refined_by_ai": False, "business_desc": "",
                        "site_pages_found": 0, "refine_error": str(e)})
    conv = lambda L: [{"kw": r["keyword"], "vol": r["volume"],
                       "origin": r.get("origin", "")} for r in L]
    return jsonify({
        "ultra": conv(s1["ultra"]), "competitive": conv(s1["competitive"]),
        "long_tail": conv(s1["long_tail"]), "head": conv(s1["head"]),
        "all": conv(s1["all"]), "refined_by_ai": s1.get("refined_by_ai", False),
        "business_desc": s1.get("business_desc", ""),
        "site_pages_found": s1.get("site_pages_found", 0),
        "grid": s1.get("grid", False),
        "services": s1.get("services", []),
        "service_volume": s1.get("service_volume", {}),
        "total_volume": s1.get("total_volume", None),
    })

@app.route("/api/metrics", methods=["POST"])
def api_metrics():
    """Step 2 — competitive adder from head-term bids. One search_volume call."""
    d = request.get_json(force=True)
    head    = [{"keyword": k} for k in d.get("head", [])]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    try:
        m3 = stage3_metrics(head, markets, state)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500
    return jsonify({"adder": m3["adder"], "score": m3["median_score"],
                    "adder_basis": m3.get("adder_basis"), "cpc_used": m3.get("cpc_used"),
                    "flat_adder": m3.get("flat_adder"),
                    "bid_error": m3.get("bid_error"),
                    "bid_location": m3.get("bid_location"),
                    "bid_terms_queried": m3.get("bid_terms_queried"),
                    "n_markets": m3.get("n_markets"),
                    "cpc": m3.get("cpc", {}), "kd": m3.get("kd", {}),
                    "median_kd": m3.get("median_kd"), "kd_error": m3.get("kd_error"),
                    "bid_stats": m3.get("bid_stats"), "breaks": m3.get("breaks")})

@app.route("/api/rankings", methods=["POST"])
def api_rankings():
    """Step 3 — rank-check ONE small batch of keywords (frontend loops batches).
    Each call is short: a few parallel SERP lookups."""
    d = request.get_json(force=True)
    batch   = d.get("batch", [])
    domain  = (d.get("domain") or "").strip()
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    brand   = (d.get("brand") or "").strip()
    dom = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    top_n = CFG["zero_ranking_top_n"]
    results, paa = [], []
    try:
        with ThreadPoolExecutor(max_workers=CFG["rank_check_workers"]) as ex:
            futs = {ex.submit(_serp_one, kw, dom, markets, state, brand, top_n): kw for kw in batch}
            done = {}
            for fut in futs:
                kw = futs[fut]
                try:
                    pos, qs = fut.result()
                    err = False
                except Exception:
                    # lookup FAILED — record it as unknown, NOT as "Not Found".
                    # Counting a failed call as not-ranking would inflate the
                    # zero-ranking percentage and therefore the price.
                    pos, qs, err = None, [], True
                done[kw] = (pos, qs, err)
        for kw in batch:
            pos, qs, err = done.get(kw, (None, [], True))
            results.append({"kw": kw,
                            "pos": ("—" if err else (pos if pos is not None else "Not Found")),
                            "ranked_top": (not err and pos is not None and pos <= top_n),
                            "error": err})
            paa.extend(qs)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500
    return jsonify({"results": results, "paa": list(dict.fromkeys(paa))})

@app.route("/api/price", methods=["POST"])
def api_price():
    """Step 4 — pure pricing math, instant. Returns hard cost + client (marked-up)."""
    d = request.get_json(force=True)
    band = d.get("band", "single_city")
    if band not in CFG["geo_anchor"]:
        return jsonify({"error": f"Unknown geo scope '{band}'."}), 400
    adder = int(d.get("adder", 0) or 0)
    zero  = bool(d.get("zero_ranking", False))
    addon = int(d.get("addon_markets", 0) or 0)
    markup = d.get("markup_pct", None)
    markup = float(markup) if markup not in (None, "") else None
    pct_not_ranking = d.get("pct_not_ranking", None)
    pct_not_ranking = float(pct_not_ranking) if pct_not_ranking not in (None, "") else None
    total_volume = d.get("total_volume", None)
    total_volume = int(total_volume) if total_volume not in (None, "") else None
    base_override = d.get("base_override", None)
    base_override = base_override if base_override not in (None, "") else None
    p = stage4_price(band, adder, zero, addon, markup,
                     pct_not_ranking=pct_not_ranking, total_volume=total_volume,
                     base_override=base_override)
    return jsonify({"anchor": p["anchor"], "adder": adder,
                    "base_pre_uplift": p["base_pre_uplift"], "manual_base": p["manual_base"],
                    "zero_ranking_uplift_pct": p["zero_ranking_uplift_pct"],
                    "volume_add": p["volume_add"],
                    "pct_not_ranking": p["pct_not_ranking"], "total_volume": p["total_volume"],
                    "base": p["base"], "step": p["step"],
                    "hard_tiers": p["hard_tiers"], "client_tiers": p["client_tiers"],
                    "hard_addon_per_market": p["hard_addon_per_market"],
                    "client_addon_per_market": p["client_addon_per_market"],
                    "markup_pct": p["markup_pct"], "addon_markets": addon, "band": band})

@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Expose the tunable pricing constants for the review panel."""
    return jsonify({
        "geo_anchor": CFG["geo_anchor"],
        "competitive_adder": CFG["competitive_adder"],
        "bid_score_breaks": CFG["bid_score_breaks"],
        "cpc_adder_enabled": CFG.get("cpc_adder_enabled", True),
        "cpc_adder_mult": CFG.get("cpc_adder_mult", 3.0),
        "cpc_adder_cap": CFG.get("cpc_adder_cap", 1500),
        "cpc_adder_free_below": CFG.get("cpc_adder_free_below", 5.0),
        "zero_ranking_bonus": CFG["zero_ranking_bonus"],
        "zero_ranking_top_n": CFG["zero_ranking_top_n"],
        "zero_ranking_frac": CFG["zero_ranking_frac"],
        "zero_ranking_tiers": CFG.get("zero_ranking_tiers", []),
        "vol_free_below": CFG.get("vol_free_below", 10000),
        "volume_brackets": CFG.get("volume_brackets", []),
        "step_ratio": CFG["step_ratio"],
        "client_floor": CFG["client_floor"],
        "addon_market_ratio": CFG["addon_market_ratio"],
        "default_markup_pct": CFG["default_markup_pct"],
        "ultra_bucket_size": CFG["ultra_bucket_size"],
        "grid_mode": CFG.get("grid_mode", True),
        "grid_max_services": CFG.get("grid_max_services", 4),
        "grid_max_cities": CFG.get("grid_max_cities", 10),
        "grid_state_suffix": CFG.get("grid_state_suffix", True),
        "competitive_bucket_size": CFG["competitive_bucket_size"],
        "longtail_target": CFG["longtail_target"],
    })

@app.route("/api/config", methods=["POST"])
def api_config_set():
    """Apply edited constants to the running session (not persisted to disk —
    a restart reverts to the file defaults). Lets Brendan tune and re-quote live."""
    d = request.get_json(force=True)
    try:
        if "geo_anchor" in d:
            for k, v in d["geo_anchor"].items():
                if k in CFG["geo_anchor"]:
                    CFG["geo_anchor"][k] = int(v)
        if "competitive_adder" in d:
            for k, v in d["competitive_adder"].items():
                CFG["competitive_adder"][int(k)] = int(v)
        if "bid_score_breaks" in d:
            CFG["bid_score_breaks"] = [float(x) for x in d["bid_score_breaks"]]
        # zero_ranking_tiers: [[pct_not_ranking, uplift_pct], ...] sorted high-to-low
        if "zero_ranking_tiers" in d and isinstance(d["zero_ranking_tiers"], list):
            tiers = []
            for pair in d["zero_ranking_tiers"]:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    tiers.append([float(pair[0]), float(pair[1])])
            tiers.sort(key=lambda t: t[0], reverse=True)
            CFG["zero_ranking_tiers"] = tiers
        # volume_brackets: [[lo, hi, dollars_per_search], ...]; hi may be null/"".
        if "volume_brackets" in d and isinstance(d["volume_brackets"], list):
            brs = []
            for b in d["volume_brackets"]:
                if isinstance(b, (list, tuple)) and len(b) >= 3:
                    lo = float(b[0])
                    hi = None if b[1] in (None, "", "null") else float(b[1])
                    rate = float(b[2])
                    brs.append([lo, hi, rate])
            brs.sort(key=lambda x: x[0])
            CFG["volume_brackets"] = brs
        if "vol_free_below" in d and d["vol_free_below"] not in (None, ""):
            CFG["vol_free_below"] = float(d["vol_free_below"])
        if "cpc_adder_enabled" in d:
            CFG["cpc_adder_enabled"] = bool(d["cpc_adder_enabled"])
        if "grid_mode" in d:
            CFG["grid_mode"] = bool(d["grid_mode"])
        if "grid_state_suffix" in d:
            CFG["grid_state_suffix"] = bool(d["grid_state_suffix"])
        for key, caster in [("grid_max_services", int), ("grid_max_cities", int)]:
            if key in d and d[key] not in (None, ""):
                CFG[key] = caster(d[key])
        for key, caster in [("zero_ranking_bonus", int), ("zero_ranking_top_n", int),
                            ("zero_ranking_frac", float), ("step_ratio", float),
                            ("client_floor", int), ("addon_market_ratio", float),
                            ("default_markup_pct", float), ("ultra_bucket_size", int),
                            ("competitive_bucket_size", int), ("longtail_target", int),
                            ("cpc_adder_mult", float), ("cpc_adder_cap", int),
                            ("cpc_adder_free_below", float)]:
            if key in d and d[key] not in (None, ""):
                CFG[key] = caster(d[key])
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid value: {e}"}), 400
    return jsonify({"ok": True})

@app.route("/api/serp_recommend", methods=["POST"])
def api_serp_recommend():
    """Pick the most persuasive head term to screenshot for a proposal:
    prefer a 'Not Found' term, then most competitive, then geo-modified."""
    d = request.get_json(force=True)
    head = d.get("head", [])          # [{"kw":..., "comp":"Ultra"/"Competitive"}]
    ranks = d.get("ranks", {})        # {kw: "Not Found" | position}
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    def is_geo(kw):
        return any(m.lower() in kw.lower() for m in markets)
    def not_found(kw):
        r = ranks.get(kw, "Not Found")
        return r == "Not Found" or r is None
    def score(item):
        kw = item.get("kw", "")
        comp_rank = 2 if item.get("comp", "").lower().startswith("ultra") else 1
        return (1 if not_found(kw) else 0,   # absent first
                comp_rank,                    # most competitive
                1 if is_geo(kw) else 0)       # geo-modified
    if not head:
        return jsonify({"recommended": None, "options": []})
    ordered = sorted(head, key=score, reverse=True)
    return jsonify({"recommended": ordered[0]["kw"],
                    "options": [h["kw"] for h in head]})

@app.route("/api/serp_queue", methods=["POST"])
def api_serp_queue():
    """Step A — queue the SERP task and return immediately with the task_id.
    Short request (no waiting). The frontend then polls /api/serp_fetch."""
    d = request.get_json(force=True)
    keyword = (d.get("keyword") or "").strip()
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    device  = d.get("device", "desktop")
    if not keyword:
        return jsonify({"error": "No keyword provided."}), 400
    try:
        tp = dfs_post("/serp/google/organic/task_post", [{
            "keyword": keyword, "location_name": loc_string(markets, state),
            "language_code": "en", "device": device, "priority": 2}])
        task = (tp.get("tasks") or [{}])[0]
        task_id = task.get("id")
        if not task_id:
            return jsonify({"error": f"Task not created: {task.get('status_message')}"}), 502
        # pass display params through so the fetch step can size the screenshot
        return jsonify({"task_id": task_id, "keyword": keyword, "device": device,
                        "width": d.get("width"), "height": d.get("height"),
                        "scale": d.get("scale")})
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

@app.route("/api/serp_fetch", methods=["POST"])
def api_serp_fetch():
    """Step B — try to fetch the screenshot for a queued task_id. Returns the
    image if ready, or {ready:false} if still processing. Frontend polls this.
    Each call is short, so no request-timeout risk."""
    d = request.get_json(force=True)
    task_id = (d.get("task_id") or "").strip()
    device  = d.get("device", "desktop")
    keyword = d.get("keyword", "")
    if not task_id:
        return jsonify({"error": "No task_id."}), 400
    # build screenshot params, including optional sizing
    shot = {"task_id": task_id, "browser_preset": device}
    if d.get("width"):  shot["browser_screen_width"]  = int(d["width"])
    if d.get("height"): shot["browser_screen_height"] = int(d["height"])
    if d.get("scale"):  shot["browser_screen_scale_factor"] = float(d["scale"])
    try:
        sc = dfs_post("/serp/screenshot", [shot])
        try:
            image_url = sc["tasks"][0]["result"][0]["items"][0]["image"]
        except (KeyError, IndexError, TypeError):
            image_url = None
        if not image_url:
            msg = (sc.get("tasks") or [{}])[0].get("status_message", "")
            return jsonify({"ready": False, "status": msg})
        login = os.environ.get("DFS_LOGIN", ""); pw = os.environ.get("DFS_PASSWORD", "")
        tok = base64.b64encode(f"{login}:{pw}".encode()).decode()
        img = requests.get(image_url, headers={"Authorization": f"Basic {tok}"}, timeout=60)
        img.raise_for_status()
        b64 = base64.b64encode(img.content).decode()
        return jsonify({"ready": True, "keyword": keyword,
                        "data_url": f"data:image/png;base64,{b64}"})
    except requests.HTTPError as e:
        # screenshot endpoint returns an error while the task is still running;
        # treat as not-ready rather than a hard failure so the poll continues
        return jsonify({"ready": False, "status": f"processing ({e})"})
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

# ---------------------------------------------------------------------------
# SAVED QUOTES — persistence with version history (like the Meta forecast tool).
# Degrades gracefully: if no DATABASE_URL, /api/quotes/status reports disabled
# and the UI shows "attach a database to enable" instead of the Save controls.
# ---------------------------------------------------------------------------
@app.route("/api/quotes/status")
def api_quotes_status():
    # Diagnostic detail so "saving is off" isn't a black box: report whether the
    # URL is present and whether the Postgres driver imported.
    return jsonify({
        "enabled": storage.enabled(),
        "has_database_url": bool(os.environ.get("DATABASE_URL", "")),
        "driver_installed": getattr(storage, "_HAVE_DRIVER", False),
        "detail": storage.status_detail(),
    })

@app.route("/api/quotes", methods=["GET"])
def api_quotes_list():
    if not storage.enabled():
        return jsonify({"enabled": False, "quotes": []})
    search = (request.args.get("q") or "").strip()
    return jsonify({"enabled": True, "quotes": storage.list_quotes(search)})

@app.route("/api/quotes", methods=["POST"])
def api_quotes_save():
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled — attach a Postgres database in Render."}), 400
    d = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Give the quote a name."}), 400
    client = (d.get("client") or "").strip()
    payload = d.get("payload") or {}
    qid = storage.save_quote(name, client, payload)
    return jsonify({"ok": True, "id": qid})

@app.route("/api/quotes/<int:qid>", methods=["GET"])
def api_quotes_load(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    q = storage.load_quote(qid)
    if not q:
        return jsonify({"error": "Not found."}), 404
    return jsonify(q)

@app.route("/api/quotes/<int:qid>", methods=["PUT"])
def api_quotes_update(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    d = request.get_json(force=True)
    payload = d.get("payload") or {}
    name = d.get("name"); client = d.get("client")
    ok, version_saved = storage.update_quote(
        qid, payload,
        name=name.strip() if isinstance(name, str) else None,
        client=client.strip() if isinstance(client, str) else None)
    if not ok:
        return jsonify({"error": "Not found."}), 404
    return jsonify({"ok": True, "id": qid,
                    "version_saved": version_saved,
                    "unchanged": not version_saved})

@app.route("/api/quotes/version/<int:vid>", methods=["DELETE"])
def api_quotes_version_delete(vid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    storage.delete_version(vid)
    return jsonify({"ok": True})

@app.route("/api/quotes/<int:qid>", methods=["DELETE"])
def api_quotes_delete(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    storage.delete_quote(qid)
    return jsonify({"ok": True})

@app.route("/api/quotes/<int:qid>/versions", methods=["GET"])
def api_quotes_versions(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    return jsonify({"versions": storage.list_versions(qid)})

@app.route("/api/quotes/version/<int:vid>", methods=["GET"])
def api_quotes_version_load(vid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    v = storage.load_version(vid)
    if not v:
        return jsonify({"error": "Not found."}), 404
    return jsonify(v)

# initialize the DB tables on startup (no-op when saving isn't enabled)
try:
    storage.init_db()
except Exception as _e:
    print(f"[storage] init skipped: {_e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
