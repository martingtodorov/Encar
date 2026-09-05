"""The server-rendered HTML: unique head, real body, honest status codes.

Every assertion here is something the SEO audit found MISSING from the raw HTML: the ad's own
title, a self-referencing canonical, hreflang, an H1, the price, photos, Vehicle schema,
og:type=product, a real 404 for a listing we do not have and `noindex` on the filter URLs
Google turned into a crawl trap.

The endpoint is exercised directly (`/api/prerender?path=…`) because that is what nginx calls;
in production the visitor's own URL is what carries the path.
"""
import os
import re

import pytest
import requests


def _base():
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    return os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


BASE = _base()
assert BASE, "REACT_APP_BACKEND_URL not configured"
API = f"{BASE}/api"


def render(path, **params):
    return requests.get(f"{API}/prerender", params={"path": path, **params}, timeout=60)


@pytest.fixture(scope="module")
def listing():
    r = requests.post(f"{API}/search", json={"lang": "bg", "page_size": 1}, timeout=60)
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        pytest.skip("no listings in the index")
    return items[0]


def head_of(html):
    return html.split("</head>")[0]


def test_language_home_is_rendered():
    r = render("/bg")
    assert r.status_code == 200
    head = head_of(r.text)
    assert "<title>" in head and "Encar" in head
    assert f'rel="canonical" href="{BASE}/bg"' in head
    for code in ("bg", "ro", "pl", "en"):
        assert f'hreflang="{code}" href="{BASE}/{code}"' in head
    assert 'hreflang="x-default"' in head
    assert '"@type":"WebSite"' in head
    assert "<h1>" in r.text


def test_car_page_carries_its_own_metadata(listing):
    r = render(f"/bg/car/{listing['id']}")
    assert r.status_code == 200
    head, body = head_of(r.text), r.text
    # Not the generic home-page title, which is what every ad used to return.
    assert "Korean cars with a final landed price" not in head
    make = listing.get("manufacturer_t") or listing.get("manufacturer")
    assert make.split()[0] in head
    assert 'property="og:type" content="product"' in head
    assert f'rel="canonical" href="{BASE}/bg/car/{listing["id"]}' in head
    assert '"@type":["Product","Car"]' in head
    assert '"@type":"Offer"' in head and '"priceCurrency":"EUR"' in head
    assert '"sku":"' in head and '"@type":"Brand"' in head
    assert '"@type":"BreadcrumbList"' in head
    assert '"@type":"Organization"' in head and '"@type":"WebSite"' in head
    # JSON-LD is JSON, so a photo URL keeps its raw ampersands (entities are not decoded
    # inside a <script>, and an escaped one would be a broken image to Google).
    assert "&amp;" not in head.split('application/ld+json">')[1].split("</script>")[0]
    assert re.search(r"<h1>[^<]{4,}</h1>", body)
    # Real photos and real internal links, not a script placeholder.
    assert body.count("<img") >= 1
    assert f"/bg/car/{listing['id']}" in body or "pr-grid" in body
    # The prerendered markup lives inside #root, which React clears on its first render.
    root = body.find('<div id="root"')
    assert root > 0 and '<main class="pr">' in body[root:root + 400]


def test_car_page_has_a_price_and_spec(listing):
    body = render(f"/bg/car/{listing['id']}").text
    assert "pr-spec" in body
    if listing.get("sale_eur"):
        assert "pr-price" in body


def test_unknown_listing_is_a_real_404():
    r = render("/bg/car/00000000")
    assert r.status_code == 404
    assert 'content="noindex, follow"' in head_of(r.text)


def test_unknown_make_slug_is_a_real_404():
    r = render("/bg/no-such-make-at-all")
    assert r.status_code == 404


def test_filter_urls_are_never_indexed():
    r = render("/bg", make="bmw", price_min="1")
    assert 'content="noindex, follow"' in head_of(r.text)
    # ...and they point at the clean landing page instead of at themselves.
    assert re.search(rf'rel="canonical" href="{re.escape(BASE)}/bg(/[a-z0-9-]+)?"',
                     head_of(r.text))


def test_junk_filter_tokens_are_gone():
    r = render("/bg", make="definitely-not-a-make")
    assert r.status_code == 410
    assert 'content="noindex, follow"' in head_of(r.text)


def test_private_pages_are_noindex_nofollow():
    for path in ("/bg/account", "/bg/admin", "/bg/login"):
        head = head_of(render(path).text)
        assert 'content="noindex, nofollow"' in head, path


def test_static_pages_are_rendered():
    for path, marker in (("/bg/how-it-works", "<h1>"), ("/en/track", "<h1>"),
                         ("/bg/terms", "<h1>")):
        r = render(path)
        assert r.status_code == 200, path
        assert marker in r.text, path
        assert 'content="index, follow' in head_of(r.text), path


def test_every_language_gets_its_own_head():
    titles = set()
    for code in ("bg", "ro", "pl", "en"):
        head = head_of(render(f"/{code}").text)
        titles.add(re.search(r"<title>(.*?)</title>", head, re.S).group(1))
        assert f'content="{ {"bg": "bg_BG", "ro": "ro_RO", "pl": "pl_PL", "en": "en_GB"}[code] }"' \
            in head or f'og:locale' in head
    assert len(titles) == 4


def test_shell_scripts_survive():
    """The bundle must still be referenced, or the prerendered page would never hydrate."""
    body = render("/bg").text
    assert "<script" in body and "/static/js/" in body or "bundle.js" in body
