"""
Reputation Management — brand scan engine.

Automates Brendan's diagnostic section: brand term universe with negative-
modifier volumes, SERP threat table for "{brand} reviews" with owned-asset
tagging, related-searches + auto-suggest flags, Google location discovery,
and review-level negative counting (worst-first pull, so counting negatives
costs cents even on a 100-location DSO).

Dependency-injected: app.py calls init(dfs_post) at import so this module
never imports app (avoids the circular).

DFS cost notes (July 2026 pricing):
  keywords_for_keywords live ......... ~$0.05 / call
  SERP organic live advanced ......... ~$0.002 / call
  SERP autocomplete live ............. ~$0.002 / call
  business_listings search live ...... ~$0.002 / call (database, instant)
  google/reviews task (priority 2) ... $0.0015 per 10 reviews, ~1 min
Sort worst-first + depth 200/location => full Sage-scale negative count ~$3-4.
"""

import re

_post = None                      # injected dfs_post(path, payload, ...)

def init(dfs_post):
    global _post
    _post = dfs_post


# ---------------------------------------------------------------- negatives
def _squash(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


# ------------------------------------------------------------- the core name
# A company name wearing its own paperwork. Only a TRAILING token counts, so
# "PA Roofing" and "Co-op Market" keep every word of their names.
#
# UNAMBIGUOUS MARKERS ONLY. The obvious additions — ag, sa, nv, bv — read as a
# state or a trade as often as an entity type, and stripping one collapses
# "Midwest Ag" to "midwest", which then counts a region's worth of other
# people's volume as this client's brand. A suffix earns its place here by
# being a word no US client's trading name ends in for any other reason.
_CORP_SUFFIX = frozenset("""llc inc incorporated corp corporation ltd limited
llp lllp pllc plc pc pa lp co company gmbh""".split())

# Words that join a name rather than being part of it. A searcher types the
# ampersand, spells it out, or drops it entirely, and all three are the same
# business.
_CONNECTORS = frozenset({"and", "of", "the"})


def _norm_tokens(text):
    """Name tokens, punctuation-blind, with '&' spelled out.

    "Cisney & O'Donnell, P.A." -> ['cisney', 'and', 'odonnell', 'pa']
    """
    out = []
    for raw in (text or "").lower().replace("&", " and ").split():
        w = re.sub(r"[^a-z0-9]", "", raw)
        if w:
            out.append(w)
    return out


def _sig(toks):
    """The tokens that carry the name — connectors dropped."""
    return [t for t in toks if t not in _CONNECTORS]


def brand_core(brand):
    """The brand as a search box gets it: normalized tokens, legal tail gone.

    A CLIENT NAME CARRIES ITS PAPERWORK AND A SEARCH BOX DOES NOT. Cisney &
    O'Donnell PA scanned to 0/mo of total brand volume — not because nobody
    searches them, but because every name match here asked for the ENTERED
    name as a literal substring and no phrase anyone types ends in "pa". Every
    row DataForSEO returned classified as a different company, the universe
    summed to zero, and Search Protection priced off its floor instead of off
    measured demand.

    The punctuation did the same damage one layer down: "cisney and o'donnell"
    and "cisney odonnell" are the same business as "cisney & o'donnell" and
    matched none of the others, so even the volume that survived the suffix
    was split three ways and mostly discarded. (2026-09-21)
    """
    toks = _norm_tokens(brand)
    while len(toks) > 1 and toks[-1] in _CORP_SUFFIX:
        toks.pop()
    # A connector cannot end a name once the suffix it joined is gone.
    while len(toks) > 1 and toks[-1] in _CONNECTORS:
        toks.pop()
    return toks


def brand_key(brand):
    """Squashed core, CONNECTORS KEPT — the listing-title gate's key.

    Kept separate from the matcher below on purpose. That one anchors the
    front of the phrase and can afford to ignore connectors; a title gate is a
    bare substring test with nothing anchoring it, and dropping the "and"
    turns "cityheatingair" loose inside "Twin City Heating Air and Electric
    Blaine" — the 45-location scan all over again.
    """
    return "".join(brand_core(brand))


def brand_seed(brand):
    """The entered brand minus its legal tail, original spelling intact.

    What gets SENT to DataForSEO, as opposed to what gets matched. Seeding
    keywords_for_keywords with "cisney & o'donnell pa" asks Google Ads to
    expand a phrase nobody types, so the result set is thin before any filter
    runs.
    """
    words = (brand or "").replace("&", " & ").split()
    while len(words) > 1:
        w = re.sub(r"[^a-z0-9]", "", words[-1].lower())
        if w in _CORP_SUFFIX or w in _CONNECTORS or not w:
            words.pop()
        else:
            break
    # "Seascape, Inc" left "Seascape," and the scan searched "seascape,
    # reviews". (2026-09-25)
    return " ".join(words).strip().rstrip(",.;:-").strip()


def _match_key(brand, alias=""):
    """The token run a phrase has to carry to be this client's.

    Normally the brand's own core. When Google's listing name is also known
    the two are reconciled on their COMMON TOKEN PREFIX, which is what lets a
    listing tail fall away: "Cisney & O'Donnell PA" and "Cisney & O'Donnell
    Builders & Remodelers" agree on "cisney odonnell", and that head is
    attested by two independent sources rather than guessed at.

    Two sources are the whole point. Trimming a tail off one name on its own
    would hand "Denver Dental Group" the term "denver dental" — a service in a
    city, the best keyword they could buy, and thousands a month of somebody
    else's volume priced as theirs.
    """
    core = _sig(brand_core(brand))
    other = _sig(brand_core(alias))
    if core and other:
        n = 0
        while n < len(core) and n < len(other) and core[n] == other[n]:
            n += 1
        if n >= 2:
            return core[:n]
    return core


def _run_at(toks, key):
    """Where `key` sits in `toks` as one contiguous run: (index, tokens eaten),
    or (-1, 0).

    Also matches the run-together spelling of a two-or-more-word name, which
    is how people type a brand they know from a URL. That match eats ONE token
    rather than the key's length, which is why the count comes back with the
    index instead of being assumed by the caller. Anchored at the front of the
    token, so "cityheatingairconditioning" is theirs and "twincityheatingair"
    is not.
    """
    n = len(key)
    if not n:
        return -1, 0
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == key:
            return i, n
    if n >= 2:
        squashed = "".join(key)
        for i, t in enumerate(toks):
            if t.startswith(squashed):
                return i, 1
    return -1, 0


def names_client(phrase, brand, domain="", alias=""):
    """Does this search phrase actually name THIS client?

    Google's related-searches and People-Also-Search-For blocks are topical, not
    brand-scoped: a scan of "hot tubs etc reviews" returns "Hot Springs hot tub
    reviews complaints" and "Bullfrog hot tub reviews" — a manufacturer and a
    competitor. Those were rendered into the client's proposal visual, and the
    Hot Springs "complaints" phrase was counted as a NEGATIVE SIGNAL against a
    client it has nothing to do with, which both recommends a cleanup campaign
    and prices one (2026-08-05).

    It asks classify_term, so the core name answers here too and one filter
    cannot disagree with the other. A SQUASHED WHOLE NAME IS NOT A BRAND KEY:
    this used to test whether the entered name ran through the phrase with its
    punctuation removed, which put "cisney & o'donnell reviews" — their own
    phrase, off their own page one — in the "names a different company" box,
    because the key it was tested against still carried the "pa". Both of that
    client's related searches were excluded that way (2026-09-21).

    The bare domain is kept as a second key for a phrase written the way a URL
    is. When neither yields a usable key the filter stands down rather than
    emptying the panel.
    """
    core = _sig(brand_core(brand))
    host = (domain or "").split("//")[-1].split("/")[0].replace("www.", "")
    d = _squash(host.rsplit(".", 1)[0] if "." in host else host)
    if not core and len(d) <= 3:
        return True
    if core and classify_term(phrase, brand, alias=alias) is not None:
        return True
    if len(d) > 3:
        return d in "".join(_sig(_norm_tokens(phrase)))
    return False


NEG_MODIFIERS = {
    "lawsuit", "lawsuits", "complaint", "complaints", "scam", "scams",
    "fraud", "ripoff", "rip-off", "sue", "sued", "suing", "settlement",
    "class action", "recall", "arrest", "arrested", "controversy",
    "scandal", "investigation", "warning", "problem", "problems",
    "horror", "worst", "avoid", "shut down", "closing", "bankrupt",
    "bankruptcy", "bbb",
}
WATCH_MODIFIERS = {"reviews", "review", "legit", "rating", "ratings",
                   "is it good", "safe"}

# Words that may sit in FRONT of the brand and still leave the phrase about
# this client: question words, articles, and the modifiers people search with.
LEADERS = {"is", "are", "was", "the", "a", "an", "does", "do", "did", "who",
           "what", "why", "how", "where", "when", "best", "worst", "about",
           "for", "of", "at", "near", "reviews", "review", "rating", "ratings",
           "complaints", "complaint", "lawsuit", "lawsuits", "scam", "scams"}


def classify_term(term, brand, alias=""):
    """Which class of brand term is this, or None if it is not the client's.

    A BRAND NAME MADE OF COMMON WORDS IS NOT A BRAND FILTER. This asked only
    whether the brand appeared ANYWHERE in the term, so a scan of "City Heating
    and Air" claimed holy city heating and air (590/mo), river city (390), bold
    city (260), twin city (260), forest city (260), queen city (170) and
    central city (110) as this client's brand universe. Their own term is
    480/mo. The other 2,710 belong to seven other companies, and Search
    Protection is priced off that total -- a 6.6x overcharge that nobody could
    see, because the old snapshot only ever displayed the flagged terms and
    every one of these classified neutral.

    So the words in FRONT of the brand have to be words a searcher would put
    there. Anything else is a different company whose name happens to contain
    these words. What comes AFTER is left alone: "city heating and air
    conditioning" is how Google lists this very client. (2026-09-17)

    MATCHED ON THE CORE NAME, NOT THE ENTERED STRING. The gate above is the
    right gate and the key it ran on was wrong: a literal substring of the
    name as typed, legal suffix and apostrophes and all. See brand_core —
    Cisney & O'Donnell PA came back with a brand universe of zero because of
    it. Tokens now, so the front stays anchored while the spelling stops
    mattering. (2026-09-21)
    """
    key = _match_key(brand, alias)
    # A one-word core has nothing but its own length keeping it from swallowing
    # a common word, so a short one falls back to the name as entered.
    if len(key) == 1 and len(key[0]) < 4:
        key = _sig(_norm_tokens(brand))
    sig = _sig(_norm_tokens(term))
    i, eaten = _run_at(sig, key)
    if i < 0:
        return None                       # not this client's brand term
    lead = sig[:i]
    if any(w not in LEADERS for w in lead):
        return None                       # someone else's name
    rest = " ".join(lead + sig[i + eaten:])
    for m in NEG_MODIFIERS:
        if m in rest:
            return "negative"
    for m in WATCH_MODIFIERS:
        if m in rest:
            return "watch"
    return "neutral"


PROBE_MODIFIERS = ["lawsuit", "complaints", "scam", "fraud", "class action",
                   "settlement", "reviews", "legit"]

def _query(brand, query=""):
    """What gets searched: the planner's term as typed, else the core name."""
    return " ".join((query or "").lower().split()) or brand_seed(brand).lower()


def _carries(phrase, query=""):
    """With no term typed every phrase passes; with one, it has to be there."""
    q = " ".join((query or "").lower().split())
    return not q or q in " ".join((phrase or "").lower().split())


def suggest_query(brand, alias="", location=None, tried=()):
    """The next term to search when page one was somebody else's, in order:
    the name with its legal tail ("seascape inc"), the name Google lists them
    under, the core plus their city, the full name plus their city. None left
    that has not been tried: "". (2026-09-25)"""
    plain = lambda x: " ".join(re.sub(r"[^\w&' ]", " ", x or "").lower().split())
    if isinstance(tried, str):
        tried = [tried]
    done = {plain(t) for t in tried} | {brand_seed(brand).lower()}
    city = plain((location or "").split(",")[0])
    for c in (plain(brand), plain(alias),
              f"{brand_seed(brand).lower()} {city}".strip(),
              f"{plain(brand)} {city}".strip()):
        if c and c not in done:
            return c
    return ""


def scan_terms(brand, alias="", query=""):
    """Brand term universe via keywords_for_keywords (US national), PLUS an
    exact-match probe of the canonical negative/watch variants. KFK returns
    GROUPED volumes that merge close variants (the same quirk the SEO tool
    works around) — so '{brand} lawsuit' can vanish into the parent term and
    silently undercount negative volume. The probe re-pulls those terms from
    the Labs keyword database, which returns per-term exact volume."""
    # NATIONAL ON PURPOSE. A brand term is searched by whoever is looking for
    # that brand, wherever they are, and the Search Protection bases were
    # fitted on national volume (Sage at 51,330/mo). The SERP and auto-suggest
    # are localized because a page one is local; a brand's own demand is not.
    # SEEDED ON THE CORE NAME. "cisney & o'donnell pa" is a phrase nobody
    # types, so Google Ads had little to expand and the probe asked after
    # eight more phrases nobody types either.
    # THE PLANNER'S SEARCH TERM WINS. A one-word core like "seascape" is also a
    # cruise ship, and its volume was priced as Seascape, Inc's. When a term is
    # typed, it seeds the lookup and a phrase has to carry it. (2026-09-25)
    b = _query(brand, query)
    payload = [{"keywords": [b], "location_code": 2840,
                "language_code": "en", "sort_by": "search_volume"}]
    data = _post("/keywords_data/google_ads/keywords_for_keywords/live",
                 payload, timeout=90)
    by_term = {}
    returned = 0
    for it in (data["tasks"][0]["result"] or []):
        returned += 1
        kw = (it.get("keyword") or "").lower()
        vol = it.get("search_volume") or 0
        cls = classify_term(kw, brand, alias=alias)
        if cls and _carries(kw, query):
            by_term[kw] = {"term": kw, "volume": vol, "class": cls, "src": "kfk"}

    # exact-match probe: canonical variants + any flagged KFK terms
    probes = [f"{b} {m}" for m in PROBE_MODIFIERS]
    probes += [t for t, r in by_term.items() if r["class"] != "neutral"]
    probes = sorted(set(probes))
    try:
        pdata = _post("/dataforseo_labs/google/keyword_overview/live",
                      [{"keywords": probes, "location_code": 2840,
                        "language_code": "en"}], timeout=45)
        for block in (pdata["tasks"][0]["result"] or []):
            for it in (block.get("items") or []):
                kw = (it.get("keyword") or "").lower()
                vol = ((it.get("keyword_info") or {}).get("search_volume")) or 0
                cls = classify_term(kw, brand, alias=alias)
                if not cls or not _carries(kw, query):
                    continue
                # exact volume overrides the grouped KFK number
                by_term[kw] = {"term": kw, "volume": vol, "class": cls,
                               "src": "exact"}
    except Exception:
        pass                      # probe is enrichment — never fail the scan

    rows = sorted(by_term.values(), key=lambda r: -r["volume"])
    tot = {c: sum(r["volume"] for r in rows if r["class"] == c)
           for c in ("neutral", "watch", "negative")}
    # WHAT THE LOOKUP RETURNED, NOT JUST WHAT IT ADDED UP TO. A total of zero
    # has two causes that price identically and read identically: Google
    # returned nothing for this brand, or it returned plenty and none of it was
    # this client's. Cisney & O'Donnell was the second for weeks and there was
    # no way to tell from the screen. Both counts travel with the total.
    # (2026-09-21)
    return {"terms": rows[:120],
            "total_volume": sum(tot.values()),
            "negative_volume": tot["negative"],
            "watch_volume": tot["watch"],
            "rows_returned": returned,
            "rows_matched": len(rows)}


# --------------------------------------------------------------------- serp
def _domain(d):
    """Normalize a domain or full URL: strip scheme, path, query, port, www."""
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0]
    return d[4:] if d.startswith("www.") else d

