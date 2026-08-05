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
import time as _time
import storage

app = Flask(__name__)

def _json_error_guard(fn):
    """Any unhandled exception in an API route produces Flask's HTML error page,
    which the frontend can only report as the opaque 'Server 500 (timeout or
    non-JSON)'. This wrapper returns the real cause as JSON instead, turning
    "it broke" into a fixable report, and logs the traceback for Render.

    Written for the save routes and originally applied only there — which meant
    a failure anywhere in the quoting pipeline was still a black box
    (2026-07-26). It is now applied to every /api/ route. abort()/HTTP errors
    are re-raised untouched so 404s stay 404s.
    """
    from functools import wraps
    from werkzeug.exceptions import HTTPException

    @wraps(fn)
    def inner(*a, **k):
        try:
            return fn(*a, **k)
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                app.logger.exception("API route failed: %s", fn.__name__)
            except Exception:
                pass
            return jsonify({"error": f"{type(e).__name__}: {e}",
                            "route": fn.__name__}), 500
    return inner



# Build stamp shown in the header — derives from the deploy commit so it
# updates automatically with every GitHub upload (falls back to boot date).
import datetime as _dt
BUILD_ID = (os.environ.get("RENDER_GIT_COMMIT", "")[:7]
            or _dt.datetime.utcnow().strftime("dev-%m%d"))

# SOURCE FINGERPRINT (2026-07-27).
# The commit hash and the deploy time both describe the DEPLOY, not the code —
# so there was no way to tell, before opening the app, whether the files you
# uploaded are the ones running. Re-uploading the same file, or dropping one in
# the wrong folder, still produces a fresh hash and a fresh timestamp. This
# hashes the actual file contents instead: the same files always produce the
# same six characters, and any change to any of them produces different ones.
# Whoever hands over a build can state the expected value in advance.
# reputation.html added 2026-08-04: it was the one shipped template NOT covered,
# so a rep-mgmt-only change left the fingerprint identical and there was no way
# to confirm from the header that the deploy had taken. rep_pricing/rep_scan
# included for the same reason — they carry the rep quote's actual maths.
FINGERPRINT_FILES = ("app.py", "storage.py", "templates/index.html",
                     "templates/reputation.html", "rep_pricing.py", "rep_scan.py")

def _source_fingerprint():
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for rel in FINGERPRINT_FILES:
        try:
            with open(os.path.join(here, rel), "rb") as fh:
                # Normalise line endings so a checkout on a different platform
                # doesn't change the answer for identical content.
                h.update(fh.read().replace(b"\r\n", b"\n"))
        except Exception:
            h.update(b"<missing>")
        h.update(b"\x00")
    return h.hexdigest()[:6]

SOURCE_FP = _source_fingerprint()


def model_is_snapshot(model_id):
    """Is this model ID a FIXED snapshot, or an alias that can move under us?

    Per Anthropic's model-versioning docs: from the 4.6 generation onward the
    dateless ID *is* the canonical snapshot — claude-sonnet-4-6 does not float.
    Only pre-4.6 dateless IDs (claude-sonnet-4-5 and earlier) are convenience
    aliases resolving to the latest dated snapshot. Anything carrying an
    explicit date is pinned by definition.
    """
    import re as _re
    mid = (model_id or "").strip().lower()
    if _re.search(r"-\d{8}$", mid):
        return True                                   # explicit dated snapshot
    m = _re.match(r"^claude-(?:sonnet|opus|haiku|fable|mythos)-(\d+)(?:-(\d+))?$", mid)
    if not m:
        return False                                  # unrecognised: treat as unpinned
    return (int(m.group(1)), int(m.group(2) or 0)) >= (4, 6)
def _build_stamp():
    """Build time in US Eastern (EST/EDT handled by the tzdb). Falls back to a
    fixed -05:00 if the container image ships without tzdata."""
    try:
        from zoneinfo import ZoneInfo
        now = _dt.datetime.now(ZoneInfo("America/New_York"))
        label = now.strftime("%Z") or "ET"
    except Exception:
        now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-5)))
        label = "ET"
    return (f"build {now.strftime('%Y-%m-%d %I:%M %p').lstrip('0')} {label} "
            f"\u00b7 {BUILD_ID} \u00b7 src {SOURCE_FP}")

