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
import os, json, base64, statistics, time, re, threading
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
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
    # Calibrated 2026-07-20 against Brendan's three actuals (Keller Builds,
    # Red Shoes, Waytek): anchors trimmed $250 and the tier step flattened, which
    # lands the formula within ~0-5% of all nine quoted tier prices.
    # Media Venue datapoint (2026-07-20, RFP bid): Brendan $2,925/$4,040/$5,150
    # vs formula $3,450/$4,400/$5,350 (+18/+9/+4%). His base sits BELOW his own
    # $2,950 card and his steps run ~$1,110 (vs his usual ~$1,000) — consistent
    # with a sharpened competitive-RFP base. Root cause of the +18%: the top-20
    # rank check scored his page-3-5 footholds as "not ranking" and fired the
    # +14% zero-ranking uplift. Fix: top-N deepened to 100 (see below) — without
    # the uplift the formula lands $3,037/$3,983/$4,928, within ~4% per tier.
    "geo_anchor": {
        # single_city raised to match contiguous after the Dental Excellence
        # datapoint (2026-07-20): Brendan's single-city Philadelphia quote was
        # his HIGHEST base ($3,350) — he prices the market, not the pin count.
        # A genuinely tiny single-town client may deserve less; no datapoint
        # yet — use the manual hard-base override until one exists.
        "single_city":          2100,
        "contiguous_region":    2100,
        "non_contiguous_region":2350,
        "statewide":            2350,
        "nationwide":           2900,
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
    "cpc_adder_mult": 3.0,                     # $ of hard-cost adder per $1 of median CPC (up to the knee)
    "cpc_adder_knee": 62.0,                    # CPC above this earns the premium rate (just above Waytek's $60 — the highest "normal" client observed)
    "cpc_adder_mult_high": 14.0,               # $/CPC above the knee (insurance-carrier tier)
    "cpc_adder_cap": 1500,                     # max adder (hard cost) so a freak CPC can't explode price
    "cpc_adder_free_below": 5.0,               # CPC at/below this adds nothing (normal-value clicks)
    "zero_ranking_bonus": 400,                # (legacy flat; superseded by tiers below)
    "default_markup_pct": 35,                 # client = hard × 1.35 ≈ original client price
    # top-N deepened 20 -> 100 (2026-07-20, Media Venue): a client with page-3-5
    # footholds (ranks 25/27/33/51 in Brendan's own table) was scoring "80% not
    # ranking" and drawing the +14% uplift, +18% over his base. "Not in top 20"
    # and "starting from scratch" are different claims — the uplift keys off the
    # latter. Depth <=100 is the same DataForSEO billing unit, so no cost change.
    # Tier thresholds unchanged; re-run Serene Health to confirm its fit holds.
    "zero_ranking_top_n": 100,
    "zero_ranking_frac": 0.10,
    # --- Brendan #5: TIERED zero-ranking. % of head terms NOT ranking in top-N
    # maps to a % uplift on the hard base. Each tier: [min_pct_not_ranking, uplift_pct].
    # Evaluated high-to-low; first threshold met wins. Replaces the flat bonus.
    # (2026-07-20) Serene Health RECLASSIFIED out of the auto-fit ledger: its
    # $3,950/$5,450/$6,950 is the same ladder as Skidmore's national card —
    # Brendan's premium/big-org card (multi-site telehealth), not a computed
    # response to keywords. Honest per-city volumes total ~2k/mo (the original
    # "fit" dated from the inflated-volume lookup bug). Handle via the manual
    # hard-base override (~$2,930 -> his card, ratio steps apply). The tiers
    # below remain calibrated on the zero-ranking signal itself.
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
    "volume_add_cap": 500,              # max hard-$ from volume: Brendan's quotes
                                        # flex a few hundred for market size, never
                                        # thousands (Waytek: his +$500 total vs the
                                        # formula's former +$1,400-4,500 vol adds)
    "volume_brackets": [
        [10000, 20000, 0.08],
        [20000, 35000, 0.05],
        [35000, 50000, 0.04],
        [50000, None,  0.03],           # open-ended top bracket so it keeps escalating
    ],
    # NATIONWIDE service clients (Skidmore Studio datapoint, 2026-07-20):
    # Brendan's national ladder $3,950/$5,450/$6,950 backs out to hard
    # $2,926/$4,037/$5,148 — base = the bare nationwide anchor (which was
    # DERIVED from his national pricing, so it already prices the scope), and
    # steps of 38% of base (the same ratio as his ecom quote). At national
    # scope the volume add and zero-ranking uplift are tautological — every
    # nationwide client has >10k volume and ranks for almost nothing on
    # national SERPs — so stacking them double-counts the scope (+$1,327
    # client on Skidmore). Multiplier below zeroes both extras for nationwide
    # NON-industry-rule clients; ecommerce keeps its own calibrated path.
    "nationwide_service_extras": 0.0,
    # Brendan steps his ladder in FLAT dollars (~$900-1,000 client per tier),
    # not proportionally — the old 38% ratio made the gap widen with every tier
    # (+15/18/20% on Keller, +13/24/34% on Waytek). Flat $700 hard = ~$950
    # client at 35% markup. step_ratio remains as fallback if flat is nulled.
    # Industry pricing: industries known to carry additional tiered pricing.
    # Matched by substring against the RZ-fed industry text ("DTC ecommerce
    # supplements" matches "ecommerce"). Each rule: anchor_add (hard $) and
    # step_mode "ratio" (proportional 38% steps) or "flat" (default ladder).
    # ecommerce calibrated on MPG Gummies (2026-07-20) — one datapoint,
    # provisional. Add industries here as Brendan prices them.
    "industry_pricing": {
        "ecommerce":  {"anchor_add": 250, "step_mode": "ratio", "note": "Product-SEO ladder — MPG Gummies calibration. Legacy toggle key."},
        "e-commerce": {"anchor_add": 250, "step_mode": "ratio", "note": "Matches RZ “Retail - General / E-commerce”. Product-SEO ladder — MPG Gummies calibration."},
        # Sibling RZ values an operator would reasonably pick for a product
        # brand (MPG is literally a supplements company) — same product-SEO
        # ladder, so the pricing can't silently vanish on an equally-valid tag.
        # Extensions of the MPG calibration; Brendan to confirm.
        "supplements":             {"anchor_add": 250, "step_mode": "ratio", "note": "Sibling of e-commerce (MPG is a supplements brand). Brendan to confirm."},
        "consumer packaged goods": {"anchor_add": 250, "step_mode": "ratio", "note": "Sibling of e-commerce — product brand tag. Brendan to confirm."},
        # Brendan's premium/big-org card (Serene Health, 2026-07-20 — one
        # datapoint, provisional): large multi-site / telehealth healthcare
        # orgs price on ORGANIZATION size, not keyword signals — his
        # $3,950/$5,450/$6,950 card. anchor_add lands the base at the card;
        # extras_off skips volume + zero-ranking (size, not SERPs, drives it);
        # ratio steps give the card's $1,500 rungs.
        # Keys must match the RZ industry taxonomy VERBATIM (substring) — the
        # line item ships values like "Health Services - Hospital", not the
        # client's marketing vocabulary. Add each big-org RZ value as Brendan
        # prices one.
        # Insurance carriers (Rockingham, 2026-07-20 — one datapoint,
        # provisional): +$800 with extras ON and default steps lands his
        # $5,450/$6,750/$7,950 within 1% per tier. Note the composition differs
        # from the hospital card: uplift stays (SEO genuinely starts from
        # scratch) and steps run the standard 24%-of-base, not the 38% card.
        # Key "insurance -" matches the RZ "Insurance - *" family only — it
        # deliberately misses "B2B - Insurance Business Solutions". OPEN
        # QUESTION for Brendan: RZ doesn't distinguish carriers from two-agent
        # local agencies; confirm whether small agencies carry the same +$800.
        "insurance -":       {"anchor_add": 450, "note": "Carrier premium — Rockingham re-calibration 2026-07-20 at the CURRENT piecewise CPC adder (which already carries ~$1,000 of insurance click value at a $120 median; the original +$800 was fit against the old +$350-capped adder and double-counted). Contiguous NoVA 9-city scope; lands 5,450/6,750/8,050 vs his 5,450/6,750/7,950. Open: do small agencies carry it too?"},
        "hospital":          {"anchor_add": 800, "step_mode": "ratio", "extras_off": True, "note": "Big-org card ($3,950/$5,450/$6,950 shape) — Serene Health calibration via RZ “Health Services - Hospital”."},
        "telehealth":        {"anchor_add": 800, "step_mode": "ratio", "extras_off": True, "note": "Big-org card — non-RZ vocabulary key, kept for free-text matches."},
        "behavioral health": {"anchor_add": 800, "step_mode": "ratio", "extras_off": True, "note": "Big-org card — non-RZ vocabulary key, kept for free-text matches."},
    },
    # Core SEO + AI Search: GEO is its OWN rate card, not a % of the SEO quote
    # (Brendan GEO proposal, 2026-07-20): $2,950 / $4,050 / $5,250 bundled with
    # SEO — intermediate is "discounted from $4,250 in conjunction with the SEO
    # campaign" — and carries a 12-MONTH minimum term (SEO is 6). One datapoint;
    # unknown whether the card flexes for premium clients the way SEO does.
    "geo_pricing_mode": "card",               # "card" (Brendan) or "pct" (legacy)
    "geo_card": {"base": 2950, "intermediate": 4050, "advanced": 5250},
    "geo_card_list": {"base": 2950, "intermediate": 4250, "advanced": 5250},
    "geo_min_term_months": 12,
    "ai_search_uplift_pct": 75,               # legacy pct mode only
    "ecom_anchor_add": 250,                   # legacy alias; industry_pricing supersedes
    "tier_step_flat": 700,                    # hard-cost $ per tier; null -> use step_ratio
    "tier_step_pct_of_base": 0.24,            # step grows past the flat floor on big bases
    "step_ratio": 0.38,                       # fallback: proportional step
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
    # Brendan targets a keyword COUNT, trading services against cities:
    #   Rockingham  10 cities x 10 services = ~104
    #   Serene       1 metro  x ~14 services = 20
    #   Skidmore     0 cities x ~20 services = 24
    # So services scale INVERSELY with cities to hold the total near target.
    "grid_target_keywords": 32,
    "grid_min_services": 4,
    "grid_max_services": 20,
    "grid_max_cities": 10,             # cities crossed against each service
    "grid_state_suffix": "auto",       # auto = suffix only cities that need it
}

