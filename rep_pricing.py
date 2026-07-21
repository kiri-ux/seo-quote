"""
Reputation Management pricing engine — adtini / SSG.

Separate module so app.py stays SEO-only. All Brendan-calibration constants
live in REP_CFG at the top; everything below is mechanics.

Pricing sources (Rep Mgmt Proposal Template doc + Sage Dental sample, June 2026):
  * Review removals — Vici rate card (July 2026 chart): whole-order hard-cost
    brackets $585 -> $422.50 across 1-500 reviews, editable margin (default 35%
    of gross) reproducing the chart's $900 -> $650 gross column. Supersedes the
    Partner A ($450 flat) / Partner B ($650->$550 tiers) client pricing from
    Brendan's Sage proposal; A/B is now internal fulfillment routing only.
  * Article removals — priced per removed article, tiered on domain authority:
    DA <= 35 standard, DA > 35 premium (CNN-class). Dollar figures below are
    PLACEHOLDERS — doc says "$[Custom Price]"; calibrate with Brendan.
  * Search Protection — monthly, "formula based on search volume (base +
    multiplier)". Calibrated so a Sage-Dental-scale brand (~20K searches/mo)
    lands on the sample actuals: suppression $3,450/mo, auto-suggest/related
    $3,950/mo  ->  base $2,950 / $3,450 + $25 per 1K monthly searches.
    The 20K assumption is a guess — re-solve the bases once Brendan confirms
    Sage's real volume.
  * Proactive Brand Shield — single monthly bundle. "$[Monthly Price]" in doc;
    placeholder below.
"""

def r50(x):
    """Round up to the next $50 — same convention as the SEO tool."""
    import math
    return int(math.ceil(x / 50.0) * 50)


