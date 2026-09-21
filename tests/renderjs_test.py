"""RENDER THE PAGE WHEN THE PLAIN READ COMES BACK WITH NOTHING.

instant_pages fetches raw HTML. A site behind a JS challenge, or one that
builds its own content client-side, hands back a shell -- and that looked
identical to a WAF refusing us. Milligan Vein came back empty from the spoofed
Chrome user agent AND from the Lighthouse fallback, which is the shape of a
page that has to be executed rather than fetched.

Two things have to hold. JS rendering is slower and dearer per call, so it must
never run on the happy path. And it has to fire on EVERY way the plain read
fails -- including the one that looks like success: for a page it could not
fetch, DataForSEO returns a FULL checks object with everything at its default,
so `checks` is populated, nothing reads as failing, and the score comes back 0.
Testing only for empty checks would skip the retry on exactly the sites it is
for.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

FAIL, RUN = [], []


def check(label, got, want):
    ok = got == want
    RUN.append(label)
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


# A real reading, a shell, an empty page, and a refusal.
# Keys off _ONPAGE_DEBT, so `failed` carries the labels the panel prints.
GOOD = {"checks": {"no_h1_tag": True, "no_title": False, "is_https": True},
        "onpage_score": 87.0, "page_timing": {"dom_complete": 900}}
# THE ONE THAT LOOKS LIKE SUCCESS: full checks, all defaults, score 0.
SHELL = {"checks": {"no_h1_tag": False, "no_title": False, "is_https": True},
         "onpage_score": 0}
EMPTY = {}
REFUSED = {"checks": {"no_h1_tag": False, "is_https": True}, "onpage_score": 0,
           "status_code": 403}

CALLS = []


def run(plain, rendered, render_cfg=True, lighthouse=False):
    """fetch_technical_health against a stubbed DFS. Returns (health, why)."""
    CALLS.clear()

    def _post(path, payload, timeout=None, **kw):
        p = payload[0]
        js = bool(p.get("enable_javascript") or p.get("enable_browser_rendering"))
        CALLS.append("rendered" if js else "plain")
        item = rendered if js else plain
        return {"tasks": [{"status_code": 20000,
                           "result": [{"items": [item]}] if item else []}]}

    real_post, real_cfg, real_lh = (app.dfs_post,
                                    app.CFG.get("onpage_render_js"),
                                    app.CFG.get("technical_health_fallback"))
    app.dfs_post = _post
    app.CFG["onpage_render_js"] = render_cfg
    app.CFG["technical_health_fallback"] = lighthouse
    try:
        return app.fetch_technical_health("example.com")
    finally:
        app.dfs_post = real_post
        app.CFG["onpage_render_js"] = real_cfg
        app.CFG["technical_health_fallback"] = real_lh


# ---------------------------------------------- never on the happy path
h, why = run(GOOD, GOOD)
check("a plain read that works costs one call", CALLS, ["plain"])
check("and is not labelled as rendered", h.get("source"), "on_page")
check("the reading comes through", (h.get("score"), h.get("failed")),
      (87.0, ["no H1"]))

# ---------------------------------------------- every way the plain read fails
for label, plain in (("a shell with full default checks", SHELL),
                     ("an empty page", EMPTY),
                     ("a refusal", REFUSED)):
    h, why = run(plain, GOOD)
    check("%s is retried rendered" % label, CALLS, ["plain", "rendered"])
    check("...and the rendered read is the answer", h.get("score"), 87.0)
    check("...and it says it was rendered", h.get("source"), "on_page rendered")

# ---------------------------------------------- when rendering does not help
h, why = run(SHELL, SHELL)
check("both reads failing is not a reading", h, {})
check("and the reason names the failure",
      "scored 0 with nothing flagged" in why, True)

# NOTHING PRICED OFF A SHELL. site_debt reads off `failed`, so a shell must not
# arrive as a clean site -- that was the Amare bug and it prices as no debt.
check("a shell never reports as clean", h.get("failed"), None)

# ---------------------------------------------- the flag turns it off
h, why = run(SHELL, GOOD, render_cfg=False)
check("with the flag off the retry does not run", CALLS, ["plain"])
check("and the plain failure stands", h, {})

# ---------------------------------------------- Lighthouse is still the last word
h, why = run(SHELL, SHELL, lighthouse=True)
check("both failing hands over to lighthouse",
      CALLS[:2], ["plain", "rendered"])

print()
print("%d checks, %d failed" % (len(RUN), len(FAIL)))
print("all ok" if not FAIL else "FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
