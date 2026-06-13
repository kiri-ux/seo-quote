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
import os, json, base64, statistics
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
BASE = "https://api.dataforseo.com/v3"

# ---------------------------------------------------------------------------
# CONFIG — every tunable constant. Brendan-calibration items live here only.
# Spring ladder ($1,450–$4,250 by geo scope), per decision.
# ---------------------------------------------------------------------------
CFG = {
    # Geo dropdown (5 options) -> 4 price anchors.
    # Non-contiguous shares the $2,950 (multi-region) anchor with statewide.
    "geo_anchor": {
        "single_city":          1450,
        "contiguous_region":    2250,
        "non_contiguous_region":2950,
        "statewide":            2950,
        "nationwide":           4250,
    },
    "competitive_adder": {0: 0, 1: 200, 2: 400},
    "bid_score_breaks": [5.0, 15.0],          # <5->0, 5-15->1, >=15->2
    "zero_ranking_bonus": 500,
    "zero_ranking_top_n": 50,
    "zero_ranking_frac": 0.10,
    "step_ratio": 0.40,
    "addon_market_ratio": 0.42,
    "ultra_bucket_size": 3,
    "competitive_bucket_size": 6,
    "list_cap": 20,
}

def r50(x):
    return int(round(x / 50.0) * 50)

def dfs_post(path, payload):
    login = os.environ.get("DFS_LOGIN", "")
    pw    = os.environ.get("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    resp = requests.post(BASE + path,
                         headers={"Authorization": f"Basic {token}",
                                  "Content-Type": "application/json"},
                         data=json.dumps(payload), timeout=120)
    resp.raise_for_status()
    return resp.json()

def loc_string(markets, state):
    if markets and state:
        return f"{markets[0]},{state},United States"
    if state:
        return f"{state},United States"
    return "United States"

# ---------------------------------------------------------------------------
# STAGE 1 — keyword list
# ---------------------------------------------------------------------------
def stage1_keyword_list(seeds, markets, state, brand):
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
    raw = [{"keyword": it["keyword"], "volume": it.get("search_volume") or 0}
           for it in items]

    seed_tokens = {t.lower() for s in seeds for t in s.split()}
    brand_l = (brand or "").lower()
    kept = []
    seen = set()
    for r in raw:
        kw = r["keyword"].lower()
        if kw in seen:
            continue
        seen.add(kw)
        if brand_l and brand_l in kw:
            continue
        if seed_tokens and not (seed_tokens & set(kw.split())):
            continue
        kept.append(r)

    kept.sort(key=lambda r: r["volume"], reverse=True)
    with_vol = [r for r in kept if r["volume"] > 0]
    u, c = CFG["ultra_bucket_size"], CFG["competitive_bucket_size"]
    ultra       = with_vol[:u]
    competitive = with_vol[u:u + c]
    head_kws    = {r["keyword"] for r in ultra + competitive}
    long_tail   = [r for r in kept if r["keyword"] not in head_kws]

    full = (ultra + competitive + long_tail)[:CFG["list_cap"]]
    fs = {r["keyword"] for r in full}
    return {
        "ultra":       [r for r in ultra if r["keyword"] in fs],
        "competitive": [r for r in competitive if r["keyword"] in fs],
        "long_tail":   [r for r in long_tail if r["keyword"] in fs],
        "head":        [r for r in (ultra + competitive) if r["keyword"] in fs],
        "all":         full,
    }

# ---------------------------------------------------------------------------
# STAGE 3a — metrics -> competitive adder
# ---------------------------------------------------------------------------
def stage3_metrics(head, markets, state):
    kws = [r["keyword"] for r in head]
    if not kws:
        return {"adder": 0, "median_score": 0, "bids": {}}
    payload = [{"keywords": kws,
                "location_name": loc_string(markets, state),
                "language_code": "en"}]
    data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
    items = (data["tasks"][0]["result"] or [])
    bids = {it["keyword"]: (it.get("high_top_of_page_bid") or 0) for it in items}
    lo, hi = CFG["bid_score_breaks"]
    scores = [2 if bids.get(k, 0) >= hi else 1 if bids.get(k, 0) >= lo else 0 for k in kws]
    median_score = int(statistics.median(scores)) if scores else 0
    return {"adder": CFG["competitive_adder"][median_score],
            "median_score": median_score, "bids": bids}

# ---------------------------------------------------------------------------
# STAGE 3b — rank check -> table + zero-ranking + PAA
# ---------------------------------------------------------------------------
def stage3_rankcheck(all_kws, domain, markets, state, brand):
    table, paa, ranked = [], [], 0
    top_n = CFG["zero_ranking_top_n"]
    dom = (domain or "").replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    for r in all_kws:
        kw = r["keyword"]
        payload = [{"keyword": kw, "location_name": loc_string(markets, state),
                    "language_code": "en", "depth": 100}]
        data = dfs_post("/serp/google/organic/live/advanced", payload)
        res = (data["tasks"][0]["result"] or [{}])[0]
        items = res.get("items", []) or []
        pos = None
        for it in items:
            if it.get("type") == "organic" and dom and dom in (it.get("domain") or ""):
                pos = it.get("rank_absolute"); break
            if it.get("type") == "people_also_ask":
                for el in it.get("items", []):
                    q = el.get("title")
                    if q and (brand or "").lower() not in q.lower():
                        paa.append(q)
        table.append({"keyword": kw, "position": pos})
        if pos is not None and pos <= top_n:
            ranked += 1
    n = len(all_kws) or 1
    frac = ranked / n
    return {"table": table, "ranked": ranked, "frac": frac,
            "zero_ranking": frac < CFG["zero_ranking_frac"],
            "paa_pool": list(dict.fromkeys(paa))}

# ---------------------------------------------------------------------------
# STAGE 4 — pricing
# ---------------------------------------------------------------------------
def stage4_price(band, adder, zero_ranking, addon_markets=0):
    anchor = CFG["geo_anchor"][band]
    base = anchor + adder + (CFG["zero_ranking_bonus"] if zero_ranking else 0)
    step = r50(base * CFG["step_ratio"])
    tiers = {"base": base, "intermediate": base + step, "advanced": base + 2*step}
    addon_per = {k: r50(v * CFG["addon_market_ratio"]) for k, v in tiers.items()}
    return {"anchor": anchor, "base": base, "step": step, "tiers": tiers,
            "addon_per_market": addon_per, "addon_markets": addon_markets}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

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

    try:
        s1 = stage1_keyword_list(seeds, markets, state, brand)
        if not s1["all"]:
            return jsonify({"error": "No keywords returned — try broader seeds or check the market/state."}), 400
        m3 = stage3_metrics(s1["head"], markets, state)
        r3 = stage3_rankcheck(s1["all"], domain, markets, state, brand)
        p  = stage4_price(band, m3["adder"], r3["zero_ranking"], addon)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO request failed: {e}. Check DFS_LOGIN / DFS_PASSWORD."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    return jsonify({
        "stage1": {
            "ultra":       [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["ultra"]],
            "competitive": [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["competitive"]],
            "long_tail":   [{"kw": r["keyword"], "vol": r["volume"]} for r in s1["long_tail"]],
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
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