REP_CFG = {
    # ------------------------------------------------------- review removals
    # Vici rate card (July 2026 chart) replaces the Partner A/B client pricing.
    # HARD COST (Vici net) is canonical; gross = hard / (1 - margin). At the
    # suggested 35% margin this reproduces the chart's gross column exactly:
    # $900 / $850 / $800 / $750 / $700 / $650. Margin is % OF GROSS (chart
    # convention) — NOT markup-on-cost like the SEO tool's x1.35.
    # Partner A/B remain internal fulfillment routing, not client pricing.
    "review_removal": {
        "default_margin_pct": 0.35,
        "brackets": [                       # whole-order: rate applies to all
            {"min": 1,   "max": 25,   "hard": 585.00},
            {"min": 26,  "max": 50,   "hard": 552.50},
            {"min": 51,  "max": 100,  "hard": 520.00},
            {"min": 101, "max": 250,  "hard": 487.50},
            {"min": 251, "max": 350,  "hard": 455.00},
            {"min": 351, "max": 500,  "hard": 422.50},
        ],
        "timeline": "\u224848 hours\u201360 days depending on fulfillment routing",
        "pay_on_success": True,
    },

    # ------------------------------------------------ website/article removals
    # Whole-order brackets = Brendan's Visions Electronics actuals (2024).
    # Premium (DA>35 / news-legal class) = Tru North actual $7,500. Brendan's
    # notes: always custom quoted + human review — these are starting anchors.
    "article_removal": {
        "brackets": [
            {"min": 1,  "max": 3,    "per": 5950},
            {"min": 4,  "max": 6,    "per": 5750},
            {"min": 7,  "max": 10,   "per": 5350},
            {"min": 11, "max": 15,   "per": 5150},
            {"min": 16, "max": None, "per": 4950},
        ],
        "premium_per": 7500,
        "timeline": "2\u20133 months average, up to 6",
        "pay_on_success": True,
    },

    # ------------------------------------------------- search protection bundle
    # monthly = base + per_1k * (monthly brand search volume / 1000), CEIL50,
    # clamped to [floor, cap]. Components can be quoted together or singly.
    "search_protection": {
        "suppression": {                       # organic search suppression
            "label": "Organic Search Suppression",
            "base": 2900, "per_1k": 10,
            "floor": 2900, "cap": 7500,
            # Intensity tiers per Brendan's Tru North structure: same work,
            # different monthly volume -> speed. Steps are his exact ±$1,000.
            "tiers": {
                "base":     {"offset": -1000, "timeline": "10\u201314 months to results"},
                "standard": {"offset": 0,     "timeline": "8\u201310 months to results"},
                "advanced": {"offset": 1000,  "timeline": "7\u20139 months to results"},
            },
        },
        "autosuggest": {
            "label": "Auto-Suggest Manipulation",
            "base": 3400, "per_1k": 10,
            "floor": 3400, "cap": 7950,
            "timeline": "2\u20133 months to results, then 3\u20136 months maintenance",
            "included_negatives": 3,
            "per_extra_negative": 250,          # GUESS
            # Guaranteed per-phrase actuals span $4,125 (Goldstone 2020, 2
            # phrases) to $9,250 (Goldstone 2021, 1 complex phrase) —
            # complexity-driven per Brendan's notes. Editable per quote.
            "guaranteed_per_phrase": 4125,
            "guaranteed_timeline": "45\u201360 days\u20136 months, pay on success",
            "maintenance_monthly": 750,          # Goldstone actual, 6-mo minimum
        },
        # Related Searches — priced SEPARATELY in every Brendan example
        # (Goldstone '21, Bing/DDG '25, Visions '24, Sage '26). Google uses
        # the same volume formula; maintenance = Visions actual $2,150/mo.
        "related": {
            "label": "Related Search Manipulation",
            "base": 3400, "per_1k": 10,
            "floor": 3400, "cap": 7950,
            "timeline": "\u224885% success over 6 months (per keyword)",
            "maintenance_monthly": 2150,
            "maintenance_timeline": "3\u20136 months post-removal maintenance",
        },
        # Bing/DuckDuckGo are FLAT monthlies (Goldstone 2025 actuals), not a
        # multiplier on the Google formula: each engine is its own campaign.
        "alt_engine_flat": {"autosuggest": 1500, "related": 1250},
        "alt_engine_timeline": "6\u20138 months to fully resolve, then maintenance",
        "review_above_volume": 150000,
        "bundle_discount_pct": 0.0,
    },

    # ------------------------------------------------- proactive brand shield
    "shield": {
        "monthly": 2950,                  # PLACEHOLDER — "$[Monthly Price]" in doc
        "included": ["SEO \u201cMoat\u201d & Asset Building",
                     "Automated Review Generation & Sentiment Routing",
                     "24/7 Brand Monitoring & Threat Detection"],
        # Review-gen outreach scales with locations; first N included.
        "included_locations": 1,
        "per_extra_location": 0,          # PLACEHOLDER — 0 until Brendan sets it
    },

    # ---------------------------------------------------------------- bundle
    "bundle": {
        # Reactive + Proactive phased plan. Optional discount applied to the
        # recurring lines (not per-asset removals) when both phases are sold.
        "recurring_discount_pct": 0.0,    # PLACEHOLDER — 0 until decided
        "phase1_months": "2\u20136 mo. duration",
        "phase2_start": "Months 4+",
    },
}


# ---------------------------------------------------------------------------
# mechanics
# ---------------------------------------------------------------------------

def price_reviews(n, margin_pct=None):
    """Review-removal line off the Vici rate card. Whole-order bracket on the
    HARD cost; client gross derived from the editable margin (% of gross).
    Returns the client-facing line plus an `internal` block (hard / profit)."""
    n = max(0, int(n or 0))
    if n == 0:
        return None
    cfg = REP_CFG["review_removal"]
    m = cfg["default_margin_pct"] if margin_pct is None else float(margin_pct)
    m = min(0.90, max(0.0, m))                      # sanity clamp
    hard_per, over_chart = None, False
    for b in cfg["brackets"]:
        if n >= b["min"] and (b["max"] is None or n <= b["max"]):
            hard_per = b["hard"]
            break
    if hard_per is None:                            # beyond 500 — extend top tier
        hard_per = cfg["brackets"][-1]["hard"]
        over_chart = True
    gross_per = round(hard_per / (1.0 - m) / 5.0) * 5   # clean $5 steps
    total = int(round(gross_per * n))
    hard_total = round(hard_per * n, 2)
    line = {
        "service": "Negative Review Removals",
        "detail": f"{n} review{'s' if n != 1 else ''} @ ${gross_per:,.0f}/removed review",
        "qty": n, "unit": gross_per, "kind": "per_asset",
        "total": total,
        "timeline": cfg["timeline"],
        "notes": ["Pay on success \u2014 billed per removed review; removal is not guaranteed.",
                  "Some sensitive content cannot be removed."],
        "internal": {
            "hard_per": hard_per, "hard_total": hard_total,
            "profit_total": round(total - hard_total, 2),
            "margin_pct": m,
        },
    }
    if over_chart:
        line["notes"].append(f"{n} reviews exceeds the 500-review rate card \u2014 "
                             "top-tier rate extended; confirm with fulfillment partner.")
    return line