def r50(x):
    return int(round(x / 50.0) * 50)

def dfs_post(path, payload, timeout=120, method="POST"):
    login = os.environ.get("DFS_LOGIN", "")
    pw    = os.environ.get("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    hdrs = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    if method == "GET":
        resp = requests.get(BASE + path, headers=hdrs, timeout=timeout)
    else:
        resp = requests.post(BASE + path, headers=hdrs,
                             data=json.dumps(payload), timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def loc_string(markets, state):
    if markets:
        city, st = parse_market(markets[0], state)
        if city and st:
            return f"{city},{st},United States"
        if city:                      # city without state — still localizes
            return f"{city},United States"
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
_ABBREV_TO_STATE = None   # built lazily — STATE_ABBREV is defined later in the module

def _abbrev_to_state():
    global _ABBREV_TO_STATE
    if _ABBREV_TO_STATE is None:
        _ABBREV_TO_STATE = {v: k for k, v in STATE_ABBREV.items()}   # 'nj' -> 'new jersey'
    return _ABBREV_TO_STATE

def parse_market(m, default_state=""):
    """Split an entered market into (city, state). Accepts 'Cherry Hill, NJ',
    'Cherry Hill, New Jersey', or plain 'Cherry Hill' (state then comes from
    the metro map or the global State field). Multi-state regions — a tri-state
    MSP, say — need per-city suffixes: 'it support cherry hill nj' but
    'it support wilmington de'; one global state would mislabel two-thirds
    of the grid."""
    m = (m or "").strip()
    city, st = m, ""
    if "," in m:
        head, tail = [p.strip() for p in m.rsplit(",", 1)]
        t = tail.lower()
        if t in _abbrev_to_state():              # 'NJ'
            city, st = head, _abbrev_to_state()[t].title()
        elif t in STATE_ABBREV:                  # 'New Jersey'
            city, st = head, tail.title()
    if not st:
        cl = city.strip().lower()
        st = CITY_STATE.get(cl, "")
        if not st and cl.endswith(" county"):
            # "san diego county" -> derive the state from "san diego". Counties
            # are REAL DataForSEO locations ("San Diego County,California,
            # United States") and real search phrasing ("bucks county roofing")
            # — they just need the state attached to resolve.
            st = CITY_STATE.get(cl[:-len(" county")].strip(), "")
        st = st or (default_state or "").strip()
    return city.strip(), st

def market_city(m, default_state=""):
    return parse_market(m, default_state)[0]

def market_state(m, default_state=""):
    return parse_market(m, default_state)[1]

def derive_state(markets, provided_state=""):
    """Return a state: use the partner's value if given, else look up the first
    market. Empty if unknown (loc_string then falls back to city,United States)."""
    if provided_state and provided_state.strip():
        return provided_state.strip()
    for mkt in markets:
        ml = mkt.strip().lower()
        s = CITY_STATE.get(ml)
        if not s and ml.endswith(" county"):
            s = CITY_STATE.get(ml[:-len(" county")].strip())
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
    deadline = time.time() + 8          # hard cap: sitemap work gets <= 8s total
    _UA_B = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
    _UA_T = {"User-Agent": "Mozilla/5.0 (compatible; adtini-seo-quote/1.0)"}
    def _get(url, timeout):
        """Fetch trying both identities — WAFs differ on which they block."""
        last = None
        for hdrs in (_UA_B, _UA_T):
            try:
                r = requests.get(url, timeout=timeout, headers=hdrs)
                if r.status_code == 200 and "<" in (r.text or ""):
                    return r
                last = r
            except Exception:
                pass
        return last

    # Candidate sitemap locations: what robots.txt declares, plus the standard
    # and WordPress-native paths. WP >=5.5 ships /wp-sitemap.xml; Yoast uses
    # /sitemap_index.xml; many themes use /page-sitemap.xml directly.
    candidates = []
    try:
        rr = _get(f"https://{dom}/robots.txt", 4)
        if rr is not None and rr.status_code == 200:
            candidates += re.findall(r"(?im)^sitemap:\s*(\S+)", rr.text)
    except Exception:
        pass
    _dom = dom
    for base_dom in dict.fromkeys([_dom, re.sub(r"^www\.", "", _dom)]):
        candidates += [f"https://{base_dom}/sitemap.xml", f"https://{base_dom}/sitemap_index.xml",
                       f"https://{base_dom}/wp-sitemap.xml", f"https://{base_dom}/page-sitemap.xml"]
    seen_sm = set()

    def _blogish(url):
        u = url.lower()
        return bool(re.search(r"/(blog|news|category|tag|author|20\d\d)/", u))

    for sm in candidates:
        if sm in seen_sm or time.time() > deadline:
            continue
        seen_sm.add(sm)
        try:
            r = _get(sm, 5)
            if r is None or r.status_code != 200 or "<" not in r.text:
                continue
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, re.I)
            if locs and all(l.lower().endswith(".xml") for l in locs[:3]):
                # sitemap INDEX — service pages live in "page" sitemaps, so read
                # those first; blog-post sitemaps are last resort
                kids = sorted(locs, key=lambda l: (("page" not in l.lower()),
                                                   ("post" in l.lower())))
                child_locs = []
                for child in kids[:4]:
                    if time.time() > deadline:
                        break
                    try:
                        cr = _get(child, 4)
                        if cr is None: continue
                        child_locs += re.findall(r"<loc>\s*(.*?)\s*</loc>", cr.text, re.I)
                    except Exception:
                        pass
                locs = child_locs or locs
            # shallow, non-blog URLs first — service pages are shallow; posts are
            # deep or dated. Service-path hints float to the top.
            def _rank(u):
                depth = u.rstrip("/").count("/") - 2
                hinted = bool(_SERVICE_PATH_HINT.search(u)) if "_SERVICE_PATH_HINT" in globals() else False
                return (_blogish(u), not hinted, depth)
            for url in sorted(locs, key=_rank):
                if _blogish(url) and len(pages) >= 5:
                    continue
                t = slug_to_topic(url)
                if t and t.lower() not in seen:
                    seen.add(t.lower()); pages.append(t)
                if len(pages) >= limit:
                    break
            if len(pages) >= 3:
                return pages[:limit]
        except Exception:
            continue
    if pages:
        return pages[:limit]

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
    """Search volume for bare service terms across THE CITIES BEING TARGETED.

    A single lookup only covers markets[0], which undercounts a multi-city grid
    by roughly the city count (e.g. 'auto insurance' is ~480/mo in Alexandria but
    the campaign also covers nine other cities). So query each city and sum per
    service — that's the client's real addressable demand.
    Returns ({term_lower: summed_volume}, error_or_None)."""
    if not terms:
        return {}, {}, None
    cities = [c for c in (markets or []) if c and c.strip()]
    if state:
        cities = [c for c in cities if c.strip().lower() != state.strip().lower()]
    if not cities:
        cities = [""]                      # nationwide / no city: single lookup
    cities = cities[:CFG.get("grid_max_cities", 10)]
    kws = [t.lower() for t in terms]

    def one(city):
        # loc_string parses "City, ST" itself; each city localizes to its own state
        loc = loc_string([city], state) if city else loc_string([], state)
        def call(location):
            payload = [{"keywords": kws, "location_name": location,
                        "language_code": "en"}]
            data = dfs_post("/keywords_data/google_ads/search_volume/live", payload,
                            timeout=25)
            task0 = (data.get("tasks") or [{}])[0]
            if task0.get("status_code") not in (20000, None):
                raise RuntimeError(f"{task0.get('status_code')}: {task0.get('status_message')}")
            return task0.get("result") or []
        try:
            return call(loc), loc
        except Exception as e:
            # An unrecognized city (misspelling, a regional phrase like "south
            # jersey", or a name DataForSEO doesn't carry) returns 40501. Retry
            # at a broader location so the quote still gets *some* demand signal
            # — but report WHICH location answered, because broad-location
            # volume must never be attributed per-city and summed: three cities
            # falling back to the same national number would count the same
            # searches three times and wildly inflate the volume add.
            if "40501" in str(e) or "not found" in str(e).lower():
                city_st = market_state(city, state)
                broader = (f"{city_st},United States" if city_st
                           else (f"{state},United States" if state else "United States"))
                return call(broader), broader
            raise

    totals, per_city, errs, ok = {}, {}, [], 0
    counted_locs, fallback_cities, results = set(), [], []
    try:
        with ThreadPoolExecutor(max_workers=min(len(cities), 8)) as ex:
            futs = {ex.submit(one, c): c for c in cities}
            for fut in futs:
                city = futs[fut]
                try:
                    rows, used_loc = fut.result()
                    was_fallback = (used_loc != (loc_string([city], state) if city
                                                 else loc_string([], state)))
                    if was_fallback:
                        fallback_cities.append(city)
                    results.append((city, rows, used_loc))
                    ok += 1
                except Exception as e:
                    errs.append(str(e))
    except Exception as e:
        return {}, {}, str(e)
    if not ok:
        return {}, {}, (errs[0] if errs else "no volume rows returned")
    # Aggregate in two phases so the rules are deterministic:
    #   1. each effective location counts into the TOTAL exactly once;
    #   2. a "United States" fallback never counts when any regional location
    #      returned data — national volume inside a city-summed regional total
    #      is a category error (it's what doubled the Waytek quote). It only
    #      counts when it's the sole data source (true-nationwide runs).
    non_us = [r for r in results if r[2] != "United States"]
    us_skipped = False
    for city, rows, used_loc in sorted(results, key=lambda r: r[2] == "United States"):
        count_it = used_loc not in counted_locs
        if used_loc == "United States" and non_us:
            count_it = False
            us_skipped = True
        counted_locs.add(used_loc)
        for it in rows:
            k = (it.get("keyword") or "").lower()
            if k:
                v = it.get("search_volume") or 0
                if count_it:
                    totals[k] = totals.get(k, 0) + v
                per_city[(city.strip().lower(), k)] = v
    notes = []
    if us_skipped:
        notes.append("some geos had no local volume data and fell back to "
                     "national numbers — shown per keyword but EXCLUDED from "
                     "the pricing total to avoid inflating regional demand")
    if ok < len(cities):
        notes.append(f"volume summed over {ok}/{len(cities)} cities (some lookups failed)")
    if fallback_cities:
        notes.append("no city-level volume for "
                     + ", ".join(sorted(set(c.strip() for c in fallback_cities)))
                     + " — used broader-location volume, counted once (not per city)")
    return totals, per_city, ("; ".join(notes) or None)


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
                           candidates, max_services, n_cities=1):
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
2b. BALANCE ACROSS SERVICE LINES — this is the rule that most often gets missed.
   Cover the business's WHOLE service range the way their own website menu does:
   no more than 2-3 variants of any one service family unless the business
   description explicitly says that family is the focus. A general dental
   practice gets family dentistry, cleanings, crowns, invisalign, veneers,
   emergency — NOT thirteen implant variants because one seed said "implants".
   Bread-and-butter services beat exotic variants: they carry the demand and
   the client's existing rankings.
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
   LONG-TAIL PHRASING: prefer COMPOUND or QUALIFIED service phrases over bare two-word niches, so the long-tail tier reads as
   genuinely longer than the head terms. Good: "home and auto insurance", "commercial umbrella insurance", "business auto insurance",
   "classic car insurance". Weaker (still valid, but use sparingly): "umbrella insurance", "boat insurance".
   Aim for at least one multi-word compound in the long_tail tier. These must still be real services the business offers —
   never invent a service, and never turn it into a question.