# Domain -> recommended tactic for the SERP threat table. Review counts in
# the removal quote are GOOGLE Business reviews only; these third-party pages
# route to other tactics (Visions precedent: complaint boards / Reddit /
# Trustpilot pages can be removed at the PAGE level via Website Removal).
ROUTES = [
    (("yelp.", "glassdoor.", "indeed.", "bbb.",
      "facebook.", "instagram.", "x.com", "twitter.", "tiktok.",
      "linkedin."), "suppression"),
    (("trustpilot.", "complaintsboard.", "pissedconsumer.", "scampulse.",
      "ripoffreport.", "gripeo.", "reddit.", "quora."), "site removal"),
]

# A page whose own title says it is praise is not a removal target, whatever
# host it sits on. "Positive Reviews on MSC Seascape : r/MSCCruises" was
# routed to site removal because it was on reddit. (2026-09-25, Kiri)
POS_TITLE = ("positive review", "love ", "loved ", "great ", "amazing",
             "excellent", "recommend", "5 star", "five star", "5-star",
             "best ")
NEG_TITLE = ("negative", "bad ", "terrible", "awful", "disappoint", "never again",
             "don't", "do not", "beware")

def positive_title(title):
    t = f" {(title or '').lower()} "
    if any(m in t for m in NEG_MODIFIERS) or any(m in t for m in NEG_TITLE):
        return False
    return any(m in t for m in POS_TITLE)