def price_articles(n_standard, n_premium):
    """Website/article removals. Standard sites use the Visions whole-order
    bracket; premium (DA>35 / news-legal) at the Tru North flat rate."""
    cfg = REP_CFG["article_removal"]
    lines = []
    n = max(0, int(n_standard or 0))
    if n:
        per = next(b["per"] for b in cfg["brackets"]
                   if n >= b["min"] and (b["max"] is None or n <= b["max"]))
        lines.append({
            "service": "Negative Website/Article Removals",
            "detail": f"{n} standard site{'s' if n != 1 else ''} @ ${per:,}/removed "
                      "(whole-order bracket, Visions actuals)",
            "qty": n, "unit": per, "kind": "per_asset", "total": per * n,
            "timeline": cfg["timeline"],
            "notes": ["Pay on success \u2014 billed only for sites removed.",
                      "Always custom-quoted after human review (Brendan)."],
        })
    p = max(0, int(n_premium or 0))
    if p:
        lines.append({
            "service": "Negative Website/Article Removals",
            "detail": f"{p} premium site{'s' if p != 1 else ''} (DA > 35 / news-legal) "
                      f"@ ${cfg['premium_per']:,}/removed (Tru North actual)",
            "qty": p, "unit": cfg["premium_per"], "kind": "per_asset",
            "total": cfg["premium_per"] * p,
            "timeline": "10\u201314 weeks typical (12-month contract window)",
            "notes": ["Pay on success \u2014 ~50% success on premium hosts.",
                      "Always custom-quoted after human review (Brendan)."],
        })
    return lines


def _vol_monthly(component, volume):
    """base + per_1k formula with floor/cap, CEIL50."""
    c = REP_CFG["search_protection"][component]
    raw = c["base"] + c["per_1k"] * (max(0, volume) / 1000.0)
    return min(c["cap"], max(c["floor"], r50(raw)))