7. VARIETY: these will be crossed with {n_cities} cit{"y" if n_cities == 1 else "ies"}, so you must supply {max_services} DISTINCT services.
   {"Because there are few or no cities to cross against, the variety has to come from the services themselves. Include close variants and qualified forms the way a real proposal does — e.g. for a supplement brand: 'energy gummies', 'electrolyte gummies', 'hydration gummies', 'energy gummies for athletes', 'electrolyte gummies for kids sports', 'best energy gummies'. For a clinic: 'adhd treatment', 'anxiety treatment', 'depression counseling', 'couples therapy', 'family therapy', 'mental health clinic', 'behavioral health services'. Synonyms, sub-services, audience qualifiers and 'best X' forms all count as distinct services." if n_cities <= 2 else "With several cities to cross against, keep the services broad and distinct rather than near-duplicates."}

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


def services_needed(n_cities):
    """How many services to generate so services x cities lands near the target
    keyword count. Few cities -> many services (a one-metro client needs service
    variety); many cities -> fewer services (the crossing supplies the volume)."""
    import math
    target = CFG.get("grid_target_keywords", 32)
    lo, hi = CFG.get("grid_min_services", 4), CFG.get("grid_max_services", 20)
    n = max(int(n_cities), 1)
    return max(lo, min(hi, math.ceil(target / n)))


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
        # Probe with the state suffix so ambiguous names resolve to the RIGHT
        # place: bare "insurance washington" matches Washington State/DC, and
        # "insurance jersey" matches New Jersey — which would rank tiny Virginia
        # towns above real metros. "insurance washington va" scores correctly.
        abbr = STATE_ABBREV.get((state or "").strip().lower(), "")
        sfx = f" {abbr}" if abbr else ""
        probe = [f"insurance {c.lower()}{sfx}" for c in cities][:700]
        payload = [{"keywords": probe,
                    "location_name": loc_string(cities, state),
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        items = (data.get("tasks") or [{}])[0].get("result") or []
        vol = {(it.get("keyword") or "").lower(): (it.get("search_volume") or 0)
               for it in items}
        ranked = sorted(cities,
                        key=lambda c: vol.get(f"insurance {c.lower()}{sfx}", 0),
                        reverse=True)
        return ranked[:limit]
    except Exception:
        return cities[:limit]


def build_grid(services, markets, state, prepicked=False):
    """Cross each SERVICE with each CITY, in the proposal format
    ('auto insurance fairfax va'). The tier comes from the service, so every
    city inherits it. Returns {ultra:[], competitive:[], long_tail:[]}."""
    cities = list(markets) if prepicked else pick_grid_cities(markets, state, CFG["grid_max_cities"])
    suffix_mode = CFG.get("grid_state_suffix", "auto")
    buckets = {"ultra": [], "competitive": [], "long_tail": []}

    def city_suffix(city_lower, city_state):
        """Brendan suffixes small/ambiguous cities but not well-known metros:
        'auto insurance alexandria va' and 'adult autism services hyde pa', but
        'adhd treatment san diego' and 'deck repair knoxville'. CITY_STATE holds
        the recognizable metros, so membership is a good proxy for 'needs no
        disambiguation'. Each city uses ITS OWN state — a tri-state footprint
        gets 'cherry hill nj' and 'wilmington de' in the same grid."""
        ab = STATE_ABBREV.get((city_state or "").strip().lower(), "")
        if not ab:
            return ""
        if suffix_mode is False or suffix_mode == 0:
            return ""
        if suffix_mode is True or suffix_mode == 1:
            return f" {ab}"
        return "" if city_lower in CITY_STATE else f" {ab}"   # auto
    for s in services:
        svc, tier = s["service"], s["tier"]
        if not cities:                     # nationwide: no crossing
            buckets[tier].append({"keyword": svc, "volume": 0,
                                  "src": "grid", "origin": "added", "service": svc})
            continue
        for city in cities:
            c_name, c_state = parse_market(city, state)
            c = c_name.strip().lower()
            svc_l = f" {svc.lower()} "
            # DMO-style seeds carry the destination INSIDE the service ("things
            # to do in central pa") — appending the market again produces
            # "central pa pennsylvania". If the service already contains this
            # market, its state name, or ends with the state abbr, keep the
            # service as-is for this crossing.
            st_of_market = (c_state or "").strip().lower() or (c if c in STATE_ABBREV else "")
            ab = STATE_ABBREV.get(st_of_market, "")
            already = (f" {c} " in svc_l
                       or (st_of_market and f" {st_of_market}" in svc_l.rstrip())
                       or (ab and svc.lower().rstrip().endswith(" " + ab)))
            if already:
                kw = svc
            else:
                # don't append the state if the "city" IS the state
                sfx = "" if (c_state and c == c_state.strip().lower()) else city_suffix(c, c_state)
                kw = f"{svc} {c}{sfx}".strip()
            if any(r["keyword"] == kw for r in buckets[tier]):
                continue                      # same term from two crossings
            buckets[tier].append({"keyword": kw,
                                  "volume": 0, "src": "grid",
                                  "origin": "added", "service": svc, "city": c})
    return buckets


def claude_refine_keywords(seeds, markets, brand, domain, candidates,
                           site_terms, business_desc="", site_pages=None,
                           state=""):
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
7. BALANCE THE VOCABULARY: the ultra/competitive buckets must carry the everyday words customers actually type (for a therapy practice: "therapist [city]", "therapy [city]", "counseling [city]", "mental health services [city]") — these hold the search volume. Clinical, technical, or page-template phrasings ("[condition] treatment [city]") belong in long_tail, and no single template word should dominate the list. If the seeds themselves are templated, FIX the vocabulary rather than propagating it.
8. Bucket by ranking difficulty: "ultra" (hardest/highest value), "competitive" (moderate), "long_tail" (longer/question-style).
9. Do NOT invent search volumes. Only real, searchable terms.

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
                   ultra, competitive, long_tail, site_terms_kw, phrase_geos=None):
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
        # Decide the city set FIRST so the service count can scale to it.
        cities = pick_grid_cities(markets, state, CFG["grid_max_cities"])
        # Search-phrase geos ("south jersey", "fox cities") cross into keyword
        # TEXT exactly like cities, but never touch a location API — no volume
        # lookup, no validation, no rank-check location. Keeps Brendan-style
        # regional phrasing without the invalid-location fallout.
        phrases = [p.strip() for p in (phrase_geos or []) if p and p.strip()]
        seen_c = {c.strip().lower() for c in cities}
        grid_cities = cities + [p for p in phrases if p.lower() not in seen_c]
        n_services = services_needed(len(grid_cities))
        services = claude_expand_services(seeds, biz, site_pages, brand, domain,
                                          cands, n_services, len(cities))
        if not services:
            # fall back to the partner's seeds, spread across tiers
            tiers = ["ultra", "ultra", "competitive", "long_tail"]
            services = [{"service": s.strip().lower(), "tier": tiers[min(i, 3)]}
                        for i, s in enumerate(seeds[:n_services])]
        g = build_grid(services, grid_cities, state, prepicked=True)
        full = g["ultra"] + g["competitive"] + g["long_tail"]
        # Volume: look up the BARE service term AT THE CLIENT'S MARKET (the
        # geo-modified forms report ~0). The same figure is shown on each city
        # row for that service, so pricing must count it ONCE PER SERVICE — not
        # once per row — or a 10-city grid would inflate volume 10x.
        svc_names = list(dict.fromkeys([s["service"] for s in services]))
        vols, per_city, vol_err = fetch_local_volume(svc_names, cities, state)
        for r in full:
            svc_l = (r.get("service") or "").lower()
            city_l = (r.get("city") or "").lower()
            # the row shows ITS OWN city's volume; pricing uses the summed total
            v = per_city.get((city_l, svc_l))
            if v is None:
                v = vols.get(svc_l)
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
            "volume_error": vol_err,
            "volume_location": loc_string(markets, state),
            "state_missing": bool(cities) and not state
                             and not any(market_state(c)
                                         or c.strip().lower() in STATE_ABBREV
                                         for c in cities),
            "grid_cities": cities,
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

def _strip_markets(kw, markets, state=None):
    """Remove the trailing geo modifier so we can look up bid/difficulty data,
    which the APIs key to the bare term ('adhd treatment'), not the geo form
    ('adhd treatment san diego'). Grid keywords may also carry a state suffix
    ('commercial contractor kaukauna wi'), so strip that FIRST — otherwise the
    city never matches the end of the string and nothing gets stripped, which
    silently kills the bid lookup."""
    k = kw
    # Strip whichever state abbr this keyword carries — in a multi-state grid
    # different keywords end in different abbrs (nj / pa / de).
    abbrs = set()
    if state:
        a = STATE_ABBREV.get(state.strip().lower(), "")
        if a: abbrs.add(a)
    for m in markets:
        a = STATE_ABBREV.get((market_state(m, state) or "").lower(), "")
        if a: abbrs.add(a)
    for a in abbrs:
        if k.lower().endswith(" " + a):
            k = k[: -(len(a) + 1)].strip()
            break
    # Then strip the city — match on the parsed city name, not the raw
    # "Cherry Hill, NJ" pill text.
    city_names = sorted({market_city(m, state) for m in markets}, key=len, reverse=True)
    for c in city_names:
        if c and k.lower().endswith(" " + c.lower()):
            k = k[: -(len(c) + 1)].strip()
            break
    return k

def stage3_metrics(head, markets, state):
    geo_kws = [r["keyword"] for r in head]
    if not geo_kws:
        return {"adder": 0, "median_score": 0, "bids": {}, "cpc": {}, "kd": {}}
    # Map each geo head term -> its bare form; query metrics on the bare forms
    # (which have real bid/difficulty data), then attribute results to both keys.
    bare_of = {g: _strip_markets(g, markets, state) for g in geo_kws}
    bare_unique = list(dict.fromkeys(bare_of.values()))

    # Google Ads bid data is sparse at small-city granularity (e.g. Kaukauna, WI
    # returns no rows even for real terms). Advertiser demand for the adder
    # doesn't need city precision, so fall back city -> state -> US and report
    # which level actually supplied the data.
    primary_loc = loc_string(markets, state)
    loc_chain = [primary_loc]
    if state and f"{state},United States" not in loc_chain:
        loc_chain.append(f"{state},United States")
    if "United States" not in loc_chain:
        loc_chain.append("United States")
    bid_err = None
    items = []
    bid_loc_used = primary_loc
    for _loc in loc_chain:
        payload = [{"keywords": bare_unique,
                    "location_name": _loc,
                    "language_code": "en"}]
        try:
            data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
            task0 = (data.get("tasks") or [{}])[0]
            # DataForSEO reports per-task problems in status_code/status_message
            # even on an HTTP 200, so surface those rather than returning nothing.
            if task0.get("status_code") not in (20000, None):
                bid_err = f"{task0.get('status_code')}: {task0.get('status_message')}"
                continue
            got = (task0.get("result") or [])
            if got and not items:
                items = got            # keep the first non-empty result set
                bid_loc_used = _loc
            # only stop early if this level actually carries bid values
            if got and any((it.get("high_top_of_page_bid") or 0) for it in got):
                items = got
                bid_loc_used = _loc
                bid_err = None
                break
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
            # Piecewise: $/CPC at the normal rate up to the knee, then a much
            # steeper rate above it. Brendan's premium grows super-linearly with
            # CPC — dental ($18) +$400 over card, Waytek ($60) +$500, Rockingham
            # ($121, insurance carrier) +$2,500. A single multiplier can't fit
            # both ends; the knee can.
            knee = CFG.get("cpc_adder_knee", 50.0)
            raw = (min(med_cpc, knee) * CFG.get("cpc_adder_mult", 3.0)
                   + max(0.0, med_cpc - knee) * CFG.get("cpc_adder_mult_high", 14.0))
            capped = min(raw, CFG.get("cpc_adder_cap", 1500))
            adder = int(round(capped / 50.0) * 50)
            adder_basis = "cpc"
        else:
            adder = 0
            adder_basis = "cpc"
    return {"adder": adder, "adder_basis": adder_basis, "cpc_used": cpc_used,
            "flat_adder": flat_adder,
            "bid_error": bid_err,
            "bid_location": bid_loc_used,
            "bid_location_fallback": (bid_loc_used != primary_loc),
            "bid_terms_queried": bare_unique[:8],
            "n_markets": len(markets),
            "median_score": median_score, "bids": bids, "cpc": cpc,
            "bid_stats": bid_stats, "breaks": [lo, hi],
            "kd": kd, "median_kd": median_kd, "kd_error": kd_err}

# ---------------------------------------------------------------------------
# STAGE 3b — rank check -> table + zero-ranking + PAA
# ---------------------------------------------------------------------------
def _serp_one(kw, domain_dom, markets, state, brand, top_n, deadline=None):
    """One keyword's SERP call. Returns (position_or_None, [paa questions]).
    Depth tracks top_n (<=100 is one DataForSEO unit either way). Works within a shared batch DEADLINE: the
    platform kills any request near ~30s, so retrying past the budget doesn't
    save this keyword — it kills the WHOLE batch, failing keywords that had
    already finished. Better to fail one fast and let the retry pass get it."""
    depth = max(top_n, 10)
    payload = [{"keyword": kw, "location_name": loc_string(markets, state),
                "language_code": "en", "depth": depth}]
    last_err = None
    for attempt in range(2):
        remaining = (deadline - time.time()) if deadline else 20
        if remaining < 4:
            raise last_err or TimeoutError("rank-check batch budget exhausted")
        tmo = min(14 if attempt == 0 else remaining - 1, remaining, 20)
        try:
            # /regular, not /advanced: organic-only, ~10x smaller JSON. Depth-100
            # advanced responses are megabyte-scale and parsing 20 of them
            # serializes on Render free tier's 0.1 vCPU; regular is also cheaper.
            # Cost: no PAA items — only ever used for the non-grid long-tail
            # top-up, an acceptable trade.
            data = dfs_post("/serp/google/organic/live/regular", payload, timeout=tmo)
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
                 pct_not_ranking=None, total_volume=None, base_override=None,
                 ecommerce=False, industry="", ai_search=False):
    if markup_pct is None:
        markup_pct = CFG["default_markup_pct"]
    m = 1.0 + (markup_pct / 100.0)
    anchor = CFG["geo_anchor"][band]                       # hard cost

    # --- volume-based add: fixed $ for volume above the normalized baseline ---
    vol_add = 0
    if total_volume is not None:
        vol_add = _volume_dollar_add(total_volume, CFG.get("vol_free_below", 10000),
                                     CFG.get("volume_brackets", []))
        cap = CFG.get("volume_add_cap")
        if cap:
            vol_add = min(vol_add, cap)

    # Base before % uplift = anchor + competitive adder + volume $ add.
    base_pre = anchor + adder + vol_add
    # Resolve industry rule (substring match against RZ-fed industry text);
    # the legacy ecommerce flag maps to the ecommerce rule.
    rule_key, rule = None, None
    ind = (industry or "").strip().lower()
    # The industry field is multi-select (values joined with " | "), so
    # several rules can match at once. Precedence: the STRONGEST card wins
    # (largest anchor_add) — a hospital that also sells products online is
    # priced as a hospital, not as a shop.
    _matches = [(k, r) for k, r in CFG.get("industry_pricing", {}).items() if k in ind]
    if _matches:
        rule_key, rule = max(_matches, key=lambda kr: int(kr[1].get("anchor_add", 0)))
    if rule is None and ecommerce:
        rule_key, rule = "ecommerce", CFG.get("industry_pricing", {}).get("ecommerce")
    if rule:
        base_pre += int(rule.get("anchor_add", 0))

    # Extras suppression: nationwide service clients (the anchor already
    # prices national scope — see CFG note) and industry rules that price on
    # organization size rather than SERP signals (extras_off).
    nw_service = (band == "nationwide" and rule is None)
    extras_off = nw_service or bool(rule and rule.get("extras_off"))
    _mult = float(CFG.get("nationwide_service_extras", 0.0)) if nw_service else 0.0
    if extras_off and vol_add:
        base_pre -= vol_add
        vol_add = int(round(vol_add * _mult))
        base_pre += vol_add

    # --- tiered zero-ranking uplift (% of head terms not ranking) ---
    zr_uplift = 0
    if pct_not_ranking is not None:
        zr_uplift = _tier_uplift(pct_not_ranking, CFG.get("zero_ranking_tiers", []))
    elif zero_ranking:
        zr_uplift = CFG.get("zero_ranking_tiers", [[0, 0]])[0][1]
    if extras_off and zr_uplift:
        zr_uplift = zr_uplift * _mult

    # MANUAL OVERRIDE: set the hard base directly; the ladder recomputes from it.
    manual_base = base_override is not None and str(base_override) != ""
    if manual_base:
        base = r50(float(base_override))
        zr_uplift = 0; vol_add = 0
    else:
        base = r50(base_pre * (1.0 + zr_uplift / 100.0))

    flat = CFG.get("tier_step_flat")
    if manual_base:
        # A manual override is the operator setting a Brendan-style base
        # directly — his premium cards ($3,950/$5,450/$6,950: Serene, Skidmore)
        # step at 38% of base, so the override ladder should too. Overriding to
        # ~$2,930 hard reproduces that card's upper tiers exactly at 35%.
        step = r50(base * CFG["step_ratio"])
    elif rule and rule.get("step_mode") == "ratio":
        # these ladders step proportionally (Brendan's ecom quote: 38% steps)
        step = r50(base * CFG["step_ratio"])
    elif band == "nationwide":
        # Brendan's national ladder also steps proportionally — $1,500 client
        # on a $3,950 base = the same 38% ratio (Skidmore, 2026-07-20)
        step = r50(base * CFG["step_ratio"])
    elif flat:
        # flat floor, scaling with base for premium clients: Brendan steps
        # ~$950 client on standard quotes but ~$1,300 on his biggest ladder —
        # roughly a quarter of the hard base once the base outgrows the floor.
        pct = CFG.get("tier_step_pct_of_base", 0.24)
        step = max(r50(flat), r50(base * pct))
    else:
        step = r50(base * CFG["step_ratio"])
    hard = {"base": base, "intermediate": base + step, "advanced": base + 2*step}

    client_base = r50(base * m)
    floor = CFG.get("client_floor", 0)
    floored = False
    if floor and client_base < floor:
        client_base = floor
        floored = True
        cstep = r50(step * m) if CFG.get("tier_step_flat") else r50(client_base * CFG["step_ratio"])
        client = {"base": client_base,
                  "intermediate": client_base + cstep,
                  "advanced": client_base + 2*cstep}
    else:
        client = {k: r50(v * m) for k, v in hard.items()}

    # Core SEO + AI Search: GEO quoted at ai_search_uplift_pct of the Core SEO
    # price, added on top — reported per tier so the quote shows the breakdown.
    ai = None
    if ai_search:
        if CFG.get("geo_pricing_mode", "card") == "card":
            card = CFG.get("geo_card", {})
            card_list = CFG.get("geo_card_list", card)
            ai = {"mode": "card",
                  "min_term_months": CFG.get("geo_min_term_months", 12),
                  "client_add":  {k: int(card.get(k, 0)) for k in client},
                  "client_list": {k: int(card_list.get(k, 0)) for k in client},
                  "hard_add":    {k: r50(int(card.get(k, 0)) / m) for k in client}}
        else:
            pct = CFG.get("ai_search_uplift_pct", 75) / 100.0
            ai = {"mode": "pct",
                  "uplift_pct": CFG.get("ai_search_uplift_pct", 75),
                  "hard_add":   {k: r50(v * pct) for k, v in hard.items()},
                  "client_add": {k: r50(v * pct) for k, v in client.items()}}
        ai["hard_total"]   = {k: hard[k] + ai["hard_add"][k] for k in hard}
        ai["client_total"] = {k: client[k] + ai["client_add"][k] for k in client}

    hard_addon   = {k: r50(v * CFG["addon_market_ratio"]) for k, v in hard.items()}
    client_addon = {k: r50(v * CFG["addon_market_ratio"]) for k, v in client.items()}
    return {"anchor": anchor, "base": base, "base_pre_uplift": base_pre, "step": step,
            "industry_rule": rule_key,
            "industry_anchor_add": int(rule.get("anchor_add", 0)) if rule else 0,
            "ai_search": ai,
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
    flat = CFG.get("tier_step_flat")
    if manual_base:
        # A manual override is the operator setting a Brendan-style base
        # directly — his premium cards ($3,950/$5,450/$6,950: Serene, Skidmore)
        # step at 38% of base, so the override ladder should too. Overriding to
        # ~$2,930 hard reproduces that card's upper tiers exactly at 35%.
        step = r50(base * CFG["step_ratio"])
    elif rule and rule.get("step_mode") == "ratio":
        # these ladders step proportionally (Brendan's ecom quote: 38% steps)
        step = r50(base * CFG["step_ratio"])
    elif band == "nationwide":
        # Brendan's national ladder also steps proportionally — $1,500 client
        # on a $3,950 base = the same 38% ratio (Skidmore, 2026-07-20)
        step = r50(base * CFG["step_ratio"])
    elif flat:
        # flat floor, scaling with base for premium clients: Brendan steps
        # ~$950 client on standard quotes but ~$1,300 on his biggest ladder —
        # roughly a quarter of the hard base once the base outgrows the floor.
        pct = CFG.get("tier_step_pct_of_base", 0.24)
        step = max(r50(flat), r50(base * pct))
    else:
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
        p  = stage4_price(band, m3["adder"], r3["zero_ranking"], addon,
                          ecommerce=bool(d.get("ecommerce")),
                          industry=(d.get("industry") or ""),
                          ai_search=bool(d.get("ai_search")))
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
    # CPC and keyword difficulty stay ON SCREEN for the reviewer but out of the
    # export — the CSV travels into proposals, and internal pricing signals
    # don't belong in a client-facing artifact.
    w.writerow(["Keyword", "Current Google Rank", "Competitiveness"])
    for r in rows:
        w.writerow([r.get("kw", ""), r.get("rank", ""), r.get("comp", "")])
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
    phrase_geos = [p.strip() for p in d.get("phrase_geos", []) if p and p.strip()]
    # rebuild bucket rows from what the frontend sends back (kw + vol)
    def rows(key):
        return [{"keyword": x["kw"], "volume": x.get("vol", 0), "src": "build"}
                for x in d.get(key, []) if x.get("kw")]
    ultra, competitive, long_tail = rows("ultra"), rows("competitive"), rows("long_tail")
    try:
        s1 = stage1b_refine(seeds, markets, state, brand, domain, business_desc,
                            ultra, competitive, long_tail, site_terms_kw, phrase_geos)
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
        "volume_error": s1.get("volume_error"),
        "volume_location": s1.get("volume_location"),
        "state_missing": s1.get("state_missing", False),
        "grid_cities": s1.get("grid_cities", []),
    })

