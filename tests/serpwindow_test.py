"""THE DOCUMENT GETS THE WINDOW, NOT THE PAGE.

The capture is stored whole so the window can move without recapturing, and
the row shows it through a 16:9 box slid to shotY. The proposal was handed the
whole page: a 2,600px column where the screen showed a landscape frame. The
document now cuts the same window the row shows.
"""
import importlib.util
import io
import os
import sys

os.environ.setdefault("DFS_LOGIN", "x")
os.environ.setdefault("DFS_PASSWORD", "x")
HERE = os.path.dirname(os.path.abspath(__file__))
SRCDIR = os.path.dirname(HERE)
sys.path.insert(0, SRCDIR)
SRC = os.path.join(SRCDIR, "app.py")
spec = importlib.util.spec_from_file_location("app", SRC)
app = importlib.util.module_from_spec(spec)
sys.modules["app"] = app
spec.loader.exec_module(app)
from PIL import Image  # noqa: E402

FAIL = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        print("         got  %r\n         want %r" % (got, want))
        FAIL.append(label)


def page(w, h, bands):
    """A tall page of solid horizontal bands, top to bottom."""
    im = Image.new("RGB", (w, h))
    bh = h // len(bands)
    for i, c in enumerate(bands):
        im.paste(c, (0, i * bh, w, h if i == len(bands) - 1 else (i + 1) * bh))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def opened(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def band_of(px):
    return {(255, 0, 0): "red", (0, 255, 0): "green",
            (0, 0, 255): "blue", (255, 255, 0): "yellow"}.get(
        tuple(min(255, (v + 8) // 16 * 16) if False else v for v in px), px)


def dominant(im, y):
    r, g, b = im.getpixel((im.width // 2, y))
    if r > 200 and g < 60 and b < 60: return "red"
    if g > 200 and r < 60 and b < 60: return "green"
    if b > 200 and r < 60 and g < 60: return "blue"
    if r > 200 and g > 200 and b < 60: return "yellow"
    return (r, g, b)


RED, GREEN, BLUE, YELLOW = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)
# 1600 wide, 2600 tall: the window is 900 tall, 1700 of room to slide.
PAGE = page(1600, 2600, [RED, GREEN, BLUE, YELLOW])

out = opened(app._window_serp_image(PAGE, 0))
check("window is 16:9", (out.width, round(out.width * 9 / 16)), (1600, out.height))
check("top: opens on the first band", dominant(out, 5), "red")
check("top: ends inside the second band", dominant(out, out.height - 5), "green")

out = opened(app._window_serp_image(PAGE, 100))
check("bottom: ends on the last band", dominant(out, out.height - 5), "yellow")
check("bottom: still 16:9", out.height, 900)

out = opened(app._window_serp_image(PAGE, 50))
# room 1700, half of it is 850: the window runs 850..1750, green then blue.
check("half: opens in the second band", dominant(out, 5), "green")
check("half: ends in the third band", dominant(out, out.height - 5), "blue")

check("clamped above 100", opened(app._window_serp_image(PAGE, 250)).height, 900)
check("non-numeric y is the top",
      dominant(opened(app._window_serp_image(PAGE, "wide")), 5), "red")
check("missing y is the top",
      dominant(opened(app._window_serp_image(PAGE, None)), 5), "red")

# A capture already landscape is not touched.
SHORT = page(1600, 700, [RED, GREEN])
check("a short capture is returned as it is", app._window_serp_image(SHORT, 40), SHORT)
check("garbage is returned as it is", app._window_serp_image(b"not an image", 40), b"not an image")

# And the document route asks for it, with the window position the row sent.
src = open(SRC).read()
check("the document cuts the window",
      "_window_serp_image(base64.b64decode(raw), sp.get(\"y\"))" in src, True)
tpl = open(os.path.join(SRCDIR, "templates", "adtini.html"), encoding="utf-8").read()
check("the row sends where the window sits",
      "y: Number((r.result || {}).shotY) || 0}" in tpl, True)

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ok all")
sys.exit(1 if FAIL else 0)
