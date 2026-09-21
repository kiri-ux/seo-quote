"""THE ADTINI ORM SLIDES, BUILT FROM THE REPUTATION QUOTE (2026-09-21, Kiri).

The SEO row has had a deck since 2026-09-19; the reputation row had only the
proposal document, so the ORM slides were still being rebuilt by hand off the
product deck every time a partner presented one.

Same quote as the document, six slide builders, every one of them conditional
on what the quote actually carries:

  1. the product, and the client's own page one under it,
  2. Strategy Details - Proactive, when a Brand Shield is on the quote,
  3. Strategy Details - Reactive, when Search Protection is,
  4. Strategy Details - Removals, when either removal line is,
  5. the Reputation Snapshot: auto-suggest, page one, the profiles and the
     star split -- the scan, as the record of what the price was read off,
  6. Product Details: the flight and the rates across the top, then one card
     per workstream sold.

A slide with nothing behind it is not printed at all. The card row on slide 6
is sized to the number of cards, so a Reactive-only quote prints one full-width
card rather than one card and three gaps.

The brand primitives come from seo_pptx and the product words from rep_docx:
two decks drawn by one hand, and the client reads the same sentences in the
deck as in the letter.
"""
import io

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

import rep_docx
import rep_scan
from seo_pptx import (BLUE, BLUE_LT, BLUE_MID, GREEN, INK, LINE, MUTED, NAVY,
                      SLIDE_H, SLIDE_W, TINT, WHITE, _blank, _box, _flight,
                      _heading, _icon, _label_para, _money, _navy_block,
                      _para, _run, _style, _text_box, _txt)

DOC = rep_docx.COPY

TITLE = "Online Reputation Management"

# ---- the deck's own words ------------------------------------------------
# Everything the client reads about the PRODUCT is in rep_docx.COPY, verbatim
# off the adtini ORM slides, so the letter and the deck cannot drift. Only the
# two strings below are the deck's alone: the removals strategy slide has no
# equivalent section in the document, which prices the removals under
# Brendan's own pay-on-success wording instead.
COPY = {
    "removals": [
        ("Review Removals",
         "A risk-free, pay-for-performance service that petitions Google to "
         "permanently remove 1, 2, and 3-star reviews from your Google "
         "Business Profile."),
        ("Site/Article Removals",
         "A risk-free, pay-for-performance service that de-indexes harmful, "
         "inaccurate, or defamatory articles and web pages on Google Search "
         "to protect your brand's digital footprint."),
    ],
    # The four values route_tactic returns, in the words the panel uses for
    # them. A table of tags with nothing saying what a tag means is a table
    # the partner has to talk over.
    "tactics": [
        ("Owned", "client's own domain, strengthen and protect it"),
        ("3rd party", "a result on a site you don't own"),
        ("positive - leave", "strong 3rd-party result, leave as-is, it helps "
                             "push negatives down"),
        ("site removal", "3rd-party page taken down or de-indexed at the source"),
        ("suppression", "can't remove it, outrank it instead"),
    ],
    "no_serp": "No page one captured for this quote.",
    "review_card": [
        "Pay on success - billed per removed review; the total is a maximum, "
        "not a committed spend",
        "Success rate: ~50-60% success rate across Google Reviews",
        "Some sensitive content cannot be removed",
    ],
    "review_timeline": "Timeframe: ~48 hours-60 days depending on fulfillment "
                       "routing",
    "site_card": [
        "Pay on success - billed only for pages removed",
        "Success rate: ~100% to date on standard hosts (compliant boards, "
        "forums, blogs); court and legal-database pages run closer to 50%",
        "Timeframe: 2-10 weeks",
    ],
    "search_card": [
        "Includes Organic Search Suppression, Auto-Suggest & Related Search "
        "Manipulation, and Branded Search Append",
        "Includes up to 3 negative phrase removals across auto-suggest and "
        "related searches",
    ],
    "shield_card": [
        "Includes up to 5 keyword monitors, SEO Brand Shield & Asset "
        "Building, 24/7 Brand Monitoring & Threat Detection, In-Depth "
        "Monthly Report",
    ],
    "shield_onetime_head": "One-Time Fee:",
    "shield_onetime": [
        "25+ page report, manual review + data platforms (not just an "
        "automated scan)",
        "Executive summary with prioritized findings, evidence, and screenshots",
        "Implementation roadmap with next steps and ownership",
        "Audit fee credited toward the first month if an SEO campaign is "
        "purchased afterward",
    ],
}

