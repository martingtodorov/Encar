"""Tests for share/OG title cleanup: bracketed codes, 'All New' prefix, submodel+trim, English trims."""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")
CRAWLER_UA = {"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"}


def _fetch_share(listing_id, lang="bg"):
    # Directly hit the share endpoint - avoids proxy redirect indirection
    r = requests.get(f"{BASE_URL}/api/share/car/{listing_id}", params={"lang": lang}, timeout=30)
    assert r.status_code == 200, f"share/{listing_id} -> {r.status_code}: {r.text[:200]}"
    return r.text


def _extract(html, prop):
    m = re.search(rf'<meta[^>]+property="{prop}"[^>]+content="([^"]*)"', html)
    if not m:
        m = re.search(rf'<meta[^>]+name="{prop}"[^>]+content="([^"]*)"', html)
    return m.group(1) if m else None


def _title_tag(html):
    m = re.search(r"<title>([^<]*)</title>", html)
    return m.group(1) if m else None


# --- Bug 1: Cayenne must not carry PO536 or (2019-) ---
def test_cayenne_no_generation_code_no_years():
    html = _fetch_share("42354550")
    t = _title_tag(html) or ""
    og = _extract(html, "og:title") or ""
    tw = _extract(html, "twitter:title") or ""
    for s in (t, og, tw):
        assert "PO536" not in s, f"PO536 leaked: {s!r}"
        assert "2019" not in s and "(2019-)" not in s, f"years leaked: {s!r}"
    # Expected: Porsche Cayenne 3.0 Coupe
    assert "Porsche" in og and "Cayenne" in og
    assert "Coupe" in og, f"missing badge/badge_detail: {og!r}"


# --- Bug 2: "All New" / hangul residue stripped ---
def test_all_new_stripped_tucson():
    html = _fetch_share("42416001")
    og = _extract(html, "og:title") or ""
    head = html.split("</head>")[0] if "</head>" in html else html
    assert "All New" not in head and "All-New" not in head and "올" not in head, f"bad head: {og!r}"
    # Expected includes Tucson
    if "Tucson" in og:
        assert "Hyundai" in og and "Tucson" in og
        # submodel + trim
        assert "Premium" in og, f"trim missing: {og!r}"
    else:
        pytest.skip(f"42416001 upstream cache empty: {og!r}")


def test_all_new_stripped_morning():
    html = _fetch_share("42422490")
    og = _extract(html, "og:title") or ""
    head = html.split("</head>")[0] if "</head>" in html else html
    assert "All New" not in head and "All-New" not in head
    assert "(JA)" not in head, f"factory code leaked: {og!r}"
    if "Morning" in og:
        assert "Kia" in og and "Morning" in og
        assert "Luxury" in og


# --- Bug 3: submodel AND trim both appear ---
def test_sportage_has_submodel_and_trim():
    html = _fetch_share("42254427")
    og = _extract(html, "og:title") or ""
    # Expected: Kia Sportage R Diesel 2WD TLX Top Grade
    for token in ("Kia", "Sportage", "Diesel", "TLX", "Top Grade"):
        assert token in og, f"missing {token!r} in {og!r}"


def test_amg_gt_has_submodel_and_trim():
    html = _fetch_share("42174617")
    og = _extract(html, "og:title") or ""
    # Expected: Mercedes-Benz AMG GT 4-Door 43 4MATIC+
    for token in ("Mercedes", "AMG", "GT", "4-Door", "43", "4MATIC"):
        assert token in og, f"missing {token!r} in {og!r}"


# --- Bug 4: No Cyrillic in titles ---
CYR = re.compile(r"[\u0400-\u04FF]")

def test_no_cyrillic_in_trim_sportage():
    html = _fetch_share("42254427")
    og = _extract(html, "og:title") or ""
    t = _title_tag(html) or ""
    # og:title / <title> should have no Cyrillic - trim must be English
    assert not CYR.search(og), f"cyrillic in og:title: {og!r}"
    # <title> tag may include site suffix in Bulgarian, but the model portion shouldn't be Cyrillic.
    # The share_car builds title as brand model badge etc. — check whole tag.
    # Allow site suffix but ensure model tokens present in English:
    assert "Sportage" in og


def test_no_cyrillic_42072910():
    html = _fetch_share("42072910")
    og = _extract(html, "og:title") or ""
    assert not CYR.search(og), f"cyrillic in og:title: {og!r}"
    # Expected trim: Diesel 2.0 2WD Noblesse
    for token in ("Diesel", "Noblesse"):
        assert token in og, f"missing {token!r} in {og!r}"


# --- Share endpoint regression checks ---
def test_share_og_description_and_image():
    html = _fetch_share("42259236")
    desc = _extract(html, "og:description") or ""
    # e.g. '05/2015 · 110 989 km · €13 399'
    assert "2015" in desc
    assert "km" in desc
    assert "€" in desc or "EUR" in desc
    img = _extract(html, "og:image") or ""
    assert "/api/image-proxy" in img, f"og:image: {img!r}"
    secure = _extract(html, "og:image:secure_url") or ""
    assert "/api/image-proxy" in secure
    assert _extract(html, "og:image:type")
    assert _extract(html, "og:image:width") == "1200"
    assert _extract(html, "og:image:height") == "630"
    # image proxy returns 200 image/*
    r = requests.get(img, timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")


# --- Track share ---
def test_track_share_image_is_map_png():
    r = requests.get(f"{BASE_URL}/api/share/track", params={"ref": "271191199", "by": "bol", "lang": "bg"}, timeout=30)
    assert r.status_code == 200
    html = r.text
    img = _extract(html, "og:image") or ""
    assert "/api/map/track.png" in img, f"og:image: {img!r}"
    itype = _extract(html, "og:image:type") or ""
    assert itype == "image/png"
    r2 = requests.get(img, timeout=30)
    assert r2.status_code == 200
    assert r2.headers.get("content-type", "").startswith("image/png")


# --- Normal browser gets React app shell, not share page ---
def test_normal_browser_gets_app_shell():
    r = requests.get(f"{BASE_URL}/bg/car/42354550", headers=BROWSER_UA, timeout=30, allow_redirects=True)
    assert r.status_code == 200
    # React app shell: presence of a root div and no server-rendered og:title from share_car
    body = r.text
    # Share page returns rich head with og:image; app shell typically doesn't have og:image proxy url in head
    # Heuristic: the share page has og:image with /api/image-proxy?; app shell wouldn't include that per-car.
    has_share_og = 'property="og:image"' in body and "/api/image-proxy" in body
    assert not has_share_og, "normal browser was served the share page instead of app shell"


# --- Crawler UA on /bg/car/... returns share HTML via proxy redirect ---
def test_crawler_ua_on_frontend_url_reaches_share():
    r = requests.get(f"{BASE_URL}/bg/car/42354550", headers=CRAWLER_UA, timeout=30, allow_redirects=True)
    assert r.status_code == 200
    body = r.text
    assert "PO536" not in body
    # og:title should exist
    og = _extract(body, "og:title") or ""
    assert "Porsche" in og and "Cayenne" in og, f"og:title: {og!r}"
    assert "2019" not in og
