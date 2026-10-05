"""A bare city name is only used when this market owns the name. The national
wording probe picked "home staging company richmond" for Richmond CA because
Richmond VA's searchers counted. (2026-10-05, Kiri)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
import app

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")

check("richmondCA.bare", app.geo_form_owns_name("Richmond, CA", "CA", "richmond"), False)
check("richmondCA.suffixed", app.geo_form_owns_name("Richmond, CA", "CA", "richmond ca"), True)
check("richmondVA.bare", app.geo_form_owns_name("Richmond, VA", "VA", "richmond"), True)
check("alameda.bare", app.geo_form_owns_name("Alameda, CA", "CA", "alameda"), True)

# The probe never offers the bare form for Richmond CA, even when it reads
# far higher nationally.
sent = []
def fake_post(path, payload, timeout=None):
    kws = payload[0]["keywords"]
    sent.extend(kws)
    return {"tasks": [{"result": [{"keyword": k, "search_volume": 900 if k.endswith("richmond") else 20}
                                  for k in kws]}]}
app.dfs_post = fake_post
forms, rep = app.pick_geo_forms(["Richmond, CA"], "CA", ["home staging"])
check("probe.noBare", any(k.endswith("richmond") for k in sent), False)
check("probe.chose", forms.get("Richmond, CA"), "richmond ca")

print(f"{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