STAR_SHADES = {"1": NAVY, "2": BLUE_LT, "3": BLUE_MID}


# ------------------------------------------------------------------ reading
def _handoff(d):
    return ((d.get("quote") or {}).get("handoff") or {})


def _int(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _snap(d):
    return d.get("snapshot") or {}


def _locs(d):
    return [l for l in (_snap(d).get("locations") or []) if isinstance(l, dict)]


def _stars(d):
    """The star split across the ticked profiles: {'1': n, '2': n, '3': n}.

    Read off the same per-location rows the flag count is, so the pie and the
    "reviews to remove" tile cannot disagree with the number on the form.
    """
    out = {"1": 0, "2": 0, "3": 0}
    for l in _locs(d):
        out["1"] += _int(l.get("neg_1"))
        out["2"] += _int(l.get("neg_2"))
        out["3"] += _int(l.get("weak_3"))
    return out


def _brand_split(phrase, brand):
    """(the brand as typed in this phrase, the modifier) -- for the bold.

    The modifier is the part that matters, so it is the part in bold. Walks the
    phrase against the brand's CORE, so a legal suffix or an apostrophe does
    not decide whether anything is bold at all. A phrase that does not lead
    with the brand is left whole.
    """
    key = [t for t in rep_scan.brand_core(brand) if t not in ("and", "of", "the")]
    s = str(phrase or "")
    if not key:
        return s, ""
    k, cut, at = 0, -1, 0
    for raw in s.split(" "):
        if not raw:
            at += 1
            continue
        toks = [t for t in rep_scan._norm_tokens(raw)
                if t not in ("and", "of", "the")]
        for t in toks:
            if k < len(key) and t == key[k]:
                k += 1
            elif not k and len(key) >= 2 and t.startswith("".join(key)):
                k = len(key)
            else:
                return s, ""
        at += len(raw) + 1
        if k >= len(key):
            cut = at - 1
            break
    if cut < 0 or cut >= len(s):
        return s, ""
    return s[:cut], s[cut:]


# ------------------------------------------------------------------ slide 1
def _slide_product(prs, d):
    """The opening slide: title and definition top left, the client's own page
    one framed as a browser under it, and what reputation management is down
    the right."""
    slide = _blank(prs, band=False)
    _navy_block(slide, Inches(11.75), Inches(1.15), Inches(2.2), Inches(4.3))
    _navy_block(slide, Inches(-0.85), Inches(3.4), Inches(1.5), Inches(3.1))

    _icon(slide, Inches(0.5), Inches(0.42))
    tb = _text_box(slide, Inches(1.4), Inches(0.36), Inches(9.6), Inches(0.9))
    _txt(tb, size=32, bold=True, color=NAVY)
    tb.text_frame.paragraphs[0].text = TITLE

    tag = _box(slide, Inches(0.5), Inches(1.36), Inches(6.0), Inches(0.9),
               fill=WHITE, radius=0.14)
    _txt(tag, size=11.5, color=INK, line=1.2)
    tag.text_frame.paragraphs[0].text = DOC["orm_def"]

    _browser(slide, _shot(d), Inches(0.55), Inches(2.44), Inches(5.95),
             Inches(3.7))

    body = _box(slide, Inches(6.75), Inches(1.36), Inches(5.65), Inches(4.85),
                fill=WHITE, radius=0.03)
    tf = _txt(body, size=10.5, line=1.18)
    for i, text in enumerate(DOC["orm_points"]):
        p = tf.paragraphs[0] if i == 0 else _para(tf, size=10.5, line=1.18,
                                                  space_before=9)
        _run(p, text, size=10.5)
    return slide


def _shot(d):
    """The page-one capture, already windowed by the endpoint."""
    for sh in (d.get("serp_shots") or []):
        if not isinstance(sh, dict):
            continue
        raw = str(sh.get("data_url") or "")
        if "," in raw and raw.lower().startswith("data:image"):
            import base64
            try:
                return base64.b64decode(raw.split(",", 1)[1])
            except Exception:                                 # noqa: BLE001
                return None
    return None


def _browser(slide, img, fx, fy, fw, fh):
    """The exhibit, in a window. It is the client's own search result and it
    reads as one when it is framed like a browser rather than dropped bare."""
    _box(slide, fx, fy, fw, fh, fill=RGBColor(0x2B, 0x33, 0x40),
         outline=None, radius=0.03)
    for i in range(3):
        dot = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, fx + Inches(0.14) + Inches(0.17) * i,
            fy + Inches(0.1), Inches(0.09), Inches(0.09))
        dot.fill.solid()
        dot.fill.fore_color.rgb = RGBColor(0x6B, 0x75, 0x84)
        dot.line.fill.background()
        dot.shadow.inherit = False
    page = _box(slide, fx + Inches(0.1), fy + Inches(0.3), fw - Inches(0.2),
                fh - Inches(0.4), fill=WHITE, outline=None, radius=0.02)
    if not img:
        _txt(page, size=12, color=MUTED, align=PP_ALIGN.CENTER)
        page.text_frame.paragraphs[0].text = COPY["no_serp"]
        page.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        return
    inner_w, inner_h = fw - Inches(0.2), fh - Inches(0.4)
    pic = slide.shapes.add_picture(io.BytesIO(img), fx + Inches(0.1),
                                   fy + Inches(0.3), width=inner_w)
    if pic.height > inner_h:
        ratio = pic.width / pic.height
        pic.height = int(inner_h)
        pic.width = Emu(int(inner_h * ratio))
        pic.left = Emu(int(fx + Inches(0.1) + (inner_w - pic.width) / 2))
    else:
        pic.top = Emu(int(fy + Inches(0.3) + (inner_h - pic.height) / 2))