def price_search_protection(volume, use_suppression, use_autosuggest,
                            suppression_tier="standard", as_mode="ongoing",
                            n_negatives=3, engine="google",
                            use_related=False, guaranteed_per_phrase=None):
    """Suppression / auto-suggest / related-search lines.
    engine: google (volume formula) | bing | ddg (flat monthlies, Goldstone
    2025 actuals — each engine is its own campaign)."""
    sp = REP_CFG["search_protection"]
    lines, warnings = [], []
    if volume and volume > sp["review_above_volume"]:
        warnings.append(
            f"Brand volume {volume:,}/mo exceeds the {sp['review_above_volume']:,} "
            "review threshold \u2014 confirm out-search capacity before quoting.")
    eng_name = {"google": "Google", "bing": "Bing", "ddg": "DuckDuckGo"}.get(engine, "Google")

    if use_suppression:
        c = sp["suppression"]
        tier = c["tiers"].get(suppression_tier) or c["tiers"]["standard"]
        m = min(c["cap"], max(c["floor"], r50(c["base"] + c["per_1k"] * (max(0, volume) / 1000.0))))
        m = max(1000, r50(m + tier["offset"]))
        lines.append({
            "service": "Search Protection \u2014 Organic Search Suppression",
            "detail": f"{suppression_tier.capitalize()} intensity \u00b7 ${c['base']:,} base "
                      f"+ ${c['per_1k']}/1K on {volume:,}/mo brand volume "
                      f"{'+' if tier['offset'] >= 0 else '\u2212'}${abs(tier['offset']):,} tier",
            "kind": "monthly", "total": m, "timeline": tier["timeline"],
            "notes": ["Positive content, link building, and owned-asset optimization "
                      "to push negative media down.",
                      "Tier changes monthly work volume \u2014 higher tiers reach results faster."],
        })

    def _vol(c):
        return min(c["cap"], max(c["floor"], r50(c["base"] + c["per_1k"] * (max(0, volume) / 1000.0))))

    if use_autosuggest:
        c = sp["autosuggest"]
        n = max(1, int(n_negatives or 1))
        if engine in ("bing", "ddg"):
            lines.append({
                "service": f"Search Protection \u2014 Auto-Suggest ({eng_name})",
                "detail": f"${sp['alt_engine_flat']['autosuggest']:,}/mo flat "
                          "(Goldstone 2025 actual)",
                "kind": "monthly", "total": sp["alt_engine_flat"]["autosuggest"],
                "timeline": sp["alt_engine_timeline"],
                "notes": ["Each engine is a separate campaign."],
            })
        elif as_mode == "guaranteed":
            per = int(guaranteed_per_phrase or c["guaranteed_per_phrase"])
            lines.append({
                "service": "Search Protection \u2014 Guaranteed Phrase Removal",
                "detail": f"{n} negative phrase{'s' if n != 1 else ''} @ ${per:,}/phrase "
                          "(actuals span $4,125\u2013$9,250 by complexity)",
                "kind": "per_asset", "total": per * n,
                "timeline": c["guaranteed_timeline"],
                "notes": ["Pay on success \u2014 nothing upfront; billed only for "
                          "phrases removed."],
            })
            lines.append({
                "service": "Search Protection \u2014 Phrase Maintenance",
                "detail": f"${c['maintenance_monthly']:,}/mo following removal",
                "kind": "monthly", "total": c["maintenance_monthly"],
                "timeline": "6-month minimum, 9\u201312 months recommended",
                "notes": ["Keeps removed phrases suppressed (Goldstone actual)."],
            })
        else:
            m = _vol(c)
            extra = max(0, n - c["included_negatives"])
            m = r50(m + extra * c["per_extra_negative"])
            det = (f"${c['base']:,} base + ${c['per_1k']}/1K on {volume:,}/mo "
                   f"brand volume \u00b7 {n} negative phrase{'s' if n != 1 else ''}")
            if extra:
                det += f" (+${c['per_extra_negative']}/phrase beyond {c['included_negatives']} \u2014 guess)"
            lines.append({
                "service": "Search Protection \u2014 Auto-Suggest Manipulation",
                "detail": det, "kind": "monthly", "total": m, "timeline": c["timeline"],
                "notes": ["Includes Branded Search Append.",
                          "Succeeds only while contracted search volume exceeds "
                          "the negative-modifier volume."],
            })

    if use_related:
        c = sp["related"]
        if engine in ("bing", "ddg"):
            lines.append({
                "service": f"Search Protection \u2014 Related Searches ({eng_name})",
                "detail": f"${sp['alt_engine_flat']['related']:,}/mo flat "
                          "(Goldstone 2025 actual)",
                "kind": "monthly", "total": sp["alt_engine_flat"]["related"],
                "timeline": sp["alt_engine_timeline"],
                "notes": ["Each engine is a separate campaign."],
            })
        else:
            lines.append({
                "service": "Search Protection \u2014 Related Search Manipulation",
                "detail": f"${c['base']:,} base + ${c['per_1k']}/1K on {volume:,}/mo "
                          "brand volume \u00b7 until negative removed",
                "kind": "monthly", "total": _vol(c), "timeline": c["timeline"],
                "notes": ["Priced per keyword carrying negatives."],
            })
            lines.append({
                "service": "Search Protection \u2014 Related Search Maintenance",
                "detail": f"${c['maintenance_monthly']:,}/mo after removal (Visions actual)",
                "kind": "monthly", "total": c["maintenance_monthly"],
                "timeline": c["maintenance_timeline"],
                "notes": ["Not billed concurrently with the active phase \u2014 "
                          "sequential: active \u2192 maintenance."],
            })

    if use_suppression and (use_autosuggest or use_related) and sp["bundle_discount_pct"]:
        for ln in lines:
            if ln["kind"] == "monthly":
                ln["total"] = r50(ln["total"] * (1 - sp["bundle_discount_pct"]))
    return lines, warnings


# --------------------------------------------------------- bbb remediation
# Brendan's July notes: "BBB remediation — tiers based on # of complaints."
# NO pricing datapoint exists — every number below is a GUESS to confirm.
BBB_BRACKETS = [
    {"min": 1,  "max": 5,    "per": 650},
    {"min": 6,  "max": 15,   "per": 550},
    {"min": 16, "max": None, "per": 450},
]

