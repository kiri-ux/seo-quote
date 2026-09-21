"""MMDDYYYY_SEO_Client Name_Order ID, and each segment only when it applies.

THE PRODUCT TAG GOES BETWEEN THE DATE AND THE NAME. A client with both
products got two files named identically apart from the extension, and an ORM
deck and an SEO deck for the same client on the same day collided outright --
same date, same name, both .pptx. Between the date and the name is where it
keeps a folder sorted by filename still grouping a client's work by day.
(2026-09-21, Kiri)
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app as m

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1; print("  ok  ", name)
    else:
        fail += 1; print("  FAIL", name, "got", repr(got), "want", repr(want))

WHEN = datetime.datetime(2026, 9, 16)
f = lambda c, o="": m.proposal_filename(c, o, when=WHEN)

check("full", f("ENT Consultants of North MS", "56310"),
      "09162026_ENT Consultants of North MS_56310.docx")
check("noOrderNoSegment", f("ENT Consultants of North MS"),
      "09162026_ENT Consultants of North MS.docx")
check("blankOrderNoSegment", f("Ski Barn", "   "), "09162026_Ski Barn.docx")
check("spacesKept", " " in f("Ski Barn", "1"), True)
check("monthAndDayPadded", f("A", "1").startswith("09162026_"), True)
check("noClient", f("", ""), "09162026_Client.docx")
check("slashesAreNotPaths", "/" not in f("Roof/Repair Co", "1"), True)
check("slashReplaced", f("Roof/Repair Co", "1"), "09162026_Roof-Repair Co_1.docx")
check("newlineStripped", "\n" not in f("Bad\nName", "1"), True)
check("orderKeptVerbatim", f("X", "SEO-2026-11"), "09162026_X_SEO-2026-11.docx")
check("extension", f("X", "1").endswith(".docx"), True)

# ---- the product tag -------------------------------------------------------
g = lambda c, o="", k="", e="docx": m.proposal_filename(c, o, ext=e, when=WHEN,
                                                        kind=k)
check("seoTagged", g("Ski Barn", "44973", "SEO"), "09162026_SEO_Ski Barn_44973.docx")
check("ormTagged", g("Ski Barn", "44973", "ORM"), "09162026_ORM_Ski Barn_44973.docx")
check("tagSitsAfterTheDate", g("Ski Barn", "", "ORM").startswith("09162026_ORM_"),
      True)
check("andBeforeTheClientName", g("Ski Barn", "", "ORM"),
      "09162026_ORM_Ski Barn.docx")
check("tagIsUpperCased", g("Ski Barn", "", "orm"), "09162026_ORM_Ski Barn.docx")
# THE TWO DECKS NO LONGER COLLIDE. Same client, same day, same extension.
check("theTwoDecksAreDifferentFiles",
      g("City Heating and Air", "44973", "SEO", "pptx")
      != g("City Heating and Air", "44973", "ORM", "pptx"), True)
# No kind is still a valid name -- nothing carries an empty segment.
check("noKindNoSegment", g("Ski Barn", "1"), "09162026_Ski Barn_1.docx")
check("noDoubleUnderscore", "__" not in g("Ski Barn", "1", ""), True)


# Every download route names the file by this rule.
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app.py"), encoding="utf-8").read()
# Five downloads now: the SEO proposal and its deck, the reputation proposal
# and its deck, and the review analysis.
check("everyRouteUsesIt", src.count("download_name=proposal_filename("), 5)
check("noOldSeoName", "_SEO_Proposal.docx" in src, False)
check("noOldRepName", "_Reputation_Proposal.docx" in src, False)
check("noOldAnalysisName", "_Review_Removal_Analysis.docx" in src, False)

# The order ID rides in on the request body.
check("orderReadFromBody", src.count('proposal_filename(d.get("brand"),'), 5)
# ...and each route names its own product: the reputation proposal, its deck
# and the review analysis are ORM; the SEO proposal and its deck are SEO.
check("threeOrmRoutes", src.count('kind="ORM"'), 3)
check("twoSeoRoutes", src.count('kind="SEO"'), 2)
check("everyRouteIsTagged",
      src.count('kind="ORM"') + src.count('kind="SEO"'),
      src.count("download_name=proposal_filename("))

# client_meta answers a read as well as a write.
check("metaReadable", "methods=[\"GET\", \"POST\"]" in src, True)
check("orderNoIsAMetaKey", "order_no" in __import__("storage").CLIENT_META_KEYS, True)
check("partnerIsAMetaKey", "partner" in __import__("storage").CLIENT_META_KEYS, True)

print(f"\n{ok + fail} checks, {fail} failed")
sys.exit(1 if fail else 0)