# ---------------------------------------------------------------- slides 2-4
def _strategy_slide(prs, lead_label, lead, items, bundle_head=None,
                    columns=1, item_color=INK):
    """One Strategy Details slide: the direction, then what it is made of."""
    slide = _blank(prs)
    _heading(slide, TITLE + " - Strategy Details", size=25)
    y = Inches(1.45)
    if lead:
        h = Inches(0.92) if len(lead) > 170 else Inches(0.72)
        box = _box(slide, Inches(0.55), y, Inches(12.2), h)
        tf = _txt(box, size=12.5, line=1.18)
        _label_para(tf, lead_label + ": ", lead, size=12.5, first=True,
                    label_color=BLUE)
        y = y + h + Inches(0.26)
    if bundle_head:
        hb = _text_box(slide, Inches(0.6), y, Inches(12.0), Inches(0.32))
        _txt(hb, size=12.5, bold=True, color=INK, space_after=0)
        p = hb.text_frame.paragraphs[0]
        p.text = bundle_head
        p.font.italic = True
        y = y + Inches(0.36)
    # SIDE BY SIDE OR STACKED IS THE SLIDE'S CALL, NOT THE COUNT'S. Inferring
    # it from len(items) put the two removal lines in two columns, where the
    # product slide stacks them full width and runs the label inline.
    if columns == 2 and len(items) == 2:
        w = Inches(5.95)
        for i, (name, text) in enumerate(items):
            box = _box(slide, Inches(0.55) + (w + Inches(0.3)) * i, y, w,
                       Inches(1.55))
            tf = _txt(box, size=11.5, line=1.18)
            _label_para(tf, name + ":", "", size=11.5, first=True,
                        label_color=INK)
            tf.paragraphs[0].font.italic = True
            p = _para(tf, size=11.5, line=1.18, space_before=4)
            _run(p, "•  " + text, size=11.5)
    else:
        for name, text in items:
            h = Inches(0.78) if len(text) > 150 else Inches(0.6)
            box = _box(slide, Inches(0.55), y, Inches(12.2), h)
            tf = _txt(box, size=11.5, line=1.18)
            _label_para(tf, name + ": ", text, size=11.5, first=True,
                        label_color=item_color)
            y = y + h + Inches(0.16)
    return slide