def tactic_of(res):
    """The tactic a saved result should show now: a scan saved before the
    title rule still says site removal on a page titled as praise."""
    if not res.get("owned") and positive_title(res.get("title")):
        return "positive \u2014 leave"
    return res.get("tactic") or ""


# A PROFILE THE CLIENT RUNS IS THEIRS. The URL shape, not the host: a
# Facebook page is theirs, a post or group thread on Facebook is not.
_PROFILE_URL = re.compile(
    r"^https?://(?:www\.|m\.)?(?:"
    r"facebook\.com/(?!groups/|events/|photo|story|permalink|watch|share)[^/?#]+"
    r"|instagram\.com/(?!p/|reel/|explore/)[^/?#]+"
    r"|(?:x|twitter)\.com/(?!i/|search)[^/?#]+"
    r"|tiktok\.com/@[^/?#]+"
    r"|youtube\.com/(?:@|c/|channel/|user/)[^/?#]+"
    r"|linkedin\.com/company/[^/?#]+"
    r")/?(?:[?#].*)?$", re.I)


def is_profile(url):
    return bool(_PROFILE_URL.match(url or ""))


def route_tactic(domain, owned=False, forum=False, rating=None, title=None):
    if owned:
        return "owned \u2014 boost"
    if positive_title(title):
        return "positive \u2014 leave"
    # A third-party result showing a strong rating is an asset working in the
    # client's favour — suppressing it would bury the brand's own good
    # reviews. Leave it, and let it help push the actual negatives down.
    # (This is routing inside the SCAN. It is not the retired "sentiment
    # routing" product, which drove outreach to customers and is not offered.)
    if rating is not None and rating >= 4.0:
        return "positive \u2014 leave"
    d = (domain or "").lower()
    for prefixes, tactic in ROUTES:
        if any(p in d for p in prefixes):
            return tactic
    return "site removal" if forum else "suppression"


