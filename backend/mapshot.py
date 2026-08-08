"""A static map picture of one shipment's route, drawn on OpenStreetMap tiles.

Chat apps and social networks never run our JavaScript, so the Leaflet map on the Track page
cannot be a link preview. This module renders the same route server side into a 1200x630 PNG.

Tiles come from OpenStreetMap and their policy asks for a real User-Agent, no bulk downloading
and heavy caching, so: the whole world at these zooms is a handful of tiles, every tile is kept
on disk for good (a coastline does not move) and every composed picture is cached too. One
preview therefore costs zero upstream requests after the first.
"""
import logging
import math
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

log = logging.getLogger("mapshot")

W, H = 1200, 630
TILE = 256
PAD = 0.12                     # keep the route off the very edge
MIN_ZOOM, MAX_ZOOM = 1, 7
BG = (20, 20, 20)
DONE = (225, 29, 72)           # the crimson the site uses
AHEAD = (148, 163, 184)

CACHE_TTL = int(os.environ.get("MAPSHOT_TTL", "21600"))
TILE_URL = os.environ.get("OSM_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
AGENT = os.environ.get(
    "OSM_USER_AGENT",
    f"EncarEurope/1.0 (+{os.environ.get('PUBLIC_SITE_URL', 'https://encareurope.com')})")


def _root():
    return Path(os.environ["MEDIA_ROOT"])


def _project(lat, lon, z):
    """Global pixel coordinates at this zoom (Web Mercator, 256px tiles)."""
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    n = TILE * 2 ** z
    x = (float(lon) + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def _zoom_for(points):
    """The closest zoom at which every point still fits inside the picture."""
    if len(points) < 2:
        return 4
    for z in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        xs, ys = zip(*(_project(la, lo, z) for la, lo in points))
        if (max(xs) - min(xs)) <= W * (1 - PAD) and (max(ys) - min(ys)) <= H * (1 - PAD):
            return z
    return MIN_ZOOM


async def _tile(client, z, x, y):
    """One tile, from disk if we have ever fetched it."""
    n = 2 ** z
    if not (0 <= y < n):
        return None
    x %= n
    path = _root() / "tiles" / str(z) / str(x) / f"{y}.png"
    if path.exists():
        try:
            return Image.open(path).convert("RGB")
        except OSError:
            path.unlink(missing_ok=True)
    r = await client.get(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": AGENT})
    if r.is_error:
        log.warning("osm tile %s/%s/%s -> %s", z, x, y, r.status_code)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    from io import BytesIO
    return Image.open(BytesIO(r.content)).convert("RGB")


async def _canvas(points):
    """The map itself: tiles stitched around the centre of the route."""
    z = _zoom_for(points)
    xs, ys = zip(*(_project(la, lo, z) for la, lo in points))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    left, top = cx - W / 2, cy - H / 2
    img = Image.new("RGB", (W, H), BG)
    x0, y0 = int(left // TILE), int(top // TILE)
    x1, y1 = int((left + W) // TILE), int((top + H) // TILE)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                tile = await _tile(client, z, tx, ty)
                if tile is not None:
                    img.paste(tile, (int(tx * TILE - left), int(ty * TILE - top)))
    return img, z, left, top


def _dashed(draw, a, b, colour, width=4, dash=14, gap=10):
    (x1, y1), (x2, y2) = a, b
    span = math.hypot(x2 - x1, y2 - y1)
    if span < 1:
        return
    ux, uy = (x2 - x1) / span, (y2 - y1) / span
    at = 0.0
    while at < span:
        end = min(at + dash, span)
        draw.line([(x1 + ux * at, y1 + uy * at), (x1 + ux * end, y1 + uy * end)],
                  fill=colour, width=width)
        at = end + gap


async def render(stops):
    """`stops` is [{lat, lon, estimated}] in travel order, exactly what the Track page draws."""
    points = [(s["lat"], s["lon"]) for s in stops]
    if not points:
        return None
    img, z, left, top = await _canvas(points)
    draw = ImageDraw.Draw(img, "RGBA")
    # A light veil under the drawing: OSM's own colours are busy and the route has to read at
    # thumbnail size in a chat list.
    draw.rectangle([0, 0, W, H], fill=(20, 20, 20, 45))
    pix = [(px - left, py - top) for px, py in (_project(la, lo, z) for la, lo in points)]
    for i in range(len(pix) - 1):
        ahead = stops[i + 1].get("estimated")
        if ahead:
            _dashed(draw, pix[i], pix[i + 1], AHEAD)
        else:
            draw.line([pix[i], pix[i + 1]], fill=DONE, width=5)
    for (x, y), s in zip(pix, stops):
        r = 9
        box = [x - r, y - r, x + r, y + r]
        if s.get("estimated"):
            draw.ellipse(box, fill=(255, 255, 255), outline=AHEAD, width=3)
        else:
            draw.ellipse(box, fill=DONE, outline=(255, 255, 255), width=3)
    return img


def cache_path(key):
    return _root() / "mapshots" / f"{key}.png"


def fresh(key):
    """The composed picture, if one was made recently enough."""
    import time
    path = cache_path(key)
    if path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL:
        return path.read_bytes()
    return None


def store(key, img):
    from io import BytesIO
    path = cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    path.write_bytes(data)
    return data