# ------------------------------------------------------------------ slide 5
def _slide_snapshot(prs, d):
    """The scan, as the record of what the price was read off: the two search
    surfaces the campaign buys, the page one it is losing, the profiles, and
    the star split the removal count came from."""
    slide = _blank(prs)
    _heading(slide, TITLE + " - Reputation Snapshot", size=25)
    snap = _snap(d)
    brand = str(d.get("brand") or "")
    _suggest_block(slide, snap, brand)
    _profiles_block(slide, d)
    _results_block(slide, snap)
    _stars_block(slide, d)
    return slide


def _col_head(slide, text, x, y, w=Inches(4.3)):
    hb = _text_box(slide, x, y, w, Inches(0.34))
    _txt(hb, size=14, bold=True, color=INK, space_after=0)
    hb.text_frame.paragraphs[0].text = text
    return hb


def _suggest_block(slide, snap, brand):
    x, w = Inches(0.3), Inches(3.5)
    _col_head(slide, "Auto-Suggest", x, Inches(1.32), w)
    rows = [str(s) for s in (snap.get("suggest") or []) if str(s).strip()][:5]
    q = str(snap.get("query") or "").strip()
    bar = _box(slide, x, Inches(1.7), w, Inches(0.4), fill=TINT, radius=0.06)
    _txt(bar, size=10, bold=True, color=NAVY, space_after=0)
    bar.text_frame.paragraphs[0].text = ("“%s”" % q) if q else "Auto-suggest"
    bar.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    h = Inches(0.3) * max(1, len(rows)) + Inches(0.2)
    box = _box(slide, x, Inches(2.12), w, h, fill=WHITE, radius=0.03)
    tf = _txt(box, size=10.5, space_after=0, line=1.1)
    if not rows:
        tf.paragraphs[0].text = "No negative suggestions found."
        _style(tf.paragraphs[0], 10.5, False, MUTED)
        return
    for i, phrase in enumerate(rows):
        head, mod = _brand_split(phrase, brand)
        p = tf.paragraphs[0] if i == 0 else _para(tf, size=10.5, space_before=4,
                                                  space_after=0, line=1.1)
        _run(p, head, size=10.5, color=INK)
        if mod:
            _run(p, mod, size=10.5, bold=True, color=INK)


def _profiles_block(slide, d):
    x, w = Inches(0.3), Inches(3.5)
    locs = sorted(_locs(d), key=lambda l: -_int(l.get("profile_reviews")))[:4]
    top = Inches(4.02)
    _col_head(slide, "Top Location Google Reviews", x, top, w)
    if not locs:
        nb = _text_box(slide, x, top + Inches(0.36), w, Inches(0.3))
        _txt(nb, size=10.5, color=MUTED)
        nb.text_frame.paragraphs[0].text = "No Google profiles matched."
        return
    rows = len(locs) + 1
    table = slide.shapes.add_table(rows, 5, x, top + Inches(0.34), w,
                                   Inches(0.28) * rows).table
    for c, cw in enumerate((Inches(1.62), Inches(0.72), Inches(0.38),
                            Inches(0.38), Inches(0.4))):
        table.columns[c].width = cw
    for c, label in enumerate(("Location", "Profile", "1★", "2★",
                               "3★")):
        cell = table.cell(0, c)
        cell.text = label
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        p = cell.text_frame.paragraphs[0]
        _style(p, 8.5, True, WHITE)
        p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
    for r, l in enumerate(locs, start=1):
        rating = l.get("profile_rating")
        prof = ("%s★/%s" % (rating, _int(l.get("profile_reviews")))
                if rating else str(_int(l.get("profile_reviews"))))
        vals = (str(l.get("title") or ""), prof, _int(l.get("neg_1")),
                _int(l.get("neg_2")), _int(l.get("weak_3")))
        for c, val in enumerate(vals):
            cell = table.cell(r, c)
            cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE
            p = cell.text_frame.paragraphs[0]
            _style(p, 8.5, False, INK)
            p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER


