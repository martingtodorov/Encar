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
