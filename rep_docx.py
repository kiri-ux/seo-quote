"""The reputation quote as Word documents.

Two of them, because they answer different questions and the second one was
being used to answer the first:

  * REVIEW REMOVALS ONLY — a Google Business Profile review analysis: how the
    stars sit per location, how many one-star removals reach the next
    one-decimal rating tier, and what that costs off the rate card. Nothing
    about ongoing reputation management. This is the document that gets sent
    when the whole conversation is "our rating is 4.4 and we want a 4.5".

  * EVERYTHING PROPOSED — every line the quote carries, one-time and monthly,
    with the totals underneath.

Shaped on the Ski Barn analysis (September 2026), which was written by hand.
(2026-09-10, Kiri)
"""
import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

ATLAS = RGBColor(0x00, 0x2D, 0x58)

# The one third-party figure the analysis carries. Attributed, so it can be
# checked and replaced when the survey is superseded.
STAT_LINE = ("“77% of consumers say negative reviews can deter them from "
             "using a business.” — BrightLocal, Local Consumer Review Survey")
GOLD = RGBColor(0xF1, 0xB4, 0x34)
MUTED = RGBColor(0x66, 0x6666 // 0x100, 0x66)


# ---------------------------------------------------------------- primitives
def _doc():
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(0.9)
        s.top_margin = s.bottom_margin = Inches(0.8)
    return doc


def _title(doc, text, sub=None, sub2=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(19)
    r.font.color.rgb = ATLAS
    if sub:
        q = doc.add_paragraph()
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rq = q.add_run(sub)
        rq.font.size = Pt(13)
        rq.bold = True
    if sub2:
        q = doc.add_paragraph()
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rq = q.add_run(sub2)
        rq.font.size = Pt(10)
        rq.italic = True


def _head(doc, text, size=13):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = ATLAS
    return p


def _body(doc, text, bold=False, size=10.5, italic=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    return p


def _bullet(doc, text, bold_head=None):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    if bold_head:
        rb = p.add_run(bold_head)
        rb.bold = True
        rb.font.size = Pt(10.5)
    r = p.add_run(text)
    r.font.size = Pt(10.5)
    return p


def _table(doc, headers, rows, widths=None, right_from=1):
    tb = doc.add_table(rows=1, cols=len(headers))
    tb.style = "Table Grid"
    hdr = tb.rows[0]
    for i, h in enumerate(headers):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        r = p.add_run(str(h))
        r.bold = True
        r.font.size = Pt(9.5)
        if i >= right_from:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for row in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            r = p.add_run("" if v is None else str(v))
            r.font.size = Pt(9.5)
            if i >= right_from:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if widths:
        for i, w in enumerate(widths):
            for row in tb.rows:
                row.cells[i].width = Inches(w)
    return tb


def _money(v):
    try:
        return "$" + format(int(round(float(v))), ",")
    except (TypeError, ValueError):
        return "—"


def _pct(v):
    try:
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return "—"


# ------------------------------------------------------------- the star math
def star_buckets(loc, rating_shift=0.0):
    """Per-star counts for one location.

    THE PULL IS SORTED LOWEST-RATING FIRST, and that is what makes this exact
    without needing the whole profile. If the pull reached a 5-star review at
    all, every review below 5 has already been seen -- so the 1, 2, 3 and 4
    counts are complete and the 5s are simply the remainder:

        n5 = total - n1 - n2 - n3 - n4

    Paramus is 619 reviews against a depth of 200: 44 ones, 14 twos, 31
    threes, 94 fours, then 17 fives. Truncated, and still exact.

    Only a pull that never reached a 5 leaves anything to infer, and there the
    profile's own average closes the system:

        n45 = total - n1 - n2 - n3
        4a + 5b = rating*total - (n1 + 2*n2 + 3*n3),  a + b = n45

    That `rating` is displayed to one decimal, so a 4.4 is anywhere in
    [4.35, 4.45); `rating_shift` walks the band so the caller can report a
    range rather than a number it cannot stand behind. (2026-09-10, Kiri)

    Returns (buckets, exact).
    """
    total = int(loc.get("profile_reviews") or 0)
    rating = float(loc.get("profile_rating") or 0)
    if total <= 0:
        return None, False
    n1 = int(loc.get("neg_1") or 0)
    n2 = int(loc.get("neg_2") or 0)
    n3 = int(loc.get("weak_3") or 0)
    n4 = loc.get("pos_4")
    n5 = loc.get("pos_5")

    if n4 is not None and n5 is not None:
        n4, n5 = int(n4), int(n5)
        if loc.get("complete"):
            b = {"5": n5, "4": n4, "3": n3, "2": n2, "1": n1}
            b["total"] = sum(b[k] for k in ("5", "4", "3", "2", "1"))
            return b, True
        if n5 > 0:
            # The pull reached the 5s, so everything under them is complete.
            rest = total - n1 - n2 - n3 - n4
            if rest >= 0:
                return {"5": rest, "4": n4, "3": n3, "2": n2, "1": n1,
                        "total": total}, True

    if rating <= 0:
        return None, False
    n45 = total - n1 - n2 - n3
    if n45 < 0:
        return None, False
    low = n1 + 2 * n2 + 3 * n3
    rest = (rating + rating_shift) * total - low          # 4a + 5b
    a = int(round(5 * n45 - rest))
    a = max(0, min(n45, a))
    b = n45 - a
    return {"5": b, "4": a, "3": n3, "2": n2, "1": n1, "total": total}, False


def _avg(b):
    n = b["total"]
    if not n:
        return 0.0
    return (5 * b["5"] + 4 * b["4"] + 3 * b["3"] + 2 * b["2"] + 1 * b["1"]) / n


def _tier(x):
    # Google shows one decimal, rounded half up -- 4.75 displays as 4.8.
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(round(x, 6))).quantize(Decimal("0.1"),
                                                    rounding=ROUND_HALF_UP))


def removal_range(loc):
    """Removals needed for one location: a number when the buckets are exact,
    a range when they were inferred from a one-decimal average.

    Returns {remove, remove_max, exact, ...} or None.
    """
    b, exact = star_buckets(loc)
    if not b:
        return None
    base = removals_to_next_tier(b)
    if exact or not base:
        if base:
            base["remove_max"] = base["remove"]
            base["exact"] = exact
        return base
    ks = [base["remove"]]
    for shift in (-0.049, 0.049):
        bb, _ = star_buckets(loc, rating_shift=shift)
        r = removals_to_next_tier(bb) if bb else None
        if r:
            ks.append(r["remove"])
    base["remove"] = min(ks)
    base["remove_max"] = max(ks)
    base["exact"] = False
    return base


def removals_to_next_tier(b):
    """Fewest 1-star removals that move the displayed rating up one tenth.

    Removing a 1-star takes 1 off the sum and 1 off the count, so the average
    rises. The answer is the smallest k where the DISPLAYED rating -- one
    decimal, half up -- reaches the next tenth. None when their own one-stars
    cannot get there.
    """
    if not b or not b["total"]:
        return None
    cur = _avg(b)
    cur_tier = _tier(cur)
    if cur_tier >= 5.0:
        return None
    target = round(cur_tier + 0.1, 1)
    total = b["total"]
    s = 5 * b["5"] + 4 * b["4"] + 3 * b["3"] + 2 * b["2"] + b["1"]
    for k in range(1, b["1"] + 1):
        n = total - k
        if n <= 0:
            break
        if _tier((s - k) / n) >= target:
            return {"remove": k, "from_tier": cur_tier, "to_tier": target,
                    "current_avg": round(cur, 3),
                    "projected_avg": round((s - k) / n, 3),
                    "one_star_before": b["1"], "one_star_after": b["1"] - k}
    return None


# --------------------------------------------------- review-removals-only doc
def build_review_removal_docx(d):
    """The review analysis and what removing the one-stars costs. No ORM."""
    doc = _doc()
    brand = (d.get("brand") or "This client").strip()
    locs = [l for l in (d.get("locations") or []) if l.get("profile_reviews")]
    where = (d.get("region") or "").strip()

    _title(doc, "Google Business Profile Review Analysis",
           brand + (f" — {where}" if where else ""),
           "Review distribution by location and star rating")

    read = [(l, *star_buckets(l)) for l in locs]
    read = [(l, b, e) for (l, b, e) in read if b]
    tot_reviews = sum(b["total"] for _, b, _ in read)
    tot_sum = sum(_avg(b) * b["total"] for _, b, _ in read)
    tot_45 = sum(b["5"] + b["4"] for _, b, _ in read)
    weighted = (tot_sum / tot_reviews) if tot_reviews else 0

    if read:
        _table(doc, ["", "Total reviews", "Weighted average",
                     "4- and 5-star", "Locations"],
               [["", format(tot_reviews, ","), f"{weighted:.2f}",
                 _pct(100.0 * tot_45 / tot_reviews if tot_reviews else 0),
                 len(read)]], right_from=1)

    # ---- per location -----------------------------------------------------
    _head(doc, "Location Summary")
    _table(doc,
           ["Location", "Reviews", "Avg. rating", "4–5 star share",
            "1–2 star share"],
           [[l.get("title") or "—", format(b["total"], ","),
             f"{_avg(b):.2f}",
             _pct(100.0 * (b["5"] + b["4"]) / b["total"]),
             _pct(100.0 * (b["2"] + b["1"]) / b["total"])]
            for l, b, _ in read]
           + ([["Combined", format(tot_reviews, ","), f"{weighted:.2f}",
                _pct(100.0 * tot_45 / tot_reviews),
                _pct(100.0 * sum(b["2"] + b["1"] for _, b, _ in read)
                     / tot_reviews)]] if len(read) > 1 else []),
           widths=[2.3, 0.9, 1.0, 1.2, 1.2])

    _head(doc, "Review Distribution by Star Rating")
    _table(doc, ["Location", "5 ★", "4 ★", "3 ★", "2 ★", "1 ★", "Total"],
           [[l.get("title") or "—", b["5"], b["4"], b["3"], b["2"], b["1"],
             format(b["total"], ",")] for l, b, _ in read]
           + ([["Combined"] + [format(sum(b[k] for _, b, _ in read), ",")
                               for k in ("5", "4", "3", "2", "1")]
               + [format(tot_reviews, ",")]] if len(read) > 1 else []),
           widths=[2.3, 0.7, 0.7, 0.7, 0.7, 0.7, 0.9])

    # ---- what stands out --------------------------------------------------
    if read:
        _head(doc, "Takeaways")
        big = max(read, key=lambda x: x[1]["total"])
        best = max(read, key=lambda x: _avg(x[1]))
        worst = max(read, key=lambda x: (x[1]["2"] + x[1]["1"]) / x[1]["total"])
        _bullet(doc, f"{big[0].get('title')} leads with "
                     f"{format(big[1]['total'], ',')} reviews, "
                     f"{_pct(100.0 * big[1]['total'] / tot_reviews)} of the "
                     f"review base.",
                bold_head="Largest review footprint: ")
        _bullet(doc, f"{best[0].get('title')} has the highest rating "
                     f"({_avg(best[1]):.2f}) and the highest 4–5 star share "
                     f"({_pct(100.0 * (best[1]['5'] + best[1]['4']) / best[1]['total'])}).",
                bold_head="Strongest profile: ")
        _bullet(doc, f"{worst[0].get('title')} carries the highest 1–2 star "
                     f"share "
                     f"({_pct(100.0 * (worst[1]['2'] + worst[1]['1']) / worst[1]['total'])}).",
                bold_head="Greatest opportunity: ")

    # ---- the scenarios ----------------------------------------------------
    doc.add_page_break()
    _head(doc, "Rating Improvement Scenarios")
    _body(doc, "One-star review removals required by location", bold=True)
    _body(doc, "Fewest removals needed to reach the next Google one-decimal "
               "rating tier, with every other review unchanged.", italic=True)

    scen, need, need_max = [], 0, 0
    for l, b, exact in read:
        r = removal_range(l)
        scen.append((l, b, r, exact))
        if r:
            need += r["remove"]
            need_max += r.get("remove_max") or r["remove"]

    for l, b, r, exact in scen:
        _body(doc, l.get("title") or "—", bold=True, size=11)
        if not r:
            _body(doc, "Removing their one-star reviews does not reach the "
                       "next tier on its own.", italic=True)
            continue
        _rng = (r.get("remove_max") or r["remove"]) != r["remove"]
        _shown = (f"{r['remove']}–{r['remove_max']}" if _rng
                  else str(r["remove"]))
        _table(doc, ["Current tier", "Next tier", "Current 1-star", "Remove",
                     "Remaining 1-star", "Projected avg."],
               [[f"{r['from_tier']:.1f}", f"{r['to_tier']:.1f}",
                 r["one_star_before"], _shown,
                 (f"{r['one_star_before'] - r['remove_max']}–"
                  f"{r['one_star_after']}" if _rng else r["one_star_after"]),
                 f"{r['projected_avg']:.3f}"]])
        if _rng:
            _body(doc, "Shown as a range: Google publishes this profile's "
                       "average to one decimal, so the exact starting figure "
                       "sits inside a band and the removals needed sit inside "
                       "one too.", italic=True)
        if not exact and not _rng:
            _body(doc, "The review pull for this location hit its depth, so "
                       "the one-star count is a floor and the removals figure "
                       "is a minimum.", italic=True)

    # ---- the money --------------------------------------------------------
    _head(doc, "Review Removal Pricing")
    _body(doc, "Pay only if we successfully remove a review:", bold=True)
    for row in (d.get("brackets") or []):
        lo, hi, price = row.get("min"), row.get("max"), row.get("price")
        span = f"{lo}-{hi}" if hi else f"{lo}+"
        _bullet(doc, f"{span} removals: {_money(price)} per review")

    if need:
        rate = d.get("rate_for_total")
        span = f"{need}" if need_max == need else f"{need}–{need_max}"
        if rate:
            cost = (_money(rate * need) if need_max == need
                    else f"{_money(rate * need)}–{_money(rate * need_max)}")
            _body(doc, f"Removing {span} one-star reviews = {_money(rate)} per "
                       f"review, {cost}.", bold=True)
        else:
            _body(doc, f"Removals needed across all locations: {span}.",
                  bold=True)

    _head(doc, "Source & Method", size=11)
    _body(doc, "Star counts come from the live Google review pull for each "
               "location. Totals and weighted averages are calculated from "
               "those counts rather than read off the profile, and the "
               "scenarios move only one-star reviews.", italic=True)
    _body(doc, d.get("stat_line") or STAT_LINE, italic=True)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


# ------------------------------------------------------ everything-proposed
def build_rep_proposal_docx(d):
    """Every line the reputation quote carries, with the totals."""
    doc = _doc()
    brand = (d.get("brand") or "This client").strip()
    q = d.get("quote") or {}
    lines = q.get("lines") or []
    totals = q.get("totals") or {}
    campaign = {"reactive": "Reactive", "proactive": "Proactive",
                "bundle": "Reactive + Proactive"}.get(
                    d.get("campaign") or "", (d.get("campaign") or "").title())

    _title(doc, "Reputation Management Proposal", brand,
           campaign + " campaign" if campaign else None)

    if not lines:
        _body(doc, "Nothing is proposed on this quote yet.")
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf

    for phase, heading in ((1, "Phase 1 — Reactive"),
                           (2, "Phase 2 — Proactive")):
        rows = [l for l in lines if int(l.get("phase") or 1) == phase]
        if not rows:
            continue
        _head(doc, heading)
        _table(doc, ["Service", "Detail", "Qty", "Price"],
               [[l.get("service") or "", l.get("detail") or "",
                 l.get("qty") or "", _money(l.get("total"))] for l in rows],
               widths=[1.9, 2.7, 0.6, 1.0], right_from=2)

    _head(doc, "Totals")
    rows = []
    if totals.get("one_time"):
        rows.append(["One-time and per-asset", _money(totals["one_time"])])
    if totals.get("monthly"):
        rows.append(["Monthly", _money(totals["monthly"]) + " / month"])
    _table(doc, ["", "Amount"], rows, widths=[4.6, 1.6])

    for w in (q.get("warnings") or []):
        _body(doc, w, italic=True)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
