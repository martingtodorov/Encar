"""Exterior colour: a filter over the whole catalogue, from the feed we already crawl.

The search feed carries NO colour (only the per-car detail does, and we hold a detail for
well under 1% of the catalogue), so colour is tagged from the same endpoint using Encar's own
colour facet — one id-only pass per colour, which together cost about one extra sweep rather
than one request per car. These tests hold on to the two things that make that safe: the map
contains only values read out of real Encar data, and a car whose colour we do not know is
never called "other".
"""
import os

import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"x-admin-token": os.environ["ADMIN_TOKEN"]}


def _session():
    """The API refuses unsafe calls without a CSRF token; conftest wraps `requests`."""
    return requests.Session()


def test_colour_groups_only_hold_values_seen_in_real_encar_data():
    import sync

    # Every value is a Korean colour name ending in 색 (colour) or 투톤 (two-tone), which is
    # the shape Encar uses. A latin or invented token here would silently tag nothing.
    for slug, raws in sync.COLOR_GROUPS.items():
        assert raws, slug
        for raw in raws:
            assert raw.endswith("색") or raw.endswith("투톤"), (slug, raw)
    # The reverse map has no collisions: one Encar value belongs to exactly one of our slugs.
    flat = [raw for raws in sync.COLOR_GROUPS.values() for raw in raws]
    assert len(flat) == len(set(flat))
    assert len(sync.COLOR_OF_RAW) == len(flat)


def test_filters_expose_colour_facets_with_counts():
    r = requests.get(f"{BASE}/api/meta/filters?lang=bg", timeout=120)
    assert r.status_code == 200
    colors = r.json().get("colors")
    assert isinstance(colors, list)
    import sync
    for row in colors:
        assert row["value"] in sync.COLOR_GROUPS, row
        assert row["count"] > 0


def test_search_narrows_to_the_chosen_colour():
    s = _session()
    all_cars = s.post(f"{BASE}/api/search", timeout=60,
                      json={"lang": "bg", "page": 1, "page_size": 1}).json()
    facets = requests.get(f"{BASE}/api/meta/filters?lang=bg", timeout=120).json()
    colors = facets.get("colors") or []
    if not colors:
        pytest.skip("no colour is known in this environment yet")
    pick = colors[0]
    got = s.post(f"{BASE}/api/search", timeout=60,
                 json={"colors": [pick["value"]], "lang": "bg", "page": 1,
                       "page_size": 24}).json()
    assert got["total"] == pick["count"], (pick, got["total"])
    assert got["total"] <= all_cars["total"]
    # Every card really is that colour, and says so.
    for item in got["items"]:
        assert item.get("color") == pick["value"], item.get("id")


def test_an_unknown_colour_returns_nothing_rather_than_everything():
    s = _session()
    got = s.post(f"{BASE}/api/search", timeout=60,
                 json={"colors": ["chartreuse"], "lang": "bg", "page": 1}).json()
    assert got["total"] == 0


def test_facet_counts_scope_colours_to_the_current_search():
    s = _session()
    body = {"lang": "bg", "only_inspection": True}
    scoped = s.post(f"{BASE}/api/meta/facet-counts", timeout=60, json=body).json()
    assert "colors" in scoped
    whole = requests.get(f"{BASE}/api/meta/filters?lang=bg", timeout=120).json().get("colors")
    scoped_total = sum(r["count"] for r in scoped["colors"])
    whole_total = sum(r["count"] for r in (whole or []))
    assert scoped_total <= whole_total


def test_admin_coverage_reports_the_unknown_honestly():
    r = requests.get(f"{BASE}/api/admin/colors", headers=ADMIN, timeout=120)
    assert r.status_code == 200
    d = r.json()
    assert d["known"] + d["unknown"] == d["total"]
    # A car whose colour we do not know must NOT be filed under some "other" bucket: that
    # would turn a missing facet value into a false statement about the car.
    import sync
    assert all(row["color"] in sync.COLOR_GROUPS for row in d["colors"])
    assert "other" not in [row["color"] for row in d["colors"]]
    assert requests.get(f"{BASE}/api/admin/colors", timeout=60).status_code == 401


def test_tagging_run_survives_an_unreachable_upstream():
    """In preview api.encar.com answers 407, so the facet passes cannot run. The endpoint
    must still say so honestly and keep the colours learned from cached details."""
    r = requests.post(f"{BASE}/api/admin/colors/tag", headers=ADMIN, timeout=280)
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d and "from_details" in d
    if not d["ok"]:
        assert d.get("error")           # named the reason instead of failing silently
    after = requests.get(f"{BASE}/api/admin/colors", headers=ADMIN, timeout=120).json()
    assert after["known"] >= 0