def _results_block(slide, snap):
    x, w = Inches(4.0), Inches(4.6)
    _col_head(slide, "Top Google Results", x, Inches(1.32), w)
    page1 = [r for r in ((snap.get("organic") or [])
                         + (snap.get("forums") or [])) if isinstance(r, dict)]
    page1 = sorted(page1, key=lambda r: _int(r.get("pos")) or 99)[:10]
    y = Inches(1.7)
    if page1:
        rows = len(page1) + 1
        table = slide.shapes.add_table(rows, 3, x, y, w,
                                       Inches(0.27) * rows).table
        for c, cw in enumerate((Inches(0.42), Inches(3.4), Inches(0.78))):
            table.columns[c].width = cw
        for c, label in enumerate(("#", "Result", "Rating")):
            cell = table.cell(0, c)
            cell.text = label
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY
            p = cell.text_frame.paragraphs[0]
            _style(p, 8.5, True, WHITE)
            p.alignment = PP_ALIGN.CENTER if c != 1 else PP_ALIGN.LEFT
        for r, res in enumerate(page1, start=1):
            rating = res.get("rating")
            votes = res.get("votes")
            rate = ("%s★%s" % (rating, " (%s)" % votes if votes else "")
                    if rating else "--")
            for c, val in enumerate((_int(res.get("pos")) or "", "", rate)):
                cell = table.cell(r, c)
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE
                p = cell.text_frame.paragraphs[0]
                if c == 1:
                    # THE DOMAIN, THEN WHAT IS TO BE DONE ABOUT IT. The tactic
                    # is the reason the row is on the slide at all.
                    _run(p, str(res.get("domain") or ""), size=8.5, color=INK)
                    _run(p, "   " + ("Owned" if res.get("owned")
                                     else "3rd party"),
                         size=7.5, bold=True,
                         color=(GREEN if res.get("owned") else MUTED))
                    tac = str(res.get("tactic") or "")
                    if tac:
                        _run(p, "   → " + tac, size=7.5, color=BLUE)
                    _style(p, 8.5, False, INK)
                else:
                    cell.text = str(val)
                    _style(p, 8.5, False, INK)
                    p.alignment = PP_ALIGN.CENTER
        y = y + Inches(0.27) * rows + Inches(0.12)
    else:
        nb = _text_box(slide, x, y, w, Inches(0.3))
        _txt(nb, size=10.5, color=MUTED)
        nb.text_frame.paragraphs[0].text = "No page one captured."
        y = y + Inches(0.36)
    legend = _box(slide, x, y, w, Inches(1.18), fill=WHITE, radius=0.03)
    tf = _txt(legend, size=7.5, space_after=0, line=1.1)
    for i, (name, text) in enumerate(COPY["tactics"]):
        p = tf.paragraphs[0] if i == 0 else _para(tf, size=7.5, space_before=3,
                                                  space_after=0, line=1.1)
        _run(p, name, size=7.5, bold=True,
             color=(GREEN if name == "Owned" else BLUE))
        _run(p, " - " + text, size=7.5, color=MUTED)


def _stars_block(slide, d):
    x, w = Inches(8.85), Inches(4.15)
    _col_head(slide, "Star Reviews Breakdown", x, Inches(1.32), w)
    stars = _stars(d)
    labels = [k for k in ("3", "2", "1") if stars.get(k)]
    if labels:
        data = CategoryChartData()
        data.categories = ["%s ★ Reviews" % k for k in labels]
        data.add_series("Reviews", tuple(stars[k] for k in labels))
        gf = slide.shapes.add_chart(XL_CHART_TYPE.PIE, x, Inches(1.62),
                                    w, Inches(2.6), data)
        chart = gf.chart
        chart.has_title = False
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.RIGHT
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(10)
        plot = chart.plots[0]
        # NO NUMBERS ON THE SLICES. The table beside it is the count; on the
        # pie they read as a second, smaller list.
        plot.has_data_labels = False
        for i, k in enumerate(labels):
            pt = plot.series[0].points[i]
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = STAR_SHADES[k]
            pt.format.line.color.rgb = WHITE
    else:
        nb = _text_box(slide, x, Inches(1.68), w, Inches(0.3))
        _txt(nb, size=10.5, color=MUTED)
        nb.text_frame.paragraphs[0].text = "No reviews counted."

    # THE NUMBER THE REMOVAL LINE IS PRICED OFF, as its own tile. It is the
    # one figure on this slide that is also a line on the quote.
    flagged = stars["1"] + stars["2"]
    tile = _box(slide, x, Inches(4.42), w, Inches(1.0), fill=BLUE_LT,
                outline=None, radius=0.06)
    _navy_block(slide, x, Inches(4.42), Inches(1.35), Inches(1.0), radius=0.06)
    nb = _text_box(slide, x, Inches(4.62), Inches(1.35), Inches(0.6))
    _txt(nb, size=26, bold=True, color=WHITE, align=PP_ALIGN.CENTER,
         space_after=0)
    nb.text_frame.paragraphs[0].text = str(flagged)
    lb = _text_box(slide, x + Inches(1.45), Inches(4.62), w - Inches(1.6),
                   Inches(0.62))
    _txt(lb, size=12.5, bold=True, color=WHITE, space_after=0, line=1.1)
    lb.text_frame.paragraphs[0].text = "1-2 ★ Reviews\nto Remove"
    return tile


