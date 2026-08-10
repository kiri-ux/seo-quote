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


def source_file_hashes():
    """Per-file hash for every fingerprinted file.

    The combined `src` hash answers "is this the build I was given" and nothing
    else. When it disagrees it cannot say WHICH file failed to land, so a handover
    turns into re-uploading everything and hoping — twice, on 2026-08-10, on a
    one-file change that was correct in the zip and never reached the app.
    Six hashes make the stale file obvious at a glance.
    """
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    for rel in FINGERPRINT_FILES:
        path = os.path.join(here, rel)
        try:
            with open(path, "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
            out.append({"file": rel,
                        "sha": hashlib.sha256(data).hexdigest()[:6],
                        "bytes": len(data),
                        "mtime": _dt.datetime.utcfromtimestamp(
                            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%SZ")})
        except Exception as e:
            out.append({"file": rel, "sha": "MISSING", "bytes": 0,
                        "mtime": "", "error": str(e)[:80]})
    return out


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
    # Now a MARGIN OF GROSS (agency share of retail), matching rep_pricing and
    # the SSG/Vici grid: retail = hard / (1 - margin). Was a markup-on-cost
    # (x1.35 = a 25.9% margin). Retail output at 35% is unchanged.
    "default_markup_pct": 35,
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
    # Campaign goals that flip the national-demand switch. See
    # GOAL_NATIONAL_DEMAND — editable here so the list can be widened without a
    # deploy. Matched case-insensitively against the exact order-form option.
    "goal_national_demand": ["Online Sales"],
    # Two clusters count as ONE region if any city in one is within this many
    # miles of any city in the other. Wider than market_radius_miles on purpose:
    # 25 miles is "same market", 60 is "same trade area".
    "scope_join_radius_miles": 60,
    # A service name below this many monthly searches (summed across the
    # client's markets) is treated as a phrase nobody types, and is replaced by a
    # higher-volume term from the operator's own list in the same topic. Set to 0
    # to switch the check off.
    "service_min_volume": 30,
    "service_max_swaps": 3,
    # UPGRADE pass. A service that clears the floor is still replaced when an
    # unused term from the operator's own list, in the SAME topic, measures at
    # least this many times more. 10x is deliberately steep: it only fires when
    # the alternative is in a different league, never on a close call, so a
    # deliberate service choice isn't second-guessed over noise. 0 turns it off.
    "service_upgrade_ratio": 10,
    # How much a STORE-INTENT term ("ski shop") outweighs a product term
    # ("outdoor furniture") of the same size when ordering the tier columns. A
    # multiplier, not a veto: 3 means a product term must carry 3x the demand to
    # take a slot ahead of a shop term. 1 = order on raw volume only.
    "store_intent_tier_boost": 3.0,
    # How many unused seed terms to measure as replacement candidates. Each one
    # adds a keyword to the existing per-city volume calls. Spread round-robin
    # across topics, shortest term first, so every product line gets measured.
    "service_candidate_cap": 21,
    # TIER MIX, measured off eight real BE proposals (303 terms, 2026-08-07)
    # rather than assumed. His splits are PROPORTIONAL, not fixed counts, and
    # they move with the client:
    #
    #   Rockingham Insurance   99 terms   39/40/20   ->  39% / 40% / 20%
    #   Keller Builds          64         16/24/24   ->  25% / 38% / 38%
    #   Waytek                 30          5/12/13   ->  17% / 40% / 43%
    #   Red Shoes              30          7/ 2/21   ->  23% /  7% / 70%
    #   PA Dental Excellence   20          6/10/ 4   ->  30% / 50% / 20%
    #   Nob Hill Dental        20          6/10/ 4   ->  30% / 50% / 20%
    #   Visit Central PA       20          5/ 9/ 6   ->  25% / 45% / 30%
    #   Media Venue            20          6/ 7/ 7   ->  30% / 35% / 35%
    #   -------------------------------------------------------------
    #   TOTAL                 303         90/114/99  ->  30% / 38% / 33%
    #
    # The old fixed "3 ultra / 6 competitive / rest is long tail" produced
    # 15% / 30% / 55% on a 20-term list — ultra half what BE writes, long tail
    # nearly double. Proportions travel across list sizes; counts do not.
    "tier_mix": {"ultra": 0.30, "competitive": 0.38, "long_tail": 0.32},
    # Hard counts kept as an escape hatch. Null -> derive from tier_mix; an
    # integer pins that bucket regardless of list length.
    "ultra_bucket_size": None,
    "competitive_bucket_size": None,
    # BE's lists run 20-99 terms (median 25). A flat cap of 20 was his FLOOR
    # applied as a ceiling — it would have truncated Rockingham by 79 terms.
    "list_cap": 60,
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
    # When a city needs no ", ST" in the keyword. Brendan writes "adhd treatment
    # san diego" but "auto insurance alexandria va" — the test is whether the
    # name is unmistakable on its own. It used to be "is this city in the
    # CITY_STATE lookup table", which is a city->state map, not a list of
    # metros: it holds Farragut (1 ZIP) and Maryville (4), so one grid built
    # "junk removal farragut" beside "junk removal clinton tn" (2026-08-10).
    # Measured instead: a big place that also owns its own name nationally.
    # These two numbers reproduce every example in the sample proposals —
    # Knoxville 31/.82 and San Diego 81/.99 pass, Alexandria VA 23/.57 does not.
    # National monthly searches the bare service terms must clear before the tool
    # will say "this looks national". Below it, zero local volume is just a thin
    # vertical and says nothing about the frame.
    "frame_national_min": 200,
    # Monthly national searches an acronym must clear to be offered as a seed.
    # Below it, it is an internal code rather than something buyers type.
    "acronym_min_volume": 20,
    # A bare acronym carrying this many times its qualified sibling's volume is
    # probably being searched for a different meaning. 8x is well clear of the
    # 1.5x a genuinely owned term shows and well under the 72x/147x of a
    # collision. Only applied to acronyms above acronym_collision_min_volume,
    # since a small number proves nothing either way.
    "acronym_collision_ratio": 8.0,
    "acronym_collision_min_volume": 100,
    # Monthly searches a proposed replacement term must clear to be offered.
    "replacement_min_volume": 20,
    "metro_no_suffix_zips": 25,
    "metro_no_suffix_share": 0.6,
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


def home_state(markets, state=""):
    """The state the client actually operates in — the one most of their
    markets sit in. Not the same question as "which market has most demand"."""
    counts = {}
    for m in (markets or []):
        st = market_state(m, state)
        if st:
            counts[st] = counts.get(st, 0) + 1
    if not counts:
        return (state or "").strip()
    top = max(counts.values())
    # Ties break on input order: the partner types the client's own town first.
    for m in (markets or []):
        st = market_state(m, state)
        if st and counts.get(st) == top:
            return st
    return ""


def measure_first(markets, state="", primary=""):
    """Order markets for LOCALISED MEASUREMENT — rank checks and bid lookups.

    primary_first() answers "where is the most demand", which is the right
    question for scoping a campaign and the wrong one for measuring a client.
    Ski Barn's markets were Wayne / Paramus / Shrewsbury / Lawrenceville NJ plus
    New York City: NYC carries an order of magnitude more demand, so it became
    the primary and the rank check asked whether a New Jersey ski shop outranks
    Manhattan. It does not, and cannot — 0/20, largest zero-ranking uplift
    (2026-08-07). Their own agency's report says as much: "NYC is a tracked
    market but the client's locations are all in NJ."

    So measurement stays inside the HOME state — the state most of the markets
    sit in — and picks the highest-demand market there. A genuinely multi-state
    client (no state holds a majority) falls back to primary_first unchanged.
    """
    mk = primary_first(markets, primary)
    # Measure in a TOWN, not a county. Both are valid Google locations, but a
    # county SERP is a wider net than the client competes in, and the entered
    # list often leads with counties simply because that is the order someone
    # types a service area. Junk Bee Gone's first ten entries were counties, so
    # rankings were measured county-wide. (2026-08-10)
    if any(county_key(m, state) for m in mk) and any(not county_key(m, state) for m in mk):
        mk = ([m for m in mk if not county_key(m, state)]
              + [m for m in mk if county_key(m, state)])
    hs = home_state(mk, state)
    if not hs:
        return mk
    inside = [m for m in mk if market_state(m, state) == hs]
    if not inside or len(inside) == len(mk):
        return mk
    # Majority test: one outlier market must not be able to move the anchor,
    # but a real 50/50 two-state footprint keeps the demand ordering.
    if len(inside) * 2 <= len(mk):
        return mk
    return inside + [m for m in mk if m not in inside]


# Strings that arrive in the markets list but are not places. They come from
# imported reports: a ranking table's market column carries "near me" rows
# because the agency tracked "junk removal near me" as its own row, and the
# importer added it as a market like any other.
#
# One of these reaching the front of the list is not cosmetic. loc_string takes
# markets[0], so "near me, TN" became the location_name on every SERP and
# volume call — a location Google has never heard of. Junk Bee Gone was measured
# "in near me, Tennessee", scored 0/35, and drew the largest zero-ranking uplift
# in the table. (2026-08-10)
_NON_PLACE_GEOS = {
    "near me", "nearme", "near by", "nearby", "close to me", "around me",
    "local", "locally", "local area", "my area", "your area", "the area",
    "area", "areas", "surrounding", "surrounding area", "surrounding areas",
    "nationwide", "national", "nation", "usa", "u.s.", "u.s.a.", "us",
    "united states", "america", "statewide", "state", "everywhere", "anywhere",
    "n/a", "na", "none", "no", "tbd", "tba", "various", "multiple", "all",
    "other", "others", "unknown", "blank", "total", "totals", "average",
    "overall", "keyword", "keywords", "market", "markets", "city", "cities",
    "<cityname>", "cityname", "city name", "xxx", "test",
}


def is_non_place_geo(m):
    """True if this entered geo is not a place at all.

    Tested on the bare name with any state suffix removed, because the importer
    qualifies everything: the pill reads "near me, TN".
    """
    s = re.sub(r"[‘’“”]", "", str(m or "")).strip().lower()
    s = re.sub(r"\s+", " ", s.strip(" .-—–\t"))
    if not s:
        return True
    if "," in s:
        head, tail = [p.strip() for p in s.rsplit(",", 1)]
        if tail in _abbrev_to_state() or tail in STATE_ABBREV:
            s = head
    return s in _NON_PLACE_GEOS


def usable_markets(markets):
    """The entered markets minus anything that isn't a place.

    Used wherever a market has to survive contact with a search API. Kept
    separate from the pill list on purpose — dropping the operator's own entry
    behind their back is worse than showing it and refusing to measure in it.
    """
    return [str(m).strip() for m in (markets or [])
            if str(m).strip() and not is_non_place_geo(m)]


def loc_string(markets, state):
    for m in usable_markets(markets) or []:
        city, st = parse_market(m, state)
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


# Cache for canonical_city_name — the nearest-point scan walks 42k ZIP rows, and
# loc_string is called on every lookup.
_CANON_CITY = {}


def canonical_city_name(city, st=""):
    """A DIFFERENT name for the same place, for when Google rejects the first.

    Google Ads has no location called "New York City" — its canonical name is
    "New York". None called "Lawrenceville, NJ" either; it is "Lawrence
    Township". So the name is wrong, not the place, and the old ladder jumped
    straight from a rejected city to its whole STATE — which is how a five-town
    New Jersey retailer ended up priced on New York statewide demand
    (2026-08-07).

    Order: drop a trailing "city", then a known alias, then the nearest name in
    the ZIP data at that exact point (both real cases resolve at 0.0 miles, so
    this is the same place relabelled rather than a neighbour).

    Returns "" when there is no alternative worth trying.
    """
    c = (city or "").strip().lower()
    key = (c, (st or "").strip().lower())
    if key in _CANON_CITY:
        return _CANON_CITY[key]

    cands = []
    if c.endswith(" city") and len(c.split()) > 1:
        cands.append(c[: -len(" city")].strip())
    for a in _CITY_ALIASES.get(c, []):
        if " " in a or len(a) > 3:          # skip 2-3 letter shorthand
            cands.append(a)

    out = ""
    abbr = (STATE_ABBREV.get((st or "").strip().lower(), "") or "").upper()
    idx = _zip_index()
    for cand in cands:
        if cand and cand != c and (not abbr or (cand, abbr) in idx):
            out = cand
            break
    if not out:
        # Nearest ZIP-data name at the same coordinates.
        pt = idx.get((c, abbr)) if abbr else None
        if pt is None:
            hits = [v for (cc, _s), v in idx.items() if cc == c]
            pt = hits[0] if len(hits) == 1 else None
        if pt:
            best = None
            for (cc, ss), p in idx.items():
                if abbr and ss != abbr:
                    continue
                if cc == c:
                    continue
                d = miles_between(pt, p)
                if best is None or d < best[0]:
                    best = (d, cc)
            # Reject an abbreviation of the name we already have. The ZIP data
            # carries "Phila" alongside "Philadelphia"; offering it to Google as
            # an alternative name is worse than the name that already works.
            if best and best[0] <= 2.0:
                cand = best[1]
                # Strict prefix test, no length tolerance. "Phila" is an
                # abbreviation of Philadelphia and "Los Angeles AFB" is a base
                # inside Los Angeles — neither is the city under another name.
                # This only gates the nearest-point scan; the explicit candidate
                # list above (drop trailing "city", alias map) is what carries
                # New York City -> New York, so that case is unaffected.
                prefix_of_each_other = c.startswith(cand) or cand.startswith(c)
                if not prefix_of_each_other:
                    out = cand
    _CANON_CITY[key] = out
    return out


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

    resolved_codes = {}
    renamed = {}

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
            rows = task0.get("result") or []
            # WHICH LOCATION ANSWERED. DataForSEO resolves a city it doesn't
            # carry up to a metro or state and returns THAT area's volume with
            # no error and no flag — Lawrenceville NJ reported 8,100/mo for
            # "outdoor furniture" against Paramus's 70 (2026-08-07). The only
            # trustworthy signal is the location_code echoed back; captured
            # defensively because it is not guaranteed to be present, and shown
            # rather than acted on until it proves reliable.
            code = None
            try:
                code = (task0.get("data") or {}).get("location_code")
                if code is None:
                    for it in rows:
                        if it.get("location_code") is not None:
                            code = it.get("location_code")
                            break
            except Exception:
                code = None
            return rows, code
        try:
            _rows, _code = call(loc)
            resolved_codes[city] = _code
            return _rows, loc
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
                # FIRST try the same place under the name Google actually uses.
                # Jumping straight to the state throws away the city entirely,
                # and for New York City that meant pricing on New York STATE.
                alt = canonical_city_name(market_city(city, state), city_st or state)
                if alt:
                    alt_loc = (f"{alt},{city_st},United States" if city_st
                               else (f"{alt},{state},United States" if state
                                     else f"{alt},United States"))
                    try:
                        _rows, _code = call(alt_loc)
                        resolved_codes[city] = _code
                        renamed[city] = alt
                        # Its own place, just spelled Google's way — so this is
                        # NOT a broader-area fallback and it counts in the total.
                        return _rows, loc
                    except Exception:
                        pass
                broader = (f"{city_st},United States" if city_st
                           else (f"{state},United States" if state else "United States"))
                _rows, _code = call(broader)
                resolved_codes[city] = _code
                return _rows, broader
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
                    results.append((city, rows, used_loc, was_fallback))
                    ok += 1
                except Exception as e:
                    errs.append(str(e))
    except Exception as e:
        return {}, {}, str(e)
    if not ok:
        return {}, {}, (errs[0] if errs else "no volume rows returned")
    # Aggregate deterministically:
    #   1. each effective location counts into the TOTAL exactly once;
    #   2. a location that is NOT the city's own never counts while any city did
    #      return its own figure. Previously only a "United States" fallback was
    #      excluded, so a STATEWIDE one was counted in full: Ski Barn's
    #      "outdoor furniture" total of 20,350/mo was New York statewide (12,100)
    #      plus New Jersey statewide (8,100) plus three real towns (150), for a
    #      five-town New Jersey retailer — and that total drives the volume
    #      component of price and promoted the term to Ultra Competitive
    #      (2026-08-07). A town Google cannot locate must not contribute its
    #      whole state's demand.
    #   3. if NO city returned its own figure, broader locations count once each
    #      rather than pricing the client at zero demand — reported either way.
    own_data = [r for r in results if not r[3]]
    us_skipped = False
    broader_skipped = []
    if own_data:
        # Own-location results first so they claim their location before any
        # fallback that resolved to the same place.
        ordered = sorted(results, key=lambda r: (r[3], r[2] == "United States"))
    else:
        ordered = sorted(results, key=lambda r: r[2] == "United States")
    for city, rows, used_loc, was_fb in ordered:
        # DataForSEO tells us which location it ACTUALLY used for each city —
        # that is exact market identity, not an inference. Two cities resolving
        # to the same effective location are the same market, which is the
        # question the add-on count turns on. Inferring it from volume vectors
        # instead only worked where the geo-modified probe had volume, so it
        # failed silently in exactly the small rural markets where collapsing
        # matters most (2026-08-03).
        city_locs[city] = used_loc
        count_it = used_loc not in counted_locs
        if was_fb and own_data:
            # Not this city's location, and someone else's figures are real.
            count_it = False
            broader_skipped.append(city)
        if used_loc == "United States" and [r for r in results if r[2] != "United States"]:
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
    if broader_skipped:
        notes.append(
            "no city-level volume for " + ", ".join(sorted(set(
                c.strip() for c in broader_skipped)))
            + " — Google doesn't hold those as targetable locations, so a wider "
              "area answered. Shown per keyword but EXCLUDED from the pricing "
              "total, because a town's whole state is not that town's demand")
    if not own_data and fallback_cities:
        notes.append(
            "NO market returned volume of its own — every figure below is a "
            "wider area's, counted once each so the quote isn't priced at zero "
            "demand. Treat the volume component as an estimate")
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
    # Two cities sharing a location_code resolved to the SAME place, which means
    # at least one of them is not reporting its own demand.
    per_city["__location_codes__"] = {_bare_city(c, state): v
                                      for c, v in resolved_codes.items() if v is not None}
    # Which cities had NO volume of their own and were answered by a broader
    # location. Previously only mentioned inside the prose note, so the per-row
    # numbers showed a county/state/national figure as though it were the city's
    # — Lawrenceville NJ read 8,100/mo for "outdoor furniture" next to Paramus's
    # 70 (2026-08-07). Callers need this as data to mark those rows.
    # Normalised the same way per_city keys are — bare city, lowercase. Storing
    # the raw pill ("Lawrenceville, NJ") meant the grid rows, which carry the
    # bare city ("lawrenceville"), never matched and the flag never fired
    # (2026-08-07).
    per_city["__fallback_cities__"] = sorted({_bare_city(c, state) for c in fallback_cities})
    # The original pill text too, so a suggestion can be built from it.
    per_city["__fallback_markets__"] = sorted({str(c).strip() for c in fallback_cities})
    # Markets Google accepted only under a different name. Worth showing: the
    # figure is genuinely the city's, and the operator may want the pill to match.
    per_city["__renamed__"] = dict(renamed)
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
# CAMPAIGN GOAL — verbatim from the adtini order form. Like the RZ industry
# list, this ARRIVES with the order; the demo carries a selector so it can be
# exercised. Added 2026-08-05 after a Ski Barn quote priced a New Jersey ski
# retailer on national demand: the goal would have said in-store sales, and the
# contradiction was sitting there unread.
GOAL_OPTIONS = [
    "In-Store Sales", "B2B Sales", "Information Requests",
    "Branding & Awareness", "Mobile App Download", "Website Traffic",
    "Leads/Form Fillouts", "Online Sales", "Phone Calls",
    "Job Recruitment", "Event Attendance",
]

# What each goal implies about WHERE demand lives. Deliberately three-valued:
# "" means the goal genuinely doesn't say, and guessing would be worse than
# staying quiet. Used to CONTRADICT the operator's scope, never to override it —
# the goal is a statement of intent, not a pricing input, and there is no
# calibration data tying goals to price.
GOAL_SCOPE = {
    "In-Store Sales":       "local",      # footfall has an address
    "Phone Calls":          "local",      # service businesses take local calls
    "Event Attendance":     "local",      # an event happens somewhere
    "Job Recruitment":      "local",      # roles are located
    "Information Requests": "",
    "Leads/Form Fillouts":  "",           # local trade or national B2B
    "Branding & Awareness": "",
    "Website Traffic":      "",
    "B2B Sales":            "national",
    "Online Sales":         "national",   # ecommerce sells everywhere
    "Mobile App Download":  "national",
}

# Goals an SEO keyword campaign is a poor instrument for. Not blocked — flagged,
# because the price would look like a retail campaign for work that isn't one.
GOAL_OFF_PATTERN = {"Mobile App Download", "Job Recruitment"}

# Goals that DO drive the national-demand switch (2026-08-07, operator request).
# Distinct from GOAL_SCOPE, which only ever warns: this set actually flips the
# volume pull. The reasoning is the same one that makes the markets veto correct
# — inferences lose to statements. A detected shopping cart is an inference about
# what a site can do; a goal of "Online Sales" is the client telling the order
# form what they are buying, so it ranks with the manual switch and an explicit
# Nationwide scope rather than with the RZ taxonomy.
#
# Deliberately NOT every GOAL_SCOPE "national" entry. "B2B Sales" maps national
# but a regional IT firm selling to businesses in three counties is a local
# campaign, and "Mobile App Download" is already flagged as off-pattern for SEO.
# Config key so the list can be widened without a deploy.
GOAL_NATIONAL_DEMAND = ["Online Sales"]


def goal_forces_national(goal):
    """Do the selected goals put the quote on national demand?

    Only when NOTHING selected is local. "Online Sales" alone is a national
    campaign; "In-Store Sales + Online Sales" is a shop that also ships, and the
    markets-veto reasoning applies — a client with premises is priced locally
    unless they say so outright (2026-08-09).
    """
    goals = goal_list(goal)
    if not goals:
        return ""
    want = {str(o).strip().lower()
            for o in (CFG.get("goal_national_demand") or GOAL_NATIONAL_DEMAND)}
    hits = [g for g in goals if g.strip().lower() in want]
    if not hits:
        return ""
    if any(GOAL_SCOPE.get(g, "") == "local" for g in goals):
        return ""            # a local goal is present — not a national campaign
    return " + ".join(hits)


def goal_list(goal):
    """Goals arrive as one string, now possibly several joined with ' | '."""
    raw = str(goal or "")
    parts = [p.strip() for p in raw.split("|")] if "|" in raw else [raw.strip()]
    return [p for p in parts if p]


def goal_scope(goal):
    """What the selected goals say about WHERE demand lives.

    With several goals, LOCAL wins: a client who picked "In-Store Sales" as well
    as "Online Sales" has premises, and pricing them on national demand quotes a
    campaign they didn't ask for. Only an all-national selection reads national.
    """
    scopes = {GOAL_SCOPE.get(g, "") for g in goal_list(goal)}
    if "local" in scopes:
        return "local"
    if "national" in scopes:
        return "national"
    return ""


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
        name = clean_kw(strip_placeholders(strip_proximity(
            _strip_markets((sd or "").lower(),
                           list(markets or []) + list(phrase_geos or []),
                           state)))).strip()
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


# Words that describe the SHAPE of a retail term rather than its subject. They
# appear across every topic a client sells, so clustering on them would merge
# "ski shop" with "bbq grill store" and report one topic where there are two.
_TOPIC_STOP = set("""shop shops store stores storefront outlet outlets retailer retailers
service services repair rental rentals sales sale supplier suppliers supply
best top cheap affordable local near me nearby quality premium discount
buy buying sell selling new used online cheapest price prices cost
and or the of for in on to with a an my your our
company companies co inc llc dealer dealers center centre centers
cityname city_name citystate locationname marketname statename clientname tbd
""".split())


def clean_seeds(seeds):
    """Normalise the operator's seed terms once, at the door.

    Seeds arrive from three places — typed, imported from a report, restored
    from a saved quote — and only the report path was being scrubbed. A saved
    Ski Barn quote still carried "bbq grill store <cityname>", so the
    placeholder became a TOPIC ("cityname — 24% of what you typed") and was
    handed its own services (2026-08-07). Cleaning here means every consumer
    downstream is clean: topic clustering, seed enforcement, grounding, grid.

    Order is preserved deliberately — the seed list is a priority list and
    enforce_seed_services fills the grid from the front.
    """
    out, seen = [], set()
    for s in (seeds or []):
        t = re.sub(r"\s+", " ", strip_placeholders(str(s or "").strip())).strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _topic_stem(t):
    """Crude stem, enough to make two spellings of one subject match.

    Plural AND gerund, because retail seed lists mix them freely: "skis" with
    "ski", "grills" with "grill", and — the one that split Ski Barn's snowboard
    topic in two — "snowboarding" with "snowboard".
    """
    t = (t or "").strip()
    if len(t) > 5 and t.endswith("ing"):
        stem = t[:-3]
        # "snowboarding" -> "snowboard"; "shopping" -> "shop" (doubled letter)
        if len(stem) > 3 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        if len(stem) > 3:
            return stem
    if len(t) > 3 and t.endswith("es") and t[-3] in "sxzh":
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _topic_tokens(text):
    """Subject words in a term, stemmed, with retail-shape words removed."""
    out = set()
    for w in re.split(r"[^a-z0-9]+", (text or "").lower()):
        if not w or w in _TOPIC_STOP:
            continue
        s = _topic_stem(w)
        if s and s not in _TOPIC_STOP and len(s) > 2:
            out.add(s)
    return out


def topic_clusters(seeds):
    """Group the operator's seed terms into TOPICS the client actually sells.

    Ski Barn entered 25 terms covering two businesses — ski/snowboard gear and
    BBQ/patio furniture — and got a 7-service grid that was entirely ski, so half
    the company was missing from its own proposal (2026-08-07). The service
    selector ranks by volume, and ski volume dwarfs patio volume, so the smaller
    topic loses every time no matter how many terms the operator types for it.

    Deliberately NOT an AI call. Topic coverage is a correctness guarantee, and a
    guarantee that depends on a non-deterministic call is not one — the same
    reasoning that put pin_head_services and enforce_seed_services in code. AI
    still gets to NAME the topics for display; this decides membership.

    Single-link on shared subject words after dropping retail-shape words.
    Returns [{"label":..., "seeds":[...], "tokens":set()}] biggest topic first.
    """
    def toks(s):
        return _topic_tokens(s)

    items = [(s, toks(s)) for s in (seeds or []) if str(s).strip()]
    items = [(s, t) for s, t in items if t]
    groups = []                       # [ {seeds:[], tokens:set()} ]
    for s, t in items:
        hits = [g for g in groups if g["tokens"] & t]
        if not hits:
            groups.append({"seeds": [s], "tokens": set(t)})
            continue
        keep = hits[0]
        keep["seeds"].append(s)
        keep["tokens"] |= t
        for g in hits[1:]:            # this seed bridges two groups — merge them
            keep["seeds"] += g["seeds"]
            keep["tokens"] |= g["tokens"]
            groups.remove(g)

    # Label each topic with its most frequent subject word.
    out = []
    for g in groups:
        counts = {}
        for s in g["seeds"]:
            for t in toks(s):
                counts[t] = counts.get(t, 0) + 1
        label = max(sorted(counts), key=lambda t: (counts[t], len(t))) if counts else ""
        out.append({"label": label, "seeds": g["seeds"], "tokens": g["tokens"],
                    "size": len(g["seeds"])})
    out.sort(key=lambda g: (-g["size"], g["label"]))
    return out


def service_topic(service, topics):
    """Which topic a chosen service belongs to, or '' if none claim it."""
    stems = _topic_tokens(service)
    best, best_n = "", 0
    for t in topics:
        n = len(stems & t["tokens"])
        if n > best_n:
            best, best_n = t["label"], n
    return best


def enforce_topic_coverage(services, seeds, max_services, cands=None, topics=None):
    """Every topic the operator typed must appear in the service list.

    Proportional to how much of the input each topic represents: a client whose
    seeds are 19 ski terms and 6 patio terms should not get 7 ski services and
    zero patio ones. Under-represented topics take slots from over-represented
    ones, cheapest slot first (the last service in the biggest topic).

    Returns (services, report) where report lists what was added and why, so the
    operator can see it happened rather than wondering why the list changed.
    """
    topics = topics if topics else topic_clusters(seeds)
    if len(topics) < 2 or not services:
        return services, []

    n_slots = min(int(max_services or len(services)), len(services)) or len(services)
    total_seeds = sum(t["size"] for t in topics) or 1

    # A topic only earns a guaranteed slot if the operator's input actually
    # weights it that far. One seed out of 29 is 3% of the input; handing it one
    # of 7 services would be 14% — over-rewarding a stray term at the expense of
    # the business. Topics below the threshold can still be picked on merit,
    # they just aren't protected.
    min_share = 1.0 / max(n_slots, 1)
    topics = [t for t in topics if t["size"] / total_seeds >= min_share * 0.75]
    if len(topics) < 2:
        return services, []

    quota = {}
    for t in topics:
        quota[t["label"]] = max(1, round(n_slots * t["size"] / total_seeds))
    # Trim quotas back to the slots available, smallest topics protected.
    while sum(quota.values()) > n_slots:
        big = max(quota, key=lambda k: quota[k])
        if quota[big] <= 1:
            break
        quota[big] -= 1

    out = [dict(x) for x in services]
    for x in out:
        x["_topic"] = service_topic(x.get("service", ""), topics)

    vol = {str(r.get("keyword", "")).lower(): (r.get("volume") or 0)
           for r in (cands or [])}
    report = []
    for t in topics:
        lab = t["label"]
        have = [x for x in out if x.get("_topic") == lab]
        need = quota.get(lab, 1) - len(have)
        if need <= 0:
            continue
        # Best unused seed from this topic, by measured volume then by order.
        used = {str(x.get("service", "")).lower() for x in out}
        pool = [s for s in t["seeds"] if str(s).lower() not in used]
        pool.sort(key=lambda s: (-vol.get(str(s).lower(), 0), t["seeds"].index(s)))
        for s in pool[:need]:
            donor_lab = max(quota, key=lambda k: len([x for x in out if x.get("_topic") == k])
                            - quota.get(k, 1))
            donors = [x for x in out if x.get("_topic") == donor_lab]
            if len(donors) <= quota.get(donor_lab, 1) or len(donors) <= 1:
                break
            drop = donors[-1]
            # Scrub on the way in. This function runs AFTER the last
            # scrub_services pass, so a seed added here is the only service that
            # never gets cleaned — which is exactly how "bbq grill store
            # cityname new york city ny" reached a grid on a build that already
            # stripped placeholders everywhere else (2026-08-07).
            name = clean_kw(strip_placeholders(strip_proximity(str(s)))).strip()
            if not name or name in {str(x.get("service", "")).lower() for x in out}:
                continue
            out.remove(drop)
            out.append({"service": name, "tier": drop.get("tier", "competitive"),
                        "_topic": lab})
            report.append({"added": name, "topic": lab,
                           "replaced": drop.get("service", ""),
                           "from_topic": donor_lab})
    for x in out:
        x.pop("_topic", None)
    return out, report


def tier_split(n_terms):
    """How many terms belong in each tier for a list of this length.

    Proportional, from CFG["tier_mix"] — measured off BE's own proposals, whose
    splits scale with list size rather than sitting at fixed counts. Returns
    (n_ultra, n_competitive, n_long_tail) summing exactly to n_terms, with at
    least one in each tier once there are three terms to spread (the proposal
    renders three columns and an empty one reads as an incomplete strategy).
    """
    n = max(int(n_terms or 0), 0)
    if n <= 0:
        return (0, 0, 0)
    mix = CFG.get("tier_mix") or {"ultra": 0.30, "competitive": 0.38, "long_tail": 0.32}
    order = ("ultra", "competitive", "long_tail")

    hard = {"ultra": CFG.get("ultra_bucket_size"),
            "competitive": CFG.get("competitive_bucket_size")}
    if hard["ultra"] is not None or hard["competitive"] is not None:
        u = int(hard["ultra"]) if hard["ultra"] is not None else round(n * mix["ultra"])
        c = int(hard["competitive"]) if hard["competitive"] is not None else round(n * mix["competitive"])
        u, c = max(0, min(u, n)), max(0, min(c, n - min(u, n)))
        return (u, c, max(0, n - u - c))

    # Largest-remainder so the three always sum to n exactly.
    raw = {t: n * float(mix.get(t, 0)) for t in order}
    base = {t: int(raw[t]) for t in order}
    left = n - sum(base.values())
    for t in sorted(order, key=lambda x: -(raw[x] - base[x]))[:max(0, left)]:
        base[t] += 1
    if n >= 3:
        # Top up any empty tier from the largest one.
        for t in order:
            if base[t] == 0:
                donor = max(order, key=lambda x: base[x])
                if base[donor] > 1:
                    base[donor] -= 1
                    base[t] += 1
    return (base["ultra"], base["competitive"], base["long_tail"])


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


# Template placeholders. Agency reports print a keyword row once with a token
# standing in for the city — "bbq grill store <cityname>" covers a dozen
# markets in one line. Imported verbatim, the token travels as a literal word:
# "bbq grill store cityname" reached the rank check and the proposal for Ski
# Barn (2026-08-07). Nobody searches it, so it is guaranteed not-ranking, which
# drags the zero-ranking ratio — and the price — up on a phantom. Angle
# brackets are optional because most readers strip them before we see them.
_PLACEHOLDER_RE = re.compile(
    r"[<\[\{\(]?\s*\b(cityname|city_name|city|citystate|location|locationname|"
    r"market|marketname|statename|state|region|geo|area|town|zip|zipcode|"
    r"keyword|kw|service|brand|clientname|client|xxx+|tbd)\b\s*[>\]\}\)]?",
    re.I)


def strip_placeholders(text):
    """Remove template tokens like <cityname> from an imported term.

    Only fires when the token is wrapped (<city>, [City], {city}) or is one of
    the tokens that is never a real search word on its own — "cityname",
    "clientname", "tbd". A BARE "city", "state" or "area" is left alone,
    because "city hall furniture" and "bay area movers" are real terms; those
    only strip inside brackets.
    """
    t = (text or "")

    def keep_or_drop(m):
        whole = m.group(0)
        word = (m.group(1) or "").lower()
        wrapped = whole[:1] in "<[{(" or whole[-1:] in ">]})"
        never_real = word in {"cityname", "city_name", "citystate", "locationname",
                              "marketname", "statename", "clientname", "zipcode", "tbd"} \
                     or word.startswith("xxx")
        return " " if (wrapped or never_real) else whole

    return re.sub(r"\s+", " ", _PLACEHOLDER_RE.sub(keep_or_drop, t)).strip()


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
        name = clean_kw(strip_placeholders(strip_proximity(
            _strip_markets((svc.get("service") or "").lower(),
                           strip_list, state)))).strip()
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
        term = clean_kw(strip_placeholders(strip_proximity(
            _strip_markets((c.get("keyword") or "").lower(), markets, state)))).strip()
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


# Term INTENT differs by goal even when the product list is identical. A ski
# retailer chasing footfall wants "ski shop", "ski rental near me", "ski shop
# open sunday"; the same retailer chasing ecommerce wants "buy ski jackets
# online", "ski jackets free shipping". Same catalogue, different keywords, and
# nothing was telling the model which campaign it was building (2026-08-05).
_GOAL_TERM_RULE = {
    "In-Store Sales": "GOAL IS IN-STORE SALES. Favour terms with shopping-trip "
        "intent — shop/store/rental/hire forms, and the categories someone "
        "drives to a shop for. Avoid pure ecommerce phrasing (\"free shipping\", "
        "\"online only\").",
    "Online Sales": "GOAL IS ONLINE SALES. Favour transactional ecommerce "
        "phrasing — buy/order/online/shipping forms and specific product "
        "categories a basket is built from. Avoid store-visit phrasing.",
    "Phone Calls": "GOAL IS PHONE CALLS. Favour terms someone searches when "
        "they want to speak to a person now — service + urgency forms, "
        "emergency/same-day/consultation variants.",
    "Leads/Form Fillouts": "GOAL IS LEAD FORMS. Favour consideration-stage "
        "service terms — quote/estimate/consultation/pricing variants.",
    "B2B Sales": "GOAL IS B2B SALES. Favour commercial and trade phrasing — "
        "wholesale/supplier/commercial/bulk/for-business variants, not consumer "
        "retail terms.",
    "Information Requests": "GOAL IS INFORMATION REQUESTS. Favour service and "
        "offering terms that lead to an enquiry, still never questions.",
    "Branding & Awareness": "GOAL IS BRANDING AND AWARENESS. Favour the broad "
        "category head terms the client wants to be known for, over narrow "
        "long-tail variants.",
    "Website Traffic": "GOAL IS WEBSITE TRAFFIC. Favour the highest-demand "
        "category terms the client can credibly rank for.",
    "Event Attendance": "GOAL IS EVENT ATTENDANCE. Favour event, tickets, "
        "schedule and things-to-do phrasing tied to the client's offering.",
    "Job Recruitment": "GOAL IS JOB RECRUITMENT. Favour jobs/careers/hiring "
        "phrasing for the roles this employer fills.",
    "Mobile App Download": "GOAL IS APP DOWNLOADS. Favour app, download and "
        "platform phrasing alongside the core category terms.",
}


def claude_expand_services(seeds, business_desc, site_pages, brand, domain,
                           candidates, max_services, n_cities=1, national=False,
                           goal=""):
    _goal_rule = _GOAL_TERM_RULE.get((goal or "").strip(),
                                     "No campaign goal supplied \u2014 pick the "
                                     "terms that best describe what the business "
                                     "sells, without assuming a channel.")
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
2g. {_goal_rule}
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


# ---- counties -------------------------------------------------------------
# A county is a legitimate thing to type: it is how a service business describes
# its footprint ("we cover Knox, Anderson and Blount"), it is a real DataForSEO
# location, and "bucks county roofing" is real search phrasing. But the ZIP
# index is keyed by CITY, so every county came back unplaceable — and
# api_markets counts each unplaceable entry as its own market.
#
# Junk Bee Gone: ten counties plus thirteen towns inside those same counties.
# The towns clustered correctly into four markets; the ten counties were counted
# separately on top, so 23 entries covering about six trade areas were reported
# as 16 markets. Everything downstream — grid shape, coverage percentages,
# add-on recommendation — is built on that number. (2026-08-10)
_COUNTY_INDEX = None
_CITY_COUNTY = None
_COUNTY_SUFFIX = re.compile(
    r"\s+(county|counties|parish|borough|census area|municipality)$")


def _county_indexes():
    """Build (county -> coords/zips/cities, city -> county) from the ZIP data."""
    global _COUNTY_INDEX, _CITY_COUNTY
    if _COUNTY_INDEX is not None:
        return _COUNTY_INDEX, _CITY_COUNTY
    cidx, ccidx = {}, {}
    try:
        import zipcodes
        acc = {}
        for r in zipcodes.list_all():
            if r.get("country") != "US":
                continue
            co = str(r.get("county") or "").strip().lower()
            st = str(r.get("state") or "").upper()
            if not co or not st:
                continue
            city = str(r.get("city") or "").strip().lower()
            e = acc.setdefault((co, st), {"pts": [], "cities": {}})
            e["cities"][city] = e["cities"].get(city, 0) + 1
            try:
                la, lo = float(r.get("lat") or 0), float(r.get("long") or 0)
            except (TypeError, ValueError):
                la = lo = 0
            if la and lo:
                e["pts"].append((la, lo))
            # Alternate ZIP names live in the same county as their host.
            for alt in (r.get("acceptable_cities") or []):
                a = str(alt).strip().lower()
                if a:
                    ccidx.setdefault((a, st), co)
            if city:
                ccidx[(city, st)] = co

        def _med(xs):
            xs = sorted(xs)
            n_ = len(xs)
            return xs[n_ // 2] if n_ % 2 else (xs[n_ // 2 - 1] + xs[n_ // 2]) / 2

        for k, e in acc.items():
            pts = e["pts"]
            cities = e["cities"]
            cidx[k] = {
                "coords": ((_med([a for a, _ in pts]), _med([b for _, b in pts]))
                           if pts else None),
                "zips": sum(cities.values()),
                "cities": cities,
                # The county's recognisable centre, for naming and for the one
                # case where a county has to stand in for a city.
                "principal": (max(cities, key=lambda c: (cities[c], -len(c)))
                              if cities else ""),
            }
    except Exception:
        app.logger.warning("zipcodes not available — county grouping is off")
    _COUNTY_INDEX, _CITY_COUNTY = cidx, ccidx
    return cidx, ccidx


def county_key(market, state=""):
    """('knox county', 'TN') for a market that names a county, else None."""
    city, st = parse_market(market, state)
    name = (city or "").strip().lower()
    if not _COUNTY_SUFFIX.search(name):
        return None
    name = _COUNTY_SUFFIX.sub(" county", name)
    abbr = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").upper()
    cidx, _cc = _county_indexes()
    if abbr and (name, abbr) in cidx:
        return (name, abbr)
    # No state given: accept a unique national match, never a guess. There are
    # Jefferson Counties in twenty-five states.
    hits = [k for k in cidx if k[0] == name]
    return hits[0] if len(hits) == 1 else None


def county_of(market, state=""):
    """The county a city sits in, as ('knox county','TN'), or None."""
    city, st = parse_market(market, state)
    c = (city or "").strip().lower()
    abbr = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").upper()
    _ci, ccidx = _county_indexes()
    if abbr:
        co = ccidx.get((c, abbr))
        return (co, abbr) if co else None
    hits = [(co, s) for (cc, s), co in ccidx.items() if cc == c]
    return hits[0] if len(hits) == 1 else None


def city_size(market, state=""):
    """Rough size proxy — how many ZIP codes a city has.

    Used to name a market after its recognisable centre. Sorting by latitude
    made a seven-town Blair County market read as "Claysburg +6" when anyone
    would call it Altoona.
    """
    city, st = parse_market(market, state)
    city = (city or "").strip().lower()
    abbr = STATE_ABBREV.get((st or state or "").strip().lower(), "").upper()
    # A county's size is its ZIP count, but it must never out-rank its own seat
    # when a group is being named: "Knoxville +4" is the market, "Knox County +4"
    # is a filing cabinet. Knox County has 35 ZIPs to Knoxville's 31, so scored
    # honestly the county would win. Halve it — enough to lose to its principal
    # city, enough to still beat a hamlet.
    ck = county_key(market, state)
    if ck:
        return (_county_indexes()[0].get(ck) or {}).get("zips", 0) // 2
    # The ZIP data uses its own names: "New York" not "New York City", "Lawrence
    # Township" not "Lawrenceville". An exact match alone scored New York City at
    # ZERO — the same as a town that doesn't exist — which made it read as the
    # smallest market in a five-market grid (2026-08-07).
    variants = [city]
    if city.endswith(" city") and len(city.split()) > 1:
        variants.append(city[: -len(" city")].strip())
    for alias in _CITY_ALIASES.get(city, []):
        variants.append(alias)
    try:
        import zipcodes
        rows = zipcodes.list_all()
        for v in variants:
            n = sum(1 for r in rows
                    if str(r.get("city", "")).lower() == v
                    and (not abbr or str(r.get("state", "")).upper() == abbr))
            if n:
                return n
        # Last resort: a township or borough carrying the same stem.
        stem = variants[-1]
        n = sum(1 for r in rows
                if str(r.get("city", "")).lower().startswith(stem + " ")
                and (not abbr or str(r.get("state", "")).upper() == abbr))
        return n
    except Exception:
        return 0


_NAME_SHARE = {}


def name_is_unmistakable(market, state=""):
    """True if this city name needs no state suffix to mean what it means.

    Two conditions, both measured off the bundled ZIP data: the place is big
    (ZIP count), and it is the dominant bearer of its name nationally. Clinton
    TN has 2 ZIPs out of 33 Clintons — a bare "clinton" is not this client's
    market. Knoxville has 31 of 38.
    """
    if county_key(market, state):
        return False                       # "knox county" always keeps its state
    city, st = parse_market(market, state)
    c = (city or "").strip().lower()
    abbr = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").upper()
    if not c or not abbr:
        return False
    if _NAME_SHARE.get("__built__") is None:
        # Built ONCE, not scanned per city: Render's free tier gives 0.1 vCPU
        # and a 16-market grid would otherwise walk 42,000 ZIP rows sixteen
        # times inside a request.
        counts = {}
        try:
            import zipcodes
            for r in zipcodes.list_all():
                cc = str(r.get("city", "")).lower()
                st_ = str(r.get("state", "")).upper()
                if not cc:
                    continue
                counts[(cc, st_)] = counts.get((cc, st_), 0) + 1
                counts[cc] = counts.get(cc, 0) + 1
        except Exception:
            pass
        _NAME_SHARE.clear()
        _NAME_SHARE.update(counts)
        _NAME_SHARE["__built__"] = True
    n_self = _NAME_SHARE.get((c, abbr), 0)
    n_all = _NAME_SHARE.get(c, 0)
    if not n_all:
        return False
    return (n_self >= int(CFG.get("metro_no_suffix_zips", 25))
            and (n_self / n_all) >= float(CFG.get("metro_no_suffix_share", 0.6)))


def name_share(market, state=""):
    """What fraction of US ZIPs carrying this city name are in THIS state.

    A distinctiveness score. Clinton TN holds 2 of 33 Clintons; Oak Ridge TN
    holds 2 of 7. Both are the same size in ZIP count, and this is what
    separates them when one has to stand for the market.
    """
    name_is_unmistakable(market, state)          # builds the index on first call
    city, st = parse_market(market, state)
    c = (city or "").strip().lower()
    abbr = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").upper()
    n_self = _NAME_SHARE.get((c, abbr), 0)
    n_all = _NAME_SHARE.get(c, 0)
    return (n_self / n_all) if n_all else 0.0


def market_anchor(group, state=""):
    """The one name that stands for a clustered market.

    Used by BOTH the market summary and the keyword grid, so the panel that says
    "Sevierville +3" and the keywords that get built cannot disagree — they did,
    and the grid crossed its terms with Pigeon Forge while the operator read
    Sevierville on screen. (2026-08-10)

    Towns before counties (a county describes coverage, not search), then size,
    then distinctiveness, then the shorter name, then alphabetical so the same
    input always gives the same answer.
    """
    g = [m for m in (group or []) if str(m).strip()]
    if not g:
        return ""
    towns = [m for m in g if not county_key(m, state)] or g
    return sorted(towns, key=lambda m: (-city_size(m, state), -name_share(m, state),
                                        len(str(m)), str(m).lower()))[0]


def city_coords(market, state=""):
    """Latitude/longitude for an entered market, or None."""
    city, st = parse_market(market, state)
    city = (city or "").strip().lower()
    if not city:
        return None
    # A county has coordinates too — the median of its ZIPs. Without this every
    # county entered was "couldn't place" and counted as a market of its own.
    ck = county_key(market, state)
    if ck:
        e = _county_indexes()[0].get(ck) or {}
        if e.get("coords"):
            return e["coords"]
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


def is_state_geo(m):
    """True if this targeting area is a whole STATE, not a market in it.

    "california" as a targeting area is unplaceable, so it was counted as its own
    market and reported as "couldn't place california" — which reads like a data
    gap rather than what it is: a state entered where a city belongs. Its cities
    are usually in the list already, so it is also double coverage. (2026-08-10)
    """
    t = re.sub(r"\s+", " ", str(m or "").strip().lower())
    if not t:
        return False
    if "," in t:
        head, tail = [p.strip() for p in t.rsplit(",", 1)]
        # "Austin, TX" is a city; only a bare state name or "Texas, TX" counts.
        if tail in _abbrev_to_state() or tail in STATE_ABBREV:
            t = head
    return t in STATE_ABBREV or t in _abbrev_to_state()


def acronym_collisions(rows, min_ratio=None, min_volume=None):
    """Which bare acronyms in the list are probably measuring someone else.

    A short acronym rarely belongs to one industry, and Google Ads volume is the
    SUM ACROSS EVERY MEANING. NASSCO's list came back with LACP at 4,400/mo and
    MACP at 2,900 — against PACP, its flagship and by far its best-known
    programme, at 480. LACP is also the Link Aggregation Control Protocol and
    MACP a Master of Arts in Counselling Psychology, and between them those two
    rows were 87% of the volume setting the price.

    The test needs no extra call, because the list already carries both forms.
    Compare the bare acronym with its qualified sibling ("lacp" vs "lacp
    certification"). Where the client genuinely owns the term the two track each
    other — PACP 480 against 320, a ratio of 1.5. Where the bare form is
    dwarfing its qualified form by two orders of magnitude, the traffic is
    arriving for a different meaning: 147x for LACP, 72x for MACP.

    Reported, not removed. An acronym can legitimately outrun its qualified form,
    and only a human looking at the SERP can settle it. (2026-08-10)
    """
    ratio_cap = float(min_ratio if min_ratio is not None
                      else CFG.get("acronym_collision_ratio", 8.0))
    vol_floor = int(min_volume if min_volume is not None
                    else CFG.get("acronym_collision_min_volume", 100))
    vols = {}
    for r in (rows or []):
        kw = str((r or {}).get("keyword") or (r or {}).get("kw") or "").strip().lower()
        if kw:
            vols[kw] = int((r or {}).get("volume") or (r or {}).get("vol") or 0)
    out = []
    for kw, v in vols.items():
        if " " in kw or not kw.isalpha() or not (3 <= len(kw) <= 6):
            continue
        if v < vol_floor:
            continue
        # Every longer phrase in the list that starts with this acronym.
        quals = {k: n for k, n in vols.items() if k.startswith(kw + " ")}
        if not quals:
            continue
        best_q = max(quals.values())
        ratio = (v / best_q) if best_q else float("inf")
        if ratio >= ratio_cap:
            out.append({"acronym": kw, "volume": v, "qualified_volume": best_q,
                        "qualified": max(quals, key=lambda k: quals[k]),
                        "ratio": (round(ratio, 1) if best_q else None)})
    out.sort(key=lambda x: -x["volume"])
    total = sum(vols.values()) or 1
    flagged = sum(x["volume"] for x in out)
    return {"items": out, "flagged_volume": flagged, "total_volume": total,
            "share": round(flagged / total * 100)}


def geo_overlaps(markets, state=""):
    """Which entered geos are already covered by another entered geo.

    Distance clustering answers "are these the same market". It does not answer
    "is this one INSIDE that one", and those are different questions with
    different consequences. Knox County and Knoxville are one footprint however
    far apart their centroids happen to compute; so are New York City and New
    York. Counting both is counting the same ground twice, and the market count
    is what the grid, the coverage percentages and the add-on recommendation are
    all built on.

    Three kinds, all read off bundled data rather than guessed:
      county    — an entered county contains an entered city
      duplicate — two entries name the same place ("nyc" / "new york city")
      non_place — not a place at all ("near me"), so it covers nothing

    Returns a list of {kind, container, contained[]} plus the non-place list.
    Detection only: nothing is removed from the operator's pills here.
    """
    mk = [m for m in (markets or []) if str(m).strip()]
    junk = [m for m in mk if is_non_place_geo(m)]
    real = [m for m in mk if m not in junk]

    # --- counties containing entered cities
    out = []
    counties = [(m, county_key(m, state)) for m in real]
    counties = [(m, k) for m, k in counties if k]
    have_county = {m for m, _k in counties}
    for m, key in counties:
        inside = [c for c in real
                  if c not in have_county and county_of(c, state) == key]
        if inside:
            out.append({"kind": "county", "container": m, "contained": inside})

    # --- same place entered twice under two names
    seen = {}
    for m in real:
        if m in have_county:
            continue
        city, st = parse_market(m, state)
        cl = (city or "").strip().lower()
        abbr = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").upper()
        # Canonicalise through the same alias ladder the volume lookup uses, so
        # "New York City, NY" and "New York, NY" land on one key.
        canon = canonical_city_name(cl, st or state) or cl
        k = (canon, abbr)
        if k in seen:
            hit = next((o for o in out
                        if o["kind"] == "duplicate" and o["container"] == seen[k]), None)
            if hit:
                hit["contained"].append(m)
            else:
                out.append({"kind": "duplicate", "container": seen[k],
                            "contained": [m]})
        else:
            seen[k] = m

    if junk:
        out.append({"kind": "non_place", "container": "", "contained": junk})
    return out


def group_by_distance(markets, state="", radius=None):
    """Cluster markets that sit within `radius` miles of each other.

    Single-link: A joins B's cluster if it is within the radius of ANY member,
    so a chain of neighbouring towns stays one market rather than splitting on
    the arithmetic of where the centre happens to fall.

    Returns (groups, located, unlocated).
    """
    r = float(radius if radius is not None else CFG.get("market_radius_miles", 25))
    mk = [m for m in (markets or []) if str(m).strip()]

    # Counties are CONTAINERS, not peers, and they must not cluster like towns.
    # Clustered as ordinary points they act as bridges: Sevier County's ZIP
    # median lands near Knoxville, so letting it chain pulled Sevierville and
    # Pigeon Forge — 30 miles out and plainly their own market — into metro
    # Knoxville and collapsed 22 entries to 3. Hold them back, cluster the towns
    # with the diameter guarantee intact, then place each county by what it
    # actually contains. (2026-08-10)
    county_of_entry = {m: county_key(m, state) for m in mk}
    counties = [m for m in mk if county_of_entry[m]]
    towns = [m for m in mk if not county_of_entry[m]]

    pts, unlocated = {}, []
    for m in towns:
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

    # Now the counties. A county holding an entered town is redundant coverage —
    # it joins that town's cluster and adds no market. It joins ONE cluster even
    # if it spans several, so it can never merge two markets that the distance
    # test kept apart.
    for m in counties:
        key = county_of_entry[m]
        best, best_n = None, 0
        for g in groups:
            n = sum(1 for t in g if county_of(t, state) == key)
            if n > best_n:
                best, best_n = g, n
        if best is not None:
            best.append(m)
            pts.setdefault(m, city_coords(m, state) or (0.0, 0.0))
            continue
        # A county with no entered town inside it IS a market of its own —
        # Roane County here. Place it at its ZIP median and let it join a
        # neighbouring cluster only if it passes the same diameter test.
        c = city_coords(m, state)
        if not c:
            unlocated.append(m)
            continue
        for g in groups:
            if all(miles_between(c, pts[o]) <= r for o in g if o in pts):
                g.append(m)
                pts[m] = c
                break
        else:
            groups.append([m])
            pts[m] = c

    # Same place under two names — "New York City, NY" and "New York, NY" — is
    # one market however the clustering fell out.
    for ov in geo_overlaps(towns, state):
        if ov["kind"] != "duplicate":
            continue
        fam = [ov["container"]] + list(ov["contained"])
        idxs = sorted({i for i, g in enumerate(groups) if any(m in g for m in fam)})
        if len(idxs) < 2:
            continue
        keep = groups[idxs[0]]
        for i in reversed(idxs[1:]):
            keep.extend(groups[i])
            del groups[i]
    return groups, list(pts), unlocated


def suggest_geo_scope(markets, state="", national_demand=False):
    """Read the geo scope OFF the entered markets instead of asking for it.

    The operator picks a band from a dropdown, and the band chooses the pricing
    anchor — so a wrong pick is a wrong price. But the markets themselves answer
    the question: how many states, how far apart, and do the clusters touch.

    Contiguity is single-link at a JOIN radius (default 60 miles) rather than
    "is every city near every other city". Wayne and Shrewsbury are 55 miles
    apart and Shrewsbury to Lawrenceville is 35 — nobody would call that two
    separate regions, but a complete-link test at 25 miles calls it three. One
    connected chain = one region; two chains that never touch = non-contiguous.

    Returns a suggestion plus the evidence, never a decision. The operator keeps
    the dropdown: "Philadelphia + South Jersey" is one trade area to a human and
    two states to a distance function. (2026-08-07)
    """
    mk = [m for m in (markets or []) if str(m).strip()]
    out = {"suggested": "", "confidence": "", "reason": "", "evidence": {}}

    # NATIONAL DEMAND AND A REGIONAL BAND ARE INCOMPATIBLE, and the band is not
    # cosmetic — it picks the pricing anchor. NASSCO sat on non_contiguous_region
    # while its volume, keywords and competition were all national: $2,300 hard
    # against $2,000, a $400/mo difference decided by a dropdown describing
    # geography the quote had stopped using. Nothing anywhere told the operator
    # to change it. (2026-08-10)
    if national_demand:
        out.update(suggested="nationwide", confidence="high",
                   reason=("Priced on national demand, so the band should be "
                           "Nationwide. The band sets the pricing anchor, and a "
                           "regional one charges for a footprint this quote is "
                           "not measuring — the keywords are bare and the volume "
                           "is a US figure."),
                   evidence={"cities": len(mk), "national_demand": True})
        return out
    if not mk:
        return out

    pts, unlocated = {}, []
    for m in mk:
        c = city_coords(m, state)
        (pts.__setitem__(m, c) if c else unlocated.append(m))

    states = sorted({market_state(m, state) for m in mk if market_state(m, state)})
    join_r = float(CFG.get("scope_join_radius_miles", 60))
    out["evidence"] = {"cities": len(mk), "states": states,
                       "located": len(pts), "unlocated": unlocated,
                       "join_radius": int(join_r)}

    if len(pts) < 2:
        # Nothing to measure. One city is one city; anything else can't be read
        # without coordinates, and guessing a band that sets the anchor is worse
        # than saying so.
        if len(mk) == 1:
            out.update(suggested="single_city", confidence="high",
                       reason="One market entered.")
        elif unlocated:
            out.update(reason=f"Could not place {len(unlocated)} of {len(mk)} "
                              "areas on the map, so the scope can't be read "
                              "from them.")
        return out

    # Single-link chain at the join radius: which clusters actually touch.
    names = list(pts)
    chains = []
    for m in names:
        joined = [c for c in chains
                  if any(miles_between(pts[m], pts[o]) <= join_r for o in c)]
        if not joined:
            chains.append([m])
        else:
            merged = [m]
            for c in joined:
                merged += c
                chains.remove(c)
            chains.append(merged)

    span = max((miles_between(pts[a], pts[b])
                for i, a in enumerate(names) for b in names[i + 1:]), default=0.0)
    out["evidence"].update(chains=len(chains), span_miles=round(span),
                           chain_sizes=sorted((len(c) for c in chains), reverse=True))

    if len(states) > 1:
        # Multi-state is only non-contiguous if the clusters are also apart.
        # Philadelphia + Cherry Hill is two states and one trade area.
        if len(chains) == 1:
            out.update(suggested="contiguous_region", confidence="medium",
                       reason=f"{len(mk)} entered areas across {len(states)} states "
                              f"({', '.join(states)}), but they form ONE "
                              f"connected area — {round(span)} miles end to end, "
                              f"no gap wider than {int(join_r)} miles.")
        else:
            out.update(suggested="non_contiguous_region", confidence="high",
                       reason=f"{len(chains)} separate clusters across "
                              f"{len(states)} states, {round(span)} miles end to "
                              "end — they do not touch.")
        return out

    if len(chains) > 1:
        out.update(suggested="non_contiguous_region", confidence="high",
                   reason=f"{len(chains)} separate clusters within "
                          f"{states[0] if states else 'one state'} — "
                          f"{round(span)} miles end to end, with gaps wider than "
                          f"{int(join_r)} miles between them.")
    elif span <= float(CFG.get("market_radius_miles", 25)):
        out.update(suggested="single_city", confidence="medium",
                   reason=f"All {len(mk)} entered areas sit within "
                          f"{round(span)} miles — one metro, not a region.")
    else:
        out.update(suggested="contiguous_region", confidence="high",
                   reason=f"{len(mk)} entered areas form one connected region, "
                          f"{round(span)} miles end to end"
                          + (f", all in {states[0]}" if states else "") + ".")
    return out


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
            t = clean_kw(strip_placeholders(strip_proximity((t or "").lower()))).strip()
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
        # A county is coverage, not a search target: "junk removal jefferson
        # county tn" is not a phrase anyone types, and a county only earns a grid
        # slot when no town of its market is available to stand for it.
        cty_rank = lambda c: 1 if county_key(c, state) else 0
        ranked = sorted(cities, key=lambda c: (-scored.get(c, 0), cty_rank(c),
                                               home_rank(c), c.lower()))
        if under_cap:
            exp["method"] = "all"
            exp["kept"] = [(c, scored.get(c, 0)) for c in ranked]
            exp["dropped"] = []
            return ranked

        # ---- one city per MARKET before a second city from any market --------
        # Ranking cities on volume alone is market-blind, and in a thin vertical
        # every city ties at Google's 10/mo floor, so the cut fell to
        # alphabetical order. Junk Bee Gone's five slots went to Knoxville,
        # Maryville, Clinton, Farragut and Jefferson County — and the first four
        # are ONE market. Three slots bought near-duplicates of Knoxville while
        # Sevierville, Oak Ridge and Morristown, three whole markets the tool had
        # just identified, got no keywords at all.
        #
        # So: round-robin across markets, best city first, and only start a
        # second lap once every market has a representative. The grouping is
        # already computed for the market count — this just stops the grid from
        # ignoring it. (2026-08-10)
        try:
            groups, _loc, _un = group_by_distance(cities, state)
            buckets = [list(g) for g in groups] + [[u] for u in _un]
        except Exception:
            buckets = [[c] for c in cities]
        order = {c: i for i, c in enumerate(ranked)}
        for bk in buckets:
            # The market's ANCHOR represents it, unless another city in it
            # actually carries more measured demand for this client's service.
            anc = market_anchor(bk, state)
            bk.sort(key=lambda c: (-scored.get(c, 0), c != anc, order.get(c, 10**6)))
        # Markets ordered by their strongest city, so the biggest market leads.
        buckets.sort(key=lambda bk: order.get(bk[0], 10**6))
        picked, lap = [], 0
        while len(picked) < limit and any(len(bk) > lap for bk in buckets):
            for bk in buckets:
                if len(bk) > lap and len(picked) < limit:
                    picked.append(bk[lap])
            lap += 1
        chosen = picked or ranked[:limit]
        exp["per_market"] = True
        exp["markets_covered"] = sum(1 for bk in buckets if any(c in chosen for c in bk))
        exp["market_count"] = len(buckets)
        ranked = chosen + [c for c in ranked if c not in chosen]
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


def claude_topics(seeds, business_desc="", brand=""):
    """Ask which PRODUCT LINES the operator's terms cover, and assign each term.

    Token clustering gets the big split right and the granularity wrong. Ski
    Barn's terms are three lines — ski/snowboard gear, BBQ and grills, and patio
    furniture — but "outdoor grill" shares a word with "outdoor furniture", so
    single-link merged all three into one topic labelled "furniture", under which
    the tool chose two grill services and no furniture at all (2026-08-07). A
    human reads those as obviously different aisles of the store.

    So the MODEL partitions and names; the CODE still enforces the quota, so the
    guarantee never depends on a non-deterministic call. Returns [] on any
    failure and topic_clusters() takes over.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    sd = [s for s in (seeds or []) if s and str(s).strip()]
    if not api_key or len(sd) < 4:
        return []
    listing = "\n".join("- " + str(s) for s in sd[:120])
    prompt = f"""Group these search terms into the PRODUCT LINES a customer would shop separately.

TERMS ({len(sd)}):
{listing}

BUSINESS: {(business_desc or '').strip()[:400] or 'not given'}
BRAND: {brand or 'not given'}

Rules:
1. A topic is an AISLE OF THE STORE — something a customer shops on its own trip. A retailer selling
   ski gear, barbecues and patio furniture has THREE topics, not one "outdoor" topic: nobody shopping
   for a grill is also shopping for skis, and grills and patio furniture are browsed separately.
2. Do NOT group by a shared adjective. "outdoor grill" and "outdoor furniture" are DIFFERENT topics
   even though both say "outdoor". Group by the THING BEING BOUGHT.
3. Do NOT split one thing into synonyms. "ski shop", "ski store", "ski outfitters", "ski gear" and
   "snowboard shop" are ONE topic. Words like shop/store/stores/service/rental/best/near me describe
   the shape of a search, not a different product.
4. Label each topic in 1-3 plain words, the way a person says it: "ski & snowboard gear",
   "bbq & grills", "patio furniture", "auto insurance", "dental implants".
5. Assign EVERY term to exactly one topic. Do not invent terms and do not drop any.
6. Most businesses have ONE topic. One topic covering everything is a correct answer — only split
   when the lines really are shopped separately.

Return ONLY JSON, no prose, no markdown:
{{"topics": [{{"label": "ski & snowboard gear", "terms": ["ski shop", "snowboard rentals"]}}]}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({
                "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 2000, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=30)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        raw = json.loads(text).get("topics") or []
    except Exception:
        app.logger.exception("claude_topics failed")
        return []

    # Map back onto the ACTUAL seeds. The model can reword a term, so only exact
    # (case-insensitive) matches count, and anything it dropped joins the biggest
    # topic rather than silently losing its claim on a slot.
    by_lower = {str(s).strip().lower(): s for s in sd}
    out, claimed = [], set()
    for t in raw:
        label = " ".join(str(t.get("label") or "").strip().lower().split())
        if len(label) > 60:
            # Trim on a word boundary. A hard [:40] produced "pipeline
            # inspection certification traini". (2026-08-10)
            label = label[:60].rsplit(" ", 1)[0]
        terms = []
        for term in (t.get("terms") or []):
            k = str(term).strip().lower()
            if k in by_lower and k not in claimed:
                claimed.add(k)
                terms.append(by_lower[k])
        if label and terms:
            toks = set()
            for x in terms:
                toks |= _topic_tokens(x)
            out.append({"label": label, "seeds": terms, "tokens": toks,
                        "size": len(terms), "source": "ai"})
    if not out:
        return []
    leftover = [by_lower[k] for k in by_lower if k not in claimed]
    if leftover:
        big = max(out, key=lambda g: g["size"])
        big["seeds"] += leftover
        big["size"] = len(big["seeds"])
        for x in leftover:
            big["tokens"] |= _topic_tokens(x)
    out.sort(key=lambda g: (-g["size"], g["label"]))
    return out


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


# Aliases people actually type instead of the full city name. Only entries that
# are genuinely more common in search than the formal name — this is not a list
# of every nickname a city has.
_CITY_ALIASES = {
    "new york city": ["nyc", "new york"],
    "new york": ["nyc"],
    "los angeles": ["la"],
    "san francisco": ["sf"],
    "philadelphia": ["philly"],
    "washington": ["dc", "washington dc"],
    "las vegas": ["vegas"],
    "atlanta": ["atl"],
    "new orleans": ["nola"],
    "saint louis": ["st louis"],
    "saint petersburg": ["st pete", "st petersburg"],
    "fort lauderdale": ["ft lauderdale"],
    "minneapolis": ["twin cities"],
}


def geo_form_candidates(market, state):
    """The ways a searcher might write this market, most formal first.

    "new york city ny" is what the grid produced for Ski Barn and nobody types
    it — the state is redundant on a city that famous, and "nyc" outsearches the
    full name several times over (2026-08-07). So generate the plausible forms
    and let measured volume choose, rather than guessing from a suffix rule.
    """
    city, st = parse_market(market, state)
    c = (city or "").strip().lower()
    if not c:
        return []
    ab = (STATE_ABBREV.get((st or "").strip().lower(), "") or "").lower()
    forms = []

    def add(f):
        f = clean_kw(re.sub(r"\s+", " ", (f or "")).strip().lower())
        if f and f not in forms:
            forms.append(f)

    if ab:
        add(f"{c} {ab}")          # the current default
    add(c)                        # bare city
    for a in _CITY_ALIASES.get(c, []):
        add(a)
        if ab and " " not in a and len(a) > 3:
            add(f"{a} {ab}")
    # "new york city" -> "new york": a trailing "city" is usually dropped.
    if c.endswith(" city") and len(c.split()) > 2:
        add(c[: -len(" city")].strip())
        if ab:
            add(f"{c[: -len(' city')].strip()} {ab}")
    return forms


def pick_geo_forms(markets, state, service_terms):
    """Choose each market's grid form by MEASURED search volume.

    Two things had to change after the first attempt reported nothing at all
    (2026-08-07):

    1. PROBE WITH GENERIC TERMS. It used the grid's lead service, which was
       "alpine ski shop" — "alpine ski shop nyc" has no measurable volume in any
       wording, so all five candidates tied at zero and the default won by
       default. Now it probes with the SHORTEST few client terms, because short
       means generic means measurable, and sums across them.

    2. MEASURE NATIONALLY. The probe was localised to the primary market, so
       "ski shop nyc" was being counted only among searchers in Wayne, New
       Jersey. The question here is not "how much demand is there" — it is
       "which spelling do people type", and that is a national property of the
       language. Absolute demand is measured elsewhere, per city, as before.

    Returns (forms, report). `forms` maps market -> chosen form. `report` has one
    entry per market ALWAYS, with a status, so a run that changed nothing is
    visibly different from a run that could not measure.
    """
    terms = [clean_kw(str(t).lower()).strip() for t in (service_terms or [])]
    terms = [t for t in terms if t]
    # Shortest first: the most generic phrasing carries the volume that makes a
    # comparison possible. Cap at 3 to keep one API call small.
    terms = sorted(dict.fromkeys(terms), key=lambda t: (len(t.split()), len(t)))[:3]
    mk = [m for m in (markets or []) if m and str(m).strip()]
    if not terms or not mk:
        return {}, []

    cand = {m: geo_form_candidates(m, state) for m in mk}
    probes = []
    for m, forms in cand.items():
        for f in forms:
            for t in terms:
                kw = clean_kw(f"{t} {f}")
                if kw:
                    probes.append(kw)
    probes = dfs_kw_list(probes)
    if not probes:
        return {}, []

    vols = {}
    try:
        payload = [{"keywords": probes[:700],
                    # NATIONAL on purpose — see the docstring. This is a question
                    # about wording, not about local demand.
                    "location_name": "United States",
                    "language_code": "en"}]
        data = dfs_post("/keywords_data/google_ads/search_volume/live", payload)
        for it in (data["tasks"][0]["result"] or []):
            vols[str(it.get("keyword", "")).lower()] = it.get("search_volume") or 0
    except Exception as e:
        return {}, [{"market": m, "status": "error", "detail": str(e)[:120]} for m in mk]

    forms_out, report = {}, []
    for m, flist in cand.items():
        scored = []
        for f in flist:
            total = sum(vols.get(clean_kw(f"{t} {f}").lower(), 0) for t in terms)
            scored.append((f, total))
        default = flist[0] if flist else ""
        best = max(scored, key=lambda x: x[1]) if scored else None
        table = [{"form": f, "volume": v} for f, v in
                 sorted(scored, key=lambda x: -x[1])]
        if not best or best[1] <= 0:
            report.append({"market": m, "status": "no data", "kept": default,
                           "tested": table, "probed_with": terms})
            continue
        forms_out[m] = best[0]
        report.append({"market": m,
                       "status": "changed" if best[0] != default else "confirmed",
                       "chose": best[0], "instead_of": default,
                       "volume": best[1],
                       "default_volume": dict(scored).get(default, 0),
                       "tested": table, "probed_with": terms})
    return forms_out, report


def suggest_market_name(market, state=""):
    """The name Google is likely to recognise for a market it rejected.

    "New York City" and "Lawrenceville" are not Google Ads locations — it holds
    "New York" and "Lawrence Township". The ZIP index knows both, and the market
    already resolves to coordinates, so the nearest ZIP-data city name at that
    exact point IS the recognised name. Both resolve at 0.0 miles, which is the
    same place under a different label rather than a guess (2026-08-07).

    Returns "City, ST" or "" when nothing better than the input can be found.
    """
    coords = city_coords(market, state)
    if not coords:
        return ""
    city, st = parse_market(market, state)
    have = (city or "").strip().lower()
    try:
        import zipcodes
        rows = zipcodes.list_all()
    except Exception:
        return ""
    best = None
    for r in rows:
        try:
            pt = (float(r["lat"]), float(r["long"]))
        except Exception:
            continue
        d = miles_between(coords, pt)
        if best is None or d < best[0]:
            best = (d, str(r.get("city") or ""), str(r.get("state") or ""))
    # Only worth suggesting if it is the SAME place under another name and the
    # name actually differs from what the operator typed.
    if not best or best[0] > 2.0:
        return ""
    name, abbr = best[1], best[2]
    if not name or name.strip().lower() == have:
        return ""
    return f"{name}, {abbr}" if abbr else name


# Words that make a search a SHOP search rather than a product search. A local
# retailer ranks and converts on these; "ski jackets" is a product query owned by
# Amazon, REI and the manufacturers, and "weber grill" is the maker's own name.
_STORE_INTENT = set("""shop shops store stores storefront outlet outlets dealer dealers
retailer retailers rental rentals service services repair shopping showroom
supplier suppliers supply center centre""".split())

# Manufacturer / product brands a retailer resells. They are legitimate keywords
# (the client stocks them) but they are not the client's own storefront demand.
_RESELLER_BRANDS = set("""weber traeger bigreenegg kamado napoleon blackstone
rossignol salomon atomic burton dakine k2 volkl nordica head fischer elan
patagonia northface columbia arcteryx oakley smith giro
trane carrier lennox rheem andersen pella marvin kohler moen""".split())


def is_store_intent(term):
    """Does this phrase describe a PLACE TO BUY rather than a thing to buy?"""
    words = set(re.split(r"[^a-z0-9]+", (term or "").lower()))
    return bool(words & _STORE_INTENT)


def is_reseller_brand(term):
    """Does this phrase lead with a manufacturer's name?"""
    words = set(re.split(r"[^a-z0-9]+", (term or "").lower()))
    return bool(words & _RESELLER_BRANDS)


def swap_low_volume_services(services, vols, seeds, topics, min_volume=None,
                            max_swaps=None, upgrade_ratio=None):
    """Replace service names nobody searches with ones the client's own list has.

    The geo WORDING is measured against search volume; the SERVICE NAMES were
    not. Ski Barn's grid spent three of seven slots on "nearest snowboard shop"
    (10/mo total, four of five markets no-data), "best snowboard store" (20) and
    "bbq grill store" (50), while the operator's own seeds held "ski shop",
    "ski store", "snowboard shop" and "ski equipment" — all unused and all much
    larger. Nobody types "nearest snowboard shop" (2026-08-08).

    A dead service slot costs twice: it fills the proposal with terms the client
    cannot win traffic on, and it drags the volume total that drives price.

    Swaps stay INSIDE the topic, so topic coverage survives — a patio-furniture
    slot is replaced by a better patio-furniture term, never by a ski term. The
    tier is inherited from the service being replaced.

    Returns (services, report).
    """
    floor = int(CFG.get("service_min_volume", 30) if min_volume is None else min_volume)
    cap = int(CFG.get("service_max_swaps", 3) if max_swaps is None else max_swaps)
    ratio = float(CFG.get("service_upgrade_ratio", 0)
                  if upgrade_ratio is None else upgrade_ratio)
    if not services or not vols:
        return services, []

    def vol_of(name):
        return int(vols.get(str(name).lower(), 0) or 0)

    def _intent_ok(current, candidate):
        """A replacement may not be weaker in INTENT than what it replaces.

        Volume alone picked "weber grill" (4,560) over "bbq grill store" (50) and
        "ski jackets" (2,440) over a shop term, so the proposal led with a
        manufacturer's name and a product query for a client whose campaign is
        in-store sales (2026-08-08). Those searches are owned by Amazon, REI and
        the makers; a five-store New Jersey retailer neither ranks for nor
        converts on them.

        So: a store term can be replaced only by another store term, and a
        manufacturer's brand can never be swapped IN. A product term may still
        replace a product term on volume.
        """
        if is_reseller_brand(candidate):
            return False
        if is_store_intent(current) and not is_store_intent(candidate):
            return False
        return True

    out = [dict(x) for x in services]
    used = {str(x.get("service", "")).lower() for x in out}
    report = []
    # Weakest slots first, so a limited number of swaps is spent where it counts.
    order = sorted(range(len(out)), key=lambda i: vol_of(out[i].get("service")))
    for i in order:
        if len(report) >= cap:
            break
        cur = out[i].get("service", "")
        cur_v = vol_of(cur)
        if cur_v >= floor:
            continue
        topic = service_topic(cur, topics) if topics else ""
        # Candidates: unused seeds from the SAME topic, best measured first.
        pool = []
        for t in (topics or []):
            if topic and t.get("label") != topic:
                continue
            pool += list(t.get("seeds") or [])
        if not topic or not pool:
            pool = list(seeds or [])
        cands = []
        for sd in pool:
            k = str(sd).strip().lower()
            if not k or k in used:
                continue
            v = vol_of(k)
            if v <= max(cur_v, floor - 1):
                continue
            if not _intent_ok(cur, k):
                continue
            cands.append((v, k))
        if not cands:
            continue
        cands.sort(reverse=True)
        best_v, best = cands[0]
        report.append({"out": cur, "out_volume": cur_v,
                       "in": best, "in_volume": best_v, "kind": "dead",
                       "topic": topic, "tier": out[i].get("tier", "")})
        used.discard(str(cur).lower())
        used.add(best)
        out[i] = {"service": best, "tier": out[i].get("tier", "competitive")}

    # UPGRADE PASS. The rule above only rescues DEAD slots, so a service that
    # scrapes past the floor keeps its place even when the operator's own list
    # holds something in a different league — Ski Barn kept "alpine ski shop"
    # (110/mo) while "ski store" (880) and "snowboard shop" (720) sat unused
    # (2026-08-08). Same-topic only, so coverage survives.
    if ratio > 0:
        order2 = sorted(range(len(out)), key=lambda i: vol_of(out[i].get("service")))
        for i in order2:
            if len(report) >= cap:
                break
            cur = out[i].get("service", "")
            cur_v = vol_of(cur)
            if cur_v <= 0:
                continue                      # handled by the floor pass
            topic = service_topic(cur, topics) if topics else ""
            pool = []
            for t in (topics or []):
                if topic and t.get("label") != topic:
                    continue
                pool += list(t.get("seeds") or [])
            if not topic or not pool:
                pool = list(seeds or [])
            cands = []
            for sd in pool:
                k = str(sd).strip().lower()
                if not k or k in used:
                    continue
                v = vol_of(k)
                if v < cur_v * ratio:
                    continue
                if not _intent_ok(cur, k):
                    continue
                cands.append((v, k))
            if not cands:
                continue
            cands.sort(reverse=True)
            best_v, best = cands[0]
            report.append({"out": cur, "out_volume": cur_v,
                           "in": best, "in_volume": best_v, "kind": "upgrade",
                           "topic": topic, "tier": out[i].get("tier", "")})
            used.discard(str(cur).lower())
            used.add(best)
            out[i] = {"service": best, "tier": out[i].get("tier", "competitive")}
    return out, report


def build_grid(services, markets, state, prepicked=False, geo_forms=None):
    """Cross each SERVICE with each CITY, in the proposal format
    ('auto insurance fairfax va'). The tier comes from the service, so every
    city inherits it. Returns {ultra:[], competitive:[], long_tail:[]}."""
    cities = list(markets) if prepicked else pick_grid_cities(markets, state, CFG["grid_max_cities"])
    suffix_mode = CFG.get("grid_state_suffix", "auto")
    buckets = {"ultra": [], "competitive": [], "long_tail": []}

    # ONE rule per grid. Brendan suffixes small or ambiguous cities but not
    # well-known metros — "auto insurance alexandria va" and "adult autism
    # services hyde pa", but "adhd treatment san diego" and "deck repair
    # knoxville". Applied city-by-city, that produced a table reading "junk
    # removal farragut" on one row and "junk removal clinton tn" on the next,
    # which reads as a mistake to whoever receives the proposal. The cities in a
    # grid are one footprint, so they get one convention: no suffix only if
    # EVERY city in the grid stands on its own name. (2026-08-10)
    _all_unmistakable = bool(cities) and all(
        name_is_unmistakable(c, state) for c in cities)

    def city_suffix(city_lower, city_state):
        """Each city uses ITS OWN state — a tri-state footprint gets
        'cherry hill nj' and 'wilmington de' in the same grid."""
        ab = STATE_ABBREV.get((city_state or "").strip().lower(), "")
        if not ab:
            return ""
        if suffix_mode is False or suffix_mode == 0:
            return ""
        if suffix_mode is True or suffix_mode == 1:
            return f" {ab}"
        return "" if _all_unmistakable else f" {ab}"          # auto
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
                # A measured form wins over the suffix rule — see pick_geo_forms.
                chosen = (geo_forms or {}).get(city) or (geo_forms or {}).get(c)
                if chosen:
                    kw = clean_kw(f"{svc} {chosen}")
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

    # Bucket sizes come from the measured tier mix, not fixed counts — see
    # CFG["tier_mix"] for the eight-proposal sample behind the proportions.
    _target = min(int(CFG.get("list_cap", 60) or 60), max(len(kept), 20))
    u, c, _lt = tier_split(_target)
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
                   national_demand=False, goal="", band="",
                   national_reason=""):
    """Second half of Step 1, run as its own request: reads the sitemap, runs the
    Claude refinement pass, and re-pulls exact-match volume. Takes the raw buckets
    from stage1_keyword_list. Kept separate so a heavy Claude call can't time out
    the list build."""
    site_terms = [{"keyword": k} for k in (site_terms_kw or [])]
    scope_note = ""
    _site_urls = []
    site_pages = fetch_site_pages(domain, collect_urls=_site_urls)
    site_locations = location_pages_from_urls(_site_urls)
    # A storefront on the client's own site used to flip national demand on
    # unconditionally. This has to happen HERE — before the volume pull below —
    # or the flip would only take effect on a second run, and the quote in front
    # of the operator would still be priced on per-city volume.
    #
    # But the flip itself was too eager. BE on the Ski Barn quote: "They have
    # specific locations, the quote didn't consider the local impact, it just
    # treated them as an ecommerce/nationwide option." Almost every retailer
    # sells online now, so "has a cart" stopped being evidence of a national
    # campaign — and the consequences all point the same way: national volume,
    # geo-less keywords, and a rank check the client cannot pass.
    #
    # Named markets outrank a detected cart, because the operator typed them on
    # purpose. So the flip only fires when there is nothing local to price
    # against — no markets, or an explicitly nationwide scope. Otherwise the
    # storefront is REPORTED and the pull stays local: geo-qualified terms,
    # per-city volume, rankings in the client's own market. (2026-08-07)
    ecom_found, ecom_reason = detect_ecommerce(_site_urls)
    ecom_suppressed = ""
    national_demand_reason = ""
    if ecom_found and not national_demand:
        if markets and (band or "") != "nationwide":
            ecom_suppressed = (
                f"Storefront detected ({ecom_reason}) — but this client has "
                f"{len(markets)} market{'' if len(markets) == 1 else 's'} entered"
                + (f" and a {band.replace('_', ' ')} geo scope" if band else "")
                + ", so demand is still being pulled LOCALLY. A store that also "
                  "ships is not a national campaign. Turn on Price on national "
                  "demand only if this really is a product brand selling "
                  "everywhere with no local trade to win.")
        else:
            national_demand = True
            national_demand_reason = f"storefront detected — {ecom_reason}"
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
                                          national=national_demand, goal=goal)
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
        # LAST, after every filter has had its say: make sure each topic the
        # operator typed is still represented. Everything above ranks by volume,
        # and the biggest topic wins every one of those contests — Ski Barn's
        # patio/BBQ half was eliminated seven times over by ski volume before
        # anyone saw the list (2026-08-07). Runs before rebalance_tiers so a
        # swapped-in service can still have its tier corrected.
        # The model partitions and names; token clustering is the fallback so a
        # dead API can't remove the guarantee, only its granularity.
        topics = claude_topics(seeds, biz, brand) or topic_clusters(seeds)
        topic_source = ("ai" if topics and topics[0].get("source") == "ai"
                        else "words")
        services, topic_fixes = enforce_topic_coverage(services, seeds,
                                                      n_services, cands,
                                                      topics=topics)
        services = rebalance_tiers(services)
        if geo_dropped is None and geo_dropped2 is None:
            geo_dropped = None
        else:
            seen_d = set()
            geo_dropped = [d for d in (list(geo_dropped or []) + list(geo_dropped2 or []))
                           if not (d[0] in seen_d or seen_d.add(d[0]))]
        pinned = [t for t in pinned
                  if any((x.get("service") or "") == t for x in services)]
        # Which WORDING of each market to cross with. Measured, not assumed —
        # "new york city ny" is nobody's search (2026-08-07).
        # Probe with the client's own SHORTEST terms, not the grid's lead
        # service: "alpine ski shop nyc" is unmeasurable in every spelling, so a
        # narrow probe makes every candidate tie at zero (2026-08-07).
        probe_terms = list(seeds) + [x.get("service") for x in services if x.get("service")]
        geo_forms, geo_form_report = ({}, [])
        if grid_cities and not national_demand:
            try:
                geo_forms, geo_form_report = pick_geo_forms(grid_cities, state,
                                                           probe_terms)
            except Exception:
                geo_forms, geo_form_report = {}, []
        g = build_grid(services, grid_cities, state, prepicked=True,
                       geo_forms=geo_forms)
        full = g["ultra"] + g["competitive"] + g["long_tail"]
        # Volume: look up the BARE service term AT THE CLIENT'S MARKET (the
        # geo-modified forms report ~0). The same figure is shown on each city
        # row for that service, so pricing must count it ONCE PER SERVICE — not
        # once per row — or a 10-city grid would inflate volume 10x.
        svc_names = list(dict.fromkeys([s["service"] for s in services]))
        # Measure the UNUSED seeds alongside the chosen services, in the same
        # call, so a dead service name can be swapped for one the client's own
        # list already has. Costs extra keywords, not extra requests.
        _chosen = {x.lower() for x in svc_names}
        _pool = [str(sd).strip().lower() for sd in (seeds or [])
                 if str(sd).strip() and str(sd).strip().lower() not in _chosen]
        _pool = list(dict.fromkeys(_pool))
        _cand_cap = int(CFG.get("service_candidate_cap", 14))
        # ROUND-ROBIN ACROSS TOPICS, not the first N in input order. The pill
        # list arrives alphabetically, so a flat slice took "ski a-s" and cut off
        # every bbq and patio candidate before it was measured — which made an
        # upgrade impossible for any topic that sorts late, silently
        # (2026-08-08).
        if topics and len(topics) > 1:
            by_topic = {}
            for sd in _pool:
                by_topic.setdefault(service_topic(sd, topics) or "", []).append(sd)
            # SHORTEST FIRST inside each topic. The budget can't cover 30 ski
            # terms, and alphabetical order is meaningless — but short means
            # generic means high volume, the same proxy the geo-wording probe
            # uses. Alphabetical would have spent the ski budget on "ski apparel"
            # ... "ski gear stores" and never measured "ski shop" or "ski store".
            for lab in by_topic:
                by_topic[lab].sort(key=lambda t: (len(t.split()), len(t)))
            _alts, _i = [], 0
            while len(_alts) < _cand_cap:
                took = False
                for lab in list(by_topic):
                    bucket = by_topic.get(lab) or []
                    if _i < len(bucket) and len(_alts) < _cand_cap:
                        _alts.append(bucket[_i])
                        took = True
                if not took:
                    break
                _i += 1
        else:
            _alts = _pool[:_cand_cap]
        vols, per_city, vol_err = fetch_local_volume(
            svc_names + _alts, [] if national_demand else cities, state,
            national=national_demand)
        # ---- IS THE LOCAL FRAME RIGHT? ---------------------------------------
        # "Should this be nationwide" was left to the operator's judgement, and
        # the obvious test — does the client have locations — is the wrong one.
        # NASSCO listed seven real cities in a document it sent us, and every one
        # of the 35 city-attached terms returned zero: a contractor looking for
        # ITCP certification types "itcp certification", not "itcp certification
        # san mateo ca". Junk Bee Gone's "junk removal knoxville tn" returns
        # 170/mo, because you need someone to drive to your house.
        #
        # So measure it instead of guessing. Same seeds, once with cities and
        # once bare. If the bare terms carry real demand and the city-attached
        # ones carry none, the buyer does not search with a place attached and
        # the local frame is producing a quote out of nothing. One extra call,
        # only on local quotes, and only reported — never applied, because
        # switching the demand basis changes the price. (2026-08-10)
        frame = {}
        # A NATIONAL build needs the same sanity check. Switching the basis fixes
        # the frame but not the wording, and NASSCO went national and still
        # returned 15 zeros out of 16 — at which point the answer is "these
        # phrases are not what anyone types", and nothing on screen said so
        # because the check only ran on local quotes. Here `vols` already IS the
        # national figure, so no extra call. (2026-08-10)
        if national_demand and svc_names:
            nat_tot = sum(int(v or 0) for v in (vols or {}).values())
            frame = {"local_total": None, "national_total": nat_tot,
                     "terms": svc_names[:6], "error": vol_err}
            if not vol_err and nat_tot < int(CFG.get("frame_national_min", 200)):
                frame["verdict"] = "no_demand"
                frame["reason"] = (
                    f"Priced on national demand, and these terms still return "
                    f"only {nat_tot:,}/mo between them. Geography was not the "
                    "problem — the wording is. These read like descriptions of "
                    "the client rather than phrases anyone types into Google.")
            elif not vol_err and cities:
                # CONFIRM the national choice rather than only questioning it.
                # The scope check reads a footprint off the site's structure and
                # says "maybe this should be local"; measuring the same terms
                # with a city attached answers that outright. NASSCO's site
                # showed 49 Google Business listings — its member directory, not
                # its offices — and the operator got two panels disagreeing with
                # each other while the demand data had already settled it.
                # (2026-08-10)
                try:
                    _loc, _pc2, _le = fetch_local_volume(svc_names, cities, state,
                                                         national=False)
                    loc_tot = sum(int(v or 0) for v in (_loc or {}).values())
                    frame["local_total"] = loc_tot
                    if not _le and loc_tot * 10 <= nat_tot:
                        frame["verdict"] = "national_ok"
                        frame["reason"] = (
                            f"{nat_tot:,}/mo bare against {loc_tot:,}/mo with a "
                            "city attached — national is the right basis, and a "
                            "footprint read off the site's page structure does "
                            "not change that.")
                except Exception:
                    pass
        if not national_demand and svc_names:
            try:
                _nat, _pc, _ne = fetch_local_volume(svc_names, [], state,
                                                    national=True)
                loc_tot = sum(int(v or 0) for v in (vols or {}).values())
                nat_tot = sum(int(v or 0) for v in (_nat or {}).values())
                frame = {"local_total": loc_tot, "national_total": nat_tot,
                         "terms": svc_names[:6], "error": _ne}
                min_nat = int(CFG.get("frame_national_min", 200))
                if not _ne and nat_tot >= min_nat and loc_tot == 0:
                    frame["verdict"] = "national"
                    frame["reason"] = (
                        f"These services draw {nat_tot:,}/mo searches nationally "
                        f"and {loc_tot}/mo with a city attached. Nobody searches "
                        "them with a place, so the city grid is measuring "
                        "something that isn't there.")
                elif not _ne and loc_tot > 0:
                    frame["verdict"] = "local"
                    frame["reason"] = (
                        f"City-attached terms carry {loc_tot:,}/mo against "
                        f"{nat_tot:,}/mo nationally — people do search these with "
                        "a place, so the local frame is measuring real demand.")
                elif not _ne and nat_tot == 0:
                    frame["verdict"] = "no_demand"
                    frame["reason"] = (
                        "These services return no volume either locally OR "
                        "nationally, so the wording is the problem, not the "
                        "geography. Check the Product / Vertical Focus terms "
                        "against what people actually type.")
            except Exception as e:
                frame = {"error": str(e)[:120]}
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
        def _apply_volumes(rows):
            """Give every crossed row its own city's measured volume.

            Extracted because the tier-reconciliation pass REBUILDS the grid,
            and the rebuilt rows were left at volume 0 — the old code re-looked
            them up by r["keyword"] ("outdoor furniture nyc") against a map keyed
            by SERVICE ("outdoor furniture"), which never matches. Result: any
            quote whose tiers moved displayed no volume against any keyword,
            which is exactly the number an operator checks the tiering against
            (2026-08-07).
            """
            fb = set()
            for x in ((per_city or {}).get("__fallback_cities__") or []):
                fb.add(str(x).strip().lower())
                fb.add(_bare_city(str(x), state))
            # Cities that resolved to the SAME location as another city are not
            # each reporting their own demand — one of them is borrowing the
            # other's area. Keep the largest as the genuine one and mark the
            # rest, because the big city is the one the shared location is
            # named after. Hard signal from the API, not a size guess.
            # Which location actually answered, per city, in friendly form.
            # "wider area" told the operator a number was wrong without saying
            # what it was — "New York statewide" is actionable (2026-08-07).
            loc_by_city = {}
            for c, l in ((per_city or {}).get("__city_locs__") or {}).items():
                bare = _bare_city(c, state)
                txt = str(l or "").replace(",United States", "").strip()
                if not txt or txt.lower() == "united states":
                    loc_by_city[bare] = "nationwide"
                elif "," in txt:
                    loc_by_city[bare] = txt.split(",")[0].strip()
                elif txt.lower() in STATE_ABBREV:
                    loc_by_city[bare] = f"{txt} statewide"
                else:
                    loc_by_city[bare] = txt
            # city_size needs the market WITH its own state. Passing the bare
            # name plus the fallback state looked up "new york, NJ" and scored
            # New York City at zero, so the smaller town was kept as the genuine
            # figure and the big one got flagged instead.
            market_of = {_bare_city(m, state): m for m in (cities or [])}
            codes = (per_city or {}).get("__location_codes__") or {}
            if codes:
                groups = {}
                for c, code in codes.items():
                    groups.setdefault(code, []).append(c)
                for code, members in groups.items():
                    if len(members) < 2:
                        continue
                    keep = max(members,
                               key=lambda c: city_size(market_of.get(c, c), state))
                    for c in members:
                        if c != keep:
                            fb.add(c)
            for r in rows:
                svc_l = (r.get("service") or "").lower()
                city_l = (r.get("city") or "").lower()
                # This city's own volume for the SERVICE. Not the volume of the
                # geo-modified phrase — local phrases mostly report zero — and
                # not the cross-city total, which would print the same number
                # against every city.
                v = per_city.get((city_l, svc_l))
                if v is not None:
                    r["volume"] = v
                    # A city with no data of its own was answered by its county,
                    # state or the whole US. That number is real but it is NOT
                    # this city's, so say so rather than letting it read as a
                    # small town out-searching Manhattan.
                    if city_l in fb:
                        r["vol_scope"] = "broader"
                        r["vol_area"] = loc_by_city.get(city_l, "")
                    continue
                # No per-city figure at all: leave the row blank rather than
                # substituting the summed total. An unknown is an unknown.
                r["volume"] = 0
                r["vol_scope"] = "unknown"
            return rows

        _apply_volumes(full)
        service_volume = {s: vols.get(s.lower(), 0) for s in svc_names}

        # SERVICE NAMES RECONCILED AGAINST MEASURED DEMAND (2026-08-08).
        # A slot holding a phrase nobody searches is worth less than the client's
        # own unused term. Runs before the tier pass so the tiers are assigned to
        # the final set.
        service_swaps = []
        _svc_check_on = (int(CFG.get("service_min_volume", 0) or 0) > 0
                         or float(CFG.get("service_upgrade_ratio", 0) or 0) > 0)
        if not national_demand and _svc_check_on:
            try:
                services, service_swaps = swap_low_volume_services(
                    services, vols, seeds, topics)
                if service_swaps:
                    svc_names = list(dict.fromkeys([x["service"] for x in services]))
                    g = build_grid(services, grid_cities, state, prepicked=True,
                                   geo_forms=geo_forms)
                    full = g["ultra"] + g["competitive"] + g["long_tail"]
                    _apply_volumes(full)
                    # service_volume was keyed by the OLD names; the tier pass
                    # below looks services up in it, so a stale map would make
                    # every swapped-in service read as unmeasured.
                    service_volume = {x: vols.get(x.lower(), 0) for x in svc_names}
            except Exception:
                app.logger.exception("swap_low_volume_services failed")
                service_swaps = []

        # TIERS RECONCILED AGAINST MEASURED DEMAND (2026-08-05).
        # Tiers are assigned by the model on judgement, BEFORE any volume is
        # known, and nothing reconciled them afterwards — rebalance_tiers only
        # guarantees no column is empty. On Ski Barn that put "ski jeans" at
        # 60,500/mo in Long Tail while "ski equipment rental" at 1,600/mo sat in
        # Ultra Competitive. A proposal whose Long Tail column carries the
        # biggest numbers reads as though the tool doesn't understand the market.
        #
        # Re-sorts by volume while PRESERVING the tier COUNTS the model chose,
        # so the proposal keeps its shape and only the assignment changes. Terms
        # with no volume data keep their original position rather than being
        # dumped into Long Tail on missing data.
        tier_moves = []
        try:
            _order = ["ultra", "competitive", "long_tail"]
            _counts = {t: sum(1 for x in services if x.get("tier") == t)
                       for t in _order}
            _measured = [x for x in services
                         if (service_volume.get(x["service"]) or 0) > 0]
            if len(_measured) >= 3 and sum(_counts.values()) == len(services):
                # Store intent gets a THUMB ON THE SCALE, not a veto. Absolute
                # precedence pushed "outdoor furniture" (4,580/mo, the largest
                # line in the quote) into Long Tail beneath terms at 80/mo,
                # because it isn't a shop phrase — and the columns stopped
                # running high-to-low, which is the one thing this pass exists
                # to guarantee (2026-08-09). A multiplier keeps a shop term
                # ahead of a comparable product term while letting a term with
                # several times the demand take the slot it has earned.
                _boost = float(CFG.get("store_intent_tier_boost", 3.0) or 1.0)
                def _rank_key(x):
                    v = service_volume.get(x["service"]) or 0
                    return -(v * (_boost if is_store_intent(x["service"]) else 1.0))
                _ranked = sorted(_measured, key=_rank_key)
                # Walk the ranked list, filling ultra first, then competitive.
                # Unmeasured terms keep whatever tier they already had, so the
                # per-tier capacity has to account for them.
                _unmeasured_in = {t: sum(1 for x in services
                                         if x.get("tier") == t and x not in _measured)
                                  for t in _order}
                _cap = {t: max(0, _counts[t] - _unmeasured_in[t]) for t in _order}
                _i = 0
                for t in _order:
                    for _ in range(_cap[t]):
                        if _i >= len(_ranked):
                            break
                        _svc = _ranked[_i]
                        if _svc.get("tier") != t:
                            tier_moves.append({"service": _svc["service"],
                                               "from": _svc.get("tier"), "to": t,
                                               "volume": service_volume.get(_svc["service"], 0)})
                            _svc["tier"] = t
                        _i += 1
                if tier_moves:
                    g = build_grid(services, grid_cities, state, prepicked=True,
                                   geo_forms=geo_forms)
                    full = g["ultra"] + g["competitive"] + g["long_tail"]
                    # Same assignment as the first pass — by service AND city.
                    _apply_volumes(full)
        except Exception:
            app.logger.exception("tier reconciliation failed")
            tier_moves = []

        # National demand on a client with PHYSICAL PREMISES is usually a
        # mis-scope, not a product brand. The signals to catch it are already
        # collected; nothing was checking them (Ski Barn: NJ stores, priced
        # nationwide, so every term came back as national head demand).
        scope_warning = ""
        goals_all = goal_list(goal)
        _gs = goal_scope(goal)
        _gforce = goal_forces_national(goal)
        if _gforce and (markets or gbp_count or site_locations):
            # Goal-driven national is intentional, so this is not a warning that
            # something is wrong — it's a statement of what the goal did, and of
            # the one thing it deliberately did NOT do.
            _where = []
            if markets:
                _where.append(f"{len(markets)} market"
                              f"{'' if len(markets) == 1 else 's'} entered")
            if gbp_count:
                _where.append(f"{gbp_count} Google Business listing"
                              f"{'' if gbp_count == 1 else 's'}")
            if site_locations:
                _where.append(f"{len(site_locations)} location page"
                              f"{'' if len(site_locations) == 1 else 's'}")
            scope_warning = (
                f"Goal is “{_gforce}”, so demand is pulled NATIONALLY "
                "even though this client has " + " and ".join(_where) + ". That "
                "is the goal doing its job — the client asked to be sold online "
                "sales, so the volumes describe the whole addressable market. "
                "Rankings are still measured in the client's own market, because "
                "whether THIS client is visible is a local question. Change the "
                "goal if the campaign is really about the stores.")
        elif goal and _gs == "local" and national_demand:
            scope_warning = (
                f"Goal is \u201c{goal}\u201d, which happens somewhere \u2014 but this "
                "quote is priced on NATIONAL demand, so every keyword, volume "
                "and ranking here describes a national campaign. Set Geo scope "
                "to the client's region and enter their markets, or change the "
                "goal if this really is a nationwide play.")
        elif goal and _gs == "national" and not national_demand:
            scope_warning = (
                f"Goal is \u201c{goal}\u201d, which usually sells everywhere \u2014 but "
                "this quote is priced on LOCAL demand, so the volumes are "
                "geo-limited and will understate the opportunity. Consider "
                "Nationwide scope or the national-demand switch.")
        elif goals_all and all(g in GOAL_OFF_PATTERN for g in goals_all):
            scope_warning = (
                f"Goal is \u201c{' + '.join(goals_all)}\u201d. An SEO keyword campaign is a weak "
                "instrument for this \u2014 the ladder below prices category-term "
                "ranking work, which may not be what the client is buying. "
                "Confirm the objective before quoting.")
        # A DELIBERATE choice does not need a warning on every rebuild. The scope
        # check exists to catch national demand INFERRED from an industry tag or
        # a storefront; when the operator ticked the switch themselves it fires
        # forever on a decision already made, and NASSCO's count is its member
        # directory rather than its offices anyway. Suppressed for a manual
        # override and for a frame the demand data has confirmed — the reasoning
        # is kept as a quiet note either way. (2026-08-10)
        _explicit = ("manual" in (national_reason or "").lower()
                     or (frame or {}).get("verdict") == "national_ok")
        if national_demand and (gbp_count or site_locations) and _explicit:
            scope_note = (
                f"National demand is set deliberately"
                + (" and confirmed by the volume data"
                   if (frame or {}).get("verdict") == "national_ok" else "")
                + f". The site shows {gbp_count} Google Business listing"
                + ("" if gbp_count == 1 else "s")
                + f" and {len(site_locations)} location page"
                + ("" if len(site_locations) == 1 else "s")
                + " — member, chapter or directory pages if the client is an "
                  "association, their own premises if not.")
        elif (national_demand and (gbp_count or site_locations)
                and (frame or {}).get("verdict") != "national_ok"):
            _bits = []
            if gbp_count:
                _bits.append(f"{gbp_count} Google Business listing"
                             f"{'' if gbp_count == 1 else 's'}")
            if site_locations:
                _bits.append(f"{len(site_locations)} location page"
                             f"{'' if len(site_locations) == 1 else 's'} on the site")
            # "A retailer with premises… if it is a store" reads as a mistake on
            # a nonprofit standards body, and a directory-style site inflates the
            # listing count with OTHER companies' locations — NASSCO scored 49
            # Google Business listings, which it does not have. So say what was
            # counted and let the operator judge it, rather than asserting the
            # client is a shop. (2026-08-10)
            scope_warning = (
                "Priced on NATIONAL demand, but this client's site suggests a "
                "physical footprint \u2014 " + " and ".join(_bits)
                + ". The keywords, volumes and rankings here are all national, "
                  "which prices a different campaign from a local one. If those "
                  "premises are the client's own, set Geo scope to their region "
                  "and enter their markets. If they belong to members, chapters "
                  "or a directory the client publishes, the count is not theirs "
                  "and national is right \u2014 check before trusting it.")

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
            # Which location ID actually answered per city. Two cities sharing
            # one ID means only one of them reported its own demand.
            "city_location_codes": (per_city or {}).get("__location_codes__") or {},
            # Markets that contributed NO volume of their own, with the name
            # Google would probably accept. Surfaced per MARKET because reading
            # it off twenty tagged keyword rows is work the tool should do.
            "service_swaps": service_swaps,
            "service_upgrade_ratio": CFG.get("service_upgrade_ratio", 0),
            "market_renames": [{"market": k, "used": v}
                               for k, v in ((per_city or {}).get("__renamed__") or {}).items()],
            "market_volume_gaps": [
                {"market": m,
                 "suggestion": suggest_market_name(m, state)}
                for m in ((per_city or {}).get("__fallback_markets__") or [])],
            "site_locations": site_locations,
            "service_areas": service_areas,
            "gbp_locations": gbp_count,
            "tier_moves": tier_moves,
            "scope_warning": scope_warning,
            "scope_note": scope_note,
            "gbp_cities": gbp_cities,
            "dropped_out_of_area": [d[0] for d in (geo_dropped or [])],
            "seed_services_used": seed_used,
            "dropped_ungrounded": [d[0] for d in (ungrounded or [])],
            "grounding_stood_down": ungrounded is None,
            # No foreign states exist on a nationwide quote, so the warning was
            # telling the operator to fix something that is not broken.
            "geo_filter_off": (geo_dropped is None) and not national_demand,
            "service_volume": service_volume,
            "volume_error": vol_err,
            "demand_frame": frame,
            "acronym_collisions": acronym_collisions(full),
            "volume_location": "United States" if national_demand else loc_string(markets, state),
            "volume_source": volume_source,
            "national_demand": bool(national_demand),
            "national_demand_reason": national_demand_reason,
            "ecommerce_detected": bool(ecom_found),
            "ecommerce_reason": ecom_reason,
            "ecommerce_suppressed": ecom_suppressed,
            "state_missing": bool(cities) and not state
                             and not any(market_state(c)
                                         or c.strip().lower() in STATE_ABBREV
                                         for c in cities),
            "grid_cities": [] if national_demand else cities,
            "total_volume": sum(service_volume.values()),   # unique, not per-row
            # Topic coverage: what the operator's terms are ABOUT, how many
            # services each topic got, and any swap made to keep a topic alive.
            "topic_source": topic_source,
            "topics": [{"label": t["label"], "seeds": t["size"],
                        "share": round(t["size"] / max(len(seeds), 1) * 100),
                        "services": len([x for x in services
                                         if service_topic(x.get("service", ""),
                                                          topics) == t["label"]])}
                       for t in topics],
            "topic_fixes": topic_fixes,
            "geo_forms": geo_form_report,
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
        "ecommerce_suppressed": ecom_suppressed,
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
def market_for_keyword(kw, markets, state=""):
    """Which entered market a keyword names, read off the keyword itself.

    The grid tags every row with its city, but a keyword list restored from a
    saved quote carries only the text — and that is the common case, because an
    operator re-checks rankings without rebuilding step 1. Depending on the tag
    meant the per-market rank check silently did nothing on every existing quote
    (2026-08-10).

    The keyword ends with the market: "junk removal morristown tn". Match on the
    END, longest first, so "oak ridge" wins over a market called "ridge" and
    "kansas city ks" is never mistaken for "kansas".
    """
    k = " " + re.sub(r"\s+", " ", clean_kw((kw or "").lower())).strip()
    if not k.strip():
        return ""
    cands = []
    for m in (markets or []):
        city, st = parse_market(m, state)
        c = clean_kw((city or "").lower()).strip()
        if not c:
            continue
        ab = (STATE_ABBREV.get((st or state or "").strip().lower(), "") or "").lower()
        forms = [f"{c} {ab}", c] if ab else [c]
        # A county reads either way round: "roane county tn" / "roane tn".
        ck = county_key(m, state)
        if ck:
            bare = _COUNTY_SUFFIX.sub("", c).strip()
            if bare and ab:
                forms.append(f"{bare} {ab}")
        for f in forms:
            if f:
                cands.append((len(f), f, m))
    for _n, form, m in sorted(cands, reverse=True):
        if k.endswith(" " + form):
            return m
    return ""


def _serp_one(kw, domain_dom, markets, state, brand, top_n, deadline=None,
              loc_override=""):
    """One keyword's SERP call. Returns (position_or_None, [paa questions]).
    Depth tracks top_n (<=100 is one DataForSEO unit either way). Works within a shared batch DEADLINE: the
    platform kills any request near ~30s, so retrying past the budget doesn't
    save this keyword — it kills the WHOLE batch, failing keywords that had
    already finished. Better to fail one fast and let the retry pass get it."""
    depth = max(top_n, 10)
    payload = [{"keyword": kw,
                # loc_override is an already-built DataForSEO location string —
                # step 3 measures each grid row in the market it names, so the
                # caller resolves the location per keyword rather than per batch.
                "location_name": loc_override or loc_string(markets, state),
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
    # DataForSEO answers HTTP 200 and reports per-TASK problems in status_code.
    # Every other caller in this module checks it; _serp_one did not — the one
    # whose result sets the price. An unresolvable location_name ("near me,
    # Tennessee") returns 40501 with result=None, which fell straight through to
    # items=[] -> pos=None -> "Not Found" for EVERY keyword in the batch. 0/35
    # ranked then drew the largest zero-ranking uplift off a lookup that never
    # ran, and the result was cached for six hours, so the re-check returned
    # instantly and agreed with itself. Raise instead: the caller already renders
    # a failed lookup as "—", keeps it out of the ranked fraction, and does not
    # cache it. (2026-08-10)
    task0 = ((data or {}).get("tasks") or [{}])[0] or {}
    if task0.get("status_code") not in (20000, None):
        raise RuntimeError(f"{task0.get('status_code')}: {task0.get('status_message')}")
    res = (task0.get("result") or [{}])[0] or {}
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
                results[i] = fut.result() + (False,)
            except Exception:
                # One bad keyword shouldn't sink the quote — but it must not be
                # counted as "not ranking" either. A failed lookup measured
                # nothing, and folding it into the denominator inflates the
                # zero-ranking percentage and therefore the price. Same rule the
                # batched /api/rankings path already follows. (2026-08-10)
                results[i] = (None, [], True)

    table, paa, ranked, errors = [], [], 0, 0
    for kw, (pos, qs, err) in zip(kws, results):
        table.append({"keyword": kw, "position": pos, "error": err})
        paa.extend(qs)
        if err:
            errors += 1
            continue
        if pos is not None and pos <= top_n:
            ranked += 1
    checked = max(len(kws) - errors, 0)
    frac = (ranked / checked) if checked else 0.0
    return {"table": table, "ranked": ranked, "frac": frac,
            "checked": checked, "errors": errors,
            # Nothing was measured, so there is no evidence of zero ranking.
            "zero_ranking": bool(checked) and frac < CFG["zero_ranking_frac"],
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
    so the location has to describe the same market the keywords do.

    BUT national demand and a national SERP are two different claims, and only
    the first one follows from a storefront. National demand says "this client
    sells everywhere, so measure DEMAND nationally" — correct for a shop that
    ships. A national SERP says "measure whether they OUTRANK the whole country",
    which no regional retailer ever does: Ski Barn (4 NJ stores, skibarn.com)
    scored 0/20 in the national top 100 on bare terms like "ski shop" and drew
    the largest zero-ranking uplift, +14% on the hard base, off a test it could
    not have passed (2026-08-07). Arithmetically inevitable, not a finding.

    So: if the client named markets, measure in the primary market even under
    national demand. Volume stays national; visibility is asked where their
    customers actually search. Only a client with NO markets at all — genuine
    pure-play ecommerce, the MPG case — gets measured nationally.
    """
    if national and not markets:
        return "United States"
    return loc_string(markets, state)


def rank_location_note(markets, state, national=False):
    """Human-readable 'where this was measured', for the Step 3 panel. A 0%
    ranked result is only interpretable next to the place it was measured."""
    loc = rank_location(markets, state, national)
    if loc == "United States":
        return {"location": loc, "scope": "national",
                "note": "Measured against the whole United States — no markets are set, "
                        "so there is nowhere local to measure."}
    if national:
        return {"location": loc, "scope": "local_under_national",
                "note": f"Measured in {loc.replace(',United States','').replace(',', ', ')}. "
                        "Demand is pulled nationally (storefront), but visibility is "
                        "measured where the client's customers search — a regional "
                        "retailer never ranks nationally, and scoring them that way "
                        "would raise the price off a test they cannot pass."}
    return {"location": loc, "scope": "local",
            "note": f"Measured in {loc.replace(',United States','').replace(',', ', ')}."}


def resolve_national_demand(industry="", band="", manual=False, markets=None,
                            goal=""):
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

    MARKETS VETO THE INDUSTRY TAG (2026-08-07). BE on the Ski Barn quote: "They
    have specific locations, the quote didn't consider the local impact, it just
    treated them as an ecommerce/nationwide option." An RZ tag of "Retail -
    General / E-commerce" describes what the client SELLS; the market list
    describes where they TRADE, and the operator typed it deliberately. With both
    present and the scope not nationwide, the market list wins — a store with
    four premises is a local campaign that also ships, and pricing it on national
    demand quotes a different campaign: geo-less terms, national volume, and a
    rank check against the whole country.

    The manual switch and an explicit nationwide scope still force national.
    Both are direct statements of intent rather than inferences from a taxonomy.

    Returns (bool, reason_string) so the UI can show WHY it flipped.
    """
    if manual:
        return True, "manual override"
    if band == "nationwide":
        return True, "nationwide geo scope"
    # The goal is the client's own statement of what they are buying, taken off
    # the adtini order form — so it outranks the market list, which describes
    # where they trade. "Online Sales" with four stores entered is a client
    # asking to be sold ecommerce visibility; price the demand nationally and
    # say so. Rankings still get measured locally when markets exist — see
    # rank_location() — because that is a question about this client, not about
    # the size of the market.
    _g = goal_forces_national(goal)
    if _g:
        return True, f"goal: {_g}"
    ind = (industry or "").strip().lower()
    mk = [m for m in (markets or []) if str(m).strip()]
    for k, r in (CFG.get("industry_pricing") or {}).items():
        if k in ind and r.get("national_demand"):
            if mk:
                return False, (f"industry “{k}” suggests national demand, but "
                               f"{len(mk)} market{'' if len(mk) == 1 else 's'} "
                               "are entered — priced on LOCAL demand. Set Geo "
                               "scope to Nationwide, or tick Price on national "
                               "demand, if this client sells everywhere.")
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
                 national_demand=False, geo_override=None, addon_override=None,
                 goal=""):
    if markup_pct is None:
        markup_pct = CFG["default_markup_pct"]
    # RETAIL IS CANONICAL (2026-08-05). The anchors and every hard-dollar extra
    # in CFG were back-solved from Brendan's QUOTED tier prices as
    # client / 1.35, so they are a calibration basis, not a real cost. The
    # agency split is 35% OF GROSS (see the SSG/Vici grid: agency profit =
    # retail x 0.35, Vici bills retail x 0.65), which is what the reputation
    # tool already does. Reading those anchors as true cost overstated partner
    # cost by 14% and implied a 25.9% margin instead of 35%.
    #
    # Fixed WITHOUT touching a single calibrated constant: convert the
    # calibration basis to true cost once, then divide by (1 - margin). At the
    # calibrated 35% this is algebraically identical to the old x1.35, so every
    # client price is unchanged; away from 35% it now moves the way a
    # margin-of-gross should. CAL_* are frozen history, not business inputs.
    CAL_MARKUP, CAL_MARGIN = 1.35, 0.35
    cal_to_hard = CAL_MARKUP * (1.0 - CAL_MARGIN)          # 0.8775
    mg = min(0.95, max(0.0, markup_pct / 100.0))           # margin OF GROSS
    m = cal_to_hard / (1.0 - mg)                           # basis -> retail
    to_true_hard = 1.0 - mg                                # retail -> true cost

    # PARTNER HARD COST IS THE CANONICAL, ROUNDED FIGURE (2026-08-05). The
    # ladder is now built cost-first: calibration basis -> true partner cost,
    # rounded to a clean $50 -> retail = cost / (1 - margin), rounded UP to $50.
    #
    # Cost rounds to the NEAREST $50, not up. Rounding both numbers up compounds
    # (cost ceils, then retail ceils again) and drifted retail +$0-100 above the
    # calibrated prices, mean +$37. Nearest-$50 on the cost cancels most of that:
    # retail is unchanged on 146 of 240 anchor values, mean drift +$0.40, worst
    # case one $50 step either way, and all three live anchors land exactly on
    # today's prices (2050 -> $2,800, 2100 -> $2,850, 2350 -> $3,200).
    #
    # Consequence to accept: with both figures on $50 boundaries the realised
    # margin lands 35.1-35.9% rather than exactly 35%. Two clean numbers and an
    # exact ratio cannot all three hold at once.
    def r50n(x):
        return int(round(round(x, 6) / 50.0) * 50)

    def cost_of(basis):
        return r50n(basis * cal_to_hard)

    def retail_of(cost):
        return r50(cost / (1.0 - mg))

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
    # No markets= here: stage4_price never receives the market list, so passing
    # one would be a NameError. The veto is applied upstream — /api/refine,
    # /api/metrics and the rank endpoints all resolve it WITH markets, and the
    # resulting flag arrives here as `national_demand`.
    nat_demand, nat_reason = resolve_national_demand(
        industry, band, bool(ecommerce) or bool(national_demand), goal=goal)

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

    # Cost first, then retail from cost.
    hard_cost = {k: cost_of(v) for k, v in hard.items()}
    client_base = retail_of(hard_cost["base"])
    floor = CFG.get("client_floor", 0)
    floored = False
    if floor and client_base < floor:
        client_base = floor
        floored = True
        cstep = (retail_of(cost_of(step)) if CFG.get("tier_step_flat")
                 else r50(client_base * CFG["step_ratio"]))
        client = {"base": client_base,
                  "intermediate": client_base + cstep,
                  "advanced": client_base + 2*cstep}
        # Floored: retail was overridden, so cost has to be restated from it or
        # the two would describe different quotes.
        hard_cost = {k: r50n(v * to_true_hard) for k, v in client.items()}
    else:
        client = {k: retail_of(v) for k, v in hard_cost.items()}

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
    # ADD-ON MARKETS ARE PRICED THROUGH THE MARGIN, NOT AS A RATIO OF RETAIL
    # (2026-08-05). The client side used to be ratio x retail, computed
    # independently of the add-on's own cost. That made the per-market retail
    # figure carry its own rounding error, which then got MULTIPLIED by the
    # market count — so realised margin sagged as add-ons accumulated (34.09%
    # at five markets against a 35% target).
    #
    # Now: partner cost per market is a clean $50, and its retail price is that
    # cost / (1 - margin), rounded UP to $50. Because every component rounds up,
    # the total is automatically a $50 multiple and the margin can never land
    # below target - verified across all 1,650 anchor x ratio x count cases.
    hard_addon   = {k: r50n(hard_cost[k] * _r(k)) for k in hard_cost}
    client_addon = {k: retail_of(hard_addon[k]) for k in hard_addon}
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
        # Override sets the BASE partner cost per market; upper tiers keep the
        # ladder's shape. Retail still comes from cost through the margin.
        _ar2 = {k: (hard_cost[k] / hard_cost["base"] if hard_cost["base"] else 1.0)
                for k in hard_cost}
        hard_addon   = {k: r50n(_ao * _ar2[k]) for k in hard_cost}
        client_addon = {k: retail_of(hard_addon[k]) for k in hard_addon}
    # True partner cost is a share of RETAIL, so derive it from the client
    # tiers rather than from the calibration basis.
    hard_true = dict(hard_cost)          # already clean $50 figures
    # The COMBINED MONTHLY BUDGET — the single figure the adtini product form
    # needs. Package retail plus the per-market retail times the market count;
    # every term is already a $50 multiple, so the sum is too.
    _n_addon = max(0, int(addon_markets or 0))
    combined = {k: client[k] + client_addon[k] * _n_addon for k in client}
    combined_hard = {k: hard_cost[k] + hard_addon[k] * _n_addon for k in hard_cost}
    return {"anchor": anchor, "base": base, "base_pre_uplift": base_pre, "step": step,
            "hard_true_tiers": hard_true,
            "margin_pct_of_gross": round(mg * 100, 2),
            "agency_profit_tiers": {k: client[k] - hard_true[k] for k in client},
            "margin_realised_pct": {k: (round((client[k] - hard_true[k]) / client[k] * 100, 1)
                                        if client[k] else 0.0) for k in client},
            "combined_monthly": combined,
            "combined_hard": combined_hard,
            "combined_margin_pct": {k: (round((combined[k] - combined_hard[k]) / combined[k] * 100, 2)
                                        if combined[k] else 0.0) for k in combined},
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
    seeds   = clean_seeds(d.get("keywords", []))
    markets = usable_markets(d.get("geo_values") or [])
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
                          addon_override=d.get("addon_override"),
                          goal=(d.get("goal") or ""))
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
    markets = usable_markets(d.get("geo_values") or [])
    state = (d.get("state") or "").strip()
    seeds = clean_seeds(d.get("keywords") or [])
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
    seeds   = clean_seeds(d.get("keywords", []))
    markets = usable_markets(d.get("geo_values") or [])
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
                       # "broader" = the figure is a county/state/US number
                       # because this city had none of its own; "unknown" = no
                       # figure at all. Neither is this city's demand.
                       "vol_scope": r.get("vol_scope", ""),
                       "vol_area": r.get("vol_area", ""),
                       # WHICH market this row names. Step 3 measures the rank
                       # in that market rather than in the primary one for every
                       # row — see api_rankings. (2026-08-10)
                       "city": r.get("city", ""),
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
    seeds   = clean_seeds(d.get("keywords", []))
    markets = usable_markets(d.get("geo_values") or [])
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
        manual=bool(d.get("national_demand")) or bool(d.get("ecommerce")),
        markets=markets, goal=(d.get("goal") or ""))
    # rebuild bucket rows from what the frontend sends back (kw + vol)
    def rows(key):
        return [{"keyword": x["kw"], "volume": x.get("vol", 0), "src": "build"}
                for x in d.get(key, []) if x.get("kw")]
    ultra, competitive, long_tail = rows("ultra"), rows("competitive"), rows("long_tail")
    try:
        s1 = stage1b_refine(seeds, markets, state, brand, domain, business_desc,
                            ultra, competitive, long_tail, site_terms_kw, phrase_geos,
                            national_demand=nat_demand,
                            national_reason=nat_reason,
                            goal=(d.get("goal") or ""),
                            band=d.get("geo_scope", d.get("band", "")))
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
                       # "broader" = the figure is a county/state/US number
                       # because this city had none of its own; "unknown" = no
                       # figure at all. Neither is this city's demand.
                       "vol_scope": r.get("vol_scope", ""),
                       "vol_area": r.get("vol_area", ""),
                       # WHICH market this row names. Step 3 measures the rank
                       # in that market rather than in the primary one for every
                       # row — see api_rankings. (2026-08-10)
                       "city": r.get("city", ""),
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
        "tier_moves": s1.get("tier_moves") or [],
        "scope_warning": s1.get("scope_warning") or "",
        "scope_note": s1.get("scope_note") or "",
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
        "demand_frame": s1.get("demand_frame") or {},
        "acronym_collisions": s1.get("acronym_collisions") or {},
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
        "ecommerce_suppressed": s1.get("ecommerce_suppressed") or "",
        "market_volume_gaps": s1.get("market_volume_gaps") or [],
        "market_renames": s1.get("market_renames") or [],
        "service_swaps": s1.get("service_swaps") or [],
        "service_upgrade_ratio": s1.get("service_upgrade_ratio", 0),
        "topics": s1.get("topics") or [],
        "topic_source": s1.get("topic_source") or "",
        "topic_fixes": s1.get("topic_fixes") or [],
        "geo_forms": s1.get("geo_forms") or [],
    })

# ---------------------------------------------------------------------------
# IMPORT AN EXISTING SEO REPORT
#
# Why a FILE and not a paste box: the numbers that matter are pictures. A real
# Ski Barn July report was checked (2026-08-05) — the ranking tables are
# embedded PNGs, so text extraction returns the traffic figures and loses the
# entire keyword list. Pasting text cannot work for this format. Reading the
# images can, and does.
#
# Everything extracted is a SUGGESTION. The operator ticks what to apply; the
# quote is never changed by an import on its own. A report is a set of claims —
# sometimes months stale, sometimes framed to flatter the incumbent.
# A slide screenshot is one picture holding several tables, and table text is
# small. Shrinking the whole thing to a 1568px long edge left ~7px glyphs and the
# reader could only make out the bottom table — a Ski Barn import returned the 9
# ski keywords and missed all 10 patio/BBQ ones, saying so in its own notes
# (2026-08-05). So: TILE anything oversized instead of shrinking it, and select
# by PIXEL AREA rather than file size, because bytes say nothing about legibility.
_REPORT_MAX_IMAGES = 16                   # tiles count toward this
_REPORT_MIN_PIXELS = 60_000               # ~250x250; below this it is an icon
# The API downsamples any image to ~1568px on its long edge before reading it,
# so sending a 4000px screenshot gains nothing — it is scaled to 0.38x and a
# table's 11px text becomes 4px. The only way to keep text legible is to TILE at
# native resolution and let each tile use its own 1568px budget.
_REPORT_TILE_EDGE = 1568
_REPORT_TILE_OVERLAP = 0.18               # so a row on a seam survives in a neighbour
_REPORT_TILES_PER_SOURCE = 4              # one dense slide can't eat the whole budget
# Below this width a single scaled image beats slicing: 2030 -> 1568 is 0.77x and
# keeps every row whole, where slicing would strand the labels.
_REPORT_STITCH_ABOVE = 2600
_REPORT_LABEL_FRACTION = 0.28             # left share of a table that holds the keywords


def _emf_text(data, row_tol=None):
    """Read the text out of a Windows METAFILE (.emf / .wmf) table.

    A ranking table pasted from Excel into PowerPoint on Windows arrives as an
    EMF, not a PNG. Pillow cannot open one — "cannot find loader for this WMF
    file" — so _report_images skipped it and the reader was handed a deck with
    no ranking tables in it at all. Junk Bee Gone's slides 2, 3 and 4 were three
    EMFs holding 2,061 text runs between them, and the import returned "no
    keyword table found" (2026-08-09).

    Rendering an EMF needs LibreOffice, which is not on the deploy. But an EMF is
    a list of drawing records and the text is stored as EMR_EXTTEXTOUTW (type
    84) with its own coordinates — so the table can be read directly, and the
    x/y positions rebuild the rows and columns. Text beats a screenshot anyway:
    no tiling, no resolution limit, no OCR.

    Returns tab-separated rows, top-to-bottom then left-to-right.
    """
    import struct
    runs, off, n = [], 0, len(data or b"")
    guard = 0
    while off < n - 8 and guard < 200000:
        guard += 1
        try:
            rtype, size = struct.unpack_from("<II", data, off)
        except Exception:
            break
        if size < 8 or off + size > n:
            break
        if rtype in (83, 84):                     # EXTTEXTOUTA / EXTTEXTOUTW
            try:
                x, y = struct.unpack_from("<ii", data, off + 36)
                nchars, offstr = struct.unpack_from("<II", data, off + 44)
                if 0 < nchars < 4096 and 8 <= offstr < size:
                    raw = data[off + offstr: off + offstr + nchars * (2 if rtype == 84 else 1)]
                    txt = (raw.decode("utf-16-le", "ignore") if rtype == 84
                           else raw.decode("latin-1", "ignore"))
                    txt = txt.replace("\x00", "").strip()
                    if txt:
                        runs.append((y, x, txt))
            except Exception:
                pass
        off += size
    if not runs:
        return ""
    # Row height comes from the FILE, not a guess. A fixed tolerance of 40 was
    # double the real row gap here (median 20), so it merged pairs of rows and
    # the keyword column came out concatenated. Half the median gap between
    # distinct y values splits rows without splitting a single row's runs.
    if row_tol is None:
        ys = sorted({r[0] for r in runs})
        gaps = sorted(b - a for a, b in zip(ys, ys[1:]) if b > a)
        row_tol = max(2, (gaps[len(gaps) // 2] // 2) if gaps else 8)
    # Rebuild rows: same y (within tolerance) is one row, x orders the columns.
    runs.sort(key=lambda r: (r[0], r[1]))
    lines, cur, last_y = [], [], None
    for y, x, txt in runs:
        if last_y is not None and abs(y - last_y) > row_tol:
            if cur:
                lines.append("\t".join(t for _, t in sorted(cur)))
            cur = []
        cur.append((x, txt))
        last_y = y
    if cur:
        lines.append("\t".join(t for _, t in sorted(cur)))
    return "\n".join(lines)


def _pptx_metafile_text(zf):
    """Every EMF/WMF in the deck, read as text and labelled by slide."""
    rel_by_slide = {}
    for name in zf.namelist():
        m = re.match(r"ppt/slides/_rels/(slide\d+)\.xml\.rels$", name)
        if not m:
            continue
        try:
            xml = zf.read(name).decode("utf-8", "ignore")
        except Exception:
            continue
        for media in re.findall(r"\.\./media/([^\"']+\.(?:emf|wmf))", xml, re.I):
            rel_by_slide.setdefault(m.group(1), []).append(media)
    out = []
    for slide in sorted(rel_by_slide, key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        for media in rel_by_slide[slide]:
            try:
                txt = _emf_text(zf.read("ppt/media/" + media))
            except Exception:
                txt = ""
            if txt.strip():
                out.append(f"[{slide}.xml · {media} — table read from metafile]\n{txt}")
    return "\n".join(out)


def _pptx_slide_text(zf):
    """Slide text straight out of the XML. No new dependency: <a:t> holds every
    run of visible text, which is enough for titles, labels and any figures that
    were typed rather than screenshotted."""
    out = []
    for name in sorted(n for n in zf.namelist()
                       if n.startswith("ppt/slides/slide") and n.endswith(".xml")):
        try:
            xml = zf.read(name).decode("utf-8", "ignore")
        except Exception:
            continue
        runs = re.findall(r"<a:t>(.*?)</a:t>", xml, re.S)
        if runs:
            txt = " ".join(re.sub(r"\s+", " ", r).strip() for r in runs)
            out.append(f"[{name.rsplit('/', 1)[-1]}] {txt}")
    return "\n".join(out)[:20000]


def _flatten(im):
    """Composite onto WHITE before anything else.

    Report screenshots are saved with the label column transparent — the text is
    dark pixels over alpha. .convert("RGB") maps transparent to BLACK, so the
    keyword column became black text on black and vanished. That is why an
    import returned "ranking numbers without keyword labels" and dropped 10 of
    19 keywords: the labels were always in the file, and this function was
    erasing them (2026-08-05).
    """
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, im).convert("RGB")
    return im.convert("RGB") if im.mode != "RGB" else im


def _encode_jpeg(im, quality=88):
    import io
    im = _flatten(im)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _tile_image(raw):
    """One source image -> request-ready JPEGs.

    Two failures drove this shape (both Ski Barn, 2026-08-05):

    1. Sent whole, a 4094x3379 slide is downsampled by the API to 0.38x and an
       11px table row becomes 4px. Only one of the two keyword tables was
       readable.
    2. Split into columns, the KEYWORD COLUMN lives only in the leftmost tile.
       Every other tile is a field of numbers with nothing to attach them to,
       and the reader correctly refused them: "ranking numbers without keyword
       labels". A 2030px-wide table lost its labels on the second tile.

    So: only split horizontally when the alternative is a severe downscale, and
    when we do, STITCH the label column onto every slice so each tile is
    self-describing. Anything moderately wide is simply scaled to fit — 2030px
    to 1568px is 0.77x and perfectly legible, and keeps rows whole.
    """
    try:
        from PIL import Image
        import io
        im = _flatten(Image.open(io.BytesIO(raw)))
        w, h = im.size
        edge = _REPORT_TILE_EDGE

        def bands(src):
            """Full-width horizontal slices, scaled to fit. Rows stay intact."""
            sw, sh = src.size
            scale = min(1.0, edge / float(sw))
            band_h = int(edge / scale) if scale < 1.0 else edge
            if sh <= band_h:
                return [_encode_jpeg(_fit_width(src, edge))]
            step = max(1, int(band_h * (1.0 - _REPORT_TILE_OVERLAP)))
            ys = list(range(0, max(1, sh - band_h) + 1, step)) or [0]
            if ys[-1] + band_h < sh:
                ys.append(max(0, sh - band_h))
            return [_encode_jpeg(_fit_width(src.crop((0, y, sw, min(sh, y + band_h))), edge))
                    for y in ys][:_REPORT_TILES_PER_SOURCE]

        if w <= _REPORT_STITCH_ABOVE:
            return bands(im)

        # Very wide: slice into column groups, each carrying the label column.
        label_w = max(1, int(w * _REPORT_LABEL_FRACTION))
        slice_w = max(1, edge - label_w)
        out, x = [], label_w
        while x < w and len(out) < _REPORT_TILES_PER_SOURCE:
            right = im.crop((x, 0, min(w, x + slice_w), h))
            labels = im.crop((0, 0, label_w, h))
            stitched = Image.new("RGB", (label_w + right.size[0], h), "white")
            stitched.paste(labels, (0, 0))
            stitched.paste(right, (label_w, 0))
            out.extend(bands(stitched))
            x += max(1, int(slice_w * (1.0 - _REPORT_TILE_OVERLAP)))
        return out[:_REPORT_TILES_PER_SOURCE] or bands(im)
    except Exception:
        return [raw]


def _fit_width(im, max_w):
    from PIL import Image
    if im.size[0] <= max_w:
        return im
    ratio = max_w / float(im.size[0])
    return im.resize((max_w, max(1, int(im.size[1] * ratio))), Image.LANCZOS)


def _report_images(filename, data):
    """Candidate images from the upload, largest first. A .pptx carries its
    screenshots in ppt/media; a bare image is itself."""
    lower = (filename or "").lower()
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return [data]
    if lower.endswith((".pptx", ".potx")):
        import io, zipfile
        try:
            from PIL import Image
        except Exception:
            Image = None
        scored = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for n in zf.namelist():
                if not (n.startswith("ppt/media/")
                        and n.lower().endswith((".png", ".jpg", ".jpeg"))):
                    continue
                raw = zf.read(n)
                px = 0
                if Image is not None:
                    try:
                        px = Image.open(io.BytesIO(raw)).size[0] * \
                             Image.open(io.BytesIO(raw)).size[1]
                    except Exception:
                        px = 0
                if px and px < _REPORT_MIN_PIXELS:
                    continue                      # icon, arrow, logo
                scored.append((px or len(raw), raw))
        # Biggest by pixel area first — that is where dense tables live.
        return [raw for _px, raw in sorted(scored, key=lambda x: -x[0])]
    return []


def _report_text(filename, data):
    lower = (filename or "").lower()
    if lower.endswith((".pptx", ".potx")):
        import io, zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # Slide text first, then any table that arrived as a metafile.
                # The metafile text is the ranking table itself on Windows decks,
                # so it must not be truncated away by the slide-text cap.
                parts = [_pptx_slide_text(zf)]
                try:
                    mf = _pptx_metafile_text(zf)
                except Exception:
                    app.logger.exception("_pptx_metafile_text failed")
                    mf = ""
                if mf:
                    parts.append(mf)
                return "\n".join(x for x in parts if x)
        except Exception:
            return ""
    if lower.endswith((".txt", ".csv", ".md")):
        return data.decode("utf-8", "ignore")[:20000]
    return ""


_REPORT_SCHEMA_PROMPT = """You are reading an SEO performance report for a client.
Extract ONLY what is actually present. Never infer, never complete a pattern, never
invent a plausible keyword. An empty list is the correct answer when the report does
not show something.

Return ONLY valid JSON, no prose:
{
  "period": "the reporting period as written, e.g. July 2026",
  "monthly_spend": null,
  "monthly_revenue": null,
  "markets": ["City, ST for every location column or named market"],
  "state": "two-letter state the client operates in, or null if genuinely unclear",
  "keywords": ["exact keyword text as written, one per row of any ranking table"],
  "notes": ["anything a pricing reviewer should know, one short sentence each"],
  "rankings": [{"keyword": "...", "best_position": 3, "markets_top10": 4}]
}

EMIT THE FIELDS IN THAT ORDER. "rankings" is last on purpose: it is the longest
section and the least important, so if you run out of room the loss falls there
rather than on the keyword list.

Rules:
- Keyword tables are often SCREENSHOTS. Read them from the images.
- A block headed "table read from metafile" is a ranking table that was pasted from
  Excel and has been decoded to TEXT for you. It is tab-separated: the first column is
  the keyword, the remaining columns are that keyword's position in each market, in the
  order the header row lists them. Trust it over any image — it is exact, not OCR.
- THERE ARE USUALLY SEVERAL TABLES, sometimes stacked in one screenshot.
- LARGE SCREENSHOTS ARE SUPPLIED AS OVERLAPPING TILES of the same picture. On a
  very wide table the KEYWORD COLUMN IS COPIED ONTO THE LEFT EDGE OF EVERY TILE,
  so a tile showing positions always carries its own labels — read them together
  rather than reporting the table as unlabelled. Tiles
  repeat content on purpose: a row cut by one tile's edge appears whole in its
  neighbour. Read every tile, MERGE what they show, and do not count a keyword
  twice because it appeared in two tiles. If a tile shows a keyword column
  without its position columns, pair it with the overlapping tile that has them.
- Read EVERY table in EVERY image and merge them. A retailer often has one table per product family
  (e.g. ski gear in one, patio/BBQ in another) — returning only the clearest
  table is a failure. If a row is genuinely illegible, say so in notes rather
  than dropping the table silently.
- Keep placeholders exactly as printed: "bbq grills <cityname>" stays as-is.
- A position of 100 (or 100+) usually means NOT RANKING.
- KEEP THE OUTPUT COMPACT. Do NOT emit one row per keyword-per-market — that is
  hundreds of rows and the response gets cut off mid-JSON. For each keyword give
  ONE row: its best position across the markets, and how many markets have it in
  the top 10. Keywords and markets are the important part; positions are context.
- monthly_spend is what the CLIENT PAYS for the campaign. Revenue, traffic value
  and ad spend are NOT campaign spend — leave it null unless the report states a fee.
- markets: only real places used as columns or headings, not every city mentioned.
- ALWAYS QUALIFY A MARKET WITH ITS STATE, even when the column header does not.
  Report columns usually read bare ("Wayne", "Paramus"), and a bare city name is
  ambiguous — there is a Wayne in NJ, PA and MI — so the quote is built without a
  state suffix and the rank check looks in the wrong place. Infer the state from
  the rest of the report: the client's own name, the business description, other
  place names, geo-qualified keywords like "ski shop paramus nj". Return
  "Wayne, NJ", not "Wayne". Set "state" to the client's main state as well. If a
  market is plainly in a different state from the others (e.g. New York City
  alongside New Jersey towns), qualify it with its OWN state.
- If a table appears twice (start vs current), use the CURRENT/most recent one for
  rankings and say so in notes."""


@app.route("/api/import_report", methods=["POST"])
@_json_error_guard
def api_import_report():
    """Read an existing SEO report and return what it contains as SUGGESTIONS."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on this deploy, so "
                                 "report reading is unavailable."}), 400
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "No file received."}), 400
    data = f.read()
    if not data:
        return jsonify({"error": "That file is empty."}), 400
    if len(data) > 25 * 1024 * 1024:
        return jsonify({"error": "File is larger than 25MB — export fewer slides."}), 400

    imgs = _report_images(f.filename, data)
    text = _report_text(f.filename, data)
    if not imgs and not text.strip():
        return jsonify({"error": f"Nothing readable in {f.filename!r}. Supported: "
                                 ".pptx, .png, .jpg, .txt, .csv."}), 400

    # ROUND-ROBIN across source images. Taking them in order let the first,
    # densest slide spend the entire budget, so the small single-table
    # screenshots later in the deck were never sent at all.
    per_source = [_tile_image(raw) for raw in imgs]
    content, n_sent, depth = [], 0, 0
    while n_sent < _REPORT_MAX_IMAGES and any(len(t) > depth for t in per_source):
        for tiles in per_source:
            if n_sent >= _REPORT_MAX_IMAGES:
                break
            if len(tiles) > depth:
                content.append({"type": "image",
                                "source": {"type": "base64",
                                           "media_type": "image/jpeg",
                                           "data": base64.b64encode(tiles[depth]).decode()}})
                n_sent += 1
        depth += 1
    content.append({"type": "text",
                    "text": _REPORT_SCHEMA_PROMPT
                            + ("\n\nTEXT FOUND IN THE FILE:\n" + text if text.strip()
                               else "\n\n(No usable text layer — read the images.)")})
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                             "max_tokens": 16000, "temperature": 0,
                             "messages": [{"role": "user", "content": content}]}),
            timeout=120)
        resp.raise_for_status()
        body = resp.json()
        txt = "".join(b.get("text", "") for b in body.get("content", [])
                      if b.get("type") == "text").strip()
        truncated = body.get("stop_reason") == "max_tokens"
    except Exception as e:
        return jsonify({"error": f"Report read failed: {e}"}), 502

    def _salvage(t):
        """A truncated reply is cut off in the LAST array it was writing, so the
        earlier ones are complete and worth keeping. Reading 50 keywords and
        then discarding all of them over a missing brace is the wrong trade
        (2026-08-06)."""
        got = {}
        for key in ("keywords", "markets", "notes"):
            mm = re.search(r'"%s"\s*:\s*\[(.*?)\]' % key, t, re.S)
            if mm:
                got[key] = [x.strip().strip(",").strip()
                            for x in re.findall(r'"((?:[^"\\]|\\.)*)"', mm.group(1))]
        for key in ("period",):
            mm = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % key, t, re.S)
            if mm:
                got[key] = mm.group(1)
        for key in ("monthly_spend", "monthly_revenue"):
            mm = re.search(r'"%s"\s*:\s*([0-9.]+)' % key, t)
            if mm:
                try:
                    got[key] = float(mm.group(1))
                except Exception:
                    pass
        return got

    m = re.search(r"\{.*\}", txt, re.S)
    out, partial = None, False
    if m:
        try:
            out = json.loads(m.group(0))
        except Exception:
            out = None
    if out is None:
        out = _salvage(txt)
        partial = True
        if not out.get("keywords") and not out.get("markets"):
            return jsonify({"error": ("The reader's reply was cut off before "
                                      "anything usable came back."
                                      if truncated else
                                      "The reader did not return usable JSON."),
                            "raw": txt[:400]}), 502

    # Normalise, and cap so a 200-row report can't flood the seed field.
    kws = [str(x).strip() for x in (out.get("keywords") or []) if str(x).strip()][:120]
    mkts = [str(x).strip() for x in (out.get("markets") or []) if str(x).strip()][:40]
    ranks = [r for r in (out.get("rankings") or []) if isinstance(r, dict)][:600]
    if partial or truncated:
        out.setdefault("notes", []).insert(0,
            "The reader's reply was cut off, so this is a partial read — the "
            "keyword and market lists came through but position detail may be "
            "incomplete. Check the list against the report before relying on it.")
    return jsonify({
        "ok": True,
        "partial": bool(partial or truncated),
        "filename": f.filename,
        # Size travels with the extraction so a quote can say WHICH file it read
        # without storing the file (see rememberReport in the template).
        "size": len(data),
        "images_read": n_sent,
        "sources_read": len(imgs),
        "text_chars": len(text),
        "keywords": kws,
        "markets": mkts,
        "rankings": ranks,
        "monthly_spend": out.get("monthly_spend"),
        "monthly_revenue": out.get("monthly_revenue"),
        "period": (out.get("period") or "")[:120],
        "state": (str(out.get("state") or "").strip().upper()[:2] or None),
        "notes": [str(n)[:300] for n in (out.get("notes") or [])][:8],
    })


@app.route("/api/metrics", methods=["POST"])
@_json_error_guard
def api_metrics():
    """Step 2 — competitive adder from head-term bids. One search_volume call."""
    d = request.get_json(force=True)
    head    = [{"keyword": k} for k in d.get("head", [])]
    markets = usable_markets(d.get("geo_values") or [])
    # phrase geos must be strippable so bare-term metrics resolve for
    # "managed it services south jersey" -> "managed it services"
    # measure_first, not primary_first: the CPC adder is a localised lookup, so
    # it belongs in the client's home state rather than in whichever market
    # happens to carry the most demand (2026-08-07).
    markets = measure_first(markets, (d.get("state") or "").strip(),
                            d.get("primary_market"))
    markets = markets + [p.strip() for p in d.get("phrase_geos", []) if p and p.strip()]
    state   = derive_state(markets, (d.get("state") or "").strip())
    # Same national-demand basis Step 1 used, resolved the same way rather than
    # trusted from the client, so the two steps cannot disagree.
    nat, _nr = resolve_national_demand(
        industry=(d.get("industry") or ""),
        band=d.get("geo_scope", d.get("band", "")),
        manual=bool(d.get("national_demand")) or bool(d.get("ecommerce")),
        markets=markets, goal=(d.get("goal") or ""))
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
    markets = usable_markets(d.get("geo_values") or [])
    state   = derive_state(markets, (d.get("state") or "").strip())
    markets = measure_first(markets, state, d.get("primary_market"))
    top_n   = CFG["zero_ranking_top_n"]
    depth   = max(top_n, 10)
    nat, _r = resolve_national_demand(d.get("industry") or "",
                                      d.get("geo_scope") or d.get("band") or "",
                                      bool(d.get("national_demand")),
                                      markets=markets,
                                      goal=(d.get("goal") or ""))
    loc     = rank_location(markets, state, nat)
    # Same per-market rule as the live path: a row naming Morristown is measured
    # in Morristown. Task mode is what the retry button uses, so leaving it on a
    # single location would silently mix two measurement bases in one table.
    cities  = {str(k.get("kw") or ""): str(k.get("city") or "")
               for k in (d.get("rows") or []) if isinstance(k, dict)}

    def _loc_for(kw):
        if nat:
            return loc
        city = cities.get(kw, "")
        named = (next((m for m in markets
                       if parse_market(m, state)[0].strip().lower() == city.lower()),
                      city) if city else market_for_keyword(kw, markets, state))
        return rank_location([named], state, False) if named else loc

    payload = [{"keyword": kw, "location_name": _loc_for(kw), "language_code": "en",
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
    # Report the SAME per-market location the live path reports. Task mode is
    # what the slow tail falls back to, and on a cold run that can be every row
    # — so a note reading "Measured in Knoxville" here made the whole per-market
    # change look like it had not shipped. (2026-08-10)
    note = rank_location_note(markets, state, nat)
    locs = sorted({_loc_for(kw) for kw in kws})
    if len(locs) > 1:
        pretty = [l.replace(",United States", "").replace(",", ", ") for l in locs]
        note = {"location": ", ".join(pretty), "scope": "per_market",
                "note": "Each keyword was measured in the market it names — "
                        + ", ".join(pretty) + "."}
    for r in out:
        r["loc"] = (_loc_for(r.get("kw") or "")
                    .replace(",United States", "").replace(",", ", "))
    return jsonify({"tasks": out, "rank_location": note})


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


@app.route("/api/rank_location", methods=["POST"])
@_json_error_guard
def api_rank_location():
    """Where a rank check WOULD be measured, without spending a lookup. Lets
    the Step 3 panel state the location even for a run served entirely from
    cache or restored from a saved quote."""
    d = request.get_json(force=True) or {}
    markets = usable_markets(d.get("geo_values") or [])
    state = derive_state(markets, (d.get("state") or "").strip())
    markets = measure_first(markets, state, d.get("primary_market"))
    nat, reason = resolve_national_demand(d.get("industry") or "",
                                          d.get("geo_scope") or d.get("band") or "",
                                          bool(d.get("national_demand")),
                                          markets=markets,
                                          goal=(d.get("goal") or ""))
    out = rank_location_note(markets, state, nat)
    out["national_demand"] = nat
    out["national_demand_reason"] = reason
    return jsonify(out)


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

def serp_top_domains(kw, loc, client_dom="", top_n=5, deadline=None):
    """The first few organic domains for one query, plus where the client sits.

    The collision check can say a bare acronym's volume looks wrong; only the
    result page can say whose it is. Cheapest possible answer: one SERP, the top
    handful of domains, and whether the client appears at all. If LACP returns
    cisco.com and juniper.net, the operator has their answer without leaving the
    page. (2026-08-10)
    """
    depth = max(int(CFG.get("zero_ranking_top_n", 100)), 10)
    payload = [{"keyword": kw, "location_name": loc, "language_code": "en",
                "depth": depth}]
    # Retry once. A single 14s read timeout left LACP — the biggest number in the
    # list and the whole reason the check exists — as "lookup failed", with the
    # operator's most important question unanswered. (2026-08-10)
    last = None
    for attempt in range(2):
        remaining = (deadline - time.time()) if deadline else 20
        if remaining < 5:
            raise last or TimeoutError("acronym SERP budget exhausted")
        try:
            data = dfs_post("/serp/google/organic/live/regular", payload,
                            timeout=min(14 if attempt == 0 else remaining - 1,
                                        remaining, 20))
            break
        except Exception as e:
            last = e
    else:
        raise last
    task0 = ((data or {}).get("tasks") or [{}])[0] or {}
    if task0.get("status_code") not in (20000, None):
        raise RuntimeError(f"{task0.get('status_code')}: {task0.get('status_message')}")
    items = ((task0.get("result") or [{}])[0] or {}).get("items") or []
    doms, client_pos = [], None
    for it in items:
        if it.get("type") != "organic":
            continue
        d = (it.get("domain") or "").lower().replace("www.", "")
        if client_dom and client_dom in d and client_pos is None:
            client_pos = it.get("rank_absolute")
        if d and d not in doms and len(doms) < top_n:
            doms.append(d)
    return doms, client_pos


def claude_replacements(removed, kept_seeds, brand="", domain="",
                        business_desc="", topic="", n=6):
    """Alternative phrasings for a service whose term had to be deleted.

    Removing a colliding acronym can leave a service uncovered — "lacp" goes and
    nothing in the list speaks to lateral assessment any more. Rebuilding refills
    the slot, but that re-runs the whole step for one gap. This proposes named
    candidates instead, inside the same topic, which are then MEASURED before any
    of them is offered: a suggestion with no search volume is the exact mistake
    that produced NASSCO's first keyword list. (2026-08-10)
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not removed:
        return []
    prompt = f"""A keyword list for {brand or domain or "a business"} had to drop the term "{removed}".
{f'The business describes itself as: {business_desc}' if business_desc else ''}
{f'That term belonged to the topic: {topic}' if topic else ''}
Its other terms are: {", ".join(str(x) for x in (kept_seeds or [])[:25])}

Propose {n} SHORT search phrases that cover the same service as "{removed}" but that
real buyers type into Google. Rules:
1. Phrases people SEARCH, not descriptions of the organisation. "manhole inspection
   certification" not "manhole assessment certification program provider".
2. 2-5 words. No city names, no brand names other than this client's own.
3. Stay on the same service as the removed term. Do not drift to its siblings.
4. Prefer the words an outsider would use over the client's internal naming.

Return ONLY JSON: {{"terms": ["...", "..."]}}"""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=json.dumps({
                "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": 600, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}), timeout=25)
        resp.raise_for_status()
        body = resp.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        terms = json.loads(text).get("terms") or []
    except Exception:
        app.logger.exception("claude_replacements failed")
        return []
    out, seen = [], {str(removed).strip().lower()}
    for t in terms:
        t = clean_kw(strip_placeholders(str(t).strip().lower()))
        if t and t not in seen and 1 < len(t.split()) <= 6:
            seen.add(t)
            out.append(t)
    return out[:n]


@app.route("/api/replacement_terms", methods=["POST"])
@_json_error_guard
def api_replacement_terms():
    """Measured candidates to fill the slot a deleted term left behind."""
    d = request.get_json(force=True) or {}
    removed = (d.get("removed") or "").strip()
    if not removed:
        return jsonify({"terms": []})
    markets = usable_markets(d.get("geo_values") or [])
    state = derive_state(markets, (d.get("state") or "").strip())
    nat = bool(d.get("national_demand")) or not markets
    cands = claude_replacements(removed,
                               [x for x in (d.get("seeds") or []) if x],
                               d.get("brand") or "", d.get("domain") or "",
                               d.get("business_desc") or "",
                               d.get("topic") or "")
    if not cands:
        return jsonify({"terms": [], "error": "no candidates proposed"})
    # MEASURE before offering. Same rule the acronym chips follow.
    try:
        vols, _pc, verr = fetch_local_volume(cands, [] if nat else markets, state,
                                             national=nat)
    except Exception as e:
        return jsonify({"terms": [], "error": str(e)[:120]})
    floor = int(CFG.get("replacement_min_volume", 20))
    rows = [{"term": t, "volume": int((vols or {}).get(t, 0) or 0)} for t in cands]
    rows.sort(key=lambda r: -r["volume"])
    return jsonify({"terms": [r for r in rows if r["volume"] >= floor],
                    "rejected": [r for r in rows if r["volume"] < floor],
                    "basis": "US national" if nat else "targeted cities",
                    "error": verr})


@app.route("/api/acronym_serp", methods=["POST"])
@_json_error_guard
def api_acronym_serp():
    """Who actually owns each flagged acronym's result page."""
    d = request.get_json(force=True) or {}
    terms = [str(t).strip() for t in (d.get("terms") or []) if str(t).strip()][:8]
    if not terms:
        return jsonify({"results": []})
    dom = (d.get("domain") or "").replace("https://", "").replace("http://", "")
    dom = dom.replace("www.", "").strip("/")
    markets = usable_markets(d.get("geo_values") or [])
    state = derive_state(markets, (d.get("state") or "").strip())
    nat, _r = resolve_national_demand(d.get("industry") or "",
                                      d.get("geo_scope") or "",
                                      bool(d.get("national_demand")),
                                      markets=markets,
                                      goal=(d.get("goal") or ""))
    # An acronym's ownership is a national question — "who does Google think this
    # word belongs to" — so it is asked nationally even on a local quote.
    loc = "United States"
    _ = (nat, state, markets)
    out = []
    budget = time.time() + max(18, REQUEST_BUDGET_S - 12)
    with ThreadPoolExecutor(max_workers=min(4, len(terms))) as ex:
        futs = {ex.submit(serp_top_domains, t, loc, dom, 5, budget): t
                for t in terms}
        for fut in futs:
            t = futs[fut]
            try:
                doms, pos = fut.result()
                out.append({"term": t, "domains": doms, "client_pos": pos})
            except Exception as e:
                out.append({"term": t, "domains": [], "client_pos": None,
                            "error": str(e)[:120]})
    order = {t: i for i, t in enumerate(terms)}
    out.sort(key=lambda r: order.get(r["term"], 99))
    return jsonify({"results": out, "location": loc, "client_domain": dom})


@app.route("/api/rankings", methods=["POST"])
@_json_error_guard
def api_rankings():
    """Step 3 — rank-check ONE small batch of keywords (frontend loops batches).
    Each call is short: a few parallel SERP lookups."""
    d = request.get_json(force=True)
    batch   = d.get("batch", [])
    domain  = (d.get("domain") or "").strip()
    markets = usable_markets(d.get("geo_values") or [])
    state   = derive_state(markets, (d.get("state") or "").strip())
    brand   = (d.get("brand") or "").strip()
    dom = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    markets = measure_first(markets, state, d.get("primary_market"))
    top_n = CFG["zero_ranking_top_n"]
    nat, _r = resolve_national_demand(d.get("industry") or "",
                                      d.get("geo_scope") or d.get("band") or "",
                                      bool(d.get("national_demand")),
                                      markets=markets,
                                      goal=(d.get("goal") or ""))
    loc = rank_location(markets, state, nat)
    # MEASURE EACH KEYWORD IN THE MARKET IT NAMES.
    #
    # Every row used to be checked from the primary market, so Knoxville's SERP
    # answered for "junk removal morristown tn" and "junk removal sevierville tn"
    # too. That produced 32/32 ranked and, through recommend_addons, "0 add-on
    # markets recommended" — a claim that the client already has a presence in
    # all six markets, from a test that only ever looked at one of them. The
    # cheap version of the question is the wrong question. Same API cost either
    # way: one call per keyword, just pointed at the right place. (2026-08-10)
    #
    # `batch` accepts plain strings (older clients) or {kw, city} objects.
    per_kw_loc, order = {}, []
    for item in batch:
        if isinstance(item, dict):
            kw = str(item.get("kw") or "").strip()
            city = str(item.get("city") or "").strip()
        else:
            kw, city = str(item or "").strip(), ""
        if not kw:
            continue
        order.append(kw)
        # A national row, a site term or a long-tail top-up carries no market;
        # those stay on the primary one, which is what they are asking about.
        mk_named = ""
        if not nat:
            if city:
                mk_named = next((m for m in markets
                                 if parse_market(m, state)[0].strip().lower()
                                 == city.lower()), city)
            else:
                # No tag on the row — read the market off the keyword text.
                mk_named = market_for_keyword(kw, markets, state)
        per_kw_loc[kw] = (rank_location([mk_named], state, False)
                          if mk_named else loc)
    batch = order
    results, paa = [], []
    hits = {}
    to_fetch = []
    err_msgs = []
    for kw in batch:
        c = _rank_cache_get(kw, per_kw_loc.get(kw, loc), dom, top_n)
        if c != "MISS":
            hits[kw] = c
        else:
            to_fetch.append(kw)
    try:
        with ThreadPoolExecutor(max_workers=CFG["rank_check_workers"]) as ex:
            _budget = int(CFG.get("rank_batch_budget_s") or 0) or max(20, REQUEST_BUDGET_S - 15)
            batch_deadline = time.time() + _budget
            futs = {ex.submit(_serp_one, kw, dom, markets, state, brand, top_n,
                              batch_deadline,
                              per_kw_loc.get(kw, loc)): kw for kw in to_fetch}
            done = {}
            for fut in futs:
                kw = futs[fut]
                try:
                    pos, qs = fut.result()
                    err = False
                except Exception as e:
                    # lookup FAILED — record it as unknown, NOT as "Not Found".
                    # Counting a failed call as not-ranking would inflate the
                    # zero-ranking percentage and therefore the price.
                    pos, qs, err = None, [], True
                    # Keep WHY. "40501 location_name not found" and "read
                    # timeout" both show as "check failed", and they call for
                    # opposite responses: fix the geo, or press retry.
                    err_msgs.append(str(e)[:160])
                done[kw] = (pos, qs, err)
                if not err:
                    _rank_cache_put(kw, per_kw_loc.get(kw, loc), dom, top_n, pos)
        for kw in batch:
            if kw in hits:
                pos, qs, err = hits[kw], [], False
            else:
                pos, qs, err = done.get(kw, (None, [], True))
            results.append({"kw": kw,
                            "pos": ("—" if err else (pos if pos is not None else "Not Found")),
                            "ranked_top": (not err and pos is not None and pos <= top_n),
                            "error": err,
                            # A batch that answers instantly is a batch that
                            # never called Google. Say so, rather than leaving
                            # the operator to wonder whether the check ran.
                            "cached": kw in hits})
            paa.extend(qs)
    except requests.HTTPError as e:
        return jsonify({"error": f"DataForSEO error: {e}."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500
    # The most common failure reason, verbatim. A batch of "40501 Invalid Field:
    # 'location_name'" means the geo is wrong and retrying will fail identically;
    # a batch of timeouts means press retry. Same "check failed" row either way,
    # so the message has to reach the panel.
    top_err = ""
    if err_msgs:
        top_err = max(set(err_msgs), key=err_msgs.count)
    note = rank_location_note(markets, state, nat)
    # Say which markets were actually measured. "Measured in Knoxville" while
    # half the rows were checked in Morristown and Sevierville would be worse
    # than saying nothing.
    locs = sorted({v for v in per_kw_loc.values()})
    if len(locs) > 1:
        pretty = [l.replace(",United States", "").replace(",", ", ") for l in locs]
        note = {"location": ", ".join(pretty), "scope": "per_market",
                "note": "Each keyword was measured in the market it names — "
                        + ", ".join(pretty)
                        + ". Checking every row from one city answers a different "
                          "question, and the add-on recommendation reads presence "
                          "per market off this table."}
    for r in results:
        r["loc"] = (per_kw_loc.get(r["kw"], loc)
                    .replace(",United States", "").replace(",", ", "))
    return jsonify({"results": results, "paa": list(dict.fromkeys(paa)),
                    "n_cached": len(hits), "n_fetched": len(to_fetch),
                    "n_errors": len(err_msgs), "error_reason": top_err,
                    "rank_location": note})

@app.route("/api/qualify_markets", methods=["POST"])
@_json_error_guard
def api_qualify_markets():
    """Attach the right state to each bare market name.

    A report's column headers read "Wayne", "Paramus", "New York City" with no
    states. The importer used to append the report's own state to all of them,
    which produced "New York City, NJ" — a market that does not exist, pointing
    the rank check and the CPC lookup at nothing (2026-08-07).

    The ZIP index already knows. Precedence:
      1. the market already carries a state -> leave it alone
      2. the city name resolves to exactly ONE state -> use it, whatever the
         report said (this is what fixes New York City)
      3. several candidates and the report's state is one of them -> report's
      4. several candidates, report's state is NOT one -> report's, flagged
      5. no candidates at all -> report's if given, else flagged as unresolved

    No external calls; runs off bundled ZIP data.
    """
    d = request.get_json(force=True) or {}
    fallback = (d.get("state") or "").strip()
    fb_abbr = (STATE_ABBREV.get(fallback.lower(), "") or
               (fallback if len(fallback) == 2 else "")).upper()
    idx = _zip_index()
    by_city = {}
    for (city, st) in idx:
        by_city.setdefault(city, set()).add(st)

    out = []
    dropped = []
    for raw in (d.get("markets") or []):
        m = str(raw or "").strip()
        if not m:
            continue
        # A ranking table's market column carries "near me" rows, because the
        # agency tracked "junk removal near me" as its own line. Qualifying it
        # produced "near me, TN" — which then became markets[0] and therefore
        # the location_name on every SERP call. Never offer it. (2026-08-10)
        if is_non_place_geo(m):
            dropped.append(m)
            continue
        already = re.search(r",\s*([A-Za-z]{2})\s*$", m)
        if already:
            out.append({"input": m, "qualified": m,
                        "abbr": already.group(1).upper(),
                        "source": "given", "certain": True})
            continue
        city = m.lower()
        # CITY_STATE is the curated metro map and outranks the ZIP scan.
        curated = CITY_STATE.get(city, "")
        cands = sorted(by_city.get(city, set()))
        if curated:
            # STATE_ABBREV stores lowercase; a pill reads "Philadelphia, PA".
            ab = (STATE_ABBREV.get(curated.lower(), "") or "").upper()
            out.append({"input": m, "qualified": f"{m}, {ab}" if ab else m,
                        "abbr": ab, "source": "known metro", "certain": True})
        elif len(cands) == 1:
            out.append({"input": m, "qualified": f"{m}, {cands[0]}",
                        "abbr": cands[0], "source": "only one state has it",
                        "certain": True})
        elif cands and fb_abbr in cands:
            out.append({"input": m, "qualified": f"{m}, {fb_abbr}",
                        "abbr": fb_abbr, "source": "report's state",
                        "certain": True})
        elif cands and fb_abbr:
            out.append({"input": m, "qualified": f"{m}, {fb_abbr}",
                        "abbr": fb_abbr, "source": "report's state",
                        "certain": False,
                        "note": f"{m} exists in {', '.join(cands[:6])} but not "
                                f"{fb_abbr} — check this one."})
        elif fb_abbr:
            out.append({"input": m, "qualified": f"{m}, {fb_abbr}",
                        "abbr": fb_abbr, "source": "report's state",
                        "certain": False,
                        "note": f"{m} isn't in the city database — using the "
                                f"report's state, {fb_abbr}."})
        else:
            out.append({"input": m, "qualified": m, "abbr": "",
                        "source": "", "certain": False,
                        "note": f"No state for {m}, and the report didn't say."})
    return jsonify({"markets": out, "dropped": dropped})


@app.route("/api/build")
def api_build():
    """What is actually on disk, file by file. Read by the header's src chip."""
    return jsonify({"build": BUILD_STR, "source_fingerprint": SOURCE_FP,
                    "files": source_file_hashes()})


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
    entered = [m for m in (d.get("geo_values") or []) if m and m.strip()]
    state = (d.get("state") or "").strip()
    if not entered:
        # An empty geo list is exactly when the band recommendation matters most:
        # nothing is left to describe, yet the dropdown may still read
        # "Non-contiguous region" and that is what sets the pricing anchor. The
        # early return skipped the suggestion entirely. (2026-08-10)
        return jsonify({"cities": 0, "entered": 0, "markets": 0, "groups": [],
                        "unlocated": [], "non_place": [], "state_geos": [],
                        "overlaps": [], "covered": [],
                        "radius": int(CFG.get("market_radius_miles", 25)),
                        "located": 0,
                        "scope_suggestion": suggest_geo_scope(
                            [], state, bool(d.get("national_demand")))})
    # Non-places cover nothing, so they cannot be markets. Reported back so the
    # operator can see WHY the count moved rather than watching a pill silently
    # stop mattering.
    non_place = [m for m in entered if is_non_place_geo(m)]
    # A whole state is not a market either. Reported separately from non-places
    # because the fix is different: a state usually means the operator wants
    # every city in it, which is a Statewide scope, not a pill.
    state_geos = [m for m in entered if m not in non_place and is_state_geo(m)]
    mk = [m for m in entered if m not in non_place and m not in state_geos]
    overlaps = geo_overlaps(entered, state)
    covered = sorted({c for o in overlaps if o["kind"] in ("county", "duplicate")
                      for c in o["contained"]})
    if not mk:
        return jsonify({"cities": len(entered), "markets": 0, "groups": [],
                        "unlocated": [], "non_place": non_place,
                        "state_geos": state_geos,
                        "overlaps": overlaps, "covered": covered,
                        "radius": int(CFG.get("market_radius_miles", 25)),
                        "located": 0, "scope_suggestion": {}})
    groups, located, unlocated = group_by_distance(mk, state)
    named = []
    for g in sorted(groups, key=len, reverse=True):
        # Prefer a real town over a county as the market's name: the anchor is
        # what the keyword grid and the rank check are built on, and nobody
        # searches "junk removal knox county tn".
        anchor = market_anchor(g, state)
        named.append({"anchor": anchor,
                      "members": [anchor] + [m for m in g if m != anchor],
                      "size": len(g)})
    return jsonify({
        "cities": len(mk),
        "entered": len(entered),
        "markets": len(groups) + len(unlocated),
        "groups": named,
        "unlocated": unlocated,
        "non_place": non_place,
        "state_geos": state_geos,
        "overlaps": overlaps,
        "covered": covered,
        "radius": int(CFG.get("market_radius_miles", 25)),
        "located": len(located),
        # The band the markets themselves imply. A suggestion, not an
        # assignment: the operator's dropdown still picks the pricing anchor.
        "scope_suggestion": suggest_geo_scope(mk, state,
                                              bool(d.get("national_demand"))),
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
    markets = usable_markets(d.get("geo_values") or [])
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
                     addon_override=d.get("addon_override"),
                     goal=(d.get("goal") or ""))
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
        "goal_options": GOAL_OPTIONS,
        "goal_scope": GOAL_SCOPE,
        "service_min_volume": CFG.get("service_min_volume", 0),
        "service_upgrade_ratio": CFG.get("service_upgrade_ratio", 0),
        "service_max_swaps": CFG.get("service_max_swaps", 3),
        "store_intent_tier_boost": CFG.get("store_intent_tier_boost", 3.0),
        "grid_target_keywords": CFG.get("grid_target_keywords", 32),
        "grid_min_services": CFG.get("grid_min_services", 4),
        "grid_max_services": CFG.get("grid_max_services", 20),
        "grid_max_cities": CFG.get("grid_max_cities", 10),
        "metro_no_suffix_zips": CFG.get("metro_no_suffix_zips", 25),
        "metro_no_suffix_share": CFG.get("metro_no_suffix_share", 0.6),
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
                            ("grid_max_services", int), ("grid_max_cities", int),
                            ("metro_no_suffix_zips", int)]:
            if key in d and d[key] not in (None, ""):
                CFG[key] = caster(d[key])
        for key, caster in [("service_min_volume", int), ("service_max_swaps", int),
                            ("service_upgrade_ratio", float),
                            ("metro_no_suffix_share", float),
                            ("store_intent_tier_boost", float),
                            ("zero_ranking_bonus", int), ("zero_ranking_top_n", int),
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
    markets = usable_markets(d.get("geo_values") or [])
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
    markets = usable_markets(d.get("geo_values") or [])
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
    cities = usable_markets(d.get("geo_values") or [])
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
                t = clean_kw(strip_placeholders(strip_proximity(v.strip().lower()))).strip()
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

_ACRONYM_STOP = {
    "USA", "US", "FAQ", "FAQS", "PDF", "HTML", "HTTP", "HTTPS", "WWW", "URL",
    "CEO", "CFO", "COO", "CTO", "HR", "IT", "PR", "AI", "SEO", "PPC", "ROI",
    "AM", "PM", "EST", "CST", "PST", "EDT", "CDT", "PDT", "MST", "UTC",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT",
    "NOV", "DEC", "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "AND", "THE", "FOR", "ALL", "NEW", "TOP", "OUR", "YOU", "NOW", "MORE",
    "LOGIN", "SIGN", "JOIN", "HOME", "ABOUT", "BLOG", "NEWS", "SHOP", "CART",
    "MENU", "NEXT", "PREV", "BACK", "SEND", "OPEN", "CLOSE", "VIEW", "READ",
    "COVID", "ADA", "GDPR", "CCPA", "TM", "LLC", "INC", "LTD", "CO",
}


def mine_acronyms(html, brand="", limit=14):
    """Find the SHORT branded names a client's buyers actually search.

    NASSCO's seeds read "bsdi pipeline inspection certification" and
    "underground infrastructure industry association" — descriptions of the
    organisation, produced by expanding nav labels into prose. Total measured
    demand across sixteen of them: 10/mo. What a contractor types is "PACP",
    "MACP", "ITCP", "CIPP". The acronyms were on the client's own site the whole
    time and nothing looked for them, because the menu converter only ever made
    labels LONGER. (2026-08-10)

    Three sources, most reliable first:
      1. "Pipeline Assessment Certification Program (PACP)" — the expansion is
         right there in the parentheses, so the meaning is certain.
      2. PACP(tm) / MACP(R) — a trademark marker means the client owns the term.
      3. A bare ALL-CAPS token that recurs, which is how a program gets
         referred to once the page has introduced it.

    Returns [{"acronym", "expansion", "hits", "source"}], commonest first.
    Measurement happens in the caller — an acronym with no search volume is a
    filing code, not a keyword.
    """
    txt = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = (txt.replace("&amp;", "&").replace("&nbsp;", " ")
              .replace("&#8482;", "\u2122").replace("&trade;", "\u2122")
              .replace("&reg;", "\u00ae"))
    txt = re.sub(r"\s+", " ", txt)

    brand_up = re.sub(r"[^A-Z]", "", (brand or "").upper())
    found = {}

    def add(ac, expansion, source):
        ac = ac.strip().upper()
        if (len(ac) < 3 or len(ac) > 6 or ac in _ACRONYM_STOP
                or not ac.isalpha() or (brand_up and ac == brand_up)):
            return
        e = found.setdefault(ac, {"acronym": ac, "expansion": "", "hits": 0,
                                  "source": source})
        if expansion and not e["expansion"]:
            # The regex greedily walks back over capitalised words, so it picks
            # up the sentence lead-in ("NASSCO The Pipeline Assessment...").
            # Trim the brand and any leading article — this is a tooltip.
            ex = expansion.strip()
            if brand_up:
                ex = re.sub(r"^\s*" + re.escape(brand or "") + r"\b", "", ex,
                            flags=re.I).strip()
            ex = re.sub(r"^(?:the|our|a|an|and|its|their)\s+", "", ex, flags=re.I)
            e["expansion"] = ex.strip()[:70]
            e["source"] = source

    # 1. Expansion followed by the abbreviation in brackets.
    for m in re.finditer(r"((?:[A-Z][A-Za-z-]+\s+){1,6})\(\s*([A-Z]{3,6})\s*[\u2122\u00ae]?\s*\)", txt):
        add(m.group(2), m.group(1), "expansion in brackets")
    # 2. Trademark marker.
    for m in re.finditer(r"\b([A-Z]{3,6})\s*[\u2122\u00ae]", txt):
        add(m.group(1), "", "trademarked by the client")
    # 3. Recurring bare capitals.
    for m in re.finditer(r"(?<![A-Za-z])([A-Z]{3,6})(?![A-Za-z])", txt):
        ac = m.group(1).upper()
        if len(ac) < 3 or ac in _ACRONYM_STOP:
            continue
        if ac in found:
            found[ac]["hits"] += 1
        else:
            add(ac, "", "repeated on the page")
            if ac in found:
                found[ac]["hits"] = 1

    out = [v for v in found.values()
           if v["hits"] >= 2 or v["source"] != "repeated on the page"]
    out.sort(key=lambda v: (v["source"] == "repeated on the page", -v["hits"],
                            v["acronym"]))
    return out[:limit]


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

    # ---- the SHORT names, measured -----------------------------------------
    # The menu converter only makes labels longer, which is how a set of seeds
    # with 10/mo between them got built. Mine the client's own acronyms and
    # price each one, so what comes back is not "here are some capitals we saw"
    # but "these are searched, these are not". One volume call. (2026-08-10)
    acronyms = []
    try:
        mined = mine_acronyms(html, d.get("brand") or "")
        if mined:
            probes, seen_p = [], set()
            for a in mined:
                for form in (a["acronym"].lower(),
                             f"{a['acronym'].lower()} certification"):
                    if form not in seen_p:
                        seen_p.add(form)
                        probes.append(form)
            vols, _pc, verr = fetch_local_volume(probes, [], "", national=True)
            floor = int(CFG.get("acronym_min_volume", 20))
            for a in mined:
                lo = a["acronym"].lower()
                forms = {f: int((vols or {}).get(f, 0) or 0)
                         for f in (lo, f"{lo} certification")}
                best = max(forms, key=lambda f: forms[f])
                a["volume"] = forms[best]
                a["term"] = best
                a["forms"] = forms
                a["worth_it"] = (not verr) and forms[best] >= floor
            acronyms = mined
    except Exception as _ae:
        acronyms = [{"error": str(_ae)[:120]}]
    return jsonify({"domain": dom, "services": out,
                    "ai_refined": ai_used, "from_sitemap": used_sitemap,
                    "from_headings": used_headings,
                    "site_description": site_desc,
                    "acronyms": acronyms,
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