def price_bbb(n):
    n = max(0, int(n or 0))
    if n == 0:
        return None
    per = next(b["per"] for b in BBB_BRACKETS
               if n >= b["min"] and (b["max"] is None or n <= b["max"]))
    return {
        "service": "BBB Remediation",
        "detail": f"{n} complaint{'s' if n != 1 else ''} @ ${per:,}/complaint "
                  "(whole-order bracket)",
        "qty": n, "unit": per, "kind": "per_asset", "total": per * n,
        "timeline": "Via BBB dispute process \u2014 timeline varies",
        "notes": ["GUESS pricing \u2014 no Brendan datapoint yet; confirm brackets.",
                  "BBB complaints cannot be bought off the platform \u2014 "
                  "remediation works the BBB's own dispute/response process."],
    }


# Sage Digital Partner proposal actuals (Sept 2025): GEO $4,950/mo setup
# phase, $9,950/mo scale phase. Applied here as reputational GEO — shaping
# AI-overview / LLM answers about the brand.
GEO = {"setup": {"monthly": 4950, "timeline": "First 1\u20132 quarters \u2014 LLM "
                "setup, citations, AI-crawlable positive assets"},
       "scale": {"monthly": 9950, "timeline": "Ongoing \u2014 scaled citation and "
                 "content program as AI search share grows"}}

def price_geo(phase="setup"):
    p = GEO.get(phase) or GEO["setup"]
    return {"service": "Reputational GEO (AI Search)",
            "detail": f"{phase.capitalize()} phase \u2014 shapes AI Overview / LLM "
                      "answers about the brand (Sage actuals)",
            "kind": "monthly", "total": p["monthly"], "timeline": p["timeline"],
            "notes": ["Targets the negative AI-generated result the scan detects.",
                      "Recommend setup phase 1\u20132 quarters, then scale."]}


# Hobart Wealth actuals (2021): PR pay-per-placement.
PR = {"premium": 8000, "secondary": 4500, "release": 1500}

def price_pr(premium=0, secondary=0, releases=0):
    lines = []
    for key, n, label in (("premium", premium, "Premium placement (Newsweek/WSJ-class)"),
                          ("secondary", secondary, "Secondary placement (regional/niche)"),
                          ("release", releases, "Press release")):
        n = max(0, int(n or 0))
        if n:
            lines.append({"service": "PR Placements",
                          "detail": f"{n} \u00d7 {label} @ ${PR[key]:,} each",
                          "qty": n, "unit": PR[key], "kind": "per_asset",
                          "total": PR[key] * n,
                          "timeline": "Quarterly cadence recommended",
                          "notes": ["Pay per placement \u2014 only successful "
                                    "placements are billed (Hobart actuals)."]})
    return lines


# Goldstone Yelp actuals: $790/stuck Yelp review (2021, pay on success);
# Google $105/review min 5/mo (2021). Dated — confirm with Brendan.
REVIEW_GEN = {"yelp": {"per": 790, "label": "Yelp (stuck reviews)", "min": 1},
              "google": {"per": 105, "label": "Google", "min": 5}}

def price_review_gen(platform="google", count=0):
    n = max(0, int(count or 0))
    if n == 0:
        return None
    c = REVIEW_GEN.get(platform) or REVIEW_GEN["google"]
    n = max(n, c["min"])
    return {"service": "Review Generation",
            "detail": f"{c['label']} \u00b7 {n} reviews @ ${c['per']:,}/review"
                      + (f" (min {c['min']}/mo)" if c["min"] > 1 else ""),
            "qty": n, "unit": c["per"], "kind": "per_asset", "total": c["per"] * n,
            "timeline": "4\u20136 months (Yelp) / monthly batches (Google)",
            "notes": ["Pay on successful posting (Goldstone actuals, 2020\u201321 "
                      "\u2014 dated, confirm current rates).",
                      "Yelp alternative when reviews can't stick: page deindexing "
                      "from Google, \u2248$10,000 one-time."]}


# Kim Anami actuals (2021): $4,950 + $6,250 per video — midpoint $5,600
# default; always custom quoted per Brendan's notes.
def price_video(count=0, per_video=5600):
    n = max(0, int(count or 0))
    if n == 0:
        return None
    per = int(per_video or 5600)
    return {"service": "Negative Video Removals",
            "detail": f"{n} video{'s' if n != 1 else ''} @ ${per:,}/video "
                      "(Kim Anami actuals: $4,950\u2013$6,250)",
            "qty": n, "unit": per, "kind": "per_asset", "total": per * n,
            "timeline": "Guaranteed \u2014 pay on success",
            "notes": ["Removes from YouTube AND Google for the listed search terms.",
                      "Always custom-quoted by complexity (Brendan)."]}