# ------------------------------------------------------------------ slide 6
def _cards(d):
    """One spec per workstream the quote carries, in the deck's order."""
    h = _handoff(d)
    out = []
    if h.get("review_removals") and _int(h.get("reviews_count")):
        out.append({
            "name": "Negative Review Removals",
            "fill": None, "dark": False,
            "rate": ("%s flagged reviews @ " % _int(h.get("reviews_count")),
                     "%s/removed review" % _money(h.get("price_per_review_removal"))),
            "bullets": COPY["review_card"],
            "accent": COPY["review_timeline"],
            "price": ("Pricing up to %s"
                      % _money(_int(h.get("reviews_count"))
                               * float(h.get("price_per_review_removal") or 0))),
        })
    if h.get("site_article_removals") and _int(h.get("standard_sites")):
        out.append({
            "name": "Negative Website/Article Removals - Standard",
            "fill": BLUE_MID, "dark": True,
            "rate": ("%s sites @ " % _int(h.get("standard_sites")),
                     "%s/removed page"
                     % _money(h.get("price_per_standard_site_removal"))),
            "bullets": COPY["site_card"],
            "price": ("Pricing up to %s"
                      % _money(_int(h.get("standard_sites"))
                               * float(h.get("price_per_standard_site_removal") or 0))),
        })
    if h.get("search_protection_monthly"):
        out.append({
            "name": "Reactive: Search Protection",
            "fill": BLUE_LT, "dark": True,
            "scales": "Scales with brand search volume: %s/mo measured"
                      % "{:,}".format(_int(h.get("search_volume"))),
            "bullets": COPY["search_card"],
            "price": "Pricing: %s/month" % _money(h.get("search_protection_monthly")),
        })
    if h.get("brand_shield_monthly"):
        n = _int(h.get("locations")) or 1
        out.append({
            "name": "Proactive: Brand Shield",
            "fill": NAVY, "dark": True,
            "scales": "Scales with number of Google locations: %s location%s "
                      "measured" % (n, "" if n == 1 else "s"),
            "bullets": COPY["shield_card"],
            "onetime": COPY["shield_onetime"],
            "price": "Pricing: %s/month" % _money(h.get("brand_shield_monthly")),
        })
    return out


