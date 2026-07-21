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

    # ------------------------------------------------------ article removals
    "article_removal": {
        # DA > 35 = premium (doc). Dollar figures are PLACEHOLDERS.
        "standard": {"label": "Standard site (DA \u2264 35)", "per_article": 2500},
        "premium":  {"label": "Premium site (DA > 35 \u2014 CNN-class)", "per_article": 7500},
        "timeline": "1\u20136 months",
        "pay_on_success": True,
    },

    # ------------------------------------------------- search protection bundle
    # monthly = base + per_1k * (monthly brand search volume / 1000), CEIL50,
    # clamped to [floor, cap]. Components can be quoted together or singly.
    "search_protection": {
        "suppression": {                       # organic search suppression
            "label": "Organic Search Suppression",
            "base": 2950, "per_1k": 25,
            "floor": 2950, "cap": 7500,
            "timeline": "4\u20136 months, then evaluate (may extend to 12)",
        },
        "autosuggest": {                       # auto-suggest + related searches
            "label": "Auto-Suggest & Related Search Manipulation",
            "base": 3450, "per_1k": 25,
            "floor": 3450, "cap": 7950,
            "timeline": "2\u20133 months to results, then 3\u20136 months maintenance",
            # Priced PER TERM SET (Sage: "Sage Dental" + "Sage Dental Reviews"
            # was one $3,950 campaign). Additional distinct term sets scale.
            "per_extra_term_set_pct": 0.50,    # each extra set adds 50% of computed monthly
        },
        # Volume-feasibility warning: campaign only works if our contracted
        # searches exceed the negative-modifier searches. Below this monthly
        # brand volume we flag it as low-signal / easy win; above the cap
        # threshold we flag for manual review.
        "review_above_volume": 150000,
        "bundle_discount_pct": 0.0,            # optional discount when both components run
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
    """Article removals split by DA tier."""
    cfg = REP_CFG["article_removal"]
    lines = []
    for key, n in (("standard", n_standard), ("premium", n_premium)):
        n = max(0, int(n or 0))
        if n == 0:
            continue
        per = cfg[key]["per_article"]
        lines.append({
            "service": "Negative Article Removals",
            "detail": f"{cfg[key]['label']} \u00b7 {n} article{'s' if n != 1 else ''} @ ${per:,}/removed article",
            "qty": n, "unit": per, "kind": "per_asset",
            "total": per * n,
            "timeline": cfg["timeline"],
            "notes": ["Pay on success \u2014 billed per removed article.",
                      "Some sensitive content cannot be removed."],
        })
    return lines


def _vol_monthly(component, volume):
    """base + per_1k formula with floor/cap, CEIL50."""
    c = REP_CFG["search_protection"][component]
    raw = c["base"] + c["per_1k"] * (max(0, volume) / 1000.0)
    return min(c["cap"], max(c["floor"], r50(raw)))


def price_search_protection(volume, use_suppression, use_autosuggest, term_sets=1):
    """Monthly recurring lines for the Search Protection components."""
    sp = REP_CFG["search_protection"]
    lines, warnings = [], []
    if volume and volume > sp["review_above_volume"]:
        warnings.append(
            f"Brand volume {volume:,}/mo exceeds the {sp['review_above_volume']:,} "
            "review threshold \u2014 auto-suggest feasibility depends on out-searching "
            "the negative modifiers; confirm capacity before quoting.")
    if use_suppression:
        m = _vol_monthly("suppression", volume)
        lines.append({
            "service": "Search Protection \u2014 Organic Search Suppression",
            "detail": f"${sp['suppression']['base']:,} base + $"
                      f"{sp['suppression']['per_1k']}/1K searches on {volume:,}/mo brand volume",
            "kind": "monthly", "total": m,
            "timeline": sp["suppression"]["timeline"],
            "notes": ["Targeted link building + optimized owned assets to push "
                      "negative media down the results."],
        })
    if use_autosuggest:
        m = _vol_monthly("autosuggest", volume)
        extra = max(0, int(term_sets or 1) - 1)
        total = r50(m * (1 + extra * sp["autosuggest"]["per_extra_term_set_pct"]))
        det = (f"${sp['autosuggest']['base']:,} base + $"
               f"{sp['autosuggest']['per_1k']}/1K searches on {volume:,}/mo brand volume")
        if extra:
            det += (f" \u00b7 {term_sets} term sets "
                    f"(+{int(sp['autosuggest']['per_extra_term_set_pct']*100)}% per extra set)")
        lines.append({
            "service": "Search Protection \u2014 Auto-Suggest & Related Searches",
            "detail": det, "kind": "monthly", "total": total,
            "timeline": sp["autosuggest"]["timeline"],
            "notes": ["Includes Branded Search Append.",
                      "Succeeds only while our contracted search volume exceeds "
                      "the negative-modifier volume."],
        })
    # optional bundle discount when both components run
    if use_suppression and use_autosuggest and sp["bundle_discount_pct"]:
        for ln in lines:
            ln["total"] = r50(ln["total"] * (1 - sp["bundle_discount_pct"]))
        warnings.append(f"Search Protection bundle discount applied: "
                        f"{int(sp['bundle_discount_pct']*100)}%.")
    return lines, warnings


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
            int(se.get("term_sets") or 1))
        phase1 += sp_lines
        warnings += sp_warn

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