def _rating_from_text(*texts):
    """Google rarely returns structured star snippets now — the rating usually
    lives in the description text ('average rating of 2.6 from 90 reviews',
    '1.4 / 5', 'Rated 3.1 out of 5'). Regex it out; None if absent."""
    pat = re.compile(
        r"(?:rated\s+|rating(?:\s+of)?[:\s]+|average rating of\s+)?"
        r"([0-5]\.\d)\s*(?:/\s*5|out of 5|stars?|\u2605|from\s+[\d,]+\s+reviews)",
        re.I)
    for t in texts:
        if not t:
            continue
        m = pat.search(t)
        if m:
            try:
                v = float(m.group(1))
                if 0 < v <= 5:
                    return v
            except ValueError:
                pass
    return None


_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_ABBR_STATE = {v: k for k, v in _US_STATES.items()}


def _words(t):
    return re.findall(r"[a-z0-9']+", (t or "").lower())


# Words that follow a name on any company's pages, so they say nothing about
# which company it is.
_GENERIC_AFTER = frozenset("""reviews review employee employees employment
jobs job careers home about contact complaints complaint ratings rating
company official website site page profile info photos near salary salaries
pay hours phone number address location locations prices pricing cost login
news overview in at of the and vs for is on by a an with from to legit safe
good bad worth""".split()) | frozenset(
    w for m in NEG_MODIFIERS for w in m.split())


def home_of(address):
    """(city, state abbreviation) off a listing address like "10571 Calle
    Lee #137, Los Alamitos, CA 90720"; (None, None) when it does not parse."""
    m = re.search(r",\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s+\d{5}", address or "")
    if not m or m.group(2) not in _ABBR_STATE:
        return None, None
    return m.group(1).strip(), m.group(2)


def states_named(text):
    """US states a result names: full names anywhere, abbreviations only
    where an address puts them ("Coventry, RI", "Coventry RI 02816")."""
    t = text or ""
    low = t.lower()
    out = {ab for name, ab in _US_STATES.items()
           if re.search(r"\b" + name + r"\b", low)}
    # "Coventry, RI" with a comma reads as an address whatever follows it --
    # a title cut to "Coventry, RI..." slipped through (2026-09-25). Without
    # the comma it has to end the phrase, so "Reviews IN the US" is not Indiana.
    for pat in (r"\b[A-Z][a-z]+,\s+([A-Z]{2})(?![A-Za-z])",
                r"\b[A-Z][a-z]+\s+([A-Z]{2})(?=\s*(?:$|\d{5}|[|,.\-\u2013\u2026\u00b7)]))"):
        for m in re.finditer(pat, t):
            if m.group(1) in _ABBR_STATE:
                out.add(m.group(1))
    return out