def _slide_details(prs, d, cards):
    """The flight and the rates across the top, then one card per workstream.

    SIZED TO WHAT WAS SOLD. The product slide has four cards because the
    product has four workstreams; a quote that bought one gets one card across
    the row rather than one card and three gaps to delete by hand.
    """
    h = _handoff(d)
    slide = _blank(prs)
    icon = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.5), Inches(0.44),
                                  Inches(0.7), Inches(0.7))
    icon.fill.solid()
    icon.fill.fore_color.rgb = RGBColor(0xE8, 0xF0, 0xFB)
    icon.line.color.rgb = NAVY
    icon.line.width = Pt(2.5)
    icon.shadow.inherit = False
    _txt(icon, size=19, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
    icon.text_frame.paragraphs[0].text = "⌕"
    tb = _text_box(slide, Inches(1.26), Inches(0.44), Inches(10.4), Inches(0.8))
    _txt(tb, size=27, bold=True, color=NAVY)
    tb.text_frame.paragraphs[0].text = TITLE + " Product Details"
    _navy_block(slide, Inches(-0.9), Inches(-0.55), Inches(2.4), Inches(1.15))
    _navy_block(slide, Inches(12.3), Inches(6.5), Inches(2.4), Inches(1.4))

    flight, months = _flight(d, 6)
    search_m = float(h.get("search_protection_monthly") or 0)
    shield_m = float(h.get("brand_shield_monthly") or 0)
    rev_max = (_int(h.get("reviews_count"))
               * float(h.get("price_per_review_removal") or 0))
    site_max = (_int(h.get("standard_sites"))
                * float(h.get("price_per_standard_site_removal") or 0))

    cells = []
    first = [("", flight)] if flight else []
    first.append(("Months Running: ", str(months)))
    cells.append(first)
    rates = []
    if rev_max:
        rates.append(("Review Removals: ",
                      _money(h.get("price_per_review_removal"))))
    if site_max:
        rates.append(("Site Removals: ",
                      _money(h.get("price_per_standard_site_removal"))))
    if rates:
        cells.append(rates)
    budgets = []
    if search_m:
        budgets.append(("Reactive Monthly Budget: ", _money(search_m)))
    if shield_m:
        budgets.append(("Proactive Monthly Budget: ", _money(shield_m)))
    if budgets:
        cells.append(budgets)
    # THE RECURRING MONEY OVER THE FLIGHT, PLUS THE REMOVALS AT THEIR MAXIMUM.
    # Every removal line is pay on success, so this is a ceiling rather than a
    # committed spend -- which is what the cards say and what the tile on the
    # row is labelled.
    total = (search_m + shield_m) * max(1, months) + rev_max + site_max
    if total:
        cells.append([("Total Budget: ", _money(total))])

    _box(slide, Inches(0.55), Inches(1.32), Inches(12.2), Inches(0.72))
    span = Inches(12.2) / len(cells)
    for i, lines in enumerate(cells):
        cell = _text_box(slide, Inches(0.55) + span * i, Inches(1.38), span,
                         Inches(0.62))
        tf = _txt(cell, size=11.5, align=PP_ALIGN.CENTER, space_after=0)
        for j, (label, value) in enumerate(lines):
            p = tf.paragraphs[0] if j == 0 else _para(
                tf, size=11.5, align=PP_ALIGN.CENTER, space_after=0)
            p.alignment = PP_ALIGN.CENTER
            _run(p, label, size=11.5, bold=True)
            _run(p, value, size=11.5, bold=not label)
        if i:
            rule = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0.55) + span * i, Inches(1.4),
                Pt(1), Inches(0.56))
            rule.fill.solid()
            rule.fill.fore_color.rgb = LINE
            rule.line.fill.background()
            rule.shadow.inherit = False

    gap = Inches(0.22)
    n = len(cards)
    card_w = (Inches(12.2) - gap * (n - 1)) / n
    top, card_h = Inches(2.16), Inches(4.5)
    for i, spec in enumerate(cards):
        x = Inches(0.55) + (card_w + gap) * i
        dark = spec["dark"]
        _box(slide, x, top, card_w, card_h, fill=spec["fill"],
             outline=(LINE if not dark else None))
        name = _text_box(slide, x, top + Inches(0.12), card_w, Inches(0.7))
        _txt(name, size=(14 if n > 2 else 15), bold=True,
             color=(WHITE if dark else INK), align=PP_ALIGN.CENTER, line=1.1)
        name.text_frame.paragraphs[0].text = spec["name"]

        y = top + Inches(0.92)
        fg = WHITE if dark else INK
        soft = TINT if dark else MUTED
        if spec.get("rate"):
            rb = _text_box(slide, x, y, card_w, Inches(0.34))
            tf = _txt(rb, size=10, space_after=0)
            p = tf.paragraphs[0]
            _run(p, spec["rate"][0], size=10, bold=True, color=BLUE)
            _run(p, spec["rate"][1], size=10, bold=True, color=fg)
            y = y + Inches(0.34)
            rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x + Inches(0.1),
                                          y, card_w - Inches(0.2), Pt(1))
            rule.fill.solid()
            rule.fill.fore_color.rgb = LINE if not dark else WHITE
            rule.line.fill.background()
            rule.shadow.inherit = False
            y = y + Inches(0.08)
        if spec.get("scales"):
            sb = _text_box(slide, x, y, card_w, Inches(0.42))
            _txt(sb, size=9, color=soft, line=1.15, space_after=0)
            sb.text_frame.paragraphs[0].text = spec["scales"]
            y = y + Inches(0.46)

        bb = _text_box(slide, x, y, card_w, card_h - (y - top) - Inches(0.5))
        tf = _txt(bb, size=9, color=fg, line=1.15, space_after=0)
        rows = list(spec.get("bullets") or [])
        for j, text in enumerate(rows):
            p = tf.paragraphs[0] if j == 0 else _para(
                tf, size=9, color=fg, line=1.15, space_before=6, space_after=0)
            head, _, rest = text.partition(" - ")
            if rest:
                _run(p, head + " - ", size=9, bold=True, color=fg)
                _run(p, rest, size=9, color=fg)
            else:
                _run(p, text, size=9, color=fg)
        if spec.get("accent"):
            p = _para(tf, size=9, color=BLUE, line=1.15, space_before=6,
                      space_after=0)
            _run(p, spec["accent"], size=9, bold=True,
                 color=(TINT if dark else BLUE))
        if spec.get("onetime"):
            p = _para(tf, size=9, color=fg, line=1.15, space_before=8,
                      space_after=0)
            _run(p, COPY["shield_onetime_head"], size=9, bold=True, color=fg)
            for text in spec["onetime"]:
                p = _para(tf, size=8, color=fg, line=1.1, space_before=3,
                          space_after=0)
                _run(p, "•  " + text, size=8, color=fg)

        if spec.get("price"):
            pill_w = min(card_w - Inches(0.3), Inches(2.1))
            pill = _box(slide, x + (card_w - pill_w) / 2,
                        top + card_h - Inches(0.42), pill_w, Inches(0.3),
                        fill=(WHITE if dark else NAVY), outline=None,
                        radius=0.5)
            _txt(pill, size=9, bold=True, color=(NAVY if dark else WHITE),
                 align=PP_ALIGN.CENTER, space_after=0)
            pill.text_frame.paragraphs[0].text = spec["price"]
            pill.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    return slide


