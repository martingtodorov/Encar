"""Sitemap files must stay inside Google's limits — both of them.

The URL count was never the problem; the BYTE size was. Each `<url>` carries five hreflang
alternates and up to five image entries (~1.6 KB), so the old 40 000-per-file chunking
shipped `sitemap-listings-1.xml` at 62.7 MB against Google's 50 MB uncompressed ceiling and
the whole file was liable to be dropped. The chunk is 10 000 now, and this test fails if
anything pushes a file back over the line.
"""
import re

import requests

from tests.test_prerender import BASE  # same REACT_APP_BACKEND_URL resolution

GOOGLE_MAX_URLS = 50_000
GOOGLE_MAX_BYTES = 50 * 1024 * 1024
# Anything above this and the next catalogue growth spurt breaks the limit, so fail early.
SAFE_BYTES = 40 * 1024 * 1024


def test_sitemap_index_lists_child_files():
    r = requests.get(f"{BASE}/sitemap.xml", timeout=120)
    assert r.status_code == 200
    assert "<sitemapindex" in r.text
    assert "sitemap-listings-1.xml" in r.text
    assert len(r.content) < GOOGLE_MAX_BYTES


def test_listing_sitemap_is_within_both_limits():
    r = requests.get(f"{BASE}/sitemap-listings-1.xml", timeout=300)
    assert r.status_code == 200
    urls = len(re.findall(r"<loc>", r.text)) - len(re.findall(r"<image:loc>", r.text))
    assert urls <= GOOGLE_MAX_URLS, urls
    assert len(r.content) <= SAFE_BYTES, (
        f"{len(r.content)} bytes for {urls} URLs — lower the chunk size in server.py")


def test_chunk_size_is_not_raised_without_measuring():
    import server
    assert server._SITEMAP_CHUNK <= 20_000, (
        "each <url> weighs ~1.6 KB with hreflang and images; above 20 000 a file can "
        "cross Google's 50 MB limit")


# ── a sitemap is a list of CANONICAL URLs, each stated once ──────────────────
def test_model_sitemap_states_each_landing_once():
    """It carried 2 630 entries for 1 315 landings — an exact 2x across the whole file."""
    r = requests.get(f"{BASE}/sitemap-models.xml", timeout=180)
    assert r.status_code == 200
    locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    assert locs, "no model landings in the sitemap at all"
    assert len(locs) == len(set(locs)), (
        f"{len(locs) - len(set(locs))} duplicate URLs in sitemap-models.xml")


def test_listing_sitemap_emits_the_canonical_slug_form():
    """A quarter of the URLs were the slug-less /car/<id> form, which then canonicalises
    somewhere else — a sitemap contradicting the pages it points at."""
    r = requests.get(f"{BASE}/sitemap-listings-1.xml", timeout=300)
    assert r.status_code == 200
    locs = [u for u in re.findall(r"<loc>(.*?)</loc>", r.text) if "/car/" in u]
    assert locs, "no listings in the sitemap at all"
    bare = [u for u in locs if re.search(r"/car/[^/]+/?$", u)]
    # A car with no latin name anywhere (not even in the translation cache) legitimately has
    # no slug, so this is a ceiling rather than a zero.
    assert len(bare) / len(locs) < 0.05, (
        f"{len(bare)} of {len(locs)} listing URLs are the non-canonical slug-less form")


def test_listing_sitemap_urls_are_unique():
    r = requests.get(f"{BASE}/sitemap-listings-1.xml", timeout=300)
    locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    assert len(locs) == len(set(locs))


def test_primary_loc_is_the_default_locale():
    """`/` redirects to /bg, so bg is what a crawler ignoring hreflang should walk."""
    r = requests.get(f"{BASE}/sitemap-static.xml", timeout=120)
    locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    assert locs
    assert all("/bg" in u for u in locs), locs[:5]
    # ...while every language is still enumerated as an alternate, bg included.
    for code in ("bg", "ro", "pl", "en"):
        assert f'hreflang="{code}"' in r.text