@app.route("/api/metrics", methods=["POST"])
def api_metrics():
    """Step 2 — competitive adder from head-term bids. One search_volume call."""
    d = request.get_json(force=True)
    head    = [{"keyword": k} for k in d.get("head", [])]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    # phrase geos must be strippable so bare-term metrics resolve for
    # "managed it services south jersey" -> "managed it services"
    markets = markets + [p.strip() for p in d.get("phrase_geos", []) if p and p.strip()]
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

def _serp_parse_items(items, domain_dom, brand):
    """Shared SERP parsing for live + task modes: first organic position for
    the client domain, plus People-Also-Ask questions (brand-mention filtered)."""
    pos, paa = None, []
    for it in items or []:
        if it.get("type") == "organic" and domain_dom and domain_dom in (it.get("domain") or ""):
            if pos is None:
                pos = it.get("rank_absolute")
        if it.get("type") == "people_also_ask":
            for el in it.get("items", []):
                q = el.get("title")
                if q and (brand or "").lower() not in q.lower():
                    paa.append(q)
    return pos, paa


@app.route("/api/rankings_submit", methods=["POST"])
def api_rankings_submit():
    """Step 3, async mode — submit ALL rank lookups as DataForSEO tasks in one
    call. Task mode has no 30s wall: the platform ceiling only ever killed us
    because LIVE lookups block while Google is crawled. Tasks queue server-side
    and the frontend polls /api/rankings_collect until they land."""
    d = request.get_json(force=True)
    kws     = [k for k in d.get("keywords", []) if k]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    top_n   = CFG["zero_ranking_top_n"]
    depth   = max(top_n, 10)
    loc     = loc_string(markets, state)
    payload = [{"keyword": kw, "location_name": loc, "language_code": "en",
                "depth": depth, "priority": 2, "tag": kw[:255]} for kw in kws]
    try:
        data = dfs_post("/serp/google/organic/task_post", payload, timeout=25)
    except Exception as e:
        return jsonify({"error": f"task submit failed: {e}"}), 502
    out = []
    for t in (data.get("tasks") or []):
        kw = ((t.get("data") or {}).get("keyword")) or ((t.get("data") or {}).get("tag")) or ""
        if t.get("status_code") in (20100, 20000) and t.get("id"):
            out.append({"kw": kw, "task_id": t["id"]})
        else:
            out.append({"kw": kw, "task_id": None,
                        "error": f"{t.get('status_code')}: {t.get('status_message')}"})
    return jsonify({"tasks": out})


