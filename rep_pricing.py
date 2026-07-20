"""
Reputation Management pricing engine — adtini / SSG.

Separate module so app.py stays SEO-only. All Brendan-calibration constants
live in REP_CFG at the top; everything below is mechanics.

Pricing sources (Rep Mgmt Proposal Template doc + Sage Dental sample, June 2026):
  * Review removals — Partner A $450 flat (40-50% success, 30-60 days);
    Partner B whole-order brackets 1-15 $650 / 16-30 $575 / 31-50 $560 /
    51+ $550 (near-100% success, ~48 hrs). Pay on success.
  * Article removals — priced per removed article, tiered on domain authority:
    DA <= 35 standard, DA > 35 premium (CNN-class). Dollar figures below are
    PLACEHOLDERS — doc says "$[Custom Price]"; calibrate with Brendan.
  * Search Protection — monthly, "formula based on search volume (base +
    multiplier)". Calibrated so a Sage-Dental-scale brand (~20K searches/mo)
    lands on the sample actuals: suppression $3,450/mo, auto-suggest/related
    $3,950/mo  ->  base $2,950 / $3,450 + $25 per 1K monthly searches.
    The 20K assumption is a guess — re-solve the bases once Brendan confirms
    Sage's real volume.
  * Audit — fixed price, 3-5 days, optionally credited toward campaign.
    "$[Fixed Price]" in doc; placeholder below.
  * Proactive Brand Shield — single monthly bundle. "$[Monthly Price]" in doc;
    placeholder below.
"""

def r50(x):
    """Round up to the next $50 — same convention as the SEO tool."""
    import math
    return int(math.ceil(x / 50.0) * 50)


REP_CFG = {
    # ------------------------------------------------------------------ audit
    "audit": {
        "price": 1500,                    # PLACEHOLDER — "$[Fixed Price]" in doc
        "timeline": "3\u20135 days",
        "credit_toward_campaign": True,   # doc: "(credit towards full campaign?)"
    },

    # ------------------------------------------------------- review removals
    "review_removal": {
        "partner_a": {
            "label": "Partner A \u2014 volume cleanup",
            "per_review": 450,
            "success": "40\u201350% success rate",
            "timeline": "30\u201360 days",
            "note": ("Best when shoring up a location's overall rating across "
                     "many reviews, with no single must-remove review."),
        },
        "partner_b": {
            "label": "Partner B \u2014 high-certainty",
            # Whole-order brackets: the rate for the total count applies to
            # EVERY review in the order (doc: "16 to 30 reviews: $575 per").
            "brackets": [
                {"min": 1,  "max": 15,   "per": 650},
                {"min": 16, "max": 30,   "per": 575},
                {"min": 31, "max": 50,   "per": 560},
                {"min": 51, "max": None, "per": 550},
            ],
            "success": "\u2248100% success rate",
            "timeline": "\u224848 hours per request",
            "note": "More expensive but fast and near-certain.",
        },
        "pay_on_success": True,   # billed per REMOVED review; no removal guarantee
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

def price_reviews(partner, n):
    """Return dict for a review-removal line. Whole-order bracket for B."""
    n = max(0, int(n or 0))
    if n == 0:
        return None
    cfg = REP_CFG["review_removal"]
    if partner == "partner_a":
        per = cfg["partner_a"]["per_review"]
        meta = cfg["partner_a"]
    else:
        per = None
        for b in cfg["partner_b"]["brackets"]:
            if n >= b["min"] and (b["max"] is None or n <= b["max"]):
                per = b["per"]
                break
        meta = cfg["partner_b"]
    total = per * n
    return {
        "service": "Negative Review Removals",
        "detail": f"{meta['label']} \u00b7 {n} review{'s' if n != 1 else ''} @ ${per:,}/removed review",
        "qty": n, "unit": per, "kind": "per_asset",
        "total": total,
        "timeline": meta["timeline"],
        "notes": [meta["success"],
                  "Pay on success \u2014 billed per removed review; removal is not guaranteed."],
    }


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


def price_audit():
    cfg = REP_CFG["audit"]
    return {
        "service": "Comprehensive Reputation Audit",
        "detail": "SERP analysis (pp. 1\u20133) \u00b7 review sentiment audit \u00b7 "
                  "backlink & asset authority check \u00b7 threat assessment",
        "kind": "one_time", "total": cfg["price"],
        "timeline": cfg["timeline"],
        "notes": (["Credited toward a full campaign if engaged."]
                  if cfg["credit_toward_campaign"] else []),
    }


def build_rep_quote(payload):
    """
    payload = {
      campaign: 'audit' | 'reactive' | 'proactive' | 'bundle',
      include_audit: bool,
      reviews: {partner: 'partner_a'|'partner_b', count: int},
      articles: {standard: int, premium: int},
      search: {volume: int, suppression: bool, autosuggest: bool, term_sets: int},
      shield: {locations: int},
    }
    Returns {lines, phases, totals, warnings}.
    """
    campaign = payload.get("campaign", "reactive")
    lines, warnings = [], []
    phase1, phase2 = [], []

    if payload.get("include_audit") or campaign == "audit":
        lines.append(dict(price_audit(), phase=0))

    if campaign in ("reactive", "bundle"):
        rv = payload.get("reviews") or {}
        ln = price_reviews(rv.get("partner", "partner_b"), rv.get("count", 0))
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