def _where(location):
    """Ask Google from the client's market when we know it, the US when we do
    not. A reputation problem is local: scanning "City Heating and Air reviews"
    nationally returned HVAC companies in Charlotte, Tucson and Blaine, and
    those pages were then counted as this client's page one and priced for
    removal. (2026-09-17)"""
    return ({"location_name": location} if location
            else {"location_code": 2840})


def scan_serp(brand, domain="", location=None, alias="", query="", tried=(),
              home=""):
    """Top-10 for '{brand} reviews': organic results (with ratings parsed from
    snippet text when Google omits star markup), the Reddit/forums block, the
    AI Overview, related searches — owned tagging against the client domain."""
    # THE CORE NAME IS THE QUERY. "cisney & o'donnell pa reviews" is not a
    # search anyone runs, so the page one it returns is not the page one the
    # client is judged on.
    q = _query(brand, query)
    kw = q if "review" in q else f"{q} reviews"
    # FROM THEIR TOWN WHEN THE ORDER IS NATIONWIDE. "seascape inc reviews"
    # asked of the whole country was a lawn care company in Rhode Island; the
    # client's Google listing says Los Alamitos. (2026-09-25)
    city, st = home_of(home)
    if not location and city:
        location = f"{city},{_ABBR_STATE[st].title()},United States"
        try:
            data = _post("/serp/google/organic/live/advanced",
                         [dict({"keyword": kw, "language_code": "en", "depth": 10},
                               **_where(location))], timeout=45)
            if (data.get("tasks") or [{}])[0].get("result") is None:
                raise ValueError("location refused")
        except Exception:
            location = None
            data = None
    else:
        data = None
    if data is None:
        data = _post("/serp/google/organic/live/advanced",
                     [dict({"keyword": kw, "language_code": "en", "depth": 10},
                           **_where(location))], timeout=45)
    own = _domain(domain)
    organic, related, forums, pasf = [], [], [], []
    ai_text = ""
    for it in (data["tasks"][0]["result"] or [{}])[0].get("items") or []:
        t = it.get("type")
        if t == "organic":
            rat = (it.get("rating") or {})
            organic.append({
                # THE ORGANIC RANK, NOT THE ABSOLUTE ONE. rank_absolute counts
                # every element on the page -- ads, the local pack, the AI
                # overview, image strips -- so the first organic result came
                # back as #6 and a top-10 pull read 6 through 14. Nobody can
                # tell whether that is page one. app.py's own rank check
                # already prefers rank_group; this is the same read.
                # (2026-09-17)
                "pos": it.get("rank_group") or it.get("rank_absolute"),
                "title": it.get("title"),
                "domain": _domain(it.get("domain")),
                # THE PAGE, NOT JUST ITS HOST. A removal is quoted per page and
                # Brendan's proposals list the URLs; the domain alone cannot say
                # which of a host's pages was tagged.
                "url": it.get("url") or "",
                "snippet": (it.get("description") or "")[:200],
                "rating": rat.get("value") or _rating_from_text(
                    it.get("description"), it.get("title")),
                "votes": rat.get("votes_count"),
                "owned": bool(own) and own == _domain(it.get("domain")),
                "tactic": route_tactic(_domain(it.get("domain")),
                                       bool(own) and own == _domain(it.get("domain")),
                                       rating=rat.get("value") or _rating_from_text(
                                           it.get("description"), it.get("title")),
                                       title=it.get("title")),
            })
        elif t in ("discussions_and_forums", "found_on_web"):
            for el in (it.get("items") or [])[:6]:
                dom = _domain(el.get("domain") or el.get("source"))
                forums.append({
                    # A block's own position on the page: it has no organic
                    # rank of its own, so absolute is the only reading.
                    "pos": it.get("rank_absolute"),
                    "domain": dom,
                    "title": el.get("title"),
                    "url": el.get("url") or "",
                    "tactic": route_tactic(dom, forum=True, title=el.get("title")),
                })
        elif t == "ai_overview":
            parts = []
            for el in (it.get("items") or []):
                for k in ("text", "title", "snippet"):
                    if el.get(k):
                        parts.append(el[k])
            if it.get("markdown"):
                parts.append(it["markdown"])
            ai_text = " ".join(parts)[:1200]
        elif t == "related_searches":
            related = [x for x in (it.get("items") or []) if x][:10]
        elif t == "people_also_search":
            pasf += [x for x in (it.get("items") or []) if isinstance(x, str)][:8]
    # PAGE ONE FOR THE NAME, NOT FOR THE WORD. "seascape reviews" came back
    # all MSC Seascape, a cruise ship, and each page was tagged and priced as
    # Seascape, Inc's. A result whose title names somebody else is set aside
    # with the phrases below; the client's own site always stays. (2026-09-25)
    #
    # A NAME IS NOT A COMPANY. "SeaScape Lawn Care Inc" in Coventry, RI names
    # "seascape" as well as the client does. Two more tells, from what the
    # scan already knows about the client: a site whose domain carries their
    # name but is not theirs (seascapeinc.com beside seascapeinc.net), and a
    # result that names a state they are not in. (2026-09-25)
    core = _squash(brand_seed(brand))
    def _ours(x):
        if x.get("owned"):
            return True
        host = (x.get("domain") or "").rsplit(".", 1)[0]
        if own and len(core) > 3 and core in _squash(host):
            return False
        named = states_named(f"{x.get('title') or ''} {x.get('snippet') or ''}")
        if st and named and st not in named:
            return False
        return names_client(x.get("title") or "", brand, domain, alias=alias)
    # THE WORD AFTER THE NAME SAYS WHOSE PAGE IT IS. "Seascape Enterprises",
    # "Seascape Technologies", "SeaScape Property Management", "Seascape
    # Kayak Tours" all name "seascape" and are six other companies. A result
    # stays only when what follows the name is the client's own: a legal
    # suffix, a word from their name, their Google listing, their own site's
    # title or their town, or a word any company's page puts there
    # ("reviews", "jobs"). (2026-09-25, Kiri)
    stem = lambda w: w[:-1] if len(w) > 3 and w.endswith("s") else w
    theirs = {stem(w) for w in _words(" ".join(
        [brand, alias, city or ""]
        + [f"{x.get('title') or ''} {x.get('snippet') or ''}"
           for x in organic if x.get("owned")]))}
    bt = _words(brand_seed(brand))
    def _next_word(x):
        w = _words(x.get("title") or "")
        for i in range(len(w)):
            if w[i:i + len(bt)] == bt:
                return w[i + len(bt)] if i + len(bt) < len(w) else None
            if len(bt) > 1 and _squash(w[i]) == core:
                return w[i + 1] if i + 1 < len(w) else None
        return None
    def _kept(x):
        if x.get("owned"):
            return True
        if not _ours(x):
            return False
        nw = _next_word(x)
        return (nw is None or nw in _CORP_SUFFIX or nw in _GENERIC_AFTER
                or stem(nw) in theirs or nw in _US_STATES
                or nw.upper() in _ABBR_STATE)
    off_brand_results = [x for x in organic + forums if not _kept(x)]
    organic = [x for x in organic if _kept(x)]
    forums = [x for x in forums if _kept(x)]
    # THEIR OWN SOCIAL PROFILE IS CLIENT-CONTROLLED. "Seascape, Inc.
    # (@seascapefoods.inc)" on Instagram was tagged 3rd party and priced for
    # suppression. Only after the filter above, so another Seascape's page is
    # never taken for theirs. (2026-09-25, Kiri)
    for x in organic:
        if not x["owned"] and is_profile(x.get("url")):
            x["owned"] = x["profile"] = True
            x["tactic"] = "owned \u2014 boost"
    # Drop phrases that name a different company BEFORE anything counts them.
    off_brand = [x for x in (related + pasf)
                 if not names_client(x, brand, domain, alias=alias)]
    related = [x for x in related if names_client(x, brand, domain, alias=alias)]
    pasf = [x for x in pasf if names_client(x, brand, domain, alias=alias)]
    neg_related = [x for x in related
                   if any(m in x.lower() for m in NEG_MODIFIERS)]
    neg_pasf = [x for x in pasf if any(m in x.lower() for m in NEG_MODIFIERS)]
    ai_negative = [m for m in NEG_MODIFIERS if m in ai_text.lower()]
    owned_top10 = sum(1 for o in organic if o["owned"])
    # MOSTLY SOMEBODY ELSE'S: name the next term to try. The page asks again
    # with it, and passes every term already tried so none repeats.
    seen = len(organic) + len(forums) + len(off_brand_results)
    suggested = (suggest_query(brand, alias, location, tried=[q, *tried])
                 if seen and len(off_brand_results) * 2 >= seen else "")
    return {"query": kw, "organic": organic[:10], "forums": forums,
            "ai_overview": ai_text, "ai_negative": ai_negative,
            "related": related, "negative_related": neg_related,
            "pasf": pasf, "negative_pasf": neg_pasf,
            "off_brand_phrases": off_brand,
            "off_brand_results": off_brand_results,
            "suggested_query": suggested,
            "searched_from": location or "United States",
            "owned_in_top10": owned_top10}


