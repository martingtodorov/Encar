"""Extended prerender coverage for gaps in the SEO audit follow-up.

Focus areas the existing test_prerender.py does not fully assert:
- price_min filter (no make) is noindex with canonical to /bg
- car page canonical ends in /{id}/{slug}
- private routes purchases + admin
- extra static routes (privacy, cookies, fees, contact, sitemap)
- description differs across all four languages
- existing endpoints untouched (/api/health, /api/sitemap*.xml, /api/robots.txt, /api/share/car/{id})
"""
import os
import re
import requests
import pytest


def _base():
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    return ""


BASE = _base()
API = f"{BASE}/api"


def render(path, **params):
    return requests.get(f"{API}/prerender", params={"path": path, **params}, timeout=60)


def head_of(html):
    return html.split("</head>")[0]


@pytest.fixture(scope="module")
def listing():
    r = requests.post(f"{API}/search", json={"lang": "bg", "page_size": 1}, timeout=60)
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        pytest.skip("no listings")
    return items[0]


# --- filters ---

def test_price_min_only_is_noindex_with_clean_canonical():
    r = render("/bg", price_min="20000")
    assert r.status_code == 200
    head = head_of(r.text)
    assert 'content="noindex, follow"' in head
    assert f'rel="canonical" href="{BASE}/bg"' in head


# --- car page canonical carries slug ---

def test_car_canonical_ends_with_slug(listing):
    r = render(f"/bg/car/{listing['id']}")
    head = head_of(r.text)
    m = re.search(rf'rel="canonical" href="{re.escape(BASE)}/bg/car/{listing["id"]}/([a-z0-9-]+)"', head)
    assert m, f"canonical without slug in head snippet: {head[:800]}"
    assert len(m.group(1)) >= 2


# --- private routes: purchases + admin extras ---

def test_purchases_and_admin_are_noindex_nofollow():
    for path in ("/bg/purchases", "/bg/admin"):
        head = head_of(render(path).text)
        assert 'content="noindex, nofollow"' in head, path


# --- extra static routes ---

def test_more_static_routes():
    for path in ("/bg/privacy", "/bg/cookies", "/bg/fees", "/bg/contact", "/bg/sitemap"):
        r = render(path)
        assert r.status_code == 200, path
        head = head_of(r.text)
        assert "<h1>" in r.text, f"no h1 on {path}"
        assert 'content="index, follow' in head, path


# --- description differs per language ---

def test_meta_description_differs_across_languages():
    descs = set()
    for code in ("bg", "ro", "pl", "en"):
        head = head_of(render(f"/{code}").text)
        m = re.search(r'name="description"\s+content="([^"]+)"', head)
        assert m, f"no description on /{code}"
        descs.add(m.group(1))
    assert len(descs) == 4, f"descriptions not all unique: {descs}"


# --- existing endpoints untouched ---

def test_health_endpoint_still_ok():
    r = requests.get(f"{API}/health", timeout=30)
    assert r.status_code == 200


def test_sitemaps_still_ok():
    for path in ("/sitemap.xml", "/sitemap-static.xml", "/sitemap-models.xml"):
        r = requests.get(f"{API}{path}", timeout=30)
        assert r.status_code == 200, path
        assert "<?xml" in r.text[:100], path


def test_robots_still_ok():
    r = requests.get(f"{API}/robots.txt", timeout=30)
    assert r.status_code == 200
    assert "User-agent" in r.text or "user-agent" in r.text.lower()


def test_share_car_still_ok(listing):
    r = requests.get(f"{API}/share/car/{listing['id']}", timeout=30, allow_redirects=False)
    # share may return 200 HTML or 3xx redirect - just ensure it responds cleanly
    assert r.status_code < 500, f"got {r.status_code}"


def test_car_direct_endpoint_still_ok(listing):
    r = requests.get(f"{API}/car/{listing['id']}?lang=bg", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert str(data.get("id")) == str(listing["id"])
