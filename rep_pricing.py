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
    multiplier)". HARD-COST CANONICAL as of July 2026: bases/per-1K/floor/cap
    in SEARCH_BUNDLE are partner hard cost (see block comment there);
    client = hard \u00f7 (1 \u2212 margin). Sage replay is now approximate
    ($7,550 vs $7,400 actual at 35%).
  * Proactive Brand Shield — single monthly bundle. "$[Monthly Price]" in doc;
    placeholder below.
"""

def r50(x):
    """Round up to the next $50 — same convention as the SEO tool. The
    round() guard strips float noise (e.g. 3000×1.35 = 4050.0000000000005)
    so exact multiples don't ceil a full $50 high."""
    import math
    return int(math.ceil(round(x, 6) / 50.0) * 50)


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
        # FIXED rate card per the Vici chart (July 2026) — gross $900/$850/
        # $800/$750/$700/$650, Vici hard (net) below. Do NOT recalibrate;
        # the chart is the product. Whole-order: rate applies to all.
        "brackets": [                       # whole-order: rate applies to all
            {"min": 1,   "max": 25,   "hard": 585.00},
            {"min": 26,  "max": 50,   "hard": 552.50},
            {"min": 51,  "max": 100,  "hard": 520.00},
            {"min": 101, "max": 250,  "hard": 487.50},
            {"min": 251, "max": 350,  "hard": 455.00},
            {"min": 351, "max": 500,  "hard": 422.50},
        ],
        # True fulfillment cost beneath the rate card — CONFIRMED (Kiri,
        # July 2026): $400/review up to 100, $300/review over 100. Shown in
        # the internal box in place of the generic 20% estimate.
        "internal_cost": [
            {"min": 1,   "max": 100,  "cost": 400.00},
            {"min": 101, "max": None, "cost": 300.00},
        ],
        "timeline": "\u224848 hours\u201360 days depending on fulfillment routing",
        "pay_on_success": True,
    },

    # ------------------------------------------------ website/article removals
    # Whole-order brackets = Brendan's Visions Electronics actuals (2024).
    # Premium (DA>35 / news-legal class) = Tru North actual $7,500. Brendan's
    # notes: always custom quoted + human review — these are starting anchors.
    "article_removal": {
        # Recalibrated July 2026 from Brendan's contractor invoice list
        # (19 URLs, Goldstone-cluster engagements): rack rate $7,500\u2013$10,000
        # per page (his words), bulk orders $4,500\u2013$5,500, top-tier news
        # $12,500. The Visions whole-order bracket ($5,950\u2192$4,950) matches
        # the BULK rate \u2014 it was a 25+ site order \u2014 so small orders now
        # start at rack and slide to the confirmed bulk floor.
        "brackets": [
            {"min": 1,  "max": 3,    "per": 7500},   # rack (observed: repost @ $7,500)
            {"min": 4,  "max": 6,    "per": 6500},
            {"min": 7,  "max": 10,   "per": 5750},
            {"min": 11, "max": 15,   "per": 5350},   # observed bulk batch ~15 @ $4.5\u20135.5K
            {"min": 16, "max": None, "per": 4950},   # Visions bulk floor
        ],
        "premium_per": 12500,                        # top-tier news actual (insurancenewsnet,
                                                     # Gannett in-depth — Goldstone list July 2026)
        "timeline": "2\u20133 months average, up to 6",
        "pay_on_success": True,
        # Site classes are ROUTING/DESCRIPTION only as of July 2026 — pricing
        # for every standard class comes off the whole-order brackets above.
        # Basis: Brendan's Goldstone-cluster removal list (July 2026) prices
        # YouTube videos, Medium posts, PacerMonitor PDFs, root domains, and
        # standard news stories all in ONE channel: bulk $4,500\u2013$5,500,
        # rack $7,500\u2013$10,000. The old market bands ($900\u2013$3,000
        # forum, $500\u2013$2,500 review-platform) have no basis in his
        # channel and under-quoted by ~3\u20134\u00d7. Top-tier/in-depth news
        # = premium_per ($12,500 \u2014 same domain can be either tier
        # depending on the piece).
        "classes": {
            # low/high/est are BACK-COMPAT/display keys only (config endpoint
            # reads them) — set to the Brendan channel band; actual pricing
            # comes off the whole-order brackets above.
            "review_platform": {
                "label": "Review platform page (Trustpilot-class)",
                "low": 4500, "high": 10000, "est": 7500,
                "route": "platform policy flag \u2192 Content Integrity review",
                "timeline": "2\u201310 weeks"},
            "forum": {
                "label": "Forum thread (Reddit / Quora)",
                "low": 4500, "high": 10000, "est": 7500,
                "route": "sitewide-policy removal or Google de-index",
                "timeline": "1\u20138 weeks"},
            "gripe": {
                "label": "Complaint board (RipoffReport-class)",
                "low": 4500, "high": 10000, "est": 7500,
                "route": "de-index / negotiated removal (no source removal on RoR)",
                "timeline": "2\u20133 months average, up to 6"},
        },
    },

    # ------------------------------------------------- search protection bundle
    # monthly = base + per_1k * (monthly brand search volume / 1000), CEIL50,
    # clamped to [floor, cap]. Components can be quoted together or singly.
    "search_protection": {
        "suppression": {                       # organic search suppression
            "label": "Organic Search Suppression",
            # Recalibrated July 2026 to the LOWER Tru North tier: $2,650
            # floor (his base campaign) + $15/1K still lands Sage's $3,450
            # exactly at 51,330/mo.
            "base": 2650, "per_1k": 15,
            "floor": 2650, "cap": 7500,
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
            "included_negatives": 3,            # ⚠ UNCONFIRMED — Sage actual
                                                # covered 2 phrases at this rate
            "per_extra_negative": 250,          # GUESS
            # Ongoing-mode maintenance mirrors the Visions related-search
            # structure ($2,150/mo after results). The $750 below stays as
            # the guaranteed-mode actual (Goldstone 2021).
            "ongoing_maintenance_monthly": 2150,
            "ongoing_maintenance_timeline": "3\u20136 months post-result hold",
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
    # Partner-hard-cost canonical (Kiri, July 2026): $2,250/mo hard base +
    # $450/mo hard per extra location. Client price = each component
    # \u00f7 (1 \u2212 margin) (margin is % OF GROSS \u2014 same mechanics as every
    # other tactic; retail carries the 35% built in), rounded UP to the
    # nearest $50 separately. At 35%: $3,500 base + $700/extra location.
    "shield": {
        "monthly_hard": 2250,             # partner hard cost, base (1 location)
        "included": ["SEO Brand Shield & Asset Building",
                     "Automated Review Generation & Sentiment Routing",
                     "24/7 Brand Monitoring & Threat Detection"],
        "included_locations": 1,
        "per_extra_location_hard": 450,   # partner hard cost per extra location
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

def price_reviews(n, margin_pct=None, scan_meta=None, hard_override=None):
    """Review-removal line off the Vici rate card. Whole-order bracket on the
    HARD cost; client gross derived from the editable margin (% of gross).
    Presented per-removal-first: the total is a pay-on-success MAXIMUM, so the
    per-review rate and the flagged count carry the line. scan_meta (from the
    brand scan) adds provenance: which Google locations were counted and
    whether the flag total covers all of them."""
    n = max(0, int(n or 0))
    if n == 0:
        return None
    cfg = REP_CFG["review_removal"]
    m = cfg["default_margin_pct"] if margin_pct is None else float(margin_pct)
    m = min(0.90, max(0.0, m))
    hard_per, over_chart, overridden = None, False, False
    if hard_override:
        hard_per, overridden = float(hard_override), True
    else:
        for b in cfg["brackets"]:
            if n >= b["min"] and (b["max"] is None or n <= b["max"]):
                hard_per = b["hard"]
                break
        if hard_per is None:
            hard_per = cfg["brackets"][-1]["hard"]
            over_chart = True
    gross_per = round(hard_per / (1.0 - m) / 5.0) * 5
    total = int(round(gross_per * n))
    hard_total = round(hard_per * n, 2)
    int_per = next((c["cost"] for c in cfg.get("internal_cost", [])
                    if n >= c["min"] and (c["max"] is None or n <= c["max"])),
                   hard_per * INTERNAL_COST_PCT["pct"])
    line = {
        "service": "Negative Review Removals",
        "detail": f"${gross_per:,.0f} per removed review \u00b7 "
                  f"{n:,} flagged review{'s' if n != 1 else ''}",
        "qty": n, "unit": gross_per,
        "unit_label": f"${gross_per:,.0f}/removed review",
        "kind": "per_asset", "total": total,
        "timeline": cfg["timeline"],
        "notes": ["Pay on success \u2014 billed per removed review; the total is "
                  "a maximum, not a committed spend.",
                  "Success rate: ~100% via 48-hour priority routing; 40\u201350% "
                  "via bulk routing (30\u201360 days).",
                  "Some sensitive content cannot be removed."],
        "internal": {
            "hard_per": hard_per, "hard_total": hard_total,
            "profit_total": round(total - hard_total, 2),
            "margin_pct": m,
            "rows": [
                {"label": "Partner hard cost",
                 "value": f"${hard_total:,.0f} (${hard_per:,.2f}/rev)"},
                {"label": "Internal hard cost (confirmed)",
                 "value": f"${int_per*n:,.0f} (${int_per:,.2f}/rev)"}],
        },
    }
    if scan_meta:
        locs = [l for l in (scan_meta.get("locations") or []) if l]
        total_locs = int(scan_meta.get("total_locations") or 0)
        if locs:
            # Surfaced in the summary card as "X/Y locations scanned"
            # (replaces the old "not yet counted" warning note, July 2026).
            line["locs_scanned"] = len(locs)
            line["locs_total"] = max(total_locs, len(locs))
        if scan_meta.get("truncated"):
            line["notes"].append(
                "\u26a0 At least one location hit the pull depth \u2014 its "
                "negative count may be understated; re-run at higher depth.")
    if over_chart:
        line["notes"].append(f"{n:,} reviews exceeds the 500-review rate card \u2014 "
                             "top-tier rate extended; confirm with fulfillment partner.")
    if overridden:
        line["notes"].insert(0, "\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote.")
    return line


# Per Kiri (July 2026): Brendan's invoice figures are CLIENT prices that
# already carry the standard 35% markup. Partner hard cost is therefore
# client_at_35 \u00d7 0.65, held canonical; the quoted client price rebuilds
# from hard cost at whatever margin the quote uses (35% default replays
# Brendan's numbers exactly).
ART_CAL_MARGIN = 0.35

# Vici internal delivery cost, modeled as a % of partner hard cost.
# Editable live via the pricing config panel.
INTERNAL_COST_PCT = {"pct": 0.20}

# Scan tunables surfaced in the pricing-config panel (rarely edited).
SCAN_SETTINGS = {"review_pull_depth": 200}

def _mrows(hard, unit_suffix="", total=None, tbd=False):
    """Two-row internal grid: partner hard cost + internal hard cost. tbd
    may be True (renders the red 'TBD \u2014 confirm' flag) or a string
    (renders that flag text instead, e.g. 'quoted manually')."""
    ip = INTERNAL_COST_PCT["pct"]
    def v(x):
        return f"${x:,.0f}{unit_suffix}" + (f" \u00b7 ${x/hard*total:,.0f} total"
                                            if total is not None else "")
    if isinstance(tbd, str):
        # manually quoted — no % basis and no computed figure to imply one
        row2 = {"label": "Internal hard cost", "value": "\u2014", "tbd": tbd}
    else:
        row2 = {"label": f"Internal hard cost ({ip:.0%})", "value": v(hard*ip)}
        if tbd:
            row2["tbd"] = tbd
    return [{"label": "Partner hard cost", "value": v(hard)}, row2]

def _art_hard(client_at_35):
    return client_at_35 * (1 - ART_CAL_MARGIN)

def _art_client(hard, margin_pct):
    m = min(0.95, max(0.0, float(margin_pct)))
    return r50(hard / (1 - m))

def _art_internal(hard_per, cnt, unit, m):
    return {"rows": _mrows(hard_per, "/pg", hard_per*cnt, tbd="quoted manually")}


def price_articles(n_standard, n_premium, classes=None, margin_pct=None,
                   hard_std_override=None, hard_prem_override=None):
    """Website/article removals. Config figures are client prices at the
    calibrated 35% markup; partner hard cost (\u00d70.65) is canonical and the
    quoted client price rebuilds from it at margin_pct (default 35% replays
    the config numbers exactly). Scan-supplied per-site-class counts price
    on ESTIMATE bands; otherwise the whole-order bracket applies."""
    cfg = REP_CFG["article_removal"]
    m = ART_CAL_MARGIN if margin_pct is None else float(margin_pct)
    lines = []
    n = max(0, int(n_standard or 0))
    cls_counts = {k: int(v) for k, v in (classes or {}).items()
                  if k in cfg["classes"] and int(v or 0) > 0}
    use_classes = cls_counts and sum(cls_counts.values()) == n
    if use_classes:
        # Whole-order bracket rate by TOTAL standard count — Brendan's July
        # 2026 list prices every standard page in one channel regardless of
        # site type; the class only determines route/label/timeline.
        if hard_std_override:
            hard = float(hard_std_override)
        else:
            per35 = next(b["per"] for b in cfg["brackets"]
                         if n >= b["min"] and (b["max"] is None or n <= b["max"]))
            hard = _art_hard(per35)
        unit = _art_client(hard, m)
        for key, cnt in cls_counts.items():
            c = cfg["classes"][key]
            lines.append({
                "service": "Negative Website/Article Removals \u2014 Standard",
                "detail": f"{cnt} \u00d7 {c['label']} @ ${unit:,}/page",
                "qty": cnt, "unit": unit, "kind": "per_asset",
                "total": unit * cnt, "timeline": c["timeline"],
                "estimated": True,
                "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_std_override else [])
                         + [f"Route: {c['route']}.",
                            "Pay on success \u2014 billed only for pages removed.",
                            "Success rate: ~100% to date on standard hosts (complaint boards, forums, blogs); court and legal-database pages run closer to 50%.",],
                "internal": _art_internal(hard, cnt, unit, m),
            })
    elif n:
        if hard_std_override:
            hard = float(hard_std_override)
        else:
            per35 = next(b["per"] for b in cfg["brackets"]
                         if n >= b["min"] and (b["max"] is None or n <= b["max"]))
            hard = _art_hard(per35)
        per = _art_client(hard, m)
        lines.append({
            "service": "Negative Website/Article Removals \u2014 Standard",
            "detail": f"{n} standard site{'s' if n != 1 else ''} @ ${per:,}/removed",
            "qty": n, "unit": per, "kind": "per_asset", "total": per * n,
            "timeline": cfg["timeline"],
            "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_std_override else [])
                     + ["Pay on success \u2014 billed only for sites removed.",
                        "Success rate: ~100% to date on standard hosts (complaint boards, forums, blogs); court and legal-database pages run closer to 50%.",
                        "Always custom-quoted after human review."],
            "internal": _art_internal(hard, n, per, m),
        })
    p = max(0, int(n_premium or 0))
    if p:
        phard = (float(hard_prem_override) if hard_prem_override
                 else _art_hard(cfg["premium_per"]))
        punit = _art_client(phard, m)
        lines.append({
            "service": "Negative Website/Article Removals \u2014 Premium (news / high-authority)",
            "detail": f"{p} premium site{'s' if p != 1 else ''} (DA > 35 / news-legal) "
                      f"@ ${punit:,}/removed",
            "qty": p, "unit": punit, "kind": "per_asset",
            "total": punit * p,
            "timeline": "10\u201314 weeks typical (12-month contract window)",
            "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_prem_override else [])
                     + ["Pay on success \u2014 billed only for pages removed.",
                        "Success rate: ~50% on premium news / high-authority hosts.",
                        "Always custom-quoted after human review."],
            "internal": _art_internal(phard, p, punit, m),
        })
    return lines


def _vol_monthly(component, volume):
    """base + per_1k formula with floor/cap, CEIL50."""
    c = REP_CFG["search_protection"][component]
    raw = c["base"] + c["per_1k"] * (max(0, volume) / 1000.0)
    return min(c["cap"], max(c["floor"], r50(raw)))


# =====================================================================
# SIMPLIFIED TACTIC MENU (July 2026, per Kiri's template): Reactive =
# review removals + article removals + Search Protection Bundle only.
# Proactive = Brand Shield Bundle only. Everything below this block that
# prices retired tactics (tiers, guaranteed phrases, engines, BBB, GEO,
# PR, review gen, video) is KEPT for reference and custom blends but is
# no longer wired into build_rep_quote.
# =====================================================================
SEARCH_BUNDLE = {
    # HARD-COST CANONICAL (Kiri, July 2026): every dollar value below is
    # PARTNER HARD COST — treat these as the starting numbers. Bases were
    # set from the retail-calibrated actuals stripped of their built-in
    # 35% margin, then rounded UP to the nearest $50; per-1K rates carry
    # the exact conversion. Client price = hard \u00f7 (1 \u2212 margin), r50'd.
    # All keys editable live via /api/rep_config.
    # \u26a0 REPLAY DRIFT: the Sage actual (51,330/mo) now quotes $7,550
    # client at 35% vs Brendan's $7,400 \u2014 +$150 (~2%) from the hard-side
    # base rounding. Prior retail-canonical version replayed it exactly.
    "supp_base": 1750,   "as_base": 2250,      # hard $/mo
    "supp_per_1k": 9.75, "as_per_1k": 6.50,    # hard $ per 1K searches
    # comp_per_1k is a LEGACY ALIAS kept so the /api/rep_config endpoint
    # and older saved configs don't break — the split supp/as keys above
    # take precedence everywhere in pricing.
    "comp_per_1k": 6.50,
    "floor": 3950, "cap": 10050,               # hard $/mo
    # 3 negative suggest/related phrases baked into the base price.
    # ⚠ UNCONFIRMED — Sage actual covered 2 phrases at this rate; 3 is an
    # internal assumption pending Brendan's confirmation.
    "included_negatives": 3,
    # Maintenance phase per the actuals: full rate until results, then a
    # drop. Visions 2024: $3,950 active → $2,150 maintenance = 0.544; the
    # ratio is applied per component on the hard side. (Suppression-side
    # maintenance is INFERRED — no SSG actual exists for it.)
    "maintenance_pct": 0.544,
    "maintenance_timeline": "Months 7\u201312",
    "timeline": "4\u20136 months",
}

def _bundle_components(volume):
    """Per-component HARD monthlies, each CEIL50'd (mirrors Brendan quoting
    the two lines separately). Falls back to legacy shared comp_per_1k if
    present in a saved config."""
    v = max(0, volume) / 1000.0
    p_s = SEARCH_BUNDLE.get("supp_per_1k", SEARCH_BUNDLE.get("comp_per_1k", 9.75))
    p_a = SEARCH_BUNDLE.get("as_per_1k", SEARCH_BUNDLE.get("comp_per_1k", 6.50))
    return (r50(SEARCH_BUNDLE["supp_base"] + p_s * v),
            r50(SEARCH_BUNDLE["as_base"] + p_a * v))

def price_search_bundle(volume, margin_pct=None, hard_override=None):
    # Hard-native: components, floor, and cap are all partner hard cost.
    # Each component keeps its own CEIL50 rounding before summing.
    supp_h, as_h = _bundle_components(volume)
    hard = (float(hard_override) if hard_override
            else min(SEARCH_BUNDLE["cap"], max(SEARCH_BUNDLE["floor"], supp_h + as_h)))
    mg = ART_CAL_MARGIN if margin_pct is None else min(0.95, max(0.0, float(margin_pct)))
    m = r50(hard / (1 - mg))
    inc = SEARCH_BUNDLE.get("included_negatives", 3)
    return {
        "service": "Search Protection Bundle",
        "detail": f"Scales with brand search volume \u00b7 "
                  f"{volume:,}/mo measured",
        "kind": "monthly", "total": m, "timeline": SEARCH_BUNDLE["timeline"],
        "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_override else [])
               + ["Includes Organic Search Suppression, Auto-Suggest & Related "
                  "Search Manipulation, and Branded Search Append.",
                  f"Includes up to {inc} negative phrase removals across "
                  "auto-suggest and related searches."],
        "internal": {"rows": _mrows(hard, "/mo") + [
            {"label": f"\u26a0 {inc}-phrase inclusion",
             "value": "internal assumption \u2014 Sage actual covered 2; "
                      "pending pricing review", "tbd": True}]},
    }


def price_search_bundle_maintenance(volume, margin_pct=None, hard_override=None):
    """Post-result maintenance phase, per the actuals: full rate while
    active, then a drop once negatives are cleared. Ratio 0.544 is derived
    from the Visions 2024 actual ($3,950 active → $2,150 maintenance) and,
    applied per component, replays the $2,150 exactly on the auto-suggest
    side. Sequential — never billed alongside the active line."""
    pct = SEARCH_BUNDLE.get("maintenance_pct", 0.544)
    if hard_override:
        # override is the ACTIVE-phase hard/mo; maintenance keeps the ratio
        hard = float(hard_override) * pct
    else:
        supp_h, as_h = _bundle_components(volume)
        hard = r50(supp_h * pct) + r50(as_h * pct)
    mg = ART_CAL_MARGIN if margin_pct is None else min(0.95, max(0.0, float(margin_pct)))
    m = r50(hard / (1 - mg))
    return {
        "service": "Search Protection \u2014 Maintenance Phase",
        "detail": "Reduced monthly rate once your results are achieved \u2014 "
                  "protects the cleaned-up search presence",
        "kind": "monthly_maint", "total": m,
        "timeline": SEARCH_BUNDLE.get("maintenance_timeline",
                                      "3\u20136 months, as results are "
                                      "achieved (auto-suggest typically "
                                      "clears in 2\u20133 months)"),
        "notes": (["\u2699 Manual hard-cost override active \u2014 maintenance "
                   "keeps its % ratio off the overridden active rate."]
                  if hard_override else [])
               + ["Begins only after the active campaign reaches its goals, "
                  "and replaces the active monthly rate \u2014 the two are "
                  "never billed together.",
                  "Recommended to lock in results and keep negative content "
                  "from returning."],
        "internal": {"rows": _mrows(hard, "/mo") + [
            {"label": "\u26a0 Maintenance reduction",
             "value": f"currently {int(pct*1000)/10}% of active (Visions "
                      "2024: $3,950\u2192$2,150) \u2014 how deep should "
                      "the reduction be?",
             "tbd": "pricing review"}]},
    }


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
                          "the negative-modifier volume.",
                          f"\u26a0 {c['included_negatives']}-phrase inclusion is an "
                          "internal assumption (Sage actual covered 2) \u2014 "
                          "pending pricing review."],
            })
            lines.append({
                "service": "Search Protection \u2014 Auto-Suggest Maintenance",
                "detail": f"${c['ongoing_maintenance_monthly']:,}/mo after results "
                          "(mirrors Visions related-search actual)",
                "kind": "monthly_maint", "total": c["ongoing_maintenance_monthly"],
                "timeline": c["ongoing_maintenance_timeline"],
                "notes": ["Sequential \u2014 replaces the active line; never "
                          "billed concurrently."],
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
                "kind": "monthly_maint", "total": c["maintenance_monthly"],
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
        "notes": ["GUESS pricing \u2014 no calibration datapoint yet; confirm brackets.",
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

def price_geo(phase="setup", margin_pct=None, hard_override=None):
    p = GEO.get(phase) or GEO["setup"]
    hard = float(hard_override) if hard_override else p["monthly"] * (1 - ART_CAL_MARGIN)
    mg = ART_CAL_MARGIN if margin_pct is None else min(0.95, max(0.0, float(margin_pct)))
    client = r50(hard / (1 - mg))
    return {"service": "Reputational AI Search",
            "detail": f"{phase.capitalize()} phase \u2014 shapes AI Overview / LLM "
                      "answers about the brand",
            "kind": "monthly", "total": client, "timeline": p["timeline"],
            "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_override else [])
                   + ["Targets the negative AI-generated result the scan detects.",
                      "Priced off the standard GEO card ($4,950 setup / $9,950 "
                      "scale) \u2014 reputational application unconfirmed.",
                      "Recommend setup phase 1\u20132 quarters, then scale."],
            "internal": {"rows": _mrows(hard, "/mo")}}


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
                      "Always custom-quoted by complexity."]}


def price_shield(locations=1, margin_pct=None, hard_override=None):
    cfg = REP_CFG["shield"]
    locations = max(1, int(locations or 1))
    extra = max(0, locations - cfg["included_locations"])
    m = 0.35 if margin_pct is None else min(0.95, max(0.0, float(margin_pct)))
    base_hard = float(hard_override) if hard_override else cfg["monthly_hard"]
    loc_hard = cfg["per_extra_location_hard"]
    base_client = r50(base_hard / (1 - m))
    loc_client = r50(loc_hard / (1 - m))
    total = base_client + extra * loc_client
    hard_total = base_hard + extra * loc_hard
    det = "Proactive Brand Shield Bundle"
    if extra:
        det += f" \u00b7 {locations} locations (+${loc_client:,}/extra location)"
    return {
        "service": "Proactive Brand Shield",
        "detail": det, "kind": "monthly", "total": total,
        "timeline": "Ongoing",
        "notes": (["\u2699 Manual hard-cost override active \u2014 formula/rate card bypassed for this quote."] if hard_override else [])
               + list(cfg["included"]),
        "internal": {"rows": _mrows(hard_total, "/mo")},
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
    ov = payload.get("overrides") or {}
    lines, warnings = [], []
    phase1, phase2 = [], []

    if campaign in ("reactive", "bundle"):
        rv = payload.get("reviews") or {}
        ln = price_reviews(rv.get("count", 0),
                           rv.get("margin_pct", payload.get("margin_pct")),
                           rv.get("scan_meta"),
                           hard_override=ov.get("review_hard"))
        if ln:
            phase1.append(ln)
        ar = payload.get("articles") or {}
        art_lines = price_articles(ar.get("standard", 0), ar.get("premium", 0),
                                   ar.get("classes"),
                                   ar.get("margin_pct", payload.get("margin_pct")),
                                   hard_std_override=ov.get("art_std_hard"),
                                   hard_prem_override=ov.get("art_prem_hard"))
        phase1 += art_lines
        se = payload.get("search") or {}
        if se.get("bundle"):
            vol = int(se.get("volume") or 0)
            sp_line = price_search_bundle(vol, payload.get("margin_pct"),
                                          hard_override=ov.get("search_hard"))
            if campaign == "bundle":
                # Reactive + Proactive: the Brand Shield (phase 2) IS the
                # post-result hold — quoting a separate maintenance phase
                # would double-bill the same protective work. SSG actuals
                # never stacked them: every maintenance quote (Visions,
                # Sage, Goldstone) was a standalone reactive engagement.
                # (Client-facing note about this removed July 2026 — the
                # absence of a maintenance line speaks for itself.)
                phase1.append(sp_line)
            else:
                phase1.append(sp_line)
                phase1.append(price_search_bundle_maintenance(vol, payload.get("margin_pct"),
                                                              hard_override=ov.get("search_hard")))
            sp = REP_CFG["search_protection"]
            if vol > sp["review_above_volume"]:
                warnings.append(
                    f"Brand volume {vol:,}/mo exceeds the "
                    f"{sp['review_above_volume']:,} review threshold \u2014 "
                    "confirm out-search capacity before quoting.")
        ge = payload.get("geo") or {}
        if ge.get("enabled"):
            phase1.append(price_geo(ge.get("phase") or "setup", payload.get("margin_pct"),
                                    hard_override=ov.get("geo_hard")))


    if campaign in ("proactive", "bundle"):
        sh = payload.get("shield") or {}
        phase2.append(price_shield(sh.get("locations", 1), payload.get("margin_pct"),
                                   hard_override=ov.get("shield_hard")))

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