def scan_autocomplete(brand, location=None, query=""):
    """Auto-suggest for the brand and '{brand} reviews' — negative flags.
    Uses client=gws-wiz (the actual Google search-box client; the DFS default
    returns a thinner set). Terms that come back empty get a fallback pass:
    trailing-space (next-word suggestions, matching Brendan's screenshots)
    then last-char-trimmed prefix. Extra calls only fire for empty terms."""
    _b = _query(brand, query)
    kws = [_b, f"{_b} reviews"]

    def _pull(keywords):
        payload = [dict({"keyword": k, "language_code": "en",
                         "client": "gws-wiz"}, **_where(location))
                   for k in keywords]
        data = _post("/serp/google/autocomplete/live/advanced", payload,
                     timeout=30)
        res = {}
        for task in data.get("tasks") or []:
            kw = ((task.get("data") or {}).get("keyword") or "")
            sugg = []
            for block in task.get("result") or []:
                for it in (block or {}).get("items") or []:
                    if it.get("type") == "autocomplete" and it.get("suggestion"):
                        sugg.append(it["suggestion"])
            res[kw] = sugg
        return res

    out = {}
    try:
        first = _pull(kws)
        for k in kws:
            out[k] = {"suggestions": first.get(k, []) or first.get(k.strip(), [])}
        # fallback pass for empties: "kw " (next-word) then "kw"[:-1] (prefix)
        empties = [k for k in kws if not out[k]["suggestions"]]
        if empties:
            variants = {}
            for k in empties:
                variants[k + " "] = (k, "next-word")
                variants[k[:-1]] = (k, "prefix")
            fb = _pull(list(variants.keys()))
            for vkey, sugg in fb.items():
                orig, how = variants.get(vkey) or variants.get(vkey.strip(), (None, None))
                if orig and sugg and not out[orig]["suggestions"]:
                    # keep only suggestions still about the original term
                    keep = [x for x in sugg if orig.split()[0] in x.lower()]
                    if keep:
                        out[orig]["suggestions"] = keep
                        out[orig]["via"] = how
        for k in kws:
            out[k]["negative"] = [x for x in out[k]["suggestions"]
                                  if any(m in x.lower() for m in NEG_MODIFIERS)]
    except Exception as e:
        for k in kws:
            out.setdefault(k, {"error": str(e)})
    return out