BUILD_STR = _build_stamp()
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
        # RECALIBRATED 2026-07-25 (2,900 -> 2,050). The 2,900 figure was
        # back-solved from Brendan's national card WITH the extras muted, so
        # it silently contained the volume add and the zero-ranking uplift —
        # it WAS the "national client with nothing ranking" price, not the
        # starting point. Now that extras are live (Brendan: volume,
        # competition and visibility are what separate national clients), the
        # anchor has to be the bare floor those signals build up FROM, or the
        # scope is charged twice. Validated on both national actuals:
        #   Skidmore (adder 50, vol 24k, 90% not ranking)
        #     -> 4,000 / 5,450 / 6,950 vs actual 3,950 / 5,450 / 6,950
        #   MPG      (adder  0, vol 25k+, 100% not ranking)
        #     -> 3,900 / 5,400 / 6,900 vs actual 3,950 / 5,450 / 6,950
        # An established national brand that already ranks now prices BELOW
        # the card, which is the behaviour Brendan described and the old
        # constant made impossible.
        "nationwide":           2050,
    },
    "competitive_adder": {0: 0, 1: 150, 2: 300},   # FLAT fallback (used when no bid data)
    "bid_score_breaks": [5.0, 15.0],          # <5->0, 5-15->1, >=15->2 (for the fallback)
    # Organic-difficulty breaks, used ONLY when no bid data exists anywhere (a
    # Google Ads restricted vertical). KD scores onto the SAME 0/1/2 ladder as
    # bids, so the suggestion reuses the existing calibration instead of
    # inventing a second one: <30 -> 0, 30-60 -> 1, >60 -> 2.
    "kd_score_breaks": [30, 60],
    # --- CPC-scaled competitive adder ---
    # The competitive adder scales with the median top-of-page bid (CPC), because
    # CPC is the market's own measure of how valuable a click is: high-CPC verticals
    # (e.g. insurance ~$150) mean ranking organically replaces huge ad spend, so the
    # SEO is worth more. adder = median_cpc × cpc_adder_mult, rounded to $50, capped.
    # When there's NO bid data, fall back to the flat score buckets above.
    "cpc_adder_enabled": True,
    "cpc_adder_mult": 3.0,                     # $ of hard-cost adder per $1 of median CPC (up to the knee)
    # CONFIDENCE FLOOR (2026-07-27). The adder scales off the MEDIAN
    # top-of-page bid, and above the knee each extra dollar of CPC adds $14 —
    # so an outlier is amplified enormously. That is fine on a real median and
    # dangerous on a sample of one: Rockingham priced a +$1,000 adder off a
    # single term's bid estimate (1 of 3 head terms returned data). Below this
    # many samples the adder still applies but the quote is flagged, because
    # the number is an extrapolation rather than a measurement. Raise this to
    # make thin samples fall back to the flat score buckets instead.
    # Grounding filter safety valve (2026-07-27). Requiring every word of a
    # model-invented service to appear in the client's own text catches
    # competitor names cleanly when the client HAS a rich vocabulary — Keller
    # says commercial/industrial/agricultural and never says Turner. It fails
    # badly when they don't: MPG's whole description is "energy and electrolyte
    # gummies for athletes", so hydration, caffeine, pre-workout and b12 all
    # read as alien and 100% of the invented services were removed. A filter
    # that deletes everything is measuring the description's length, not the
    # services' legitimacy — so above this drop ratio it stands down entirely
    # and says so rather than gutting the list.
    # A suggested region name must clear this monthly volume WITH a service
    # attached before it can enter the grid. Below it the name may be real but
    # nobody searches it, and an unsearched keyword in a proposal is a promise
    # to rank for something with no demand behind it.
    "region_min_volume": 10,
    "grounding_max_drop_ratio": 0.5,
    # Rank-check batch budget. Was hardcoded at 24s "to stay well under the
    # ~30s platform kill" — which was right when gunicorn's default 30s
    # timeout applied, and is now far too tight: any keyword still waiting
    # when the budget runs out is recorded as a FAILED lookup, which is what
    # produces "7 lookups failed and were excluded" on a healthy account
    # (2026-07-28). They aren't permanent failures; they're keywords that ran
    # out of clock. Derived from REQUEST_BUDGET_S so raising the server
    # timeout actually buys more lookups instead of nothing.
    "rank_batch_budget_s": 0,           # 0 = derive from REQUEST_BUDGET_S
    "cpc_adder_min_samples": 1,          # apply the CPC adder at/above this n
    "cpc_adder_low_confidence_n": 3,     # warn below this n
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
    # Visibility moves the price BOTH ways. Brendan: "it's more about their
    # current visibility + search volume + competition." Until now visibility
    # could only add — a client with established rankings paid the same as an
    # average one. The negative bottom tier is the discount for a client that
    # already ranks; fit on Susquehanna (60% of head terms ranking, quoted
    # ~7% under the statewide anchor). ONE datapoint — confirm with Brendan
    # before trusting it on a second well-ranked client.
    "zero_ranking_tiers": [
        [80, 14],   # 80%+ not ranking -> +14%
        [65, 9],    # 65-80% -> +9%
        [50, 5],    # 50-65% -> +5%
        [45, 0],    # 45-50% -> par (buffer so the sign doesn't flip on a hair)
        # RECALIBRATED 2026-07-27 (-7 -> -3). The -7 was fit on Susquehanna
        # alone. Red Shoes is the second well-ranked client and it contradicts
        # it: 80% of its terms rank — BETTER than Susquehanna's 60% — and it
        # was quoted the standard $2,950 card, not a discount. Swept against
        # both, -7 is the worst value in the range (7.7% error on Red Shoes);
        # 0 to -3 is the best balance and the two are within noise of each
        # other. -3 keeps a small, defensible nod to existing visibility
        # without the one-client overfit. The residual on Susquehanna is an
        # ANCHOR question (statewide at 2,350 for a small regional bureau),
        # not a visibility one — don't chase it with this tier.
        [0, -3],    # under 45% not ranking = well-ranked -> small discount
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
    # HEAD-TERM PINNING (2026-07-25). The service list comes from a Claude
    # call, so the same client can produce a different list run to run. That is
    # fine for long-tail colour and NOT fine for pricing: Skidmore's first run
    # carried "brand identity design" (18,100/mo = 76% of its total volume),
    # the second dropped it for "brand identity agency" (320), and the quote
    # fell $700/tier on nothing the client did. Volume is a pricing input, so
    # the highest-demand terms the search API actually returned are FORCED into
    # the list regardless of what the model picks. Set pin_head_terms to 0 to
    # go back to a purely model-chosen list.
    "pin_head_terms": 3,                # how many top-volume candidates to force
    "pin_min_volume": 300,              # ignore anything thinner than this
    "pin_as_ultra": 2,                  # the top N pins are the ultra-competitive tier
    # VOLUME IS OPPORTUNITY, NOT DEMAND (2026-07-25).
    # Susquehanna River Valley VB has the largest raw volume of any calibration
    # client (135k/mo) and the largest value-weighted demand after Skidmore,
    # and Brendan priced it BELOW the statewide anchor. It also already ranks
    # for 60% of its head terms. The reconciliation: a client that already
    # ranks for its demand has nothing to buy — you are not selling them that
    # volume, you are maintaining it. The volume add prices the OPPORTUNITY,
    # so it only applies where the demand is still uncaptured.
    #
    # Checked against every signal available on three clients with published
    # actuals; only this one splits them:
    #   raw volume    135k -> $0,  25k -> $500,  24k -> $500   non-monotonic
    #   volume x CPC  100k -> $0,  24k -> $500, 471k -> $500   non-monotonic
    #   % not ranking  40% -> $0, 100% -> $500,  88% -> $500   clean at 50%
    # (This is why the value-weighted model was NOT adopted: it fails on MPG,
    # which has the lowest click value of the three and needs the full add.)
    # The 50 pivot is the one zero_ranking_tiers already turns on.
    # A hard gate at 50% put a $900/tier cliff between a client at 49% and one
    # at 51%, which no operator could defend in a room. Ramped instead: the
    # volume add scales linearly from 0% of itself at the bottom of this range
    # to 100% at the top. Fits the same three actuals (Susquehanna 40 -> none,
    # Skidmore 88 and MPG 100 -> full) with no discontinuity in between.
    "vol_add_ramp": [40, 60],           # [no opportunity, full opportunity] % not ranking
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
    # $2,926/$4,037/$5,148 — base = the bare nationwide anchor, steps of 38%.
    #
    # (2026-07-25 REVISION — Brendan meeting) This multiplier was 0.0 on the
    # theory that at national scope the volume add and zero-ranking uplift are
    # tautological ("every nationwide client has >10k volume and ranks for
    # almost nothing"). Brendan says the opposite: volume, competition and
    # CURRENT VISIBILITY are precisely what separate one national client from
    # another — a brand with nothing ranking pays more, an established one
    # pays less. At 0.0 those signals were multiplied out and every national
    # client priced identically. Set to 1.0 (extras live). The Skidmore fit
    # must be re-validated at 1.0 — the original +$1,327 finding was measured
    # against the old inflated-volume lookup and the flat-adder era.
    # If Skidmore comes back high, prefer lowering volume_add_cap over
    # re-zeroing this — the cap is the honest lever, the multiplier is a mute.
    "nationwide_service_extras": 1.0,
    # Brendan steps his ladder in FLAT dollars (~$900-1,000 client per tier),
    # not proportionally — the old 38% ratio made the gap widen with every tier
    # (+15/18/20% on Keller, +13/24/34% on Waytek). Flat $700 hard = ~$950
    # client at 35% markup. step_ratio remains as fallback if flat is nulled.
    # Industry pricing: industries known to carry additional tiered pricing.
    # Matched by substring against the RZ-fed industry text ("DTC ecommerce
    # supplements" matches "ecommerce"). Rule keys:
    #   anchor_add      hard $ added to the base
    #   step_mode       "ratio" (proportional 38% steps) or "flat" (default)
    #   extras_off      skip volume + zero-ranking (org size, not SERPs, prices)
    #   national_demand price on GEO-LESS volume — sets no price of its own
    #
    # (2026-07-25 REVISION — Brendan meeting) The ecommerce family previously
    # carried anchor_add 250 + ratio steps, fit to MPG Gummies. Brendan:
    # ecommerce is "not auto more expensive, but normally in more competitive
    # industries — look at the volumes w/o the geo." So industry no longer
    # moves the price for these; it flips the volume lookup to national and
    # lets volume + CPC adder + zero-ranking do the pricing themselves.
    # NOTE the nationwide anchor ($2,900 hard = $3,915 client) already
    # reproduces Brendan's $3,950 card base on its own — the +$250 was very
    # likely fitting a number the band was going to hit anyway.
    "industry_pricing": {
        "ecommerce":  {"national_demand": True, "note": "Product brand — price on national demand, not a geo-qualified pull. Carries NO price of its own (pricing authority, 2026-07-25). Legacy toggle key."},
        "e-commerce": {"national_demand": True, "note": "Matches RZ “Retail - General / E-commerce”. Price on national demand; no anchor add."},
        # Sibling RZ values an operator would reasonably pick for a product
        # brand (MPG is literally a supplements company) — same volume mode,
        # so the behaviour can't silently vanish on an equally-valid tag.
        "supplements":             {"national_demand": True, "note": "Sibling of e-commerce (MPG is a supplements brand)."},
        "consumer packaged goods": {"national_demand": True, "note": "Sibling of e-commerce — product brand tag."},
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
    # Core SEO + AI Search — GEO PRICING.
    # (2026-07-25 REVISION — Brendan meeting) The $2,950/$4,050/$5,250 card was
    # read off the MPG proposal and hard-coded as universal. It is NOT: MPG had
    # near-zero visibility (little traditional-search presence, almost no AI
    # presence, very few backlinks) which is why its GEO landed ~95% of SEO.
    # Brendan's actual rule: GEO runs 30-50% LESS than SEO on average — i.e.
    # 50-70% of the SEO price — and rises toward parity when nothing ranks.
    # So GEO is a PERCENTAGE of the client's own Core SEO quote, and the
    # percentage is driven by current visibility (the same pct_not_ranking
    # signal the zero-ranking uplift already computes off the top-100 check).
    # Tiers are [min_pct_not_ranking, geo_pct_of_seo], evaluated high-to-low.
    "geo_pricing_mode": "pct",                # "pct" (Brendan rule) or "card" (legacy MPG)
    # CALIBRATION NOTE: MPG's GEO list price is 78% of its SEO price, almost
    # exactly. His intermediate GEO list of $4,250 / SEO intermediate $5,450 =
    # 77.98%; base and advanced back-solve to 78.6% and 79.5% once the 5%
    # bundle discount is removed. So the zero-visibility ceiling is ~78% of
    # SEO -- slightly ABOVE Brendan's stated 50-75% normal band, which is
    # precisely what he said should happen for a client with no visibility.
    # (This assumes MPG's SEO ladder was 3,950/5,450/6,950 -- CONFIRM.)
    # REVISED 2026-07-28: the separate bundle discount is gone and its 5% is
    # folded into these percentages, so this table is now the WHOLE of GEO
    # pricing. Every rate is its old value x 0.95, which leaves the quoted
    # numbers identical — this is a simplification of how the price is
    # expressed, not a change to what anyone pays. Two knobs describing one
    # decision meant the headline rate was never the rate actually charged.
    "geo_pct_tiers": [
        [90, 74],   # <10% of head terms rank  -> the MPG ceiling (was 78 less 5%)
        [70, 66],   # 10-30% rank              -> top of the normal band
        [40, 59],   # 30-60% rank              -> mid of the normal band
        [0,  48],   # 60%+ rank (established)  -> the established-client floor
    ],
    "geo_pct_default": 57,                    # used when no ranking data exists
    # Bundle discount off the GEO line when sold with Core SEO.
    # Provenance: MPG's proposal (2026-06-10) listed the intermediate GEO at
    # "$4,050, discounted from $4,250 in conjunction with the SEO campaign" =
    # 4.7%, and the pricing authority confirmed (2026-07-25) it applies to all
    # three tiers rather than just the one the proposal showed it on.
    # It is doing real work in the fit: against MPG's actual GEO ladder,
    #   5% -> 2,950 / 4,050 / 5,150   avg error 0.6%
    #   0% -> 3,100 / 4,250 / 5,400   avg error 4.3%
    # so it should only be zeroed on a decision that the practice has changed,
    # not on the assumption that the number is stale. Set to 0 and the list
    # row and the "sold with SEO" note disappear from the quote entirely.
    "geo_bundle_discount_pct": 0,             # RETIRED — folded into geo_pct_tiers
    # Minimum term. Brendan: "we usually do 6 months for both, however where
    # someone has like ZERO visibility sometimes we do 12 because it takes
    # that long to get results." Same trigger as the top geo_pct rung.
    "min_term_months": 6,
    "min_term_months_zero_visibility": 12,
    "zero_visibility_pct_not_ranking": 90,    # >= this % not ranking = "nothing ranks"
    # Legacy MPG card, kept for reference / geo_pricing_mode="card" only.
    "geo_card": {"base": 2950, "intermediate": 4050, "advanced": 5250},
    "geo_card_list": {"base": 2950, "intermediate": 4250, "advanced": 5250},
    "geo_min_term_months": 12,                # legacy card mode only
    "ai_search_uplift_pct": 75,               # legacy flat-pct mode only
    "ecom_anchor_add": 0,                     # RETIRED 2026-07-25 (Brendan): ecommerce carries no anchor add
    "tier_step_flat": 700,                    # hard-cost $ per tier; null -> use step_ratio
    "tier_step_pct_of_base": 0.24,            # step grows past the flat floor on big bases
    "step_ratio": 0.38,                       # fallback: proportional step
    "client_floor": 0,                        # no floor — raised anchors carry pricing
    # Add-on market pricing, per tier. Confirmed against TN Water & Air
    # (2026-03-25): a Knoxville ladder of 2,250 / 2,950 / 3,650 with add-on
    # markets at 950 / 1,250 / 1,750 — 42%, 42%, 48%. The flat 0.42 was right
    # on the first two tiers and 11% light on advanced, because the extra work
    # an advanced campaign does per location scales more than the shared work
    # does. Per-tier ratios reproduce all three exactly.
    # Add-on recommendation thresholds. Both fit on TWO proposals (Skills of
    # Central PA and TN Water & Air) — treat the suggestion as a prompt to
    # think, not a decision, until more actuals confirm them.
    # Markets within this many miles of each other are one market. 25 is a
    # metro radius and separates the two clients we can check — Brent Cogan's
    # towns span 22 miles, TN Water & Air's are 101 and 160 apart — but it is
    # fitted on two proposals, so treat it as a starting point.
    # Straight-line, not drive time: two towns 20 miles apart across a ridge or
    # a state line can still be separate markets.
    "market_radius_miles": 25,
    "addon_free_markets": 3,        # at or below this, always one campaign
    # Need rank data on this share of the ENTERED markets before suggesting.
    # Note the interaction with grid_max_cities: at 5 crossed cities, a client
    # with 8+ markets can never clear 70% and will always be told there isn't
    # enough data. That is the honest answer rather than a bug — the tool
    # genuinely hasn't looked at those markets — but it means wide-footprint
    # clients need Grid max cities raised for one run to decide add-ons, then
    # dropped back for the proposal list.
    "addon_min_measured_share": 0.7,
    "addon_covered_share": 0.6,     # rank in this share of measured markets = one footprint
    # Add-ons are priced off the CORE SEO ladder only — no AI Search component.
    # This is an assumption, not a calibration: TN Water & Air is the only
    # proposal with add-on markets and predates AI Search, while MPG is the
    # only AI Search proposal and has no add-ons. The reasoning is that AI
    # Search work is brand-level — Brendan's GEO tiers are defined by premium
    # content placements, which lift the whole brand rather than a suburb — but
    # it is worth a lot: at Woodstock's 7 add-ons it is ~$5,600/mo on base
    # alone. Confirm before treating it as settled.
    "addon_market_ratio": 0.42,                    # legacy flat value, kept as fallback
    "addon_market_ratio_tiers": {"base": 0.42, "intermediate": 0.42, "advanced": 0.48},
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
    # REVISED 2026-07-28 after live tuning: min services 4 -> 7, max cities
    # 10 -> 5. At the old settings a wide-footprint client hit the service
    # FLOOR — 10 cities forced services down to 4, so a 40-row list showed
    # only four things and read as padding rather than strategy. Trading
    # cities for services keeps the total near target while nearly doubling
    # the variety, and the cities that survive are the highest-demand ones
    # for this client's own service, so the ones dropped cost least.
    "grid_target_keywords": 32,
    "grid_min_services": 7,
    "grid_max_services": 20,
    "grid_max_cities": 5,             # cities crossed against each service
    "grid_state_suffix": "auto",       # auto = suffix only cities that need it
}

def r50(x):
    return int(round(x / 50.0) * 50)

# REQUEST TIMEOUT BUDGET (2026-07-27).
# dfs_post defaulted to a 120s timeout while gunicorn's default worker timeout
# is 30s, so a slow DataForSEO call got the worker killed BEFORE the app's own
# timeout could fire. A killed worker returns no body at all, which the
# frontend can only report as "Server 500 (timeout or non-JSON)" — the app
# never got the chance to say what went wrong. Step 2 made this worse by
# retrying up to three locations in sequence: 3 x 120s against a 30s ceiling.
#
# Two changes: per-call timeouts now fit inside a server window (DFS_TIMEOUT),
# and multi-call stages carry a wall-clock DEADLINE so the chain stops itself
# and returns a readable partial result instead of being killed mid-flight.
#
# IMPORTANT: also raise the server's own timeout, or long calls still die.
# In Render, set the start command to:
#     gunicorn app:app --timeout 120 --workers 1 --threads 4
# Threads, not workers: nearly all of this app's time is spent WAITING on
# DataForSEO and Anthropic, so concurrency should come from threads (one
# process's memory) rather than a second worker process, which doubles memory
# on a 512 MB Starter instance for no gain on I/O-bound work.
# REQUEST_BUDGET_S must stay comfortably BELOW that number.
DFS_TIMEOUT     = int(os.environ.get("DFS_TIMEOUT", "25"))      # per API call
REQUEST_BUDGET_S = int(os.environ.get("REQUEST_BUDGET_S", "90"))  # per route


class BudgetExceeded(Exception):
    """Raised when a multi-call stage runs out of wall clock. Carries a message
    the operator can act on rather than a stack trace."""


def _deadline(budget=None):
    """Start a wall-clock budget for the current request."""
    return _time.time() + float(budget or REQUEST_BUDGET_S)


def _remaining(deadline, minimum=5):
    """Seconds left before the deadline, or None if the budget is spent."""
    left = deadline - _time.time()
    return left if left >= minimum else None


def dfs_post(path, payload, timeout=None, method="POST", retries=1):
    """One DataForSEO call, retried once on a TRANSIENT failure.

    There was no retry at all, so a single read timeout was fatal to whatever
    depended on it. On a Ski Barn quote the volume lookup timed out once and
    the whole volume component of the price silently became $0 (2026-08-04).

    Only network-level failures and 5xx are retried — a 4xx is a real answer
    about the request and repeating it just wastes the budget. Two attempts at
    the 25s default fit inside the 90s per-route budget.
    """
    if timeout is None:
        timeout = DFS_TIMEOUT
    login = os.environ.get("DFS_LOGIN", "")
    pw    = os.environ.get("DFS_PASSWORD", "")
    token = base64.b64encode(f"{login}:{pw}".encode()).decode()
    hdrs = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    last = None
    for attempt in range(int(retries) + 1):
        try:
            if method == "GET":
                resp = requests.get(BASE + path, headers=hdrs, timeout=timeout)
            else:
                resp = requests.post(BASE + path, headers=hdrs,
                                     data=json.dumps(payload), timeout=timeout)
            if resp.status_code >= 500 and attempt < retries:
                last = requests.HTTPError(f"HTTP {resp.status_code}")
                time.sleep(1.0 + attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            if attempt >= retries:
                break
            time.sleep(1.0 + attempt)
    raise last

def recommend_addons(markets, state, rows, top_n=None, site_locations=None,
                     site_pages_found=None, metro_groups=None, city_volumes=None):
    """Suggest how many markets should be priced as separate campaigns.

    The judgement, per the pricing authority: 2-3 related nearby markets run
    under one campaign; many locations become separate campaigns; what tips it
    is how different the markets are, how competitive they are, and the
    client's budget. The last of those the tool cannot see, so this is a
    suggestion with its reasoning attached, never an answer.

    Count alone doesn't separate the two real proposals — Skills of Central PA
    got ONE campaign across 8 Pennsylvania towns while TN Water & Air was
    scoped to Knoxville with 12 markets offered as add-ons. What does separate
    them is whether the client's footprint is ALREADY multi-market:

      Skills ranks 1st/1st/1st/2nd/2nd/3rd across its towns — one domain
      already serves them, so the work is improving a presence that exists.
      TN ranks nowhere outside Knoxville — every other market is greenfield,
      which is a separate build each.

    "How many markets" is the wrong question. "Are we improving one footprint
    or creating eleven" is the right one, and step 3 already answers it.
    """
    mk = [m for m in (markets or []) if m and m.strip()]
    # Collapse cities Google Ads treats as one place. Counting pills instead of
    # markets inflates everything downstream: fourteen metro-Atlanta suburbs
    # are two or three markets, not fourteen, and an add-on count built on
    # fourteen is four times too big.
    # "Thin" = fewer than half the markets return any volume at all. Below
    # that, grouping has nothing to work with and the count is guesswork.
    _cv = city_volumes or {}
    thin_volume = bool(_cv) and sum(1 for v in _cv.values() if v) < max(2, len(_cv) / 2)
    collapsed = 0
    for g in (metro_groups or []):
        members = [m for m in mk if m in g]
        collapsed += max(0, len(members) - 1)
    n = len(mk) - collapsed
    out_pills = len(mk)
    out = {"markets": n, "pills": out_pills, "collapsed": collapsed,
           "markets_absent": [],
           "metro_groups": [g for g in (metro_groups or []) if len(g) > 1],
           "suggested": 0, "basis": "", "covered": 0,
           "measured": 0, "unmeasured": 0, "states": 0, "confident": False,
           "site_locations": 0}
    if n <= 1:
        # A single market is a CONFIDENT zero, not an absence of information.
        # Leaving confident False made the panel say "not enough data to
        # suggest" and — worse — meant the stepper was never clamped, so a
        # field left at 5 from an earlier run kept charging for five add-on
        # markets that the tool had just determined don't exist (2026-08-03).
        out["basis"] = "single market — nothing to add on."
        out["confident"] = True
        return out

    # Only count states we actually KNOW — a market tagged "City, ST". Inferring
    # them from a name-collision table and then telling the operator the client
    # "spans 2 states" is a confident claim built on a guess.
    states = {(parse_market(m, "")[1] or "").lower() for m in mk if "," in m}
    states.discard("")
    out["states"] = len(states)

    if n <= int(CFG.get("addon_free_markets", 3)):
        out["basis"] = f"{n} markets — three or fewer run as one campaign."
        out["confident"] = True
        return out


    # ABSTAIN when the markets carry almost no search volume. Grouping infers
    # market identity from demand patterns, and a town with no demand has no
    # pattern — three separate attempts at this (geo-modified probe, resolved
    # location name, per-city volume) all failed on Brent Cogan's seven Blair
    # County towns for the same underlying reason: the data does not contain
    # the answer (2026-08-03). Counting them as seven separate markets is a
    # confident wrong answer worth $6,000/mo, which is worse than no answer.
    if thin_volume:
        out["basis"] = (f"{n} markets entered, but they carry almost no search "
                        f"volume individually — there is no demand pattern to tell "
                        f"whether they are one market or several. Decide by hand: "
                        f"towns within a short drive of each other are normally one "
                        f"campaign.")
        return out


    # PRESENCE PER MARKET, not a count of locations. Counting gets both known
    # outcomes backwards: Skills of Central PA has ~8 facilities and got ONE
    # campaign, TN Water & Air has one Knoxville location and was offered 11
    # add-ons. Physical location count is nearly anti-correlated with add-on
    # count, because the question isn't "how many places do they have" — it's
    # "which of the markets we're targeting do they already operate in".
    #
    #   Skills targets 8 markets and has a presence in all 8  -> improving
    #     coverage that exists -> one campaign.
    #   TN targets 12 and has a presence in 1                 -> entering 11
    #     new markets -> a campaign each.
    #
    # A location page or a Google Business Profile answers that per market,
    # and so does a top-100 ranking. All three are the same question asked
    # different ways, which is why they agree where we can check them.
    locs = [str(l).lower() for l in (site_locations or []) if l]
    out["site_locations"] = len(locs)
    # "No location pages" and "we couldn't read the site" look identical from
    # an empty list, and they mean opposite things: the first is evidence, the
    # second is a gap. Woodstock's site refused a TLS handshake, so its crawl
    # returned nothing and the strongest signal was silently absent rather
    # than negative.
    out["site_read"] = (None if site_pages_found is None
                        else bool(site_pages_found))
    if locs:
        with_page = [m for m in mk
                     if any(l in (parse_market(m, state)[0] or m).lower()
                            or (parse_market(m, state)[0] or m).lower() in l
                            for l in locs)]
        # Presence has to be counted in MARKETS too. Counting cities against a
        # collapsed market total gave "present in 5 of 2 markets", and the
        # missing-market arithmetic went negative.
        def _key(m):
            g = next((tuple(sorted(x.lower() for x in grp))
                      for grp in (metro_groups or []) if m in grp), None)
            return g or m.lower()
        present_keys = {_key(m) for m in with_page}
        out["markets_with_location_page"] = len(present_keys)
        # Name the gaps. A count tells the operator a decision was made; the
        # list tells them WHICH markets it rests on, which is the part they can
        # actually check against what they know about the client. When cities
        # have been collapsed into metros, report one name per metro so the
        # list matches the market count rather than the pill count.
        absent, seen_grp = [], set()
        for m in mk:
            if m in with_page:
                continue
            grp = next((tuple(g) for g in (metro_groups or []) if m in g), None)
            if grp:
                if grp in seen_grp or any(x in with_page for x in grp):
                    continue
                seen_grp.add(grp)
                absent.append(f"{m} +{len(grp)-1}" if len(grp) > 1 else m)
            else:
                absent.append(m)
        out["markets_absent"] = absent
        if present_keys:
            missing = n - len(present_keys)
            if missing <= 0:
                out["suggested"] = 0
                out["basis"] = (f"The client has a presence in all {n} markets — one "
                                f"footprint to improve, not {n} to build.")
            elif len(present_keys) >= max(2, int(n * 0.7)):
                out["suggested"] = 0
                out["basis"] = (f"The client has a presence in {len(present_keys)} of "
                                f"{n} markets — operating in most, so one footprint "
                                f"rather than {n} builds.")
            else:
                out["suggested"] = missing
                out["basis"] = (f"The client has a presence in {len(present_keys)} of "
                                f"{n} markets. They aren't in the other {missing} yet, "
                                f"so each of those is a campaign from scratch.")
            out["confident"] = True
            return out

    # Which markets does the client already rank in? A keyword carries its city,
    # so match each market against the terms that mention it.
    top = int(top_n or CFG.get("zero_ranking_top_n", 100))
    covered, measured = set(), set()
    for r in (rows or []):
        kw = (r.get("kw") or "").lower()
        pos = r.get("pos")
        for m in mk:
            city = (parse_market(m, state)[0] or m).strip().lower()
            if city and city in kw:
                measured.add(m)
                if isinstance(pos, (int, float)) and pos <= top:
                    covered.add(m)
    out["covered"], out["measured"] = len(covered), len(measured)

    out["unmeasured"] = n - len(measured)
    if len(measured) < 2:
        out["basis"] = (f"Rankings measured in only {len(measured)} markets — run "
                        f"step 3 first.")
        return out

    # Coverage has to be read against the markets ENTERED, not the ones that
    # happened to be measured. The grid crosses only the top few cities by
    # demand, so a client can show "5 of 5 measured" while nine markets were
    # never looked at — and those nine are precisely the ones most likely to be
    # greenfield, because they were the LOWEST-demand markets. Concluding "one
    # footprint" from the best five is the tool marking its own homework.
    meas_share = len(measured) / n
    if meas_share < float(CFG.get("addon_min_measured_share", 0.7)):
        out["basis"] = (f"Only {len(measured)} of {n} markets have rank data, and "
                        f"the unmeasured ones are the lowest-demand — the ones "
                        f"the client is least likely to already be in. Raise the Grid max "
                        f"cities cap \u2014 it limits markets of any kind, counties "
                        f"included \u2014 and re-run step 3.")
        return out

    share = len(covered) / len(measured)
    if share >= float(CFG.get("addon_covered_share", 0.6)):
        out["suggested"] = 0
        out["basis"] = (f"Already ranking in {len(covered)} of {len(measured)} "
                        f"markets — one footprint to improve, not {n} to build.")
        out["confident"] = True
    else:
        out["suggested"] = max(0, n - 1)
        out["basis"] = (f"Ranking in only {len(covered)} of {len(measured)} markets, "
                        f"so the rest are a campaign from scratch each.")
        out["confident"] = True
    if len(states) > 1:
        out["suggested"] = max(out["suggested"], n - 1)
        out["basis"] += f" They span {len(states)} states — separate territories."
    return out


def primary_first(markets, primary):
    """Put the highest-demand market at the front of the list.

    Bid and rank lookups localise to markets[0], which was whatever the partner
    typed first — usually alphabetical, so Acworth (210/mo) anchored a quote
    whose real market was Marietta (880/mo). Step 1 already ranks the markets
    by actual demand for the client's service; steps 2 and 3 should use that
    answer rather than input order. Two signals that drive price — the CPC
    adder and the zero-ranking uplift — were both being measured in the wrong
    town.
    """
    mk = [m for m in (markets or []) if m and m.strip()]
    p = (primary or "").strip()
    if not p:
        return mk
    rest = [m for m in mk if m.strip().lower() != p.lower()]
    return [p] + rest


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
        # An EXPLICIT fallback state beats the metro map. The map is a guess
        # from the city name alone, and city names collide: "Cleveland" maps to
        # Ohio, so a Tennessee client with a Cleveland TN branch had its state
        # silently rewritten (2026-07-28). Someone who selected a fallback
        # state has told us where this client operates; a lookup table has not.
        ds = (default_state or "").strip()
        st = ds or st
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

def get_client_site(url, timeout=10, headers=None, allow_redirects=True):
    """GET a CLIENT'S OWN marketing site, tolerating a broken TLS chain.

    Plenty of small-business sites serve a valid leaf certificate but omit the
    intermediate, so the chain can't be built. Browsers paper over it — they
    cache intermediates and follow the AIA pointer — and requests does not, so
    the site menu and description auto-fill just fail with a wall of SSL text
    (Woodstock Furniture, 2026-07-27).

    Verification is attempted first and only relaxed on a certificate error,
    for the client's own public pages. That content is read-only, used to
    suggest keywords a human then reviews, and never a credential path. This
    helper is deliberately NOT used for DataForSEO or Anthropic — those carry
    API keys and must always verify.

    Returns (response, insecure_flag). Raises the original error if the retry
    also fails.
    """
    kw = {"timeout": timeout, "headers": headers or {},
          "allow_redirects": allow_redirects}
    try:
        return requests.get(url, **kw), False
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        return requests.get(url, verify=False, **kw), True


# A page under one of these paths is a LOCATION page — the thing the industry
# actually counts. Every multi-location pricing model turns on "each location
# needs its own profile, reviews, local content and ideally its own location
# page", and Brendan scoped Skills of Central PA with exactly this test:
# "This campaign would cover all locations mentioned on the website."
_LOCATION_PATH = re.compile(
    r"/(?:our[-_])?(?:locations?|stores?|offices?|branch(?:es)?|showrooms?|"
    r"clinics?|dealers?|service[-_]areas?|areas?[-_]we[-_]serve)(?:/|$)", re.I)
# The index page itself isn't a location — "/locations/" lists them, and
# "/locations/marietta/" is one.
_LOCATION_INDEX = re.compile(
    r"/(?:our[-_])?(?:locations?|stores?|offices?|branch(?:es)?|showrooms?|"
    r"clinics?|dealers?|service[-_]areas?|areas?[-_]we[-_]serve)/?$", re.I)


def google_business_cities(brand, domain):
    """Cities where the client has a Google Business listing.

    The rep tab already pulls these — one Business Listings search, about two
    cents, returning every listing at once regardless of how many markets are
    involved. The SEO tab was ignoring it and inferring presence from location
    pages instead, which fails for anyone using a store-locator widget: it read
    Woodstock Furniture as having zero locations while the rep tab found six
    (2026-07-28).

    A Google Business Profile IS the local presence an SEO campaign optimises,
    so it answers "does the client operate in this market" more directly than
    anything else available. Non-fatal — a failure just leaves the other
    signals to decide.
    """
    try:
        import rep_scan
        res = rep_scan.scan_locations(brand, domain=domain) or {}
    except Exception:
        app.logger.exception("google_business_cities failed")
        return [], None
    cities, seen = [], set()
    for loc in (res.get("locations") or []):
        addr = (loc.get("address") or "")
        # "1234 Main St, Marietta, GA 30060" -> the part before the state
        parts = [p.strip() for p in addr.split(",") if p.strip()]
        city = parts[-2] if len(parts) >= 2 else ""
        city = re.sub(r"\s+\d{5}(-\d{4})?$", "", city).strip()
        if city and city.lower() not in seen:
            seen.add(city.lower())
            cities.append(city)
    return cities, len(res.get("locations") or [])


# Headings that introduce a client's own list of markets.
_SERVICE_AREA_HEADING = re.compile(
    r"(?:where\s+we\s+(?:serve|work)|service\s+areas?|areas?\s+we\s+serve|"
    r"proudly\s+serve|communities\s+we\s+serve|our\s+locations|"
    r"cities\s+we\s+serve)", re.I)

# Words that show up in these lists but aren't markets.
_NOT_A_MARKET = re.compile(
    r"^(?:and\s+)?(?:surrounding|nearby|other|all|more)\b|"
    r"\b(?:areas?|communities|region|counties|county|and\s+beyond)$", re.I)

# Calls to action and nav labels sit immediately after these lists and are
# capitalised exactly like place names, so shape alone can't tell them apart —
# "Book Now" survived every structural test (2026-07-28).
_CTA_WORDS = re.compile(
    r"\b(?:book|call|contact|get|start|started|learn|read|more|free|quote|"
    r"schedule|request|now|today|us|home|about|services?|products?|offers?|"
    r"menu|search|login|sign|apply|shop|buy|order|view|see|click|here|next|"
    r"back|close|submit|send|email|phone|hours|reviews?|blog|news|faq|careers?|"
    r"privacy|terms|sitemap|contact)\b", re.I)


def service_areas_from_html(html):
    """Pull the market list off a client's 'Where We Serve' page.

    TN Water & Air names eighteen service areas on one page under "We proudly
    serve the following areas". Its proposal then prices twelve distinct
    markets — the same list with the metro clusters collapsed. That list is
    the source SSG actually scoped from, and we were reading neither it nor
    anything close: the URL matcher sees no /locations/ paths because the
    areas are body text, and the Google Business pull returns three, because
    three offices serve twelve markets (2026-07-28).

    So read the page. Anchor on a heading, take the short text items that
    follow, and stop at the first stretch of prose — the lists are always
    short link or list-item labels, never sentences.
    """
    if not html:
        return []
    m = _SERVICE_AREA_HEADING.search(html)
    if not m:
        return []
    window = html[m.end():m.end() + 12000]
    items = re.findall(r">([^<>{}]{2,40})<", window)
    out, seen = [], set()
    for raw in items:
        t = re.sub(r"\s+", " ", raw).strip(" \u00b7|,-–—\t")
        if not t or len(t) < 3 or len(t.split()) > 4:
            continue
        if not re.match(r"^[A-Z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+)*$", t):
            continue          # markets are capitalised; nav junk usually isn't
        if _NOT_A_MARKET.search(t) or _CTA_WORDS.search(t):
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= 40:
            break
    return out


def fetch_service_areas(domain):
    """Find and read the client's service-area page. Non-fatal."""
    if not domain:
        return []
    base = domain if domain.startswith("http") else f"https://{domain}"
    base = base.rstrip("/")
    paths = ["/service-areas", "/service-area", "/areas-we-serve", "/where-we-serve",
             "/where-we-work", "/locations", "/service-areas/", ""]
    for p in paths:
        try:
            r, _ = get_client_site(base + p, timeout=8,
                                   headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200 or "<" not in (r.text or ""):
                continue
            found = service_areas_from_html(r.text[:400_000])
            if len(found) >= 3:
                return found
        except Exception:
            continue
    return []


def location_pages_from_urls(urls):
    """Location page slugs found in a set of site URLs, de-duplicated."""
    out, seen = [], set()
    for u in urls or []:
        u = str(u or "")
        # Sitemap files are now collected alongside page URLs (they identify a
        # storefront by name), and "/locations/sitemap.xml" would otherwise be
        # read as a location called "sitemap.xml".
        if u.split("?")[0].lower().endswith(".xml"):
            continue
        if not _LOCATION_PATH.search(u) or _LOCATION_INDEX.search(u):
            continue
        slug = [p for p in u.split("?")[0].rstrip("/").split("/") if p]
        name = (slug[-1] if slug else "").replace("-", " ").replace("_", " ").strip()
        if name and name.lower() not in seen and len(name) < 40:
            seen.add(name.lower())
            out.append(name)
    return out


def fetch_site_pages(domain, limit=30, collect_urls=None):
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
                r, _insecure = get_client_site(url, timeout=timeout, headers=hdrs)
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
            index_locs = []
            if locs and all(l.lower().endswith(".xml") for l in locs[:3]):
                # sitemap INDEX — service pages live in "page" sitemaps, so read
                # those first; blog-post sitemaps are last resort
                kids = sorted(locs, key=lambda l: (("page" not in l.lower()),
                                                   ("post" in l.lower())))
                # Keep the index's OWN entries. They are thrown away below when
                # the children are read, and their NAMES are evidence in their
                # own right — "sitemap_products_1.xml" identifies a storefront
                # without costing a fetch. That mattered for Grav: this sort
                # deliberately reads the pages sitemap first, and the 8s budget
                # then ran out before the products sitemap, so every product URL
                # was missed and the store went undetected (2026-08-04).
                index_locs = list(locs)
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
            if isinstance(collect_urls, list):
                collect_urls.extend(locs)
                collect_urls.extend(index_locs)   # names are evidence; see above
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
                u = it.get("url") or ""
                # This fallback never fed collect_urls, so on any site without a
                # readable sitemap the caller got page topics but ZERO urls —
                # silently disabling both storefront and location-page detection.
                if u and isinstance(collect_urls, list):
                    collect_urls.append(u)
                t = slug_to_topic(u)
                if t and t.lower() not in seen:
                    seen.add(t.lower()); pages.append(t)
        return pages[:limit]
    except Exception:
        return pages[:limit]


def _bare_city(m, state=""):
    """The city name alone — the form every per-city lookup uses."""
    try:
        return (parse_market(m, state)[0] or m).strip().lower()
    except Exception:
        return (m or "").strip().lower()


def fetch_local_volume(terms, markets, state, national=False):
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
    if national:
        # Product brands / national scope: the client's cities still build the
        # GRID (the proposal table stays per-city), but pricing demand is the
        # national figure. A geo-qualified pull structurally undercounts a DTC
        # brand — nobody searches "collagen gummies fairfax va".
        cities = [""]
    if not cities:
        cities = [""]                      # nationwide / no city: single lookup
    cities = cities[:CFG.get("grid_max_cities", 10)]
    kws = [t.lower() for t in terms]

    def one(city):
        # loc_string parses "City, ST" itself; each city localizes to its own state
        loc = loc_string([city], state) if city else loc_string([], state)
        def call(location):
            payload = [{"keywords": dfs_kw_list(kws), "location_name": location,
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
    city_locs = {}
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
        # DataForSEO tells us which location it ACTUALLY used for each city —
        # that is exact market identity, not an inference. Two cities resolving
        # to the same effective location are the same market, which is the
        # question the add-on count turns on. Inferring it from volume vectors
        # instead only worked where the geo-modified probe had volume, so it
        # failed silently in exactly the small rural markets where collapsing
        # matters most (2026-08-03).
        city_locs[city] = used_loc
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
                # Key on the BARE city, which is how every consumer reads it.
                # Writing "altoona, pa" while the grid rows and the metro
                # grouping both look up "altoona" meant every per-city lookup
                # missed, rows silently fell back to the summed service total —
                # printing the same number for every city — and the grouping
                # had nothing to compare (2026-08-03).
                per_city[(_bare_city(city, state), k)] = v
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
    # Hand the resolved locations back so the caller can collapse cities that
    # Google treats as one market. Stashed on the dict rather than widening the
    # signature, since three call sites unpack this tuple.
    per_city["__city_locs__"] = city_locs
    return totals, per_city, ("; ".join(notes) or None)


def _labs_loc_field(markets, state, national=False):
    """location field for a LABS payload. Always country-level US (2840).

    Two rounds of trying to target Labs at the client's actual market both
    failed against the API (2026-08-04): location_name is rejected outright
    ("40501 Invalid Field: 'location_name'"), and a Google Ads city code is
    rejected too ("Invalid Field: 'location_code'") because Labs keys off its
    own, much smaller location set — Google Ads criteria IDs for suburbs are
    not in it.

    Country level is also the CORRECT granularity here, which is why the
    keyword-difficulty call has always hardcoded 2840 with the note that
    difficulty "is a national-level organic metric". Labs CPC is modelled the
    same way. Nothing is lost: per-market volume comes from fetch_local_volume,
    which calls a Google Ads endpoint that does accept a location_name.

    Returns (payload_fragment, label) — the label is what the UI reports.
    """
    return {"location_code": 2840}, "United States"


def fetch_exact_volume(keywords, markets, state, national=False):
    """Exact-match search volume. The Google Ads keywords_for_keywords endpoint
    we use to GENERATE terms returns GROUPED (broad) volumes that merge similar
    terms — which is why the numbers looked inflated/off. For the FINAL list we
    re-pull volume from the Labs keyword database, which returns per-term exact
    volume. Returns {keyword_lower: volume}. Non-fatal: {} on any failure."""
    if not keywords:
        return {}
    out = {}
    # The comment here used to say "use the city if known, else US" while the
    # code hardcoded 2840 (US) unconditionally, so EVERY client's exact volume
    # was pulled nationally — overstating demand, and therefore price, on every
    # local quote (2026-08-04). Labs takes a numeric location_code ONLY — the
    # first cut of this sent location_name and every local lookup came back
    # "40501 Invalid Field", which this function swallows into {} and prices as
    # zero volume. Resolve to a code instead.
    loc_field, _loc_used = _labs_loc_field(markets, state, national)
    try:
        # batch up to 1000 per call
        for i in range(0, len(keywords), 1000):
            chunk = keywords[i:i+1000]
            payload = [{"keywords": [k.lower() for k in chunk],
                        **loc_field, "language_code": "en"}]
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

# Words that carry no identifying weight, so they never need grounding.
# Words that carry no evidence about WHOSE service a term is. "can" and "get"
# were missing, so a pinned question was reported as blocked because the client
# "never uses the word can" — technically true, entirely beside the point
# (2026-08-04).
_GROUNDING_STOP = set("""a an and or the of for in on to with your our best top near me
services service company companies agency agencies firm firms group inc llc co
local affordable cheap professional expert experts quality quote quotes free
how what why when where which who whose can could should would will does did
is are was were do has have had am get gets getting rid without into from
about after before during over under you your they them their there here
that this these those not new more most less much many any all out off per
""".split())

# Questions, as opposed to services. The service-list prompt has always said
# "never a question", but pinning skips the model entirely and reads straight
# from the volume-ranked candidate pool, where questions are plentiful and
# frequently outrank every real service in the set.
# Interrogatives are conclusive wherever they lead a phrase.
_QUESTION_LEAD = re.compile(r"^(?:how|what|why|when|where|which|who|whose)\b", re.I)
# Auxiliaries are NOT. "can am repair" is a Can-Am dealer, "am radio antenna" is
# a product, "will call service" is a fulfilment term — all led by an auxiliary,
# none of them questions. Real questions built on an auxiliary run longer ("does
# insurance cover chiropractic care"), so require length before treating one as
# a question. A false positive here silently deletes a real service, which is
# worse than a question slipping through to the grounding filter.
_AUX_LEAD = re.compile(r"^(?:is|are|was|were|do|does|did|can|could|should|"
                       r"would|will|has|have|had|am)\b", re.I)
_AUX_MIN_WORDS = 4


def is_question_kw(text):
    """Is this a question phrase rather than a service a client could sell?"""
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t or "how to" in t:
        return True
    if _QUESTION_LEAD.search(t):
        return True
    return bool(_AUX_LEAD.search(t)) and len(t.split()) >= _AUX_MIN_WORDS


def drop_ungrounded_services(services, seeds, business_desc, site_pages, brand, domain):
    """Drop model-invented services containing a word the client never used.

    Three rounds of prompt wording failed to stop competitor names getting in:
    Keller Builds still came back with "turner construction company" and "clark
    construction company" — the two largest national contractors — because the
    keyword-idea pool is ranked by national volume and they sit at the top of
    it looking exactly like services (2026-07-27).

    Detecting "is this a competitor" in the abstract is hard. Detecting "did
    the client ever say this word" is easy and gets the same answer: Keller's
    seeds, description and site say commercial, industrial, agricultural,
    warehouse — they never say Turner. A service has to be GROUNDED in the
    client's own vocabulary. Seeds are exempt — they are the client's words by
    definition.

    Pins are NOT exempt (2026-08-04). They used to be, on the reasoning that a
    pin is backed by real search volume. Volume proves a term is SEARCHED, not
    that it is the client's: Grav, a smoke shop, had "glass water pitcher",
    "glass chess set" and "glass water carafe" pinned — kitchenware and board
    games that match on the word "glass" and sit high in the keyword pool. They
    then bypassed this filter, which would have caught all three, because
    pitcher/chess/carafe appear nowhere in the client's vocabulary.

    Returns (services, dropped, blocked_pins). `dropped` is the model's own
    picks that failed; `blocked_pins` is reported separately because a pin is
    forced in for PRICE STABILITY, so the operator needs to see when one was
    refused rather than have it vanish.
    """
    corpus = " ".join([
        " ".join(seeds or []), business_desc or "",
        " ".join(site_pages or []), brand or "", (domain or "").replace(".", " "),
    ]).lower()
    # Matching is singular/plural-insensitive. Site navigation is written in
    # the plural ("Bongs For Sale", "Bubblers", "Nectar Collectors") while a
    # service is written in the singular ("glass bong"), so exact word matching
    # called the client's own catalogue foreign and removed real services as
    # unrecognised (Grav, 2026-08-04). Fold both sides to a bare stem instead.
    def _stem(w):
        w = w.strip("-/")
        if len(w) > 3 and w.endswith("es") and w[-3] in "sxzh":
            return w[:-2]
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w

    known = set()
    for w in corpus.replace(",", " ").split():
        known.add(w.strip("-/"))
        known.add(_stem(w))

    def _alien(svc):
        return [w for w in (svc.get("service") or "").lower().split()
                if w not in _GROUNDING_STOP and len(w) > 2
                and w not in known and _stem(w) not in known]

    out, dropped, blocked_pins = [], [], []
    for svc in services or []:
        if svc.get("from_seed"):
            out.append(svc)
            continue
        alien = _alien(svc)
        if alien and svc.get("pinned"):
            # Always enforced, and deliberately NOT counted toward the
            # stand-down ratio below. That valve asks "is the corpus too thin
            # to judge the MODEL fairly"; pins are a handful of terms whose
            # only job is to hold the price steady, and a junk pin corrupts
            # pricing directly. Refuse it and say so.
            blocked_pins.append((svc.get("service"), alien[0]))
            continue
        if alien:
            dropped.append((svc.get("service"), alien[0]))
            continue
        out.append(svc)
    # Stand down when the corpus is too thin to be a fair test — but measure
    # that against the WHOLE list, not just the model's share of it. Keller
    # contributed only 3 non-seed services and 2 were competitors: a correct
    # 2-of-3 read as a 67% drop and tripped the valve, so Turner and Clark
    # survived (2026-07-27). Against the full list those 2 are 29% — plainly
    # a targeted removal — while MPG's 8 wipe out 73% of its list, which is
    # the runaway this valve exists to catch.
    # Pins sit outside this measurement on both sides of the fraction — they
    # are enforced unconditionally above, so counting them would let three bad
    # pins trip the valve and hand the model's competitors back too.
    unpinned = [s for s in (services or []) if not s.get("pinned")]
    total = len(unpinned)
    max_ratio = float(CFG.get("grounding_max_drop_ratio", 0.5) or 0.5)
    if total and len(dropped) / total > max_ratio:
        # Stood down for the model's picks only. Blocked pins stay blocked.
        blocked_l = {(b[0] or "").lower() for b in blocked_pins}
        return ([s for s in (services or [])
                 if (s.get("service") or "").lower() not in blocked_l],
                None, blocked_pins)          # None = filter stood down
    return out, dropped, blocked_pins


def enforce_seed_services(services, seeds, max_services, markets, state, phrase_geos=None):
    """Make the partner's own seed terms the backbone of the service list.

    The prompt asks for this and the model does not reliably comply: a
    Northern Virginia insurance agency supplied eight clean seeds (auto, home,
    renters, landlord, homeowners...) and got back "state farm homeowners
    insurance quote" — a competitor — while its own seeds went unused
    (Rockingham, 2026-07-27). No wording fixes this dependably, because the
    keyword-idea pool is ranked by national volume and the largest competitor
    in any trade sits at the top of it looking like a service.

    So the seeds are enforced here. Someone who knows the account typed them;
    they outrank anything the model invents. Model-chosen services only fill
    the slots the seeds don't. Returns (services, used_seed_count).
    """
    clean = []
    seen = set()
    for sd in seeds or []:
        name = clean_kw(strip_proximity(
            _strip_markets((sd or "").lower(),
                           list(markets or []) + list(phrase_geos or []),
                           state))).strip()
        if name and name not in seen and len(name.split()) <= 6:
            seen.add(name)
            clean.append(name)
    if not clean:
        return list(services or []), 0

    # Seeds FIRST, then model picks fill what's left. The earlier version
    # appended seeds to the model's list and displaced from the tail, which
    # left the model's competitor pick in place whenever the seeds ran out —
    # exactly the case this exists to prevent. Building seeds-first makes the
    # partner's list the default and the model's contribution the remainder.
    def norm(t):
        return " ".join((t or "").lower().split())

    tiers = ["ultra", "ultra", "competitive", "competitive", "competitive",
             "long_tail", "long_tail"]
    out, taken = [], set()
    for i, term in enumerate(clean[:max_services]):
        if norm(term) in taken:
            continue
        taken.add(norm(term))
        out.append({"service": term, "tier": tiers[min(i, len(tiers) - 1)],
                    "from_seed": True})
    used = len(out)
    # Model-chosen services fill any remaining slots, in the order it ranked
    # them. Exact duplicates only — "auto insurance" and "bundle home and auto
    # insurance" are different services and both belong.
    for svc in services or []:
        if len(out) >= max_services:
            break
        n = norm(svc.get("service"))
        if not n or n in taken:
            continue
        taken.add(n)
        out.append(dict(svc))
    return out[:max_services], used


def rebalance_tiers(services):
    """Guarantee all three tiers are represented.

    Anything that removes a service — the out-of-area filter, seed
    enforcement, pinning — can empty a tier, and the proposal renders three
    columns. An empty one reads as an incomplete strategy rather than a
    deliberate choice. Move from the most-crowded tier into the empty one,
    preferring the longest phrase for long_tail and the shortest for ultra,
    which is how the tiers actually differ.
    """
    order = ["ultra", "competitive", "long_tail"]
    out = [dict(x) for x in (services or [])]
    if len(out) < 3:
        return out                     # too few to fill three tiers honestly
    for _ in range(len(order)):
        counts = {t: [x for x in out if x.get("tier") == t] for t in order}
        empty = [t for t in order if not counts[t]]
        if not empty:
            break
        need = empty[0]
        donor = max(order, key=lambda t: len(counts[t]))
        if len(counts[donor]) < 2:
            break
        pool = counts[donor]
        pick = (max(pool, key=lambda x: len(x["service"].split())) if need == "long_tail"
                else min(pool, key=lambda x: len(x["service"].split())))
        for x in out:
            if x is pick:
                x["tier"] = need
                break
    return out


def drop_foreign_geo_services(services, markets, state):
    """Remove services naming a US state the client doesn't operate in.

    The keyword-idea pool is ranked by national volume, so it fills with terms
    anchored to whichever state searches most — a Northern Virginia insurer
    came back with "state of california fire insurance" as a service
    (Rockingham, 2026-07-27). No prompt wording reliably suppresses this,
    because the term reads as a plausible insurance product; it is only wrong
    once you know where the client sells. That is a fact the code has and the
    model has to be told, so enforce it here rather than asking.

    The client's own state and any state named in their markets are kept, so
    "virginia farm insurance" survives for a Virginia client.
    """
    # If we cannot establish the client's own state, we cannot judge which
    # states are foreign — and dropping on a guess would delete a legitimate
    # home-state service ("virginia farm insurance" for a Virginia client whose
    # market pills are bare city names). Say nothing rather than guess wrong.
    known_state = bool((state or "").strip()) or any(
        p in STATE_ABBREV or p in set(STATE_ABBREV.values())
        for m in (markets or [])
        for p in (m or "").lower().replace(",", " ").split())
    if not known_state:
        return list(services or []), None      # None = filter could not run

    ours = set()
    for m in list(markets or []) + [state or ""]:
        t = (m or "").strip().lower()
        if not t:
            continue
        for part in t.replace(",", " ").split():
            if part in STATE_ABBREV:
                ours.add(part)
                ours.add(STATE_ABBREV[part])
            elif part in set(STATE_ABBREV.values()):
                ours.add(part)
                for full, ab in STATE_ABBREV.items():
                    if ab == part:
                        ours.add(full)
    out, dropped = [], []
    for svc in services or []:
        name = (svc.get("service") or "").lower()
        toks = set(name.replace(",", " ").split())
        foreign = [st for st in STATE_ABBREV
                   if st not in ours and (f" {st} " in f" {name} ")]
        # Two-word state names ("new york", "north carolina") need a substring
        # test; single-word ones are covered by the token check above.
        if not foreign:
            foreign = [st for st in STATE_ABBREV
                       if " " in st and st not in ours and st in name]
        if foreign:
            dropped.append((svc.get("service"), foreign[0]))
            continue
        out.append(svc)
    return out, dropped


# Proximity phrases. Google reads these against the SEARCHER's location, so
# they are a substitute for a place name, not a companion to one.
_PROXIMITY_RE = re.compile(
    r"\b(near me|nearby|near by|close to me|around me|in my area|"
    r"near my location|closest|near you)\b")


def strip_proximity(text):
    """Remove 'near me'-style phrases from a SERVICE name.

    The grid appends a city to every service, so a service carrying "near me"
    becomes "mattress store near me acworth ga" (Woodstock Furniture,
    2026-07-27). Nobody types that: "near me" IS the location, so pairing it
    with an explicit city is a contradiction. Those terms report almost no
    volume, and they go into a proposal as keywords the client is quoted to
    rank for. Bare "near me" terms are legitimate — the grid just isn't where
    they belong, because the grid's whole job is to add the place.
    """
    return re.sub(r"\s+", " ", _PROXIMITY_RE.sub(" ", (text or "").lower())).strip()


def scrub_services(services, markets, state, phrase_geos=None):
    """Strip any market/state text out of the SERVICE names and de-duplicate.

    A service is meant to be a bare offering ("business tech") that the grid
    crosses with cities. When one arrives already carrying a geo — the model
    echoes a candidate back verbatim, or a pinned candidate keeps a market the
    strip list didn't cover — the grid appends a SECOND city on top, producing
    "business tech cherry hill south jersey" (Waytek, 2026-07-27). It also
    burns a slot on a near-duplicate of a service already in the list, which
    on a 6-service grid is a sixth of the proposal.

    Scrubbing here means the grid only ever sees bare services, so the
    crossing is the only thing that adds geography.
    """
    strip_list = list(markets or []) + [g for g in (phrase_geos or []) if g]
    out, seen = [], set()
    for svc in services or []:
        name = clean_kw(strip_proximity(
            _strip_markets((svc.get("service") or "").lower(),
                           strip_list, state))).strip()
        if not name or name in seen:
            continue                      # empty after scrubbing, or a duplicate
        seen.add(name)
        out.append({**svc, "service": name})
    return out


def pin_head_services(services, cands, markets, state, brand, max_services):
    """Force the highest-volume candidate terms into the service list.

    `services` is the model's pick; `cands` are the keyword rows the search API
    returned, each with a real volume. Any top-volume term the model dropped is
    inserted, displacing the lowest-priority model picks so the list length is
    unchanged. Returns (services, pinned_terms).

    Matching is containment-based in both directions so we don't double up:
    if the model already chose "energy gummies", the candidate "energy gummies"
    (or "best energy gummies") is considered covered by it.
    """
    n_pin = int(CFG.get("pin_head_terms", 0) or 0)
    if n_pin <= 0 or not cands:
        return services, []
    min_vol = int(CFG.get("pin_min_volume", 0) or 0)
    b = (brand or "").strip().lower()

    # Bare, brand-free candidate terms ranked by real search volume.
    ranked, seen = [], set()
    for c in sorted(cands, key=lambda r: (-(r.get("volume") or 0),
                                          str(r.get("keyword") or ""))):
        if (c.get("volume") or 0) < min_vol:
            break
        term = clean_kw(strip_proximity(
            _strip_markets((c.get("keyword") or "").lower(), markets, state))).strip()
        if not term or (b and b in term) or term in seen:
            continue
        # A question is never a service, so it should never be pinned. Skipping
        # it HERE rather than letting the grounding filter catch it downstream
        # means the slot goes to the next real head term instead of being spent
        # and then discarded — and the operator stops being told that "how to
        # get rid of a headache" was blocked over the word "get" (2026-08-04).
        if is_question_kw(term):
            continue
        seen.add(term)
        ranked.append((term, c.get("volume") or 0))
        if len(ranked) >= n_pin:
            break
    if not ranked:
        return services, []

    have = [(x.get("service") or "").lower() for x in services]
    def covered(term):
        return any(term == h or term in h or h in term for h in have if h)

    missing = [(t, v) for t, v in ranked if not covered(t)]
    if not missing:
        return services, []

    keep_l = {t for t, _ in ranked}
    out = list(services)

    def _drop_one():
        """Free a slot WITHOUT emptying a tier.

        Displacing from the tail looked reasonable — the model returns its
        strongest picks first — but the model also orders long_tail last, so
        on a short list (6 services for a 6-city client) the pins ate every
        long-tail service and the proposal came back with an empty Long Tail
        column (Waytek, 2026-07-27). Take from the tier that can best afford
        it instead: the most-represented one, from its own tail.
        """
        counts = {}
        for x in out:
            if (x.get("service") or "").lower() not in keep_l:
                counts[x.get("tier")] = counts.get(x.get("tier"), 0) + 1
        # Only tiers that would still have a member afterwards are eligible.
        eligible = {t: n for t, n in counts.items() if n > 1}
        pool = eligible or counts
        if not pool:
            return False
        victim_tier = max(pool.items(), key=lambda kv: kv[1])[0]
        for i in range(len(out) - 1, -1, -1):
            x = out[i]
            if x.get("tier") == victim_tier and (x.get("service") or "").lower() not in keep_l:
                out.pop(i)
                return True
        return False

    for term, vol in missing:
        if len(out) >= max_services and not _drop_one():
            break                          # everything is pinned; nothing to give
        rank = [t for t, _ in ranked].index(term)
        tier = "ultra" if rank < int(CFG.get("pin_as_ultra", 2)) else "competitive"
        out.insert(min(rank, len(out)), {"service": term, "tier": tier, "pinned": True})
    return out, [t for t, _ in missing]


def claude_expand_services(seeds, business_desc, site_pages, brand, domain,
                           candidates, max_services, n_cities=1, national=False):
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
1. A SERVICE is a short, generic phrase with NO city and NO brand — e.g. "auto insurance", "home insurance", "insurance agency", "umbrella insurance". {"This is a NATIONAL product brand: these terms are the final keyword list and will NOT be crossed with cities. Qualify the long-tail entries by AUDIENCE or USE CASE instead of location (e.g. \'electrolyte gummies for athletes\', \'energy gummies for teen athletes\'), never by place." if national else "It will be crossed with city names later, so do NOT include any location."}
2. Only services this business actually offers. Exclude anything they don't do.
2p. NEVER include "near me", "nearby", "closest" or any other proximity phrase. Every service is
   crossed with a city later, and "mattress store near me acworth ga" is not a phrase any human
   types — "near me" IS the location. Write the bare service; the grid adds the place.
2s. THE PARTNER'S SEED TERMS COME FIRST. They were typed by someone who knows the account, so treat
   them as the client's own service list. Any seed that is already a clean, bare service belongs in the
   output essentially as written. Only when you have fewer seeds than {max_services} should you add
   services of your own — and then from the business description and site pages before the keyword-idea
   list, which is ranked by national volume and is full of competitor names and out-of-area terms.
   Never spend a slot on an invented term while a usable seed goes unused.
2a. NEVER include a COMPETITOR'S company name as a service. The keyword-idea list WILL contain them
   (a search for "commercial construction company" surfaces the big national contractors) and they look
   like plausible services because they end in a trade word. They are not. Someone searching a specific
   firm's name wants that firm — the intent is navigational, the client will not outrank the brand for
   its own name, and because those terms come back "not ranking" every time they also inflate the quoted
   price on a client who actually ranks well.
2b. NARROW EXCEPTION: a brand name is allowed ONLY when it is a PHYSICAL PRODUCT LINE the client
   resells or installs — "butler building contractor", "trane furnace installation", "andersen window
   replacement". The client stocks or fits that manufacturer's goods, so customers really do search the
   brand plus the service.
   This exception does NOT cover a firm that PROVIDES THE SAME SERVICE as the client. An insurance
   agency does not "carry" State Farm; a builder does not "carry" Turner; an agency does not "carry" a
   rival agency. If the name belongs to a company a customer could hire INSTEAD of the client, it is a
   competitor — exclude it, no matter how much search volume it has. The keyword-idea list is ranked by
   volume, so the largest national competitor in the trade will almost always appear near the top and
   will look tempting. It is still wrong.
   When you cannot tell which kind of name it is, leave it out.
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
   Adjust the mix if {max_services} differs, but ALWAYS include at least one long_tail and at least one ultra —
   even when {max_services} is small (a 6-service list still needs a long_tail; the proposal shows three columns
   and an empty one reads as an incomplete strategy).
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


# --- geographic market grouping -------------------------------------------
# Three attempts at inferring market identity from SEARCH DEMAND all failed on
# the same client: geo-modified probes, resolved location names, and per-city
# volumes. The reason was the same each time — Blair County towns have no
# measurable individual demand, so no demand-based method can say whether they
# are one market or seven. Distance always can, and it is the thing the rule
# actually means: "2-3 related NEARBY markets normally run under one campaign".
#
# Brent Cogan's seven towns span 22 miles end to end. TN Water & Air's markets
# are 101 and 160 miles apart. One threshold separates them.
_ZIP_INDEX = None


def _zip_index():
    """city+state -> mean lat/long, built once from the bundled ZIP dataset."""
    global _ZIP_INDEX
    if _ZIP_INDEX is not None:
        return _ZIP_INDEX
    idx = {}
    try:
        import zipcodes
        acc = {}
        for r in zipcodes.list_all():
            if r.get("country") != "US" or not r.get("lat"):
                continue
            la, lo = float(r["lat"]), float(r["long"])
            # The dataset carries placeholder rows at 0,0 — Kennesaw GA has one,
            # and averaging it in put the city in the Atlantic, 1,100 miles from
            # its neighbours (2026-08-03).
            if not la or not lo:
                continue
            st_ = str(r.get("state", "")).upper()
            acc.setdefault((str(r.get("city", "")).lower(), st_), []).append((la, lo))
            # Some cities have no ZIPs of their own and appear only as an
            # alternate name on a neighbour's — Milton GA shares Alpharetta's
            # 30004/30009 — so they were reported as unplaceable and counted
            # as separate markets (2026-08-03). Index the alternates too, at
            # the host ZIP's coordinates, which is where they actually are.
            for alt in (r.get("acceptable_cities") or []):
                acc.setdefault((str(alt).lower(), st_), []).append((la, lo))

        def _med(xs):
            xs = sorted(xs)
            n_ = len(xs)
            return xs[n_ // 2] if n_ % 2 else (xs[n_ // 2 - 1] + xs[n_ // 2]) / 2

        # Median, not mean: one stray record can't drag a city across the map.
        idx = {k: (_med([a for a, _ in v]), _med([b for _, b in v]))
               for k, v in acc.items()}
    except Exception:
        app.logger.warning("zipcodes not available — geographic grouping is off")
    _ZIP_INDEX = idx
    return idx


def city_size(market, state=""):
    """Rough size proxy — how many ZIP codes a city has.

    Used to name a market after its recognisable centre. Sorting by latitude
    made a seven-town Blair County market read as "Claysburg +6" when anyone
    would call it Altoona.
    """
    city, st = parse_market(market, state)
    city = (city or "").strip().lower()
    abbr = STATE_ABBREV.get((st or state or "").strip().lower(), "").upper()
    try:
        import zipcodes
        return sum(1 for r in zipcodes.list_all()
                   if str(r.get("city", "")).lower() == city
                   and (not abbr or str(r.get("state", "")).upper() == abbr))
    except Exception:
        return 0


def city_coords(market, state=""):
    """Latitude/longitude for an entered market, or None."""
    city, st = parse_market(market, state)
    city = (city or "").strip().lower()
    if not city:
        return None
    abbr = STATE_ABBREV.get((st or state or "").strip().lower(), "")
    idx = _zip_index()
    if abbr:
        hit = idx.get((city, abbr.upper()))
        if hit:
            return hit
    # No usable state: accept a unique national match, never a guess between
    # several — there are Springfields in thirty states.
    hits = [v for (c, _s), v in idx.items() if c == city]
    return hits[0] if len(hits) == 1 else None


def miles_between(a, b):
    from math import radians, sin, cos, asin, sqrt
    (la1, lo1), (la2, lo2) = a, b
    la1, lo1, la2, lo2 = map(radians, [la1, lo1, la2, lo2])
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 3958.8 * asin(sqrt(h))


def group_by_distance(markets, state="", radius=None):
    """Cluster markets that sit within `radius` miles of each other.

    Single-link: A joins B's cluster if it is within the radius of ANY member,
    so a chain of neighbouring towns stays one market rather than splitting on
    the arithmetic of where the centre happens to fall.

    Returns (groups, located, unlocated).
    """
    r = float(radius if radius is not None else CFG.get("market_radius_miles", 25))
    pts, unlocated = {}, []
    for m in (markets or []):
        c = city_coords(m, state)
        (pts.__setitem__(m, c) if c else unlocated.append(m))
    # Complete-link: a city joins only if it is within the radius of EVERY
    # member, which caps the cluster's diameter at the radius. Single-link
    # chained Jasper into metro Atlanta through Canton even though Jasper is
    # 36 miles from Marietta — a market has a size, not just neighbours.
    groups = []
    for m in sorted(pts, key=lambda x: (pts[x][0], pts[x][1])):
        for g in groups:
            if all(miles_between(pts[m], pts[o]) <= r for o in g):
                g.append(m)
                break
        else:
            groups.append([m])
    return groups, list(pts), unlocated


def group_by_metro(vectors, min_terms=2):
    """Group cities that Google Ads treats as the same place.

    Google Ads doesn't hold volume for every town — it resolves a city to the
    nearest TARGETABLE location, which for most suburbs is the metro. So two
    cities in one metro return the identical figure for every term, because
    they are literally the same location as far as the data is concerned.

    That makes "same market" free to detect: cities whose volume VECTOR across
    several distinct terms matches exactly are one market. Woodstock entered
    fourteen Georgia towns and seven returned exactly 10/mo on every probe —
    not a floor artifact, one metro answering seven times (2026-07-28).

    It matters because everything downstream counts markets: a client with
    fourteen pills that are really three markets gets an add-on count, a grid
    shape and a coverage percentage all built on a number that is four times
    too big.

    `vectors` maps city -> list of volumes, in a consistent term order.
    Returns a list of groups, biggest first.
    """
    cities = [c for c, v in (vectors or {}).items() if v]
    if len(cities) < 2:
        return [[c] for c in cities]
    # A single shared term proves nothing — thin terms report 0 or 10 almost
    # everywhere. Require several, and require at least one to be non-zero, so
    # cities aren't grouped on a shared absence of data.
    groups, seen = [], set()
    for c in cities:
        if c in seen:
            continue
        vec = tuple(vectors[c])
        if len(vec) < min_terms or not any(vec):
            groups.append([c])
            seen.add(c)
            continue
        same = [d for d in cities
                if d not in seen and tuple(vectors.get(d, ())) == vec]
        for d in same:
            seen.add(d)
        groups.append(same or [c])
    groups.sort(key=len, reverse=True)
    return groups


def pick_grid_cities(markets, state, limit, probe_term="", explain=None,
                    home_hint=""):
    """`explain` is an optional dict that gets filled with WHY these cities won.

    Selection quietly discards markets the partner entered, which is the kind
    of decision that should never be invisible — an operator seeing four of
    thirteen cities in the grid has no way to tell whether the other nine were
    judged or just dropped. The dict records the probe used, every city's
    score, and what was cut.
    """
    """Choose WHICH cities go in the grid when more are supplied than the cap.
    Taking the first N by input order picks alphabetically-early villages over
    real metros (e.g. 'Augusta Springs' before 'Fairfax'). Instead, rank the
    supplied cities by how much search demand they actually carry, using a
    generic '<city>' population-proxy query, and keep the biggest.
    Falls back to input order if the lookup fails."""
    exp = explain if isinstance(explain, dict) else {}
    exp.update({"limit": limit, "method": "", "probe": "", "kept": [], "dropped": []})
    cities = [m.strip() for m in markets if m.strip()]
    # drop a market that is actually the state name — it isn't a city
    if state:
        cities = [c for c in cities if c.lower() != state.strip().lower()]
    # NOTE: we do NOT return early when the cities fit under the cap. The same
    # probe that ranks them is what reveals which ones Google treats as one
    # place, and the market count matters whether or not any city was dropped —
    # four towns in one metro are one market, cap or no cap. Returning early
    # here meant grouping only ever ran for clients OVER the limit
    # (2026-08-03).
    under_cap = len(cities) <= limit
    try:
        # Probe with the state suffix so ambiguous names resolve to the RIGHT
        # place: bare "insurance washington" matches Washington State/DC, and
        # "insurance jersey" matches New Jersey — which would rank tiny Virginia
        # towns above real metros. "insurance washington va" scores correctly.
        abbr = STATE_ABBREV.get((state or "").strip().lower(), "")
        sfx = f" {abbr}" if abbr else ""
        # Probe with the CLIENT'S OWN service where we have one. "insurance"
        # was a population proxy — it ranks cities by how big they are, not by
        # how much demand this client has in them, and those differ: a commuter
        # town can out-search a bigger neighbour for furniture and lose badly on
        # insurance. Measuring the actual service picks the markets that matter
        # to this quote. Falls back to the proxy when no seed is available.
        # Probe with EVERY seed and sum, not just the first one. seeds[0] is
        # whatever the partner happened to type first — for Woodstock that was
        # "furniture design consultation", a niche term with no volume in any
        # market, so the real signal never got a chance and the generic proxy
        # took over (2026-07-28). Summing across the seeds means one thin term
        # can't blind the ranking.
        terms = []
        for t in (probe_term if isinstance(probe_term, (list, tuple)) else [probe_term]):
            t = clean_kw(strip_proximity((t or "").lower())).strip()
            if t and t not in terms:
                terms.append(t)
        terms = terms[:4] or ["insurance"]
        # Build the probe key the SAME way it will be sent. dfs_kw_list strips
        # punctuation, so a market tagged "Hollidaysburg, PA" was looked up as
        # "...hollidaysburg, pa" while the API was asked for "...hollidaysburg
        # pa" — every volume read as zero, the proxy fallback fired, the metro
        # vectors were all zeros so nothing grouped, and the city ranking fell
        # back to alphabetical (2026-08-03). It only bit clients whose markets
        # carry a state tag, which is the format we ask for.
        _ck = {c: clean_kw(parse_market(c, state)[0] or c).lower() for c in cities}
        key = lambda t, c: clean_kw(f"{t} {_ck[c]}{sfx}")
        probe = [key(t, c) for c in cities for t in terms][:700]
        payload = [{"keywords": dfs_kw_list(probe),
                    "location_name": loc_string(cities, state),
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        items = (data.get("tasks") or [{}])[0].get("result") or []
        vol = {(it.get("keyword") or "").lower(): (it.get("search_volume") or 0)
               for it in items}
        exp["probe"] = " / ".join(f"{t} <city>{sfx}" for t in terms)
        exp["method"] = "client term"
        scored = {c: sum(vol.get(key(t, c), 0) for t in terms) for c in cities}
        # The same lookup that ranks the cities also reveals which of them
        # Google Ads treats as one place — no extra call.
        vectors = {c: [vol.get(key(t, c), 0) for t in terms] for c in cities}
        exp["metro_groups"] = [g for g in group_by_metro(vectors, min_terms=len(terms))
                               if len(g) > 1]
        term = terms[0]
        # If the client's own term returns nothing anywhere, the ranking is
        # noise — fall back to the population proxy rather than picking cities
        # by accident of ordering.
        if term != "insurance" and not any(scored.values()):
            probe2 = [key("insurance", c) for c in cities][:700]
            data2 = dfs_post("/keywords_data/google_ads/search_volume/live",
                             [{"keywords": dfs_kw_list(probe2),
                               "location_name": loc_string(cities, state),
                               "language_code": "en"}])
            v2 = {(it.get("keyword") or "").lower(): (it.get("search_volume") or 0)
                  for it in ((data2.get("tasks") or [{}])[0].get("result") or [])}
            scored = {c: v2.get(key("insurance", c), 0) for c in cities}
            # Regroup on the proxy too. Woodstock's seeds were niche enough to
            # return nothing anywhere, so the vectors were all zeros and no two
            # cities could be matched — the grouping went silent exactly when
            # the fallback fired, which is the case it is most needed in
            # (2026-07-28). The proxy resolves to the same Google Ads location
            # as any other term, so it groups just as well.
            vectors = {c: [v2.get(key("insurance", c), 0)] for c in cities}
            exp["metro_groups"] = [g for g in group_by_metro(vectors, min_terms=1)
                                   if len(g) > 1]
            exp["probe"] = f"insurance <city>{sfx}"
            exp["method"] = "population proxy"
        # Ties broken by name so the same input always gives the same cities.
        # Ties are common in small markets — DataForSEO floors thin terms at
        # 10/mo, so seven towns can score identically and an alphabetical
        # tiebreak silently drops the biggest one. Where the client's own name
        # or domain contains a market, that market is almost always their
        # flagship, so it wins a tie.
        # Matching the WHOLE market string ("clarendon hills, il") against the
        # hint could never succeed: a domain is "clarendonchiro.com", with no
        # space, no state and usually only the first word of the town. So
        # compare on the bare city, on its de-spaced form, and on its first
        # token — which is what a domain almost always carries (2026-08-04).
        hint_raw = (home_hint or "").lower()
        hint_squashed = re.sub(r"[^a-z0-9]", "", hint_raw)

        def home_rank(c):
            bare = (parse_market(c, state)[0] or c).strip().lower()
            if not bare:
                return 1
            squashed = re.sub(r"[^a-z0-9]", "", bare)
            if len(squashed) > 3 and squashed in hint_squashed:
                return 0                       # "clarendonhills" in the hint
            if len(bare) > 3 and bare in hint_raw:
                return 0                       # "clarendon hills" spelled out
            first = bare.split()[0]
            if len(first) >= 5 and first in hint_squashed:
                return 0                       # "clarendon" in clarendonchiro
            return 1
        ranked = sorted(cities, key=lambda c: (-scored.get(c, 0), home_rank(c), c.lower()))
        if under_cap:
            exp["method"] = "all"
            exp["kept"] = [(c, scored.get(c, 0)) for c in ranked]
            exp["dropped"] = []
            return ranked
        exp["kept"] = [(c, scored.get(c, 0)) for c in ranked[:limit]]
        exp["dropped"] = [(c, scored.get(c, 0)) for c in ranked[limit:]]
        # If the cut line falls inside a tie, the choice between those markets
        # was arbitrary and the operator needs to know rather than assume the
        # tool measured something.
        if exp["dropped"]:
            edge = scored.get(ranked[limit - 1], 0)
            tied = [c for c in cities if scored.get(c, 0) == edge]
            exp["tied_at_cut"] = tied if len(tied) > 1 else []
            exp["tie_value"] = edge
        return ranked[:limit]
    except Exception:
        exp.update({"method": "input order",
                    "kept": [(c, None) for c in cities[:limit]],
                    "dropped": [(c, None) for c in cities[limit:]]})
        return cities[:limit]


# DataForSEO's Google Ads keyword endpoints reject a specific punctuation set
# outright: the whole BATCH 40501s, so one dirty term zeroes every volume in
# the run and the volume component of price silently becomes $0. Seen
# 2026-07-25 on a partner seed that carried the client's own city with a comma
# ("corner dental salem,"), which also defeated the grid's "service already
# contains this market" check and produced "corner dental salem, salem or".
# Apostrophes and hyphens are legal and meaningful ("kid's dentist",
# "same-day crowns"), so they are deliberately NOT in this set.
DFS_BAD_CHARS = re.compile(r"[,!@%^()={};~`<>?\\|]")

def clean_kw(text):
    """Strip characters DataForSEO rejects and normalise whitespace."""
    t = DFS_BAD_CHARS.sub(" ", (text or ""))
    return re.sub(r"\s+", " ", t).strip()

def dfs_kw_ok(text):
    """DFS also caps keywords at 80 chars and 10 words. Terms past either
    limit are dropped from LOOKUPS only — they stay in the proposal list."""
    t = (text or "").strip()
    return bool(t) and len(t) <= 80 and len(t.split()) <= 10

def dfs_kw_list(terms):
    """Sanitised, de-duplicated, API-safe keyword list."""
    out, seen = [], set()
    for t in terms or []:
        c = clean_kw(t).lower()
        if c and c not in seen and dfs_kw_ok(c):
            seen.add(c)
            out.append(c)
    return out


def claude_region_names(markets, state, brand="", business_desc=""):
    """Ask for the vernacular names locals use for these markets.

    Returns a list of candidate names — Appleton -> "fox cities", Cherry Hill
    -> "south jersey", Lewisburg -> "central pa". These are proposals only;
    nothing reaches the quote until search volume backs it (see
    validate_region_names). Many markets have no such name and an empty list
    is the correct answer for them.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    cities = [c for c in (markets or []) if c and c.strip()]
    if not api_key or not cities:
        return []
    prompt = f"""Name the informal REGIONAL terms that local people use for these markets, and that they
would plausibly type into Google along with a service.

MARKETS: {", ".join(cities)}
STATE: {state or "unknown"}

Rules:
1. Return only vernacular region names — the ones on local radio and in local business names.
   "fox cities" (Appleton WI), "south jersey" (Cherry Hill NJ), "central pa" (Lewisburg PA),
   "lehigh valley" (Bethlehem PA), "the triangle" (Raleigh NC), "inland empire" (Riverside CA).
2. NEVER return: the city itself, the state on its own, a county name, a neighbourhood, a metro
   area label nobody says out loud ("Allentown-Bethlehem-Easton MSA"), or a compass phrase you
   invented ("north-central Wisconsin") unless it is genuinely in common use.
3. Most markets have NO such term. Returning an empty list is a correct and expected answer —
   a wrong region name is far worse than a missing one, because it becomes a keyword the client
   is quoted to rank for.
4. At most 3, lowercase, no state suffix.

Return ONLY a JSON object, no prose, no markdown:
{{"regions": ["fox cities"]}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({
                "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 300, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=25)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        out = []
        for r in (json.loads(text).get("regions") or []):
            name = clean_kw(str(r).lower()).strip()
            if name and name not in out and len(name.split()) <= 4:
                out.append(name)
        return out[:3]
    except Exception:
        app.logger.exception("claude_region_names failed")
        return []


def validate_region_names(candidates, service_term, markets, state):
    """Keep only region names with REAL search demand for this client's service.

    A name being locally recognised doesn't mean anyone searches it with a
    service attached, and an unsearched region name in the grid is a keyword
    the client is being quoted to rank for. So each candidate is measured the
    way it will actually be used — service + region — against the same phrase
    built from the client's own city, which is the honest benchmark.

    Testing the bare region name would not work: "fox cities" has volume as a
    navigational query whether or not anyone searches "roofing fox cities".

    Returns (kept, rejected) where each entry is (name, volume).
    """
    svc = clean_kw((service_term or "").lower()).strip()
    cands = [c for c in (candidates or []) if c]
    if not svc or not cands:
        return [], []
    city = next((c for c in (markets or []) if c and c.strip()), "")
    if city:
        _c, _st = parse_market(city, state)
        _sfx = f"{_c} {STATE_ABBREV.get((_st or '').lower(), '')}".strip()
        city_kw = clean_kw(f"{svc} {_sfx}")
    else:
        city_kw = svc
    probe = dfs_kw_list([f"{svc} {c}" for c in cands] + ([city_kw] if city_kw else []))
    if not probe:
        return [], []
    vols = {}
    try:
        payload = [{"keywords": probe,
                    "location_name": loc_string(markets, state) or "United States",
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        for row in ((data.get("tasks") or [{}])[0].get("result") or []):
            vols[(row.get("keyword") or "").lower()] = row.get("search_volume") or 0
    except Exception:
        app.logger.exception("validate_region_names lookup failed")
        return [], [(c, None) for c in cands]

    floor = int(CFG.get("region_min_volume", 10) or 10)
    kept, rejected = [], []
    for c in cands:
        v = vols.get(f"{svc} {c}".lower(), 0)
        (kept if v >= floor else rejected).append((c, v))
    kept.sort(key=lambda t: -t[1])
    return kept, rejected


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
        svc, tier = clean_kw(s["service"]).lower(), s["tier"]
        if not svc:
            continue
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
                kw = clean_kw(f"{svc} {c}{sfx}")
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

    # Tie-break on the term itself: volumes tie constantly at the thin end
    # (10, 40, 70/mo) and the API's own ordering is not stable between runs,
    # so without this the candidate pool — and therefore the keyword list —
    # reshuffles for reasons that have nothing to do with the client.
    kept.sort(key=lambda r: (-(r["volume"] or 0), r["keyword"]))
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
        geo_heads.sort(key=lambda r: (-(r["volume"] or 0), r["keyword"]))
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
    lt_candidates.sort(key=lambda r: (-len(r["keyword"].split()),
                                      -(r["volume"] or 0), r["keyword"]))
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
                   ultra, competitive, long_tail, site_terms_kw, phrase_geos=None,
                   national_demand=False):
    """Second half of Step 1, run as its own request: reads the sitemap, runs the
    Claude refinement pass, and re-pulls exact-match volume. Takes the raw buckets
    from stage1_keyword_list. Kept separate so a heavy Claude call can't time out
    the list build."""
    site_terms = [{"keyword": k} for k in (site_terms_kw or [])]
    _site_urls = []
    site_pages = fetch_site_pages(domain, collect_urls=_site_urls)
    site_locations = location_pages_from_urls(_site_urls)
    # A storefront on the client's own site is national demand, whatever the
    # RZ tag says. This has to happen HERE — before the volume pull below — or
    # the flip would only take effect on a second run, and the quote in front
    # of the operator would still be priced on per-city volume.
    ecom_found, ecom_reason = detect_ecommerce(_site_urls)
    if ecom_found and not national_demand:
        national_demand = True
        national_demand_reason = f"storefront detected — {ecom_reason}"
    else:
        national_demand_reason = ""
    # A Google Business listing is stronger evidence of operating in a market
    # than a page on the website, and it is the only one that works when the
    # site uses a store-locator widget. Merge, don't replace — a client can
    # have a location page without a listing and vice versa.
    # The client's own service-area list is the closest thing to the market
    # list a proposal is scoped from — better than listings for anyone whose
    # markets outnumber their premises.
    service_areas = fetch_service_areas(domain)
    for a in service_areas:
        if a.lower() not in {l.lower() for l in site_locations}:
            site_locations.append(a)
    gbp_cities, gbp_count = google_business_cities(brand, domain)
    for c in gbp_cities:
        if c.lower() not in {l.lower() for l in site_locations}:
            site_locations.append(c)
    biz = business_desc.strip() if business_desc else ""

    # ---- GRID MODE: build a service x city grid like the real proposals -----
    if CFG.get("grid_mode"):
        cands = ultra + competitive + long_tail
        # Decide the city set FIRST so the service count can scale to it.
        city_pick = {}
        cities = pick_grid_cities(markets, state, CFG["grid_max_cities"],
                                  probe_term=list(seeds or []),
                                  explain=city_pick,
                                  # Location pages and named service areas are
                                  # direct evidence of where the client
                                  # actually operates — better than the domain
                                  # alone, which only ever names one town.
                                  home_hint=" ".join(
                                      [brand or "", domain or ""]
                                      + [str(x) for x in (site_locations or [])]
                                      + [str(x) for x in (service_areas or [])]))
        # Search-phrase geos ("south jersey", "fox cities") cross into keyword
        # TEXT exactly like cities, but never touch a location API — no volume
        # lookup, no validation, no rank-check location. Keeps Brendan-style
        # regional phrasing without the invalid-location fallout.
        phrases = [p.strip() for p in (phrase_geos or []) if p and p.strip()]
        seen_c = {c.strip().lower() for c in cities}
        grid_cities = cities + [p for p in phrases if p.lower() not in seen_c]
        # NATIONAL DEMAND (2026-07-25): a product brand's keywords carry no
        # city. "energy gummies texas" is not a search anyone runs for a DTC
        # supplement, and pairing a national volume figure with a geo-suffixed
        # term misrepresents what the number counts. So the grid stops crossing
        # and becomes a flat national service list — build_grid already has
        # that path (it emits the bare service when cities is empty). The
        # client's geos stay on the order as their targeting area; they just
        # don't enter the keyword text or the volume lookup.
        if national_demand:
            grid_cities = []
        n_services = services_needed(len(grid_cities))
        services = claude_expand_services(seeds, biz, site_pages, brand, domain,
                                          cands, n_services,
                                          0 if national_demand else len(cities),
                                          national=national_demand)
        if not services:
            # fall back to the partner's seeds, spread across tiers
            tiers = ["ultra", "ultra", "competitive", "long_tail"]
            services = [{"service": s.strip().lower(), "tier": tiers[min(i, 3)]}
                        for i, s in enumerate(seeds[:n_services])]
        # Pricing must not swing on a non-deterministic model call: force the
        # highest-volume terms the search API returned into the list.
        # Bare the services BEFORE pinning so the containment check compares
        # like with like, and before the grid so nothing carries a geo into
        # the crossing.
        services = scrub_services(services, markets, state, phrase_geos)
        services, geo_dropped = drop_foreign_geo_services(services, markets, state)
        services, pinned = pin_head_services(services, cands, markets, state,
                                             brand, n_services)
        services = scrub_services(services, markets, state, phrase_geos)
        # Pinning pulls straight from the keyword-idea pool, which is exactly
        # where out-of-area terms live — so a term filtered out above can be
        # re-inserted below it. Filter again AFTER pinning and fold the two
        # result sets together; a pin is not a licence to sell in a state the
        # client doesn't operate in.
        services, seed_used = (enforce_seed_services(services, seeds, n_services,
                                                    markets, state, phrase_geos)
                               if seeds else (services, 0))
        services, geo_dropped2 = drop_foreign_geo_services(services, markets, state)
        services, ungrounded, blocked_pins = drop_ungrounded_services(
            services, seeds, biz, [p.get("title", "") if isinstance(p, dict) else str(p)
                                   for p in (site_pages or [])], brand, domain)
        services = rebalance_tiers(services)
        if geo_dropped is None and geo_dropped2 is None:
            geo_dropped = None
        else:
            seen_d = set()
            geo_dropped = [d for d in (list(geo_dropped or []) + list(geo_dropped2 or []))
                           if not (d[0] in seen_d or seen_d.add(d[0]))]
        pinned = [t for t in pinned
                  if any((x.get("service") or "") == t for x in services)]
        g = build_grid(services, grid_cities, state, prepicked=True)
        full = g["ultra"] + g["competitive"] + g["long_tail"]
        # Volume: look up the BARE service term AT THE CLIENT'S MARKET (the
        # geo-modified forms report ~0). The same figure is shown on each city
        # row for that service, so pricing must count it ONCE PER SERVICE — not
        # once per row — or a 10-city grid would inflate volume 10x.
        svc_names = list(dict.fromkeys([s["service"] for s in services]))
        vols, per_city, vol_err = fetch_local_volume(
            svc_names, [] if national_demand else cities, state,
            national=national_demand)
        # LAST RESORT for a national quote: Labs carries per-term volume and is
        # a different service, so a Google Ads outage doesn't take it down too.
        # Restricted to national_demand deliberately — Labs answers at country
        # level, which for a national quote is the SAME figure, but for a local
        # one it would substitute national demand for local and inflate the
        # price. A local quote keeps the honest error instead.
        volume_source = "google_ads"
        if vol_err and national_demand and svc_names:
            _lv = fetch_exact_volume(svc_names, [], "", national=True)
            if _lv and any(_lv.values()):
                vols = _lv
                volume_source = "labs"
                vol_err = None
        # Collapse cities that resolved to the SAME Google Ads location. This
        # is the exact answer — DataForSEO reports the location it used — and
        # it replaces the volume-vector inference, which needed the geo-modified
        # probe to have volume and therefore gave up in small rural markets.
        # Group on the PER-CITY VOLUMES that were just fetched. Google Ads holds
        # demand at the nearest targetable location, so cities in one market
        # return the identical figure for every service — Brent Cogan's five
        # towns all came back 30 / 10 / 10 (2026-08-03).
        #
        # Two earlier attempts missed this. Matching on the geo-modified probe
        # ("electrical panel upgrade hollidaysburg pa") needed volume the term
        # doesn't have in a rural county, so every vector was zero. Matching on
        # the location NAME failed because the name recorded is the one we
        # SENT — "Bellwood,Pennsylvania" — not the one Google resolved it to.
        # These volumes are the resolution, observed rather than inferred.
        # Distance first — it is the only signal that works when the markets
        # have no measurable demand, which is exactly when grouping matters.
        if not national_demand:
            _g, _loc, _un = group_by_distance(markets, state)
            _real = [x for x in _g if len(x) > 1]
            if _real:
                city_pick["metro_groups"] = _real
                city_pick["grouped_by"] = (
                    f"distance — markets within {int(CFG.get('market_radius_miles', 25))} "
                    f"miles of each other")
                city_pick["unlocated_markets"] = _un
        if not city_pick.get("metro_groups") and per_city and not national_demand:
            _svcs = [x.lower() for x in svc_names]
            _vecs = {}
            for _c in cities:
                _cl2 = _bare_city(_c, state)
                _v = [per_city.get((_cl2, _s)) for _s in _svcs]
                if any(x is not None for x in _v):
                    _vecs[_c] = [(0 if x is None else x) for x in _v]
            _groups = [g for g in group_by_metro(_vecs, min_terms=1) if len(g) > 1]
            if _groups:
                city_pick["metro_groups"] = _groups
                city_pick["grouped_by"] = "identical per-market search volume"
            elif not city_pick.get("metro_groups"):
                city_pick["metro_groups"] = []
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
            "pinned_head_terms": pinned,
            # [(term, offending_word)] — pins refused for being ungrounded.
            "blocked_pins": [[b[0], b[1]] for b in (blocked_pins or [])],
            "city_selection": city_pick,
            # per_city is keyed by (city, keyword) tuples but also carries the
            # "__city_locs__" side-channel, so every key has to be checked
            # before it is unpacked — destructuring in the comprehension blew
            # up the whole refine pass with "too many values to unpack"
            # (2026-08-03).
            "city_volumes": {c: max([v for k, v in (per_city or {}).items()
                                     if isinstance(k, tuple) and len(k) == 2
                                     and k[0] == _bare_city(c, state)] or [0])
                             for c in cities},
            "city_locs": {c: l for c, l in
                          ((per_city or {}).get("__city_locs__") or {}).items()},
            "site_locations": site_locations,
            "service_areas": service_areas,
            "gbp_locations": gbp_count,
            "gbp_cities": gbp_cities,
            "dropped_out_of_area": [d[0] for d in (geo_dropped or [])],
            "seed_services_used": seed_used,
            "dropped_ungrounded": [d[0] for d in (ungrounded or [])],
            "grounding_stood_down": ungrounded is None,
            "geo_filter_off": geo_dropped is None,
            "service_volume": service_volume,
            "volume_error": vol_err,
            "volume_location": "United States" if national_demand else loc_string(markets, state),
            "volume_source": volume_source,
            "national_demand": bool(national_demand),
            "national_demand_reason": national_demand_reason,
            "ecommerce_detected": bool(ecom_found),
            "ecommerce_reason": ecom_reason,
            "state_missing": bool(cities) and not state
                             and not any(market_state(c)
                                         or c.strip().lower() in STATE_ABBREV
                                         for c in cities),
            "grid_cities": [] if national_demand else cities,
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

    exact = fetch_exact_volume([r["keyword"] for r in full], markets, state,
                               national=national_demand)
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
        # Carried on this path too — the storefront read is independent of
        # whether the grid build ran, and dropping it here would silently undo
        # the flip for any client that falls through to the non-grid list.
        "national_demand": bool(national_demand),
        "national_demand_reason": national_demand_reason,
        "ecommerce_detected": bool(ecom_found),
        "ecommerce_reason": ecom_reason,
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

# Verticals Google Ads restricts. The Keyword Planner "metrics for keywords you
# provide" endpoint (search_volume) policy-filters these and returns NO rows,
# while the keyword-IDEAS endpoint answers normally — which is why a cannabis
# client can show real volumes in Step 1 and a $0 adder in Step 2 off the same
# API key (Grav, 2026-08-04). Matched by substring against the RZ industry text.
# Substrings, so they must not appear inside innocent categories: bare "gun"
# hits "Burgundy" and bare "adult" hits "Adult Day Care" / "Adult Education",
# both real RZ categories that are not restricted at all.
RESTRICTED_VERTICALS = (
    "cannabis", "marijuana", "cbd", "hemp", "kratom", "vape", "smoke shop",
    "dispensary", "tobacco", "firearm", "ammunition", "gun shop", "gun range",
    "gambling", "casino", "sportsbook", "adult entertainment",
)


def restricted_vertical(industry=""):
    """Which restricted term (if any) this industry matches. '' when none."""
    ind = (industry or "").strip().lower()
    for k in RESTRICTED_VERTICALS:
        if k in ind:
            return k
    return ""


def fetch_bids_via_ideas(terms, location_name):
    """Top-of-page bids from the keyword-IDEAS endpoint.

    Used only when search_volume returns nothing. Same Google Ads account, same
    payload shape — but keywords_for_keywords is not policy-filtered, so it is
    the one endpoint that answers for restricted verticals. It returns cpc and
    bid fields alongside search_volume; the candidate-pool parse throws them
    away, so they were being paid for and discarded.

    Ideas responses are seeded BY the terms and come back with extra keywords,
    so only exact matches on what we asked for are kept. Returns
    ({keyword: {bid, cpc, volume}}, error_or_None).
    """
    kws = dfs_kw_list(terms)
    if not kws:
        return {}, None
    try:
        payload = [{"keywords": kws[:200], "location_name": location_name,
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/keywords_for_keywords/live", payload)
        task0 = (data.get("tasks") or [{}])[0]
        if task0.get("status_code") not in (20000, None):
            return {}, f"{task0.get('status_code')}: {task0.get('status_message')}"
        want = set(kws)
        out = {}
        for it in (task0.get("result") or []):
            k = (it.get("keyword") or "").lower()
            if k not in want:
                continue                      # ideas the seed pulled in, not ours
            out[k] = {"bid": it.get("high_top_of_page_bid") or 0,
                      "cpc": it.get("cpc") or it.get("high_top_of_page_bid") or 0,
                      "volume": it.get("search_volume") or 0}
        return out, None
    except Exception as e:
        return {}, str(e)


def fetch_bids_via_labs(terms, markets, state, national=False):
    """Bids and CPC from the DataForSEO LABS keyword database.

    The last resort, and the one most likely to answer in a restricted vertical.
    Labs is DataForSEO's own aggregated database rather than a live Google Ads
    call, so it is not subject to the ad-policy filtering that empties
    search_volume for cannabis and friends — which is exactly why keyword
    DIFFICULTY has been coming back for these clients all along.

    The keyword_info block this reads already reaches us on every Step 1 run:
    fetch_exact_volume calls the same endpoint and keeps search_volume alone,
    discarding cpc and the bid fields sitting beside it.

    NOTE: Labs CPC is modelled, not a live auction reading, so it can differ
    from Google Ads. The caller reports which source supplied the number so an
    adder built on Labs is never mistaken for one built on Google Ads.
    Returns ({keyword: {bid, cpc, volume}}, error_or_None).
    """
    kws = dfs_kw_list(terms)
    if not kws:
        return {}, None
    loc_field, _loc_used = _labs_loc_field(markets, state, national)
    try:
        payload = [{"keywords": [k.lower() for k in kws[:1000]],
                    **loc_field, "language_code": "en"}]
        data = dfs_post("/dataforseo_labs/google/keyword_overview/live", payload)
        task0 = (data.get("tasks") or [{}])[0]
        if task0.get("status_code") not in (20000, None) and not task0.get("result"):
            return {}, f"{task0.get('status_code')}: {task0.get('status_message')}"
        out = {}
        for block in (task0.get("result") or []):
            for it in (block.get("items") or []):
                k = (it.get("keyword") or "").lower()
                ki = it.get("keyword_info") or {}
                if not k:
                    continue
                bid = ki.get("high_top_of_page_bid") or 0
                out[k] = {"bid": bid,
                          "cpc": ki.get("cpc") or bid or 0,
                          "volume": ki.get("search_volume") or 0}
        return out, None
    except Exception as e:
        return {}, str(e)


def stage3_metrics(head, markets, state, national=False, industry=""):
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
    # Step 1 prices national demand on geo-less volume; Step 2 has to measure
    # competition on the SAME basis or the two halves of one quote describe
    # different markets. This was never plumbed through, so a nationwide client
    # with cities entered had its bids read from those cities (2026-08-04).
    primary_loc = "United States" if national else loc_string(markets, state)
    loc_chain = [primary_loc]
    if state and f"{state},United States" not in loc_chain:
        loc_chain.append(f"{state},United States")
    if "United States" not in loc_chain:
        loc_chain.append("United States")
    bid_err = None
    items = []
    bid_loc_used = primary_loc
    _dl = _deadline()
    for _loc in loc_chain:
        _left = _remaining(_dl)
        if _left is None:
            break                       # budget spent: use what we have
        payload = [{"keywords": dfs_kw_list(bare_unique),
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

    # FALLBACK. search_volume gave us no usable bid — either it returned no rows
    # at all, or rows with every bid blank. Ask the ideas endpoint, which is not
    # policy-filtered. Costs one extra call and only on the failing path.
    bid_source = "search_volume"
    ideas_err = labs_err = None

    def _adopt(src, got):
        """Take bids from a fallback source. Returns True if it supplied any."""
        nonlocal bare_bid, bid_source, bid_err
        if not any((v or {}).get("bid") for v in got.values()):
            return False
        bare_bid = {k: v["bid"] for k, v in got.items() if v.get("bid")}
        for k, v in got.items():
            if v.get("cpc"):
                bare_cpc[k] = v["cpc"]
        bid_source = src
        bid_err = None
        return True

    if not any(bare_bid.values()):
        # 2nd: Google Ads keyword IDEAS — same account, not policy-filtered.
        ideas, ideas_err = fetch_bids_via_ideas(bare_unique, bid_loc_used)
        if not _adopt("keyword_ideas", ideas):
            # 3rd: LABS. Its own database rather than a live Ads call, so it is
            # the source that still answers when advertising in the vertical is
            # banned outright. Modelled CPC, hence last.
            labs, labs_err = fetch_bids_via_labs(bare_unique, markets, state,
                                                 national=national)
            _adopt("labs", labs)
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
    n_bids = (bid_stats or {}).get("n", 0)
    min_n = int(CFG.get("cpc_adder_min_samples", 1) or 1)
    cpc_low_conf = bool(bid_stats) and n_bids < int(CFG.get("cpc_adder_low_confidence_n", 3))
    if (CFG.get("cpc_adder_enabled") and bid_stats and bid_stats["median"]
            and n_bids >= min_n):
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
    # No bid data from EITHER endpoint. The adder is then not a measurement of
    # $0 competition, it is an absence of evidence — and this quote is priced as
    # if the vertical were free. Say so and make the operator decide.
    restricted = restricted_vertical(industry)
    no_bids = not bid_vals
    # When there are no bids anywhere, organic difficulty is the only competition
    # signal left. Score it on the SAME 0/1/2 ladder as bids and APPLY it: an
    # adder the tool can derive from evidence should not need to be typed in by
    # hand. The operator can still override, but the default is now a reasoned
    # number rather than a blank field (2026-08-04).
    kd_suggested_adder = kd_score = None
    if no_bids and median_kd is not None:
        klo, khi = CFG.get("kd_score_breaks", [30, 60])
        kd_score = 2 if median_kd > khi else 1 if median_kd >= klo else 0
        kd_suggested_adder = CFG["competitive_adder"][kd_score]
        adder = kd_suggested_adder
        adder_basis = "kd"
    # Only a total absence of evidence still stops the quote: no bids from any
    # of the three sources AND no organic difficulty either. Then there really
    # is nothing to reason from and a human has to supply the number.
    adder_blocked = no_bids and kd_suggested_adder is None
    return {"adder": adder, "adder_basis": adder_basis, "cpc_used": cpc_used,
            "cpc_low_confidence": cpc_low_conf, "cpc_n_bids": n_bids,
            "flat_adder": flat_adder,
            "bid_source": bid_source,
            "bid_ideas_error": ideas_err,
            "bid_labs_error": labs_err,
            "adder_blocked": adder_blocked,
            "kd_suggested_adder": kd_suggested_adder,
            "kd_score": kd_score,
            "restricted_vertical": restricted,
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

def rank_location(markets, state, national=False):
    """Where to measure rankings. Under national demand the keywords carry no
    city ("energy gummies", not "energy gummies texas"), so a Texas-localised
    SERP would be reporting a local result for a national term. Brendan's own
    MPG table (2026-06-10) lists one national rank per bare keyword, which is
    the format this matches. The zero-ranking uplift keys off these positions,
    so the location has to describe the same market the keywords do."""
    return "United States" if national else loc_string(markets, state)


def resolve_national_demand(industry="", band="", manual=False):
    """Should this client be priced on GEO-LESS (national) search volume?

    Three sources, any of which is sufficient:
      1. RZ industry taxonomy — a rule carrying national_demand (ecommerce and
         its product-brand siblings). Industry sets no price of its own; it
         only says "measure demand nationally," and the volume/competition/
         visibility signals then price the client on their own merits.
      2. Geo scope of nationwide — no cities, so the pull is already geo-less.
      3. Manual operator checkbox, for the cases RZ mistags.

    A fourth source — an actual storefront detected on the client's own site —
    is applied inside stage1b_refine, because it is only knowable once the
    sitemap has been read. See detect_ecommerce().

    Returns (bool, reason_string) so the UI can show WHY it flipped.
    """
    if manual:
        return True, "manual override"
    if band == "nationwide":
        return True, "nationwide geo scope"
    ind = (industry or "").strip().lower()
    for k, r in (CFG.get("industry_pricing") or {}).items():
        if k in ind and r.get("national_demand"):
            return True, f"industry: {k}"
    return False, ""


# Storefront fingerprints, checked against the sitemap URLs already collected
# by fetch_site_pages. Ordered most-specific first so the reason names the
# platform when it can. Each entry: (label, regex, weight_threshold).
_ECOM_SIGNATURES = [
    ("Shopify",      re.compile(r"/(collections|products)/", re.I)),
    ("WooCommerce",  re.compile(r"/(product-category|product-tag)/", re.I)),
    ("BigCommerce",  re.compile(r"/(categories|brands)/[^/]+/?$", re.I)),
    ("Magento",      re.compile(r"/catalog/(product|category)/", re.I)),
    ("store",        re.compile(r"/(shop|store|product|catalogue|catalog)/", re.I)),
]
# A cart or checkout route is conclusive on its own — nothing but a store has
# one — so it does not need the repetition threshold the catalog paths do.
_ECOM_CHECKOUT = re.compile(r"/(cart|checkout|basket|my-account/orders)\b", re.I)


def detect_ecommerce(urls, min_hits=3):
    """Is the client running a storefront? Reads ONLY the sitemap URLs that
    fetch_site_pages already collected — no extra HTTP calls, no extra latency.

    Exists because national-demand pricing hangs off the RZ industry tag, and
    the tag is routinely missing or wrong: a smoke shop selling nationwide gets
    filed under a local retail category, so its volume is pulled per-city and
    the quote is built on the wrong demand figure entirely.

    A single /product/ URL is not a store — brochure sites use that path for
    one product page — so catalog patterns need `min_hits` distinct matches.
    A cart or checkout route is accepted on its own.

    Returns (bool, reason_string).
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return False, ""
    for u in urls:
        if _ECOM_CHECKOUT.search(u):
            return True, "cart/checkout page on site"
    if any("sitemap_products" in u.lower() for u in urls):
        return True, "Shopify product sitemap"
    for label, rx in _ECOM_SIGNATURES:
        hits = {u for u in urls if rx.search(u)}
        if len(hits) >= min_hits:
            return True, f"{len(hits)} {label} product URLs on site"
    return False, ""


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
                 ecommerce=False, industry="", ai_search=False,
                 national_demand=False, geo_override=None, addon_override=None):
    if markup_pct is None:
        markup_pct = CFG["default_markup_pct"]
    m = 1.0 + (markup_pct / 100.0)

    # Resolve the industry rule FIRST — national demand has to be known before
    # the anchor is picked, because it routes to the national anchor.
    rule_key, rule = None, None
    ind = (industry or "").strip().lower()
    # The industry field is multi-select (values joined with " | "), so
    # several rules can match at once. Precedence: the STRONGEST card wins
    # (largest anchor_add) — a hospital that also sells products online is
    # priced as a hospital, not as a shop.
    _matches = [(k, r) for k, r in CFG.get("industry_pricing", {}).items() if k in ind]
    if _matches:
        rule_key, rule = max(_matches, key=lambda kr: int(kr[1].get("anchor_add", 0)))
    # The legacy ecommerce checkbox no longer maps to a pricing rule (it has
    # no anchor_add as of 2026-07-25) — it is a national-demand signal only.
    nat_demand, nat_reason = resolve_national_demand(
        industry, band, bool(ecommerce) or bool(national_demand))

    # A product brand priced on national demand sits on the NATIONAL anchor
    # even when the operator picked a local/statewide scope — the client's
    # cities describe where they ship, not where the demand is measured.
    anchor_band = "nationwide" if nat_demand else band
    anchor = CFG["geo_anchor"][anchor_band]                # hard cost

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
    if rule:
        base_pre += int(rule.get("anchor_add", 0))

    # The volume add prices UNCAPTURED demand. A client already ranking for
    # most of its terms owns that traffic; charging for it double-counts.
    ramp = CFG.get("vol_add_ramp") or None
    vol_opportunity = 1.0
    if ramp and pct_not_ranking is not None and vol_add:
        lo, hi = float(ramp[0]), float(ramp[1])
        vol_opportunity = 0.0 if hi <= lo else (float(pct_not_ranking) - lo) / (hi - lo)
        vol_opportunity = max(0.0, min(1.0, vol_opportunity))
        _prev = vol_add
        vol_add = int(round(vol_add * vol_opportunity))
        # Adjust by the DELTA — base_pre already carries the industry rule's
        # anchor_add at this point, so reassigning it from scratch silently
        # dropped the hospital/insurance premium (caught in regression).
        base_pre += (vol_add - _prev)
    vol_captured = vol_opportunity < 1.0

    # Extras suppression.
    #  - Industry rules that price on ORGANISATION size rather than SERP
    #    signals (hospital / telehealth / behavioral health) still zero both.
    #  - Nationwide scope is now governed by nationwide_service_extras, which
    #    is 1.0 as of 2026-07-25 (Brendan): volume, competition and current
    #    visibility are what separate national clients, so muting them made
    #    every national client price identically. Left as a live multiplier
    #    rather than deleted so Skidmore can be re-fit without a code change.
    nw_service = (anchor_band == "nationwide" and not (rule and rule.get("anchor_add")))
    rule_extras_off = bool(rule and rule.get("extras_off"))
    _mult = (float(CFG.get("nationwide_service_extras", 1.0)) if nw_service
             else (0.0 if rule_extras_off else 1.0))
    extras_off = _mult != 1.0
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
    elif anchor_band == "nationwide":
        # Brendan's national ladder steps PROPORTIONALLY — $1,500 client rungs
        # on a $3,950 base = 38% (Skidmore and MPG both). Keyed to anchor_band
        # so a product brand on national demand gets the card's shape too:
        # keeping flat $700 steps there was most of MPG's 15% shortfall (his
        # rungs are $1,500 client, the flat ladder gave $950).
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

    # ---- minimum term (applies to the whole quote, not just GEO) ----
    zv_thresh = CFG.get("zero_visibility_pct_not_ranking", 90)
    zero_visibility = (pct_not_ranking is not None and pct_not_ranking >= zv_thresh)
    min_term = (CFG.get("min_term_months_zero_visibility", 12) if zero_visibility
                else CFG.get("min_term_months", 6))

    # ---- Core SEO + AI Search: GEO as a % of the client's own Core SEO ----
    # Brendan: GEO averages 30-50% below SEO, rising toward parity when the
    # client has no visibility. The list price is that %; the quoted price is
    # the list less the bundle discount, applied to ALL THREE tiers.
    ai = None
    if ai_search:
        if CFG.get("geo_pricing_mode", "pct") == "card":
            card = CFG.get("geo_card", {})
            card_list = CFG.get("geo_card_list", card)
            ai = {"mode": "card",
                  "min_term_months": CFG.get("geo_min_term_months", 12),
                  "client_add":  {k: int(card.get(k, 0)) for k in client},
                  "client_list": {k: int(card_list.get(k, 0)) for k in client},
                  "hard_add":    {k: r50(int(card.get(k, 0)) / m) for k in client}}
        else:
            if pct_not_ranking is None:
                geo_pct = float(CFG.get("geo_pct_default", 60))
                geo_basis = "default (no ranking data)"
            else:
                geo_pct = float(CFG.get("geo_pct_default", 60))
                geo_basis = "default"
                for thresh, val in CFG.get("geo_pct_tiers", []):
                    if pct_not_ranking >= thresh:
                        geo_pct = float(val)
                        geo_basis = f"{pct_not_ranking:.0f}% of head terms not ranking"
                        break
            disc = float(CFG.get("geo_bundle_discount_pct", 5)) / 100.0
            p_list = geo_pct / 100.0
            p_net  = p_list * (1.0 - disc)
            ai = {"mode": "pct",
                  "uplift_pct": geo_pct,
                  "geo_pct": geo_pct,
                  "geo_pct_basis": geo_basis,
                  "bundle_discount_pct": CFG.get("geo_bundle_discount_pct", 5),
                  "min_term_months": min_term,
                  "zero_visibility": zero_visibility,
                  "client_list": {k: r50(v * p_list) for k, v in client.items()},
                  "hard_add":    {k: r50(v * p_net)  for k, v in hard.items()},
                  "client_add":  {k: r50(v * p_net)  for k, v in client.items()}}
        # GEO can be overridden independently of SEO. The percentage model is
        # a good default and a bad straitjacket: a client may have agreed a GEO
        # number that has nothing to do with their SEO price — a flat retainer,
        # a carried-over rate — and the alternative is overriding SEO to a
        # fiction just to move GEO. The override sets the BASE and the ladder
        # keeps its shape, scaling the upper tiers by the same ratio the SEO
        # ladder uses, so the three tiers stay proportionate to each other.
        try:
            geo_base = float(geo_override) if geo_override not in (None, "") else None
        except (TypeError, ValueError):
            geo_base = None
        if geo_base and geo_base > 0:
            ratio = {k: (hard[k] / hard["base"] if hard["base"] else 1.0) for k in hard}
            ai["hard_add"] = {k: r50(geo_base * ratio[k]) for k in hard}
            ai["client_add"] = {k: r50(ai["hard_add"][k] * m) for k in hard}
            ai["client_list"] = dict(ai["client_add"])
            ai["manual_geo"] = True
            ai["geo_pct_basis"] = "manual override"
            ai["geo_pct"] = (round(ai["client_add"]["base"] / client["base"] * 100, 1)
                             if client.get("base") else None)
        ai["hard_total"]   = {k: hard[k] + ai["hard_add"][k] for k in hard}
        ai["client_total"] = {k: client[k] + ai["client_add"][k] for k in client}
        ai["bundle_savings"] = {k: ai["client_list"][k] - ai["client_add"][k]
                                for k in client} if "client_list" in ai else {}

    _ar = CFG.get("addon_market_ratio_tiers") or {}
    _r  = lambda k: float(_ar.get(k, CFG["addon_market_ratio"]))
    hard_addon   = {k: r50(v * _r(k)) for k, v in hard.items()}
    client_addon = {k: r50(v * _r(k)) for k, v in client.items()}
    # An add-on market can be negotiated independently of the ratio. A client
    # taking eleven of them will argue the per-market rate long before the
    # primary campaign, and the alternative is distorting the whole ladder to
    # move one number. Sets the BASE; the upper tiers keep the SEO ladder's
    # shape so the three stay proportionate.
    try:
        _ao = float(addon_override) if addon_override not in (None, "") else None
    except (TypeError, ValueError):
        _ao = None
    manual_addon = bool(_ao and _ao > 0)
    if manual_addon:
        _ar2 = {k: (hard[k] / hard["base"] if hard["base"] else 1.0) for k in hard}
        hard_addon   = {k: r50(_ao * _ar2[k]) for k in hard}
        client_addon = {k: r50(hard_addon[k] * m) for k in hard}
    return {"anchor": anchor, "base": base, "base_pre_uplift": base_pre, "step": step,
            "national_demand": nat_demand, "national_demand_reason": nat_reason,
            "volume_captured": vol_captured,
            "volume_opportunity": round(vol_opportunity, 3),
            "min_term_months": min_term, "zero_visibility": zero_visibility,
            "extras_multiplier": _mult,
            "manual_geo": bool(ai and ai.get("manual_geo")),
            "manual_addon": manual_addon,
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
    return render_template("index.html", build=BUILD_STR)

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
                          ai_search=bool(d.get("ai_search")),
                          national_demand=bool(d.get("national_demand")),
                          geo_override=d.get("geo_override"),
                          addon_override=d.get("addon_override"))
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

@app.route("/api/suggest_regions", methods=["POST"])
@_json_error_guard
def api_suggest_regions():
    """Propose vernacular region names for the entered markets, then keep only
    the ones with real search demand for the client's own service."""
    d = request.get_json(force=True) or {}
    markets = [m for m in (d.get("geo_values") or []) if m and m.strip()]
    state = (d.get("state") or "").strip()
    seeds = [k for k in (d.get("keywords") or []) if k and k.strip()]
    if not markets:
        return jsonify({"regions": [], "rejected": [],
                        "note": "Add at least one geographic targeting area first."})
    if not seeds:
        return jsonify({"regions": [], "rejected": [],
                        "note": "Add a Keyword / Vertical Focus term first — a region name is "
                                "only tested against the client's own service."})
    cands = claude_region_names(markets, state, d.get("brand") or "",
                                d.get("business_desc") or "")
    if not cands:
        return jsonify({"regions": [], "rejected": [],
                        "note": "No commonly-searched regional name for these markets. That is a "
                                "normal answer — most markets don't have one."})
    svc = clean_kw(seeds[0].lower()).strip()
    kept, rejected = validate_region_names(cands, svc, markets, state)
    return jsonify({
        "regions": [{"name": n, "volume": v} for n, v in kept],
        "rejected": [{"name": n, "volume": v} for n, v in rejected],
        "tested_with": svc,
        "note": "" if kept else
                f"Suggested {', '.join(c for c in cands)} — but none reach "
                f"{CFG.get('region_min_volume', 10)} searches a month with \u201c{svc}\u201d "
                f"attached, so none are worth quoting against.",
    })


@app.route("/api/keywords", methods=["POST"])
@_json_error_guard
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
@_json_error_guard
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
    # National demand: RZ industry (ecommerce family) OR nationwide scope OR
    # the operator's manual checkbox. Flips the volume pull to geo-less; the
    # grid itself still uses the client's cities.
    nat_demand, nat_reason = resolve_national_demand(
        industry=(d.get("industry") or ""),
        band=d.get("geo_scope", d.get("band", "")),
        manual=bool(d.get("national_demand")) or bool(d.get("ecommerce")))
    # rebuild bucket rows from what the frontend sends back (kw + vol)
    def rows(key):
        return [{"keyword": x["kw"], "volume": x.get("vol", 0), "src": "build"}
                for x in d.get(key, []) if x.get("kw")]
    ultra, competitive, long_tail = rows("ultra"), rows("competitive"), rows("long_tail")
    try:
        s1 = stage1b_refine(seeds, markets, state, brand, domain, business_desc,
                            ultra, competitive, long_tail, site_terms_kw, phrase_geos,
                            national_demand=nat_demand)
    except Exception as e:
        # graceful: hand back the unrefined list so the pipeline still works
        conv0 = lambda L: [{"kw": r["keyword"], "vol": r["volume"], "origin": ""} for r in L]
        app.logger.exception("stage1b_refine failed")
        return jsonify({"national_demand": nat_demand,
                        "national_demand_reason": nat_reason,
                        "ultra": conv0(ultra), "competitive": conv0(competitive),
                        "long_tail": conv0(long_tail),
                        "head": conv0(ultra + competitive),
                        "all": conv0(ultra + competitive + long_tail),
                        "refined_by_ai": False, "refine_attempted": True,
                        "business_desc": "",
                        "site_pages_found": 0, "refine_error": str(e)})
    conv = lambda L: [{"kw": r["keyword"], "vol": r["volume"],
                       "origin": r.get("origin", "")} for r in L]
    return jsonify({
        "ultra": conv(s1["ultra"]), "competitive": conv(s1["competitive"]),
        "long_tail": conv(s1["long_tail"]), "head": conv(s1["head"]),
        "all": conv(s1["all"]), "refined_by_ai": s1.get("refined_by_ai", False),
        "refine_attempted": True,
        # Diagnostics from the list build. api_refine names the keys it
        # forwards, so anything stage1b_refine returns that isn't listed here
        # never reaches the browser — every one of these panels has been
        # rendering against undefined and showing nothing (2026-07-28).
        "city_selection": s1.get("city_selection") or {},
        "city_locs": s1.get("city_locs") or {},
        "city_volumes": s1.get("city_volumes") or {},
        "site_locations": s1.get("site_locations") or [],
        "service_areas": s1.get("service_areas") or [],
        "gbp_locations": s1.get("gbp_locations"),
        "gbp_cities": s1.get("gbp_cities") or [],
        "seed_services_used": s1.get("seed_services_used", 0),
        "pinned_head_terms": s1.get("pinned_head_terms") or [],
        "blocked_pins": s1.get("blocked_pins") or [],
        "dropped_out_of_area": s1.get("dropped_out_of_area") or [],
        "geo_filter_off": bool(s1.get("geo_filter_off")),
        "dropped_ungrounded": s1.get("dropped_ungrounded") or [],
        "grounding_stood_down": bool(s1.get("grounding_stood_down")),
        "business_desc": s1.get("business_desc", ""),
        "site_pages_found": s1.get("site_pages_found", 0),
        "grid": s1.get("grid", False),
        "services": s1.get("services", []),
        "service_volume": s1.get("service_volume", {}),
        "total_volume": s1.get("total_volume", None),
        "volume_error": s1.get("volume_error"),
        "volume_location": s1.get("volume_location"),
        "volume_source": s1.get("volume_source") or "google_ads",
        "state_missing": s1.get("state_missing", False),
        "grid_cities": s1.get("grid_cities", []),
        # stage1b_refine can UPGRADE this after reading the site (a storefront
        # is national demand even when the RZ tag missed it), so its answer
        # wins over the one resolved before the site was fetched.
        "national_demand": bool(s1.get("national_demand", nat_demand)),
        "national_demand_reason": s1.get("national_demand_reason") or nat_reason,
        "ecommerce_detected": bool(s1.get("ecommerce_detected")),
        "ecommerce_reason": s1.get("ecommerce_reason") or "",
    })

@app.route("/api/metrics", methods=["POST"])
@_json_error_guard
def api_metrics():
    """Step 2 — competitive adder from head-term bids. One search_volume call."""
    d = request.get_json(force=True)
    head    = [{"keyword": k} for k in d.get("head", [])]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    # phrase geos must be strippable so bare-term metrics resolve for
    # "managed it services south jersey" -> "managed it services"
    markets = primary_first(markets, d.get("primary_market"))
    markets = markets + [p.strip() for p in d.get("phrase_geos", []) if p and p.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    # Same national-demand basis Step 1 used, resolved the same way rather than
    # trusted from the client, so the two steps cannot disagree.
    nat, _nr = resolve_national_demand(
        industry=(d.get("industry") or ""),
        band=d.get("geo_scope", d.get("band", "")),
        manual=bool(d.get("national_demand")) or bool(d.get("ecommerce")))
    try:
        m3 = stage3_metrics(head, markets, state, national=nat,
                            industry=(d.get("industry") or ""))
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500
    return jsonify({"adder": m3["adder"], "score": m3["median_score"],
                    "adder_basis": m3.get("adder_basis"), "cpc_used": m3.get("cpc_used"),
                    "cpc_low_confidence": m3.get("cpc_low_confidence"),
                    "cpc_n_bids": m3.get("cpc_n_bids"),
                    "flat_adder": m3.get("flat_adder"),
                    "bid_source": m3.get("bid_source"),
                    "bid_ideas_error": m3.get("bid_ideas_error"),
                    "bid_labs_error": m3.get("bid_labs_error"),
                    "adder_blocked": m3.get("adder_blocked"),
                    "kd_suggested_adder": m3.get("kd_suggested_adder"),
                    "kd_score": m3.get("kd_score"),
                    "restricted_vertical": m3.get("restricted_vertical"),
                    "national_demand": nat,
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
@_json_error_guard
def api_rankings_submit():
    """Step 3, async mode — submit ALL rank lookups as DataForSEO tasks in one
    call. Task mode has no 30s wall: the platform ceiling only ever killed us
    because LIVE lookups block while Google is crawled. Tasks queue server-side
    and the frontend polls /api/rankings_collect until they land."""
    d = request.get_json(force=True)
    kws     = [k for k in d.get("keywords", []) if k]
    markets = [m.strip() for m in d.get("geo_values", []) if m.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    markets = primary_first(markets, d.get("primary_market"))
    top_n   = CFG["zero_ranking_top_n"]
    depth   = max(top_n, 10)
    nat, _r = resolve_national_demand(d.get("industry") or "",
                                      d.get("geo_scope") or d.get("band") or "",
                                      bool(d.get("national_demand")))
    loc     = rank_location(markets, state, nat)
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
@_json_error_guard
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
@_json_error_guard
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
    markets = primary_first(markets, d.get("primary_market"))
    top_n = CFG["zero_ranking_top_n"]
    nat, _r = resolve_national_demand(d.get("industry") or "",
                                      d.get("geo_scope") or d.get("band") or "",
                                      bool(d.get("national_demand")))
    loc = rank_location(markets, state, nat)
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
            _budget = int(CFG.get("rank_batch_budget_s") or 0) or max(20, REQUEST_BUDGET_S - 15)
            batch_deadline = time.time() + _budget
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

@app.route("/api/markets", methods=["POST"])
@_json_error_guard
def api_markets():
    """How many distinct MARKETS the entered geos actually cover.

    Separate question from add-on markets, and asked much earlier: this is
    "what does this footprint amount to", which decides the grid shape, the
    coverage percentages and the market count everything else is built on. It
    runs off bundled coordinates, so there is no API call and it can answer
    the moment the geos are typed rather than after a full build.
    """
    d = request.get_json(force=True) or {}
    mk = [m for m in (d.get("geo_values") or []) if m and m.strip()]
    state = (d.get("state") or "").strip()
    if not mk:
        return jsonify({"cities": 0, "markets": 0, "groups": [], "unlocated": []})
    groups, located, unlocated = group_by_distance(mk, state)
    named = []
    for g in sorted(groups, key=len, reverse=True):
        anchor = max(g, key=lambda m: city_size(m, state)) if len(g) > 1 else g[0]
        named.append({"anchor": anchor,
                      "members": [anchor] + [m for m in g if m != anchor],
                      "size": len(g)})
    return jsonify({
        "cities": len(mk),
        "markets": len(groups) + len(unlocated),
        "groups": named,
        "unlocated": unlocated,
        "radius": int(CFG.get("market_radius_miles", 25)),
        "located": len(located),
    })


@app.route("/api/addon_suggestion", methods=["POST"])
@_json_error_guard
def api_addon_suggestion():
    """Suggest an add-on market count from the assembled rank table.

    Its own route because it needs the WHOLE table, which only exists on the
    frontend after step 3 has looped its batches. No external calls — pure
    arithmetic on data the quote already holds.
    """
    d = request.get_json(force=True) or {}
    markets = [m.strip() for m in d.get("geo_values", []) if m and m.strip()]
    state = derive_state(markets, (d.get("state") or "").strip())
    out = recommend_addons(markets, state, d.get("table") or [],
                           site_locations=d.get("site_locations") or [],
                           site_pages_found=d.get("site_pages_found"),
                           metro_groups=d.get("metro_groups") or [],
                           city_volumes=d.get("city_volumes") or {})
    out["gbp_locations"] = d.get("gbp_locations")
    # Surface HOW the markets were counted. Four rounds of this were spent
    # guessing which branch ran because nothing on screen said (2026-08-03).
    out["grouped_by"] = d.get("grouped_by") or ""
    out["city_locs"] = d.get("city_locs") or {}
    out["service_areas"] = len(d.get("service_areas") or [])
    return jsonify(out)


@app.route("/api/price", methods=["POST"])
@_json_error_guard
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
                     ai_search=bool(d.get("ai_search")),
                     national_demand=bool(d.get("national_demand")),
                     geo_override=d.get("geo_override"),
                     addon_override=d.get("addon_override"))
    return jsonify({"anchor": p["anchor"], "adder": adder,
                    "national_demand": p.get("national_demand", False),
                    "national_demand_reason": p.get("national_demand_reason", ""),
                    "min_term_months": p.get("min_term_months"),
                    "zero_visibility": p.get("zero_visibility", False),
                    "extras_multiplier": p.get("extras_multiplier", 1.0),
                    "manual_geo": p.get("manual_geo", False),
                    "manual_addon": p.get("manual_addon", False),
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
@_json_error_guard
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
        "ecom_anchor_add": CFG.get("ecom_anchor_add", 0),
        "geo_pricing_mode": CFG.get("geo_pricing_mode", "pct"),
        "geo_pct_tiers": CFG.get("geo_pct_tiers", []),
        "geo_pct_default": CFG.get("geo_pct_default", 60),
        "geo_bundle_discount_pct": CFG.get("geo_bundle_discount_pct", 5),
        "min_term_months": CFG.get("min_term_months", 6),
        "min_term_months_zero_visibility": CFG.get("min_term_months_zero_visibility", 12),
        "zero_visibility_pct_not_ranking": CFG.get("zero_visibility_pct_not_ranking", 90),
        "nationwide_service_extras": CFG.get("nationwide_service_extras", 1.0),
        "vol_add_ramp": CFG.get("vol_add_ramp", [40, 60]),
        # Shown so a model change is visible rather than silent: an unpinned
        # alias can move under you and quietly reshape every keyword list.
        # Pin it with the CLAUDE_MODEL env var.
        "claude_model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        "claude_model_pinned": model_is_snapshot(os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")),
        "source_fingerprint": SOURCE_FP,
        "dfs_timeout": DFS_TIMEOUT,
        "request_budget_s": REQUEST_BUDGET_S,
        "pin_head_terms": CFG.get("pin_head_terms", 3),
        "pin_min_volume": CFG.get("pin_min_volume", 300),
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
@_json_error_guard
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
        # geo_pct_tiers: [[min_pct_not_ranking, geo_pct_of_seo], ...] high-to-low
        if "geo_pct_tiers" in d and isinstance(d["geo_pct_tiers"], list):
            gt = []
            for pair in d["geo_pct_tiers"]:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    gt.append([float(pair[0]), float(pair[1])])
            gt.sort(key=lambda t: t[0], reverse=True)
            CFG["geo_pct_tiers"] = gt
        if "vol_add_ramp" in d and isinstance(d["vol_add_ramp"], list) and len(d["vol_add_ramp"]) == 2:
            CFG["vol_add_ramp"] = [float(d["vol_add_ramp"][0]), float(d["vol_add_ramp"][1])]
        if "geo_pricing_mode" in d and d["geo_pricing_mode"] in ("pct", "card"):
            CFG["geo_pricing_mode"] = d["geo_pricing_mode"]
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
                            ("ecom_anchor_add", int),
                            ("pin_head_terms", int),
                            ("pin_min_volume", int),
                            ("geo_pct_default", float),
                            ("geo_bundle_discount_pct", float),
                            ("min_term_months", int),
                            ("min_term_months_zero_visibility", int),
                            ("zero_visibility_pct_not_ranking", float),
                            ("nationwide_service_extras", float)]:
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
@_json_error_guard
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
@_json_error_guard
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

def _trim_serp_image(png_bytes, max_h=None, blank_thresh=245, collapse_over=110, keep=36, aspect=None):
    """Collapse tall near-blank horizontal bands in a SERP screenshot (the AI
    Mode 'Thinking' placeholder leaves hundreds of empty pixels), optionally
    cap the final height, and re-encode as JPEG. Blank detection samples a
    40px-wide downscale per row, so it's fast even on 8000px pages."""
    import io
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = im.size
    # Dark-mode guard: DFS occasionally renders Google in dark theme. Detect a
    # dark page background (sample corners + center-top) and convert to a
    # light-mode look: invert luminance, then rotate hue 180\u00b0 so brand
    # colors (blue links, logo) come back approximately correct.
    _pts = [(4, 4), (w - 5, 4), (w // 2, 4), (4, min(h - 5, 200))]
    if sum(sum(im.getpixel(p)) for p in _pts) / (len(_pts) * 3) < 100:
        inv = ImageOps.invert(im)
        hsv = inv.convert("HSV")
        ch = list(hsv.split())
        ch[0] = ch[0].point(lambda x: (x + 128) % 256)
        im = Image.merge("HSV", ch).convert("RGB")
        # White-point fix: the inverted background is light grey; scale so it
        # reads as true white without blowing out text or brand colors.
        bg = max(1, max(sum(im.getpixel(p)) // 3 for p in _pts))
        if bg < 250:
            scale = 255.0 / bg
            im = im.point(lambda x: min(255, int(x * scale)))
    strip = im.resize((40, h))
    px = strip.load()
    blank = []
    for y in range(h):
        row_ok = True
        for x in range(40):
            r, g, b = px[x, y]
            if r < blank_thresh or g < blank_thresh or b < blank_thresh:
                row_ok = False
                break
        blank.append(row_ok)
    segments, y = [], 0
    while y < h:
        if blank[y]:
            start = y
            while y < h and blank[y]:
                y += 1
            run = y - start
            if run > collapse_over:
                segments.append((start, start + keep))       # keep a sliver
            else:
                segments.append((start, y))
        else:
            start = y
            while y < h and not blank[y]:
                y += 1
            segments.append((start, y))
    new_h = sum(b - a2 for a2, b in segments)
    out = Image.new("RGB", (w, new_h), (255, 255, 255))
    cy = 0
    for a2, b in segments:
        band = im.crop((0, a2, w, b))
        out.paste(band, (0, cy))
        cy += b - a2
    # Right-edge crop (post-collapse, so blank rows can't dilute the sample):
    # sample 128 row-bands per column; a column counts as content if ANY band
    # is non-blank. Mirror the left margin so the crop looks intentional.
    w, h2 = out.size
    strip2 = out.resize((w, 128))
    spx = strip2.load()
    def _col_has_content(x):
        for yy in range(128):
            r, g, b = spx[x, yy]
            if r < blank_thresh or g < blank_thresh or b < blank_thresh:
                return True
        return False
    right = w - 1
    while right > 0 and not _col_has_content(right):
        right -= 1
    left_margin = 0
    while left_margin < w - 1 and not _col_has_content(left_margin):
        left_margin += 1
    new_w = min(w, right + 1 + max(24, left_margin))
    if 0 < new_w < w * 0.97:
        out = out.crop((0, 0, new_w, h2))
    if aspect:
        # Enforce a fixed aspect ratio (e.g. "3:2" landscape) for consistent
        # proposal layout: crop the bottom if too tall, pad white if too short.
        try:
            aw, ah = (float(x) for x in str(aspect).split(":"))
        except (ValueError, TypeError):
            aw = ah = 0
        if aw > 0 and ah > 0:
            w2, h2 = out.size
            target = int(round(w2 * ah / aw))
            if h2 > target:
                out = out.crop((0, 0, w2, target))
            elif h2 < target:
                canvas = Image.new("RGB", (w2, target), (255, 255, 255))
                canvas.paste(out, (0, 0))
                out = canvas
    if max_h and out.size[1] > max_h:
        out = out.crop((0, 0, out.size[0], max_h))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=85)
    return buf.getvalue()


@app.route("/api/serp_fetch", methods=["POST"])
@_json_error_guard
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
        content, mime = img.content, "image/png"
        if d.get("trim"):
            # Rep-tool proposal shots: collapse blank bands (AI-overview
            # placeholder renders as a huge white gap), cap height for a
            # landscape-ish exhibit, JPEG to keep saved-quote payloads sane.
            try:
                content = _trim_serp_image(content, max_h=int(d.get("max_h") or 0) or None,
                                           aspect=d.get("aspect"))
                mime = "image/jpeg"
            except Exception as _te:
                print(f"[serp trim] skipped: {_te}")
        b64 = base64.b64encode(content).decode()
        return jsonify({"ready": True, "keyword": keyword,
                        "data_url": f"data:{mime};base64,{b64}"})
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
_LOCATIONS_CACHE = {"names": None, "codes": None}


def us_location_code(name):
    """Numeric Google Ads location_code for a DataForSEO location_name.

    NOT usable for Labs endpoints — Labs keys off its own location set and
    rejects Google Ads city codes ("40501 Invalid Field: 'location_code'").
    Kept for Google-Ads-side lookups. Returns None when unrecognised.
    """
    if not name:
        return None
    if _LOCATIONS_CACHE.get("codes") is None:
        try:
            data = dfs_get("/keywords_data/google_ads/locations/us")
            items = (data.get("tasks") or [{}])[0].get("result") or []
            _LOCATIONS_CACHE["codes"] = {
                (it.get("location_name") or "").strip().lower(): it.get("location_code")
                for it in items
                if it.get("location_name") and it.get("location_code")}
        except Exception:
            _LOCATIONS_CACHE["codes"] = {}
    return _LOCATIONS_CACHE["codes"].get(str(name).strip().lower())

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
@_json_error_guard
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
- NEVER add "near me", "nearby", "closest" or any other proximity phrase. Every term is crossed with
  a city later, and "mattress store near me acworth ga" is not a phrase any human types — "near me"
  IS the location. Write the bare service and let the grid add the place.
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
            out = {}
            for k, v in parsed.items():
                if not (isinstance(v, str) and v.strip()):
                    out[k] = None
                    continue
                # Strip proximity here too. The prompt asks; this guarantees.
                t = clean_kw(strip_proximity(v.strip().lower())).strip()
                out[k] = t or None
            return out
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
@_json_error_guard
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
                r, insecure = get_client_site(
                    url, timeout=10, allow_redirects=True,
                    headers={"User-Agent": ua,
                             "Accept": "text/html,application/xhtml+xml",
                             "Accept-Language": "en-US,en;q=0.9"})
                candidate = r.text[:800_000]
                nlinks = candidate.lower().count("<a")
                diag.append(f"{url} [{ua_name}] -> HTTP {r.status_code}, {nlinks} links"
                            + (" (TLS chain incomplete — read without verifying)"
                               if insecure else ""))
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
        _fe = str(fetch_err)
        if "CERTIFICATE_VERIFY_FAILED" in _fe or "SSLError" in _fe:
            _fe = ("the site's HTTPS certificate chain is incomplete, and reading it "
                   "without verification also failed. Browsers hide this; a server does "
                   "not. Type the services into Keyword / Vertical Focus by hand — "
                   "nothing else in the quote depends on reading the site.")
        elif "Max retries" in _fe or "timed out" in _fe.lower():
            _fe = ("the site didn't respond in time — it may be blocking automated "
                   "requests. Enter the services by hand and continue.")
        return jsonify({"error": f"Couldn't fetch the site: {_fe}",
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
@_json_error_guard
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
@_json_error_guard
def api_quotes_list():
    if not storage.enabled():
        return jsonify({"enabled": False, "quotes": []})
    search = (request.args.get("q") or "").strip()
    tool = (request.args.get("tool") or "seo").strip()
    return jsonify({"enabled": True, "quotes": storage.list_quotes(search, tool)})

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
@_json_error_guard
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
@_json_error_guard
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
@_json_error_guard
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
    """Same template as the owning tool; the frontend sees /review/ in the
    path and switches to read-only review mode."""
    tool = "seo"
    if storage.enabled():
        tool = storage.get_tool_by_token(token) or "seo"
    return render_template("reputation.html" if tool == "rep" else "index.html", build=BUILD_STR)

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
    """Edit deep-link: opens the owning tool with this saved quote loaded,
    ready to revise. Version history makes collaborative edits safe — every
    save snapshots the prior state."""
    tool = "seo"
    if storage.enabled():
        q = storage.load_quote(qid)
        if q:
            tool = (q.get("tool") if isinstance(q, dict) else None) or "seo"
    return render_template("reputation.html" if tool == "rep" else "index.html", build=BUILD_STR)

@app.route("/api/quotes/version/<int:vid>", methods=["DELETE"])
@_json_error_guard
def api_quotes_version_delete(vid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    storage.delete_version(vid)
    return jsonify({"ok": True})

@app.route("/api/quotes/<int:qid>", methods=["DELETE"])
@_json_error_guard
def api_quotes_delete(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    storage.delete_quote(qid)
    return jsonify({"ok": True})

@app.route("/api/quotes/<int:qid>/versions", methods=["GET"])
@_json_error_guard
def api_quotes_versions(qid):
    if not storage.enabled():
        return jsonify({"error": "Saving isn't enabled."}), 400
    return jsonify({"versions": storage.list_versions(qid)})

@app.route("/api/quotes/version/<int:vid>", methods=["GET"])
@_json_error_guard
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
@_json_error_guard
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
@_json_error_guard
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
@_json_error_guard
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
@_json_error_guard
def api_rep_scan_locations():
    """Google Business location discovery (instant, database-backed)."""
    d = request.get_json(force=True)
    brand = (d.get("brand") or "").strip()
    if not brand:
        return jsonify({"error": "Brand name required."}), 400
    try:
        return jsonify(rep_scan.scan_locations(brand, domain=(d.get("domain") or "")))
    except Exception as e:
        return jsonify({"error": f"Location scan failed: {e}"}), 502

@app.route("/api/rep_reviews_submit", methods=["POST"])
@_json_error_guard
def api_rep_reviews_submit():
    """Queue worst-first review pulls for selected locations (priority ~1min)."""
    d = request.get_json(force=True)
    pids = [p for p in (d.get("place_ids") or []) if p]
    if not pids:
        return jsonify({"error": "No locations selected."}), 400
    try:
        return jsonify(rep_scan.reviews_submit(
            pids, int(d.get("depth") or rep_pricing.SCAN_SETTINGS["review_pull_depth"])))
    except Exception as e:
        return jsonify({"error": f"Review submit failed: {e}"}), 502

@app.route("/api/rep_reviews_collect", methods=["POST"])
@_json_error_guard
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
    return render_template("reputation.html", build=BUILD_STR)

@app.route("/api/rep_config", methods=["GET"])
@_json_error_guard
def api_rep_config_get():
    """Expose the rep-tool tunables for the pricing panel — mirror of the
    SEO tool's /api/config."""
    rc = rep_pricing.REP_CFG
    return jsonify({
        "review_margin_pct": rc["review_removal"]["default_margin_pct"],
        "review_brackets": rc["review_removal"]["brackets"],
        "site_brackets": rc["article_removal"]["brackets"],
        "site_premium_per": rc["article_removal"]["premium_per"],
        "bundle": {k: rep_pricing.SEARCH_BUNDLE[k]
                   for k in ("supp_base", "as_base", "comp_per_1k", "floor", "cap")},
        "shield_monthly": rc["shield"]["monthly_hard"],
        "shield_per_extra_location": rc["shield"]["per_extra_location_hard"],
        "geo": {p: rep_pricing.GEO[p]["monthly"] for p in ("setup", "scale")},
        "bundle_discount_pct": rc["bundle"]["recurring_discount_pct"],
        "internal_cost_pct": rep_pricing.INTERNAL_COST_PCT["pct"],
        "review_pull_depth": rep_pricing.SCAN_SETTINGS["review_pull_depth"],
    })

@app.route("/api/rep_config", methods=["POST"])
@_json_error_guard
def api_rep_config_set():
    """Apply edited constants to the running session (not persisted — a
    restart reverts to file defaults). Same live-tuning model as the SEO tool."""
    d = request.get_json(force=True)
    rc = rep_pricing.REP_CFG
    try:
        if "review_margin_pct" in d:
            rc["review_removal"]["default_margin_pct"] = min(0.90, max(0.0, float(d["review_margin_pct"])))
        if "review_brackets" in d and isinstance(d["review_brackets"], list):
            for i, b in enumerate(d["review_brackets"]):
                if i < len(rc["review_removal"]["brackets"]) and "hard" in b:
                    rc["review_removal"]["brackets"][i]["hard"] = float(b["hard"])
        if "site_brackets" in d and isinstance(d["site_brackets"], list):
            for i, b in enumerate(d["site_brackets"]):
                if i < len(rc["article_removal"]["brackets"]) and "per" in b:
                    rc["article_removal"]["brackets"][i]["per"] = int(float(b["per"]))
        if "site_premium_per" in d:
            rc["article_removal"]["premium_per"] = int(float(d["site_premium_per"]))
        if "bundle" in d and isinstance(d["bundle"], dict):
            for k in ("supp_base", "as_base", "comp_per_1k", "floor", "cap"):
                if k in d["bundle"]:
                    rep_pricing.SEARCH_BUNDLE[k] = int(float(d["bundle"][k])) if k != "comp_per_1k" else float(d["bundle"][k])
        if "shield_monthly" in d:
            rc["shield"]["monthly_hard"] = int(float(d["shield_monthly"]))
        if "shield_per_extra_location" in d:
            rc["shield"]["per_extra_location_hard"] = int(float(d["shield_per_extra_location"]))
        if "geo" in d and isinstance(d["geo"], dict):
            for p in ("setup", "scale"):
                if p in d["geo"]:
                    rep_pricing.GEO[p]["monthly"] = int(float(d["geo"][p]))
        if "bundle_discount_pct" in d:
            rc["bundle"]["recurring_discount_pct"] = min(0.9, max(0.0, float(d["bundle_discount_pct"])))
        if "internal_cost_pct" in d:
            rep_pricing.INTERNAL_COST_PCT["pct"] = min(1.0, max(0.0, float(d["internal_cost_pct"])))
        if "review_pull_depth" in d:
            rep_pricing.SCAN_SETTINGS["review_pull_depth"] = min(4490, max(10, int(float(d["review_pull_depth"]))))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": f"Config apply failed: {e}"}), 400

@app.route("/api/rep_quote", methods=["POST"])
@_json_error_guard
def api_rep_quote():
    d = request.get_json(force=True)
    try:
        return jsonify(rep_pricing.build_rep_quote(d))
    except Exception as e:
        return jsonify({"error": f"Quote build failed: {e}"}), 500

@app.route("/api/rep_volume", methods=["POST"])
@_json_error_guard
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