@app.route("/api/rankings_collect", methods=["POST"])
def api_rankings_collect():
    """Poll pending rank tasks. Returns done rows (same shape as /api/rankings)
    and the still-pending task list to poll again."""
    d = request.get_json(force=True)
    tasks  = d.get("tasks", [])
    domain = (d.get("domain") or "").strip()
    brand  = (d.get("brand") or "").strip()
    dom = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    top_n = CFG["zero_ranking_top_n"]
    done, pending, paa = [], [], []

    def one(t):
        data = dfs_post(f"/serp/google/organic/task_get/regular/{t['task_id']}",
                        None, timeout=12, method="GET")
        task0 = (data.get("tasks") or [{}])[0]
        sc = task0.get("status_code")
        if sc == 20000:
            res = (task0.get("result") or [{}])[0]
            pos, qs = _serp_parse_items(res.get("items") or [], dom, brand)
            return ("done", pos, qs)
        if sc in (40601, 40602, 40100):      # queued / in progress
            return ("pending", None, [])
        return ("error", None, [])

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(one, t): t for t in tasks if t.get("task_id")}
        results = {}
        for fut in futs:
            t = futs[fut]
            try:
                results[t["kw"]] = fut.result()
            except Exception:
                results[t["kw"]] = ("pending", None, [])   # transient: poll again
    for t in tasks:
        if not t.get("task_id"):
            done.append({"kw": t["kw"], "pos": "—", "ranked_top": False, "error": True})
            continue
        status, pos, qs = results.get(t["kw"], ("pending", None, []))
        if status == "done":
            done.append({"kw": t["kw"],
                         "pos": (pos if pos is not None else "Not Found"),
                         "ranked_top": (pos is not None and pos <= top_n),
                         "error": False})
            paa.extend(qs)
        elif status == "error":
            done.append({"kw": t["kw"], "pos": "—", "ranked_top": False, "error": True})
        else:
            pending.append(t)
    return jsonify({"done": done, "pending": pending, "paa": paa[:40]})


# (kw, location, domain, top_n) -> (pos, ts). In-memory: 1 gunicorn worker,
# so every request sees it; restarts just mean a cold cache. TTL keeps a
# calibration session fast without ever serving stale-day rankings.
RANK_CACHE = {}
RANK_CACHE_TTL = 6 * 3600
RANK_CACHE_MAX = 8000
_rank_cache_lock = threading.Lock()