# ---------------------------------------------------------------- locations
def _market_city(location):
    """The city out of a DataForSEO location string, lowercased.
    'Knoxville,Tennessee,United States' -> 'knoxville'."""
    head = str(location or "").split(",")[0].strip().lower()
    return head if len(head) > 2 else ""


def scan_locations(brand, limit=200, domain=None, location=None):
    """Google Business location discovery via the Business Listings database
    (instant, no scrape). Tries the `title` search field, filter fallbacks,
    and — when the client website is known — a domain match, which finds the
    listing even when its name differs from the client name."""
    dom = (domain or "").lower().strip()
    dom = re.sub(r"^https?://", "", dom).split("/")[0].replace("www.", "")
    # THE DOMAIN GOES FIRST, NOT LAST. A listing pointing at the client's own
    # website IS the client; a listing whose name contains the client's words
    # is a guess. The domain attempts used to sit at the end of this list, so
    # they only ran when every name search had come back empty -- and a generic
    # name never comes back empty. "City Heating and Air" (cityheatandair.com)
    # matched 45 unrelated HVAC companies by name, the review pull ran on all
    # 45, and the quote priced 130 flagged reviews belonging to other people's
    # businesses. (2026-09-17)
    attempts = []
    if dom:
        attempts += [
            {"filters": [["domain", "=", dom]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
            {"filters": [["url", "like", f"%{dom}%"]], "limit": limit,
             "order_by": ["rating.votes_count,desc"], "_via_domain": True},
        ]
    # THE CORE NAME, NOT THE PAPERWORK. A Google Business listing is titled
    # the way the business trades, so "Cisney & O'Donnell PA" matched nothing
    # by name and only the domain attempt found their one listing.
    nm = brand_seed(brand)
    attempts += [
        {"title": nm, "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{nm.title()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
        {"filters": [["title", "like", f"%{nm.lower()}%"]], "limit": limit,
         "order_by": ["rating.votes_count,desc"]},
    ]
    last_err = None
    city = _market_city(location)
    # THE BRAND AS A PHRASE, NOT AS LOOSE WORDS. The gate used to ask whether
    # every token appeared ANYWHERE in the title, in any order, as a substring
    # -- so "city", "heating", "and", "air" all land inside "Twin City Heating
    # Air and Electric Blaine" and inside "City Air Experts Heating and
    # Cooling". Squashing both sides and asking for one contiguous run drops
    # both, and still tolerates the punctuation and spacing differences the
    # name matching exists for ("Hot Tubs Etc." -> hottubsetc).
    # CONNECTORS STAY IN THIS KEY. _squash dropped the ampersand outright, so a
    # client listed as "City Heating & Air" failed its own gate while the token
    # form keeps the "and" that holds "Twin City Heating Air and Electric
    # Blaine" out. The legal tail comes off; nothing else does.
    b_key = brand_key(brand)
    for payload in attempts:
        via_domain = payload.pop("_via_domain", False)
        try:
            data = _post("/business_data/business_listings/search/live",
                         [payload], timeout=90)
            task = (data.get("tasks") or [{}])[0]
            if task.get("status_code") != 20000:
                last_err = task.get("status_message") or "unknown DFS error"
                continue
            items = ((task.get("result") or [{}])[0] or {}).get("items") or []
            locs = []
            for it in items:
                title = (it.get("title") or "")
                # Title searches must carry the brand as a phrase; domain
                # matches skip that gate — a name mismatch is exactly what
                # they solve.
                if (not via_domain and len(b_key) > 3
                        and b_key not in brand_key(title)):
                    continue
                rat = it.get("rating") or {}
                locs.append({
                    "title": title,
                    "address": it.get("address"),
                    "place_id": it.get("place_id"),
                    "cid": it.get("cid"),
                    "rating": rat.get("value"),
                    "reviews": rat.get("votes_count") or 0,
                })
            strategy = ("domain" if via_domain
                        else ("title" if "title" in payload else "filter"))
            # A NAME MATCH THAT IS ALSO IN THEIR TOWN. The domain match is
            # identity and needs no help; the name fallback is a guess, and a
            # brand made of common words still collects Green City, Queen City
            # and River City after the phrase gate. When the order names a
            # market, keep the listings in it. If that empties the panel the
            # market is wrong or they trade elsewhere, so the unfiltered list
            # stands rather than nothing -- and `strategy` says which.
            if locs and not via_domain and city:
                near = [l for l in locs if city in (l.get("address") or "").lower()]
                if near:
                    locs, strategy = near, "title+market"
            if locs:
                return {"locations": locs,
                        "total_reviews": sum(l["reviews"] for l in locs),
                        "strategy": strategy}
        except Exception as e:
            last_err = str(e)
    if last_err:
        return {"locations": [], "total_reviews": 0,
                "error_detail": f"Listings lookup failed: {last_err}"}
    return {"locations": [], "total_reviews": 0}


# ------------------------------------------------------------- review pulls
def reviews_submit(place_ids, depth=200):
    """Queue worst-first review pulls (priority 2, ~1 min). Returns task ids.
    depth=200 => $0.03/location at priority pricing."""
    depth = max(10, min(4490, int(depth)))
    payload = [{"place_id": pid, "location_code": 2840, "language_code": "en",
                "depth": depth, "sort_by": "lowest_rating", "priority": 2,
                "tag": pid}
               for pid in place_ids]
    data = _post("/business_data/google/reviews/task_post", payload, timeout=60)
    tasks = []
    for t in data.get("tasks") or []:
        tasks.append({"id": t.get("id"),
                      "place_id": (t.get("data") or {}).get("tag"),
                      "ok": t.get("status_code") in (20000, 20100)})
    return {"tasks": tasks, "depth": depth}


def reviews_collect(task_ids):
    """Poll queued pulls. Counts 1-2 star (negative) and 3 star (weak) per
    task; flags when negatives hit the pull depth (=> more exist).

    QUEUED IS TRANSIENT. GONE IS PERMANENT. THEY CANNOT SHARE A BRANCH.

    This caught every raised exception and filed it as "pending: poll again",
    which is the same bug the rank check had on 2026-09-04 and the same one
    DataForSEO wrote to Kiri about. A 40401 Task Not Found arrives as an HTTP
    404, which dfs_post raises, and the browser re-sends every pending id twelve
    times at five-second intervals -- so one dead task is twelve failed calls
    per scan, and a ten-location DSO is a hundred and twenty.

    A task is gone the moment it has been read: DataForSEO drops it on
    collection and expires it after that. The trap is the completed pull with
    an empty result, a location with nothing to return -- that read consumed the
    task, so asking a second time is a guaranteed 40401. It is terminal, not
    pending. (2026-09-19, Kiri)
    """
    done, pending, gone = [], [], []
    for tid in task_ids:
        try:
            data = _post(f"/business_data/google/reviews/task_get/{tid}",
                         None, timeout=30, method="GET")
        except Exception as e:                       # noqa: BLE001
            # 40401 as an HTTP 404. Anything else is worth another ask.
            _code = getattr(getattr(e, "response", None), "status_code", None)
            (gone if _code in (404, 410) else pending).append(tid)
            continue
        try:
            task = (data.get("tasks") or [{}])[0]
            res = (task.get("result") or [None])[0]
            _sc = task.get("status_code")
            if _sc in (40401, 40400):                # 40401 inside a 200 body
                gone.append(tid)
                continue
            if _sc == 20000 and not res:
                # Read and empty: the task is spent, and asking again is a 404.
                #
                # EXCEPT WHEN 20000 MEANS "STILL WORKING". "Task Handed." and
                # "Task In Queue." both arrive under a 20000 on this provider,
                # and calling those spent would drop a location's whole star
                # split to save one call. The message is what separates them.
                if re.search(r"in queue|in progress|task handed|not yet completed",
                             str(task.get("status_message") or ""), re.I):
                    pending.append(tid)
                else:
                    gone.append(tid)
                continue
            if _sc == 20000 and res:
                items = res.get("items") or []
                vals = [((i.get("rating") or {}).get("value") or 5) for i in items]
                n1 = sum(1 for v in vals if v <= 1)
                n2 = sum(1 for v in vals if v == 2)
                n12 = n1 + n2
                n3 = sum(1 for v in vals if v == 3)
                # THE 4s AND 5s TOO. Without them the star split has to be
                # inferred from the profile's one-decimal average, and a 4.4
                # is anything from 4.35 to 4.45 -- on 600 reviews that is a
                # band 30 rating-points wide, which moves the "how many
                # removals reach 4.5" answer by several reviews. When the pull
                # covers the whole profile these are exact and nothing needs
                # inferring. (2026-09-10, Kiri)
                n4 = sum(1 for v in vals if v == 4)
                n5 = sum(1 for v in vals if v >= 5)
                _total = res.get("reviews_count") or 0
                done.append({
                    "id": tid,
                    "place_id": (task.get("data") or {}).get("tag"),
                    "title": res.get("title"),
                    "profile_rating": (res.get("rating") or {}).get("value"),
                    "profile_reviews": res.get("reviews_count"),
                    "pulled": len(items),
                    "neg_1": n1, "neg_2": n2, "neg_1_2": n12, "weak_3": n3,
                    "pos_4": n4, "pos_5": n5,
                    # Every review on the profile was pulled, so the buckets
                    # above are the whole distribution rather than a sample.
                    "complete": bool(_total and len(items) >= int(_total)),
                    "truncated": n12 >= len(items) and len(items) > 0,
                })
            else:
                pending.append(tid)                  # still in Google's queue
        except Exception:                            # noqa: BLE001
            # A malformed body is not a missing task; ask again.
            pending.append(tid)
    return {"done": done, "pending": pending, "gone": gone,
            "total_negatives": sum(d["neg_1_2"] for d in done),
            "total_weak": sum(d["weak_3"] for d in done)}
