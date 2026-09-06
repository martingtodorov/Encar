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


# ── the formatting and freshness work (2026-09) ──────────────────────────────
def _xml(path, timeout=300):
    """Parse it the way a validator does: a sitemap that will not parse is not a sitemap."""
    import xml.etree.ElementTree as ET

    r = requests.get(f"{BASE}{path}", timeout=timeout)
    assert r.status_code == 200, path
    return r, ET.fromstring(r.content)


def test_every_sitemap_is_well_formed_xml():
    for path in ("/sitemap.xml", "/sitemap-static.xml", "/sitemap-models.xml",
                 "/sitemap-listings-1.xml"):
        _xml(path)


def test_files_are_pretty_printed():
    """These are read by people (Search Console, the owner) as often as by crawlers."""
    r, _ = _xml("/sitemap-listings-1.xml")
    lines = r.text.splitlines()
    assert lines[0] == '<?xml version="1.0" encoding="UTF-8"?>'
    assert any(ln.strip() == "<url>" for ln in lines), "everything is still on one line"
    assert any(ln.startswith("    <loc>") for ln in lines), "no indentation"


def test_lastmod_is_per_sitemap_not_todays_date():
    """`lastmod` said TODAY for every entry, recomputed on each fetch — a claim that the
    whole site changed this morning, every morning, which devalues the signal."""
    r, root = _xml("/sitemap.xml")
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    stamps = {}
    for node in root.findall(f"{ns}sitemap"):
        loc = node.findtext(f"{ns}loc")
        stamps[loc.rsplit("/", 1)[-1]] = node.findtext(f"{ns}lastmod")
    assert stamps, "no child sitemaps"
    # W3C datetime with a zone, not a bare date.
    for name, stamp in stamps.items():
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$", stamp), (name, stamp)
    # The evergreen pages and the catalogue have different clocks; they used to share one.
    assert stamps["sitemap-static.xml"] != stamps["sitemap-listings-1.xml"]


def test_listing_images_carry_a_title_and_one_caption():
    r, root = _xml("/sitemap-listings-1.xml")
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    img = "{http://www.google.com/schemas/sitemap-image/1.1}"
    urls = root.findall(f"{ns}url")
    assert urls
    for url in urls[:20]:
        images = url.findall(f"{img}image")
        if not images:
            continue
        assert all(i.findtext(f"{img}title") for i in images), "an image with no title"
        captions = [i for i in images if i.findtext(f"{img}caption")]
        # The lead photo only: five captions per car buy nothing and cost megabytes.
        assert len(captions) == 1, f"{len(captions)} captions on one car"
        assert captions[0] is images[0]


def test_a_full_chunk_would_still_fit_google_ceiling():
    """Titles and captions add bytes, and preview holds far fewer cars than production, so
    the guard has to be per-URL weight projected onto a full chunk rather than file size."""
    import server

    r, _ = _xml("/sitemap-listings-1.xml")
    urls = r.text.count("<url>")
    assert urls, "no listings to measure"
    per_url = len(r.content) / urls
    projected = per_url * server._SITEMAP_CHUNK
    assert projected <= SAFE_BYTES, (
        f"{per_url:.0f} bytes per URL x {server._SITEMAP_CHUNK} = {projected / 1e6:.1f} MB")