# ------------------------------------------------------------------- build
def build_rep_proposal_pptx(d):
    """The ORM deck, from the same quote the reputation proposal is built
    from."""
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    strat = _strategies(d)
    _slide_product(prs, d)
    if "Proactive" in strat:
        _strategy_slide(prs, DOC["proactive_heading"], DOC["proactive_lead"],
                        DOC["proactive_items"], columns=2)
    if "Reactive" in strat:
        _strategy_slide(prs, DOC["reactive_heading"], DOC["reactive_lead"],
                        DOC["reactive_items"],
                        bundle_head=DOC["reactive_bundle_head"])
    removals = [r for r in COPY["removals"]
                if (r[0] == "Review Removals" and "Review Removals" in strat)
                or (r[0] == "Site/Article Removals"
                    and "Site/Article Removals" in strat)]
    if removals:
        _strategy_slide(prs, "", "", removals, item_color=BLUE)
    # A SNAPSHOT WITH NOTHING IN IT IS A SLIDE TO DELETE BY HAND.
    snap = _snap(d)
    if any(snap.get(k) for k in ("suggest", "organic", "forums", "locations")):
        _slide_snapshot(prs, d)
    cards = _cards(d)
    if cards:
        _slide_details(prs, d, cards)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def _strategies(d):
    """What was sold, read off the quote rather than off a campaign word.

    build_rep_quote sends `strategy` as the four values, one per line the
    quote actually carries, so each slide is independent of the others and
    every combination is covered by the same four rules.
    """
    h = _handoff(d)
    named = [str(x) for x in (h.get("strategy") or [])]
    if named:
        return set(named)
    raw = d.get("strategy") or d.get("campaign") or ""
    text = (raw if isinstance(raw, str)
            else ", ".join(str(x) for x in raw)).lower()
    out = set()
    if "reactive" in text or "bundle" in text:
        out.add("Reactive")
    if "proactive" in text or "bundle" in text:
        out.add("Proactive")
    return out