def price_shield(locations=1):
    cfg = REP_CFG["shield"]
    extra = max(0, int(locations or 1) - cfg["included_locations"])
    total = r50(cfg["monthly"] + extra * cfg["per_extra_location"])
    det = "Proactive Brand Shield Bundle"
    if extra and cfg["per_extra_location"]:
        det += (f" \u00b7 {locations} locations "
                f"(+${cfg['per_extra_location']:,}/extra location)")
    return {
        "service": "Proactive Brand Shield",
        "detail": det, "kind": "monthly", "total": total,
        "timeline": "Ongoing",
        "notes": cfg["included"],
    }


def build_rep_quote(payload):
    """
    payload = {
      campaign: 'reactive' | 'proactive' | 'bundle',
      reviews: {count: int, margin_pct: float (0.35 = 35% of gross)},
      articles: {standard: int, premium: int},
      search: {volume: int, suppression: bool, autosuggest: bool, term_sets: int},
      shield: {locations: int},
    }
    Returns {lines, phases, totals, warnings}.
    """
    campaign = payload.get("campaign", "reactive")
    lines, warnings = [], []
    phase1, phase2 = [], []

    if campaign in ("reactive", "bundle"):
        rv = payload.get("reviews") or {}
        ln = price_reviews(rv.get("count", 0), rv.get("margin_pct"))
        if ln:
            phase1.append(ln)
        ar = payload.get("articles") or {}
        phase1 += price_articles(ar.get("standard", 0), ar.get("premium", 0))
        se = payload.get("search") or {}
        sp_lines, sp_warn = price_search_protection(
            int(se.get("volume") or 0),
            bool(se.get("suppression")), bool(se.get("autosuggest")),
            se.get("suppression_tier") or "standard",
            se.get("as_mode") or "ongoing",
            int(se.get("n_negatives") or 3),
            se.get("engine") or "google",
            bool(se.get("related")),
            se.get("guaranteed_per_phrase"))
        phase1 += sp_lines
        warnings += sp_warn
        bb = payload.get("bbb") or {}
        bln = price_bbb(bb.get("count", 0))
        if bln:
            phase1.append(bln)
        ge = payload.get("geo") or {}
        if ge.get("enabled"):
            phase1.append(price_geo(ge.get("phase") or "setup"))
        pr = payload.get("pr") or {}
        phase1 += price_pr(pr.get("premium", 0), pr.get("secondary", 0), pr.get("releases", 0))
        rg = payload.get("review_gen") or {}
        rln = price_review_gen(rg.get("platform") or "google", rg.get("count", 0))
        if rln:
            phase1.append(rln)
        vd = payload.get("video") or {}
        vln = price_video(vd.get("count", 0), vd.get("per_video") or 5600)
        if vln:
            phase1.append(vln)

    if campaign in ("proactive", "bundle"):
        sh = payload.get("shield") or {}
        phase2.append(price_shield(sh.get("locations", 1)))

    # bundle discount on recurring lines when both phases present
    if campaign == "bundle" and REP_CFG["bundle"]["recurring_discount_pct"]:
        pct = REP_CFG["bundle"]["recurring_discount_pct"]
        for ln in phase1 + phase2:
            if ln["kind"] == "monthly":
                ln["total"] = r50(ln["total"] * (1 - pct))
        warnings.append(f"Bundle discount applied to recurring lines: {int(pct*100)}%.")

    for ln in phase1:
        ln["phase"] = 1
    for ln in phase2:
        ln["phase"] = 2
    lines += phase1 + phase2

    totals = {
        "one_time":  sum(l["total"] for l in lines if l["kind"] in ("one_time", "per_asset")),
        "monthly":   sum(l["total"] for l in lines if l["kind"] == "monthly"),
        "per_asset": sum(l["total"] for l in lines if l["kind"] == "per_asset"),
    }
    return {"campaign": campaign, "lines": lines, "totals": totals,
            "warnings": warnings,
            "bundle_meta": REP_CFG["bundle"] if campaign == "bundle" else None}