def _rank_cache_get(kw, loc, dom, top_n):
    with _rank_cache_lock:
        ent = RANK_CACHE.get((kw, loc, dom, top_n))
    if ent and time.time() - ent[1] < RANK_CACHE_TTL:
        return ent[0]
    return "MISS"

def _rank_cache_put(kw, loc, dom, top_n, pos):
    with _rank_cache_lock:
        if len(RANK_CACHE) > RANK_CACHE_MAX:
            RANK_CACHE.clear()
        RANK_CACHE[(kw, loc, dom, top_n)] = (pos, time.time())

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
    loc = loc_string(markets, state)
    results, paa = [], []
    hits = {}
    to_fetch = []
    for kw in batch:
        c = _rank_cache_get(kw, loc, dom, top_n)
        if c != "MISS":
            hits[kw] = c
        else:
            to_fetch.append(kw)
    try:
        with ThreadPoolExecutor(max_workers=CFG["rank_check_workers"]) as ex:
            batch_deadline = time.time() + 24   # stay well under the ~30s platform kill
            futs = {ex.submit(_serp_one, kw, dom, markets, state, brand, top_n,
                              batch_deadline): kw for kw in to_fetch}
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
                if not err:
                    _rank_cache_put(kw, loc, dom, top_n, pos)
        for kw in batch:
            if kw in hits:
                pos, qs, err = hits[kw], [], False
            else:
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
                     base_override=base_override, ecommerce=bool(d.get("ecommerce")),
                     industry=(d.get("industry") or ""),
                     ai_search=bool(d.get("ai_search")))
    return jsonify({"anchor": p["anchor"], "adder": adder,
                    "industry_rule": p.get("industry_rule"),
                    "industry_anchor_add": p.get("industry_anchor_add", 0),
                    "ai_search": p.get("ai_search"),
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
        "industry_pricing": CFG.get("industry_pricing", {}),
        "competitive_adder": CFG["competitive_adder"],
        "bid_score_breaks": CFG["bid_score_breaks"],
        "cpc_adder_enabled": CFG.get("cpc_adder_enabled", True),
        "cpc_adder_mult": CFG.get("cpc_adder_mult", 3.0),
        "cpc_adder_cap": CFG.get("cpc_adder_cap", 1500),
        "cpc_adder_knee": CFG.get("cpc_adder_knee", 62.0),
        "cpc_adder_mult_high": CFG.get("cpc_adder_mult_high", 14.0),
        "tier_step_pct_of_base": CFG.get("tier_step_pct_of_base", 0.24),
        "ecom_anchor_add": CFG.get("ecom_anchor_add", 250),
        "geo_pricing_mode": CFG.get("geo_pricing_mode", "card"),
        "geo_card": CFG.get("geo_card", {}),
        "geo_min_term_months": CFG.get("geo_min_term_months", 12),
        "cpc_adder_free_below": CFG.get("cpc_adder_free_below", 5.0),
        "zero_ranking_bonus": CFG["zero_ranking_bonus"],
        "zero_ranking_top_n": CFG["zero_ranking_top_n"],
        "zero_ranking_frac": CFG["zero_ranking_frac"],
        "zero_ranking_tiers": CFG.get("zero_ranking_tiers", []),
        "vol_free_below": CFG.get("vol_free_below", 10000),
        "volume_brackets": CFG.get("volume_brackets", []),
        "step_ratio": CFG["step_ratio"],
        "tier_step_flat": CFG.get("tier_step_flat"),
        "volume_add_cap": CFG.get("volume_add_cap"),
        "client_floor": CFG["client_floor"],
        "addon_market_ratio": CFG["addon_market_ratio"],
        "default_markup_pct": CFG["default_markup_pct"],
        "ultra_bucket_size": CFG["ultra_bucket_size"],
        "grid_mode": CFG.get("grid_mode", True),
        "grid_target_keywords": CFG.get("grid_target_keywords", 32),
        "grid_min_services": CFG.get("grid_min_services", 4),
        "grid_max_services": CFG.get("grid_max_services", 20),
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
        for key, caster in [("grid_target_keywords", int), ("grid_min_services", int),
                            ("grid_max_services", int), ("grid_max_cities", int)]:
            if key in d and d[key] not in (None, ""):
                CFG[key] = caster(d[key])
        for key, caster in [("zero_ranking_bonus", int), ("zero_ranking_top_n", int),
                            ("zero_ranking_frac", float), ("step_ratio", float),
                            ("client_floor", int), ("addon_market_ratio", float),
                            ("default_markup_pct", float), ("ultra_bucket_size", int),
                            ("competitive_bucket_size", int), ("longtail_target", int),
                            ("cpc_adder_mult", float), ("cpc_adder_cap", int),
                            ("cpc_adder_free_below", float), ("cpc_adder_knee", float),
                            ("cpc_adder_mult_high", float), ("tier_step_pct_of_base", float),
                            ("ecom_anchor_add", int)]:
            if key in d and d[key] not in (None, ""):
                CFG[key] = caster(d[key])
        # Nullable knobs: empty/0 disables (flat step falls back to step_ratio;
        # no cap means volume brackets run uncapped).
        for key in ("tier_step_flat", "volume_add_cap"):
            if key in d:
                v = d[key]
                CFG[key] = None if v in (None, "", "null", 0, "0") else int(float(v))
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
_LOCATIONS_CACHE = {"names": None}

def dfs_get(path, timeout=60):
    login = os.environ.get("DFS_LOGIN", "")
    pw    = os.environ.get("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    resp = requests.get(BASE + path,
                        headers={"Authorization": f"Basic {token}"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def us_location_names():
    """All US location_names DataForSEO recognises, cached for the process.
    Used to validate the cities a partner typed BEFORE spending API calls on a
    misspelling (e.g. 'Kakuana' should be 'Kaukauna')."""
    if _LOCATIONS_CACHE["names"] is not None:
        return _LOCATIONS_CACHE["names"]
    try:
        data = dfs_get("/keywords_data/google_ads/locations/us")
        items = (data.get("tasks") or [{}])[0].get("result") or []
        names = [it.get("location_name", "") for it in items if it.get("location_name")]
        _LOCATIONS_CACHE["names"] = names
        return names
    except Exception:
        _LOCATIONS_CACHE["names"] = []
        return []


def validate_cities(cities, state):
    """Check each entered city resolves to a real DataForSEO location in the
    chosen state. Returns [{city, ok, resolved, suggestions[]}]. Suggestions use
    close-match scoring so a typo surfaces the intended city."""
    import difflib
    names = us_location_names()
    out = []
    if not names:
        return [{"city": c, "ok": None, "resolved": "", "suggestions": []} for c in cities]
    for c in cities:
        c_name, c_state = parse_market(c, state)
        state_l = (c_state or "").strip().lower()
        in_state = [n for n in names if state_l and f",{state_l}," in n.lower()] if state_l else names
        city_only = {}
        for n in in_state:
            first = n.split(",")[0].strip().lower()
            city_only.setdefault(first, n)
        cl = c_name.strip().lower()
        if cl in STATE_ABBREV:            # a state used AS a geo ("delaware")
            out.append({"city": c, "ok": True, "kind": "state",
                        "resolved": f"{cl.title()},United States", "suggestions": []})
        elif cl in city_only:
            out.append({"city": c, "ok": True, "kind": "city",
                        "resolved": city_only[cl], "suggestions": []})
        else:
            close = difflib.get_close_matches(cl, list(city_only.keys()), n=3, cutoff=0.72)
            if close:                     # probably a typo of a real city
                out.append({"city": c, "ok": False, "kind": "typo", "resolved": "",
                            "suggestions": [city_only[m] for m in close]})
            else:                         # regional phrase ("south jersey") —
                                          # legit in keyword TEXT, not a location
                out.append({"city": c, "ok": True, "kind": "phrase",
                            "resolved": "", "suggestions": []})
    return out


@app.route("/api/validate_geo", methods=["POST"])
def api_validate_geo():
    d = request.get_json(force=True)
    cities = [c.strip() for c in d.get("geo_values", []) if c.strip()]
    state  = (d.get("state") or "").strip()
    if not cities:
        return jsonify({"error": "No cities to check."}), 400
    try:
        return jsonify({"state": state, "results": validate_cities(cities, state)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def claude_menu_to_terms(labels, brand, domain, seeds, business_desc):
    """Convert raw nav-menu labels into search-phrase service terms. A menu
    says 'Healthcare' or 'Warehouse'; a searcher types 'healthcare construction
    company'. Returns {label: term_or_None} — None means drop it (careers,
    press, process pages). Empty dict when the AI isn't available, so the
    caller can fall back to raw labels."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not labels:
        return {}
    prompt = f"""These are navigation menu labels scraped from a business's website. Convert each into the search phrase a potential CUSTOMER would type into Google when looking for that service from this kind of business.

BUSINESS: {brand or "(unknown)"} — {domain}
WHAT THEY DO: {business_desc or "(infer from the labels and any seeds)"}
EXISTING SEED TERMS: {", ".join(seeds) if seeds else "(none)"}

MENU LABELS: {json.dumps(labels, ensure_ascii=False)}

Rules:
- Sector/industry labels get the core service appended: for a commercial builder, "Healthcare" -> "healthcare construction company", "Self-Storage" -> "self storage construction".
- Labels that already read like a service ("Commercial Construction") may pass through nearly as-is, normalized to how people search.
- USE THE CUSTOMER'S VOCABULARY, not the site's page template. If most labels share one template word (a menu of "X Treatment & Therapy" condition pages, "Y Repair Services" pages), do NOT echo that word into every term — a person with anxiety types "anxiety therapist" or "anxiety therapy", not "anxiety treatment therapy". Vary the phrasing to match real searches.
- When the labels are all variations of ONE parent service (conditions, specialties, sub-services), ALSO make sure the parent's everyday head terms are represented — the bread-and-butter words customers actually type ("therapist", "therapy", "counseling", "mental health clinic" for a behavioral-health practice) — by mapping the most general labels to those instead of to another templated variant.
- Map to null anything that is NOT a purchasable service: careers, press, blog, media, "our process", team pages, generic CTAs.
- Lowercase, no geo, 2-5 words each.

Return ONLY a JSON object mapping every input label to its search phrase or null. No preamble, no markdown fences."""
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 1500, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=25)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {k: (v.strip().lower() if isinstance(v, str) and v.strip() else None)
                    for k, v in parsed.items()}
    except Exception:
        pass
    return {}


class _NavLinkParser(HTMLParser):
    """Collect anchor text from the page, tracking whether each link sits inside
    menu context. Menu structure is the signal: businesses list the services
    they actually sell in their navigation. Menu context means a semantic
    <nav>/<header> OR any element whose class/id contains nav|menu — WordPress
    themes and page builders routinely skip the semantic tags and ship
    <div class="menu">/<ul id="main-menu"> instead."""
    _NAV = {"nav", "header"}
    _MENUISH = re.compile(r"(?:^|[\s_-])(?:nav|menu)(?:$|[\s_-])|nav(?:bar|igation)|menu[-_]", re.I)
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []          # per open tag: True if it opened menu context
        self.nav_depth = 0
        self._in_a = False
        self._href = ""
        self._buf = []
        self.nav_links, self.other_links = [], []
    _VOID = {"br","img","input","meta","link","hr","area","base","col","embed","source","track","wbr"}
    def _is_menuish(self, tag, attrs):
        if tag in self._NAV: return True
        d = dict(attrs)
        blob = (d.get("class") or "") + " " + (d.get("id") or "") + " " + (d.get("role") or "")
        return bool(self._MENUISH.search(blob)) or (d.get("role") or "").lower() == "navigation"
    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:
            return
        menuish = self._is_menuish(tag, attrs)
        self._stack.append((tag, menuish))
        if menuish: self.nav_depth += 1
        if tag == "a":
            self._in_a = True; self._buf = []
            self._href = (dict(attrs).get("href") or "")
    def handle_endtag(self, tag):
        # pop to the matching open tag (tolerates unclosed tags in the wild)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _t, m in self._stack[i:]:
                    if m and self.nav_depth: self.nav_depth -= 1
                del self._stack[i:]
                break
        if tag == "a" and self._in_a:
            self._in_a = False
            text = " ".join("".join(self._buf).split())
            rec = (text, self._href)
            (self.nav_links if self.nav_depth else self.other_links).append(rec)
    def handle_data(self, data):
        if self._in_a: self._buf.append(data)

_MENU_GENERIC = {
    "home","about","about us","contact","contact us","blog","news","careers",
    "gallery","portfolio","testimonials","reviews","faq","faqs","privacy policy",
    "privacy","terms","terms of use","team","our team","meet the team","locations",
    "location","sitemap","login","log in","search","services","our services",
    "projects","our projects","our work","work","resources","get a quote",
    "request a quote","free quote","free estimate","get started","learn more",
    "read more","view all","see all","menu","español","facebook","instagram",
    "linkedin","twitter","youtube","x",
    "start my career","start my project","our process","approach","our approach","media","blogs",
    "press releases","press","join our team","apply now","employment",
    "history","our history","our story","leadership","safety","awards",
}
_SERVICE_PATH_HINT = re.compile(
    r"/[a-z0-9-]*(?:services?|markets?|sectors?|industr(?:y|ies)|what-we-do|"
    r"capabilit(?:y|ies)|specialt(?:y|ies)|divisions?|expertise|solutions?)"
    r"[a-z0-9-]*(?:/|$)", re.I)

@app.route("/api/site_services", methods=["POST"])
def api_site_services():
    """Parse the client site's navigation into candidate service terms. Menu
    items are how the business describes what it sells — often a better seed
    list than anything a partner types in freehand."""
    d = request.get_json(force=True) or {}
    dom = re.sub(r"^https?://", "", (d.get("domain") or "").strip()).strip("/")
    pasted = (d.get("pasted") or "").strip()
    if not dom and not pasted:
        return jsonify({"error": "Add the client website first."}), 400

    if pasted:
        # Manual escape hatch for sites that block automated access entirely:
        # the partner pastes the menu / service list (one per line or
        # comma-separated) and it runs through the same cleanup + AI conversion
        # as a parsed nav would.
        raw = [p.strip(" \t•·-–—>") for chunk in pasted.splitlines()
               for p in chunk.split(",")]
        out, seen = [], set()
        for t in raw:
            t = re.sub(r"[»›→▸▾▼+]+$", "", t).strip()
            tl = t.lower()
            if not t or tl in _MENU_GENERIC or len(t) > 48 or len(t.split()) > 6:
                continue
            if tl in seen:
                continue
            seen.add(tl)
            out.append({"label": t, "source": "pasted", "service_path": False})
        out = out[:40]
        seeds = [x for x in (d.get("seeds") or []) if isinstance(x, str)]
        mapping = claude_menu_to_terms([x["label"] for x in out],
                                       d.get("brand") or "", dom or "(pasted list)",
                                       seeds, d.get("business_desc") or "")
        ai_used = bool(mapping)
        if ai_used:
            conv, seen_t = [], set()
            for x in out:
                term = mapping.get(x["label"], x["label"].lower())
                if term is None or term in seen_t:
                    continue
                seen_t.add(term); x["term"] = term; conv.append(x)
            out = conv
        else:
            for x in out:
                x["term"] = x["label"].lower()
        return jsonify({"domain": dom, "services": out, "ai_refined": ai_used,
                        "from_sitemap": False, "pasted": True, "n_nav_links": 0})
    # Two identities: some servers stub out bots, others' WAFs block a Chrome UA
    # that lacks full browser fingerprints while allowing honest bots through.
    # Try both per URL and keep whichever returns a page with real links.
    _UAS = [("browser", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            ("bot", "Mozilla/5.0 (compatible; adtini-seo-quote/1.0)")]
    html = ""
    fetch_err = None
    diag = []
    # try both host variants regardless of how the pill was entered — and never
    # double the www. prefix (www.www.example.org is how that bug looks)
    bare = re.sub(r"^www\.", "", dom)
    for url in dict.fromkeys([f"https://{dom}", f"https://{bare}", f"https://www.{bare}"]):
        for ua_name, ua in _UAS:
            try:
                r = requests.get(url, timeout=10, allow_redirects=True,
                                 headers={"User-Agent": ua,
                                          "Accept": "text/html,application/xhtml+xml",
                                          "Accept-Language": "en-US,en;q=0.9"})
                candidate = r.text[:800_000]
                nlinks = candidate.lower().count("<a")
                diag.append(f"{url} [{ua_name}] -> HTTP {r.status_code}, {nlinks} links")
                if nlinks >= 5:
                    html = candidate
                    break
                if not html:
                    html = candidate
            except Exception as e:
                fetch_err = e
                diag.append(f"{url} [{ua_name}] -> {type(e).__name__}")
        if html and html.lower().count("<a") >= 5:
            break
    if not html:
        return jsonify({"error": f"Couldn't fetch the site: {fetch_err}",
                        "diag": diag}), 502
    p = _NavLinkParser()
    try:
        p.feed(html)
    except Exception:
        pass

    # The homepage's own self-description — meta description (or og:description)
    # — is the business's one-line answer to "what are you?", which is exactly
    # what the business-description field wants. Offered as a prefill, never
    # silently applied: it's marketing copy, so a human should glance at it.
    def _meta(name_attr, name_val):
        m = re.search(
            r'<meta[^>]+' + name_attr + r'\s*=\s*["\']' + name_val +
            r'["\'][^>]*content\s*=\s*["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(
                r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]*' + name_attr +
                r'\s*=\s*["\']' + name_val + r'["\']', html, re.I)
        return (m.group(1).strip() if m else "")
    site_desc = _meta("name", "description") or _meta("property", "og:description")
    site_desc = re.sub(r"\s+", " ", site_desc)[:400]

    def _clean(t):
        t = re.sub(r"[»›→▸▾▼+]+$", "", t).strip()
        return t
    def _keep(t, href, require_hint):
        tl = t.lower().strip()
        if not tl or tl in _MENU_GENERIC: return False
        if len(tl) > 48 or len(tl.split()) > 6: return False
        if not re.search(r"[a-z]", tl): return False
        if re.search(r"\d{3}", tl): return False          # phone numbers
        if require_hint and not _SERVICE_PATH_HINT.search(href or ""): return False
        return True

    out, seen = [], set()
    # Pass 1 — links inside <nav>/<header>. Pass 2 — links anywhere on the page
    # whose URL path looks service-ish (/services/, /markets/, /industries/...),
    # which catches sites that render menus without semantic nav tags.
    for links, need_hint, src in ((p.nav_links, False, "menu"),
                                  (p.other_links, True, "page")):
        for text, href in links:
            t = _clean(text)
            if not _keep(t, href, need_hint): continue
            key = t.lower()
            if key in seen: continue
            seen.add(key)
            hinted = bool(_SERVICE_PATH_HINT.search(href or ""))
            out.append({"label": t, "source": src, "service_path": hinted})

    # Pass 2.5 — HEADINGS. Portfolio-style sites (design studios, agencies)
    # run deliberately minimal navs — Work / About / Contact, all generic — and
    # put the actual service taxonomy in on-page section headings ("01.Branding",
    # "02.Packaging Design"). Links can't see those, so when the nav yields
    # nothing, harvest heading + <strong>/<b> text instead. The AI conversion
    # step already drops non-service items, so this can afford to over-collect.
    used_headings = False
    if len(out) < 3:
        raw_heads = re.findall(r"<(h[1-6]|strong|b)\b[^>]*>(.*?)</\1>",
                               html, re.I | re.S)
        import html as _htmlmod
        n_before = len(out)
        for _tag, inner in raw_heads:
            t = re.sub(r"<[^>]+>", " ", inner)          # strip nested tags
            t = _htmlmod.unescape(t)
            t = " ".join(t.split())
            t = re.sub(r"^\s*\d{1,2}\s*[.):\-–—]?\s*", "", t)  # "01.Branding" -> "Branding"
            t = t.strip(" :·•|")
            tl = t.lower()
            if not t or tl in _MENU_GENERIC or tl in seen: continue
            if len(t) > 48 or len(t.split()) > 6: continue
            if not re.search(r"[a-z]", tl): continue
            if re.search(r"\d{3}", tl): continue          # phone numbers
            if re.search(r"[.!?]$", t): continue          # sentences, not labels
            seen.add(tl)
            out.append({"label": t, "source": "heading", "service_path": False})
            if len(out) - n_before >= 15: break
        used_headings = len(out) > n_before

    # Pass 3 — JS-built navs render no anchors in raw HTML. The sitemap is
    # static XML that JavaScript can't hide, and page slugs map to the same
    # service taxonomy a menu would. Same crawler used for business-desc
    # inference; capped at ~5s internally.
    used_sitemap = False
    if len(out) < 3:
        try:
            for topic in fetch_site_pages(dom, limit=30):
                key = topic.lower()
                if key in seen or key in _MENU_GENERIC: continue
                if len(topic) > 48 or len(topic.split()) > 6: continue
                seen.add(key)
                out.append({"label": topic.title(), "source": "sitemap",
                            "service_path": False})
            used_sitemap = len(out) > 0
        except Exception:
            pass
    # service-path links first (strongest signal), then menu order
    out.sort(key=lambda x: (not x["service_path"], x["source"] != "menu"))
    out = out[:40]

    # Convert raw labels into search-phrase terms. "Healthcare" is a menu item,
    # not a search — a customer types "healthcare construction company". Claude
    # sees the whole label set plus business context, so it also drops
    # non-service items the static filter missed. On any failure, raw labels
    # pass through so the feature degrades instead of breaking.
    seeds = [s for s in (d.get("seeds") or []) if isinstance(s, str)]
    mapping = claude_menu_to_terms([s["label"] for s in out],
                                   d.get("brand") or "", dom, seeds,
                                   d.get("business_desc") or site_desc or "")
    ai_used = bool(mapping)
    if ai_used:
        converted, seen_terms = [], set()
        for s in out:
            term = mapping.get(s["label"], s["label"].lower())
            if term is None:
                continue                      # AI says: not a service
            if term in seen_terms:
                continue                      # two labels -> same phrase
            seen_terms.add(term)
            s["term"] = term
            converted.append(s)
        out = converted
    else:
        for s in out:
            s["term"] = s["label"].lower()

    return jsonify({"domain": dom, "services": out,
                    "ai_refined": ai_used, "from_sitemap": used_sitemap,
                    "from_headings": used_headings,
                    "site_description": site_desc,
                    "n_nav_links": len(p.nav_links), "diag": diag})


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
    tool = (request.args.get("tool") or "seo").strip()
    return jsonify({"enabled": True, "quotes": storage.list_quotes(search, tool)})

def _json_error_guard(fn):
    """Saves were failing as opaque 'Server 500 (timeout or non-JSON)' — a bare
    exception produces an HTML error page the frontend can't read. Wrap the
    persistence routes so any failure comes back as JSON with the actual cause,
    which turns 'it broke' into a fixable report."""
    from functools import wraps
    @wraps(fn)
    def inner(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    return inner

@app.route("/api/quotes", methods=["POST"])
@_json_error_guard
def api_quotes_save():
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled — attach a Postgres database in Render."}), 400
    d = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Give the quote a name."}), 400
    client = (d.get("client") or "").strip()
    payload = d.get("payload") or {}
    tool = (d.get("tool") or "seo").strip()
    qid = storage.save_quote(name, client, payload, tool)
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
@_json_error_guard
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

@app.route("/api/quotes/<int:qid>/share", methods=["POST"])
def api_quotes_share(qid):
    """Mint (or return the existing) read-only review link for a saved quote."""
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled — attach Postgres first."}), 400
    token = storage.get_or_create_share_token(qid)
    if not token:
        return jsonify({"error": "Quote not found."}), 404
    return jsonify({"token": token,
                    "url": request.host_url.rstrip("/") + "/review/" + token})

@app.route("/api/review/<token>")
def api_review(token):
    """Read-only quote fetch for the review page. Token is the credential;
    no edit endpoints accept it."""
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    q = storage.load_by_token(token)
    if not q:
        return jsonify({"error": "This review link is invalid or the quote was deleted."}), 404
    return jsonify(q)

@app.route("/review/<token>")
def review_page(token):
    """Same template as the tool; the frontend sees /review/ in the path and
    switches to read-only review mode."""
    return render_template("index.html")

@app.route("/favicon.svg")
def favicon():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<rect width='64' height='64' rx='14' fill='#002D58'/>
<circle cx='28' cy='27' r='13' fill='none' stroke='#F1B434' stroke-width='5'/>
<line x1='37.5' y1='36.5' x2='50' y2='49' stroke='#F1B434' stroke-width='6' stroke-linecap='round'/>
<text x='28' y='32.5' font-family='Arial,Helvetica,sans-serif' font-size='15' font-weight='bold'
      fill='#FDFBF7' text-anchor='middle'>$</text>
</svg>"""
    from flask import Response
    return Response(svg, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=604800"})

@app.route("/q/<int:qid>")
def edit_link_page(qid):
    """Edit deep-link: opens the tool with this saved quote loaded, ready to
    revise. Version history makes collaborative edits safe — every save
    snapshots the prior state."""
    return render_template("index.html")

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

# ---------------------------------------------------------------------------
# Reputation Management tab — separate template + pricing module (rep_pricing).
# Shares this Render service and the DFS credentials; nothing else overlaps
# with the SEO pipeline.
# ---------------------------------------------------------------------------
import rep_pricing
import rep_scan
rep_scan.init(dfs_post)

@app.route("/api/rep_scan_terms", methods=["POST"])
def api_rep_scan_terms():
    """Brand term universe + negative-modifier volumes (one KFK live call)."""
    d = request.get_json(force=True)
    brand = (d.get("brand") or "").strip()
    if not brand:
        return jsonify({"error": "Brand name required."}), 400
    try:
        return jsonify(rep_scan.scan_terms(brand))
    except Exception as e:
        return jsonify({"error": f"Term scan failed: {e}"}), 502

@app.route("/api/rep_scan_serp", methods=["POST"])
def api_rep_scan_serp():
    """'{brand} reviews' top-10 threat table + related searches + autosuggest."""
    d = request.get_json(force=True)
    brand = (d.get("brand") or "").strip()
    if not brand:
        return jsonify({"error": "Brand name required."}), 400
    try:
        return jsonify(rep_scan.scan_serp(brand, (d.get("domain") or "").strip()))
    except Exception as e:
        return jsonify({"error": f"SERP scan failed: {e}"}), 502

@app.route("/api/rep_scan_autocomplete", methods=["POST"])
def api_rep_scan_autocomplete():
    """Auto-suggest flags — separate endpoint so its latency never stacks
    onto the SERP call (Render's proxy cuts requests around 100s)."""
    d = request.get_json(force=True)
    brand = (d.get("brand") or "").strip()
    if not brand:
        return jsonify({"error": "Brand name required."}), 400
    try:
        return jsonify(rep_scan.scan_autocomplete(brand))
    except Exception as e:
        return jsonify({"error": f"Autocomplete scan failed: {e}"}), 502

@app.route("/api/rep_scan_locations", methods=["POST"])
def api_rep_scan_locations():
    """Google Business location discovery (instant, database-backed)."""
    d = request.get_json(force=True)
    brand = (d.get("brand") or "").strip()
    if not brand:
        return jsonify({"error": "Brand name required."}), 400
    try:
        return jsonify(rep_scan.scan_locations(brand))
    except Exception as e:
        return jsonify({"error": f"Location scan failed: {e}"}), 502

@app.route("/api/rep_reviews_submit", methods=["POST"])
def api_rep_reviews_submit():
    """Queue worst-first review pulls for selected locations (priority ~1min)."""
    d = request.get_json(force=True)
    pids = [p for p in (d.get("place_ids") or []) if p]
    if not pids:
        return jsonify({"error": "No locations selected."}), 400
    try:
        return jsonify(rep_scan.reviews_submit(pids, int(d.get("depth") or 200)))
    except Exception as e:
        return jsonify({"error": f"Review submit failed: {e}"}), 502

@app.route("/api/rep_reviews_collect", methods=["POST"])
def api_rep_reviews_collect():
    d = request.get_json(force=True)
    tids = [t for t in (d.get("task_ids") or []) if t]
    if not tids:
        return jsonify({"error": "No task ids."}), 400
    try:
        return jsonify(rep_scan.reviews_collect(tids))
    except Exception as e:
        return jsonify({"error": f"Review collect failed: {e}"}), 502


@app.route("/reputation")
def reputation():
    return render_template("reputation.html")

@app.route("/api/rep_quote", methods=["POST"])
def api_rep_quote():
    d = request.get_json(force=True)
    try:
        return jsonify(rep_pricing.build_rep_quote(d))
    except Exception as e:
        return jsonify({"error": f"Quote build failed: {e}"}), 500

@app.route("/api/rep_volume", methods=["POST"])
def api_rep_volume():
    """US-national exact-match volume for the brand terms — drives the
    Search Protection base+multiplier formula. Reuses fetch_exact_volume
    (Labs keyword_overview, per-term exact volume)."""
    d = request.get_json(force=True)
    terms = [t.strip() for t in (d.get("terms") or []) if t and t.strip()]
    if not terms:
        return jsonify({"error": "No brand terms provided."}), 400
    vols = fetch_exact_volume(terms, [], "")
    if not vols:
        return jsonify({"error": "DataForSEO returned no volume — check terms "
                                 "or DFS credentials."}), 502
    per_term = {t: vols.get(t.lower(), 0) for t in terms}
    return jsonify({"per_term": per_term, "total": sum(per_term.values())})


# initialize the DB tables on startup (no-op when saving isn't enabled)
try:
    storage.init_db()
except Exception as _e:
    print(f"[storage] init skipped: {_e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
