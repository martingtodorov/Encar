"""English slug + resolve endpoint regression tests.

Covers: /api/meta/taxonomy (levels 1-3), /api/meta/filters, /api/meta/resolve
edge cases, and /api/search accepting the resolved Korean values.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ── /api/meta/taxonomy: slugs present, unique, no duplicate values ────────────
class TestTaxonomySlugs:
    def test_level1_unique_makes_and_slugs(self, sess):
        r = sess.get(f"{API}/meta/taxonomy", params={"level": 1, "lang": "en"}, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        # Encar has 62 marques; the owner's curation folds some into another (Chevrolet
        # (GM Daewoo) -> Chevrolet), so the list is 62 minus the merges, never more.
        raw = sess.get(f"{API}/meta/taxonomy",
                       params={"level": 1, "lang": "en", "raw": 1}, timeout=30).json()["items"]
        merged = len([i for i in raw if i.get("merged_into")])
        assert len(items) == len(raw) - merged, (
            f"expected {len(raw) - merged} makes after {merged} merges, got {len(items)}")
        values = [i["value"] for i in items]
        assert len(set(values)) == len(values), "duplicate taxonomy values found"
        slugs = [i["slug"] for i in items if i.get("slug")]
        assert len(slugs) > 55, "almost every make should have a slug"
        assert len(set(slugs)) == len(slugs), "duplicate slugs at level 1"
        # Every item exposes the slug field (empty string allowed).
        assert all("slug" in i for i in items)

    def test_level1_stable_across_calls(self, sess):
        a = sess.get(f"{API}/meta/taxonomy", params={"level": 1, "lang": "en"}).json()["items"]
        b = sess.get(f"{API}/meta/taxonomy", params={"level": 1, "lang": "en"}).json()["items"]
        map_a = {i["value"]: i["slug"] for i in a}
        map_b = {i["value"]: i["slug"] for i in b}
        assert map_a == map_b, "slugs are unstable across consecutive calls"

    def test_level2_unique_for_hyundai(self, sess, hyundai_value):
        r = sess.get(f"{API}/meta/taxonomy",
                     params={"level": 2, "make": hyundai_value, "lang": "en"}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        values = [i["value"] for i in items]
        slugs = [i["slug"] for i in items if i["slug"]]
        assert len(set(values)) == len(values), "duplicate models"
        assert len(set(slugs)) == len(slugs), "duplicate model slugs within make"

    def test_level3_unique_for_hyundai_model(self, sess, hyundai_value, hyundai_model_value):
        r = sess.get(f"{API}/meta/taxonomy",
                     params={"level": 3, "make": hyundai_value,
                             "model": hyundai_model_value, "lang": "en"}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        values = [i["value"] for i in items]
        slugs = [i["slug"] for i in items if i["slug"]]
        assert len(set(values)) == len(values), "duplicate badges"
        assert len(set(slugs)) == len(slugs), "duplicate badge slugs"


# ── /api/meta/filters: slugs on makes/fuels/regions ───────────────────────────
class TestFiltersSlugs:
    def test_filters_have_slugs(self, sess):
        r = sess.get(f"{API}/meta/filters", params={"lang": "en"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        for group in ("makes", "fuels", "regions"):
            items = data[group]
            assert len(items) > 0, f"{group} empty"
            assert all("slug" in i for i in items), f"{group} missing slug field"
            slugs = [i["slug"] for i in items if i["slug"]]
            assert len(slugs) > 0, f"{group} has no populated slugs"
            assert len(set(slugs)) == len(slugs), f"duplicate slugs in {group}"


# ── /api/meta/resolve: edge cases ─────────────────────────────────────────────
class TestResolve:
    def test_resolve_make_only(self, sess):
        r = sess.get(f"{API}/meta/resolve", params={"make": "hyundai"})
        assert r.status_code == 200
        data = r.json()
        assert data["make"] and data["make"] != "hyundai", \
            f"make slug should resolve to Korean, got {data['make']!r}"
        assert data["model"] == ""
        assert data["fuels"] == []
        assert data["regions"] == []

    def test_resolve_make_and_model(self, sess, hyundai_value):
        # find a real model slug
        tax = sess.get(f"{API}/meta/taxonomy",
                       params={"level": 2, "make": hyundai_value, "lang": "en"}).json()
        model_slug = next((i["slug"] for i in tax["items"] if i["slug"]), None)
        assert model_slug, "no model slug available"
        r = sess.get(f"{API}/meta/resolve",
                     params={"make": "hyundai", "model": model_slug})
        assert r.status_code == 200
        data = r.json()
        assert data["make"] == hyundai_value
        assert data["model"] and data["model"] != model_slug

    def test_resolve_fuels_and_regions(self, sess):
        r = sess.get(f"{API}/meta/resolve",
                     params={"fuels": "petrol~diesel", "regions": "seoul"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["fuels"], list) and len(data["fuels"]) == 2
        assert isinstance(data["regions"], list) and len(data["regions"]) == 1
        # each slug should have been resolved (not the same string)
        assert data["fuels"] != ["petrol", "diesel"], "fuels not resolved"
        assert data["regions"] != ["seoul"], "region not resolved"

    def test_resolve_unknown_slug_echoed(self, sess):
        r = sess.get(f"{API}/meta/resolve", params={"make": "not-a-make"})
        assert r.status_code == 200
        assert r.json()["make"] == "not-a-make"

    def test_resolve_raw_korean_echoed(self, sess):
        r = sess.get(f"{API}/meta/resolve", params={"make": "현대"})
        assert r.status_code == 200
        # raw Korean value must be echoed through so legacy links still work
        assert r.json()["make"] == "현대"

    def test_resolve_empty_params(self, sess):
        r = sess.get(f"{API}/meta/resolve")
        assert r.status_code == 200
        data = r.json()
        assert data["make"] == "" and data["model"] == ""
        assert data["fuels"] == [] and data["regions"] == []


# ── /api/search with the resolved values ──────────────────────────────────────
class TestSearchWithResolved:
    def test_search_matches_resolved_values(self, sess):
        r = sess.get(f"{API}/meta/resolve",
                     params={"make": "hyundai", "fuels": "petrol"})
        data = r.json()
        korean_make = data["make"]
        korean_fuels = data["fuels"]
        assert korean_make and korean_fuels

        payload = {
            "makes": [korean_make],
            "fuels": korean_fuels,
            "page": 1, "page_size": 24, "sort": "newest",
        }
        s = sess.post(f"{API}/search", json=payload, timeout=60)
        assert s.status_code == 200, s.text
        body = s.json()
        assert body.get("total", 0) > 0, "no results for resolved hyundai+petrol"
        items = body.get("items") or body.get("results") or []
        assert len(items) > 0
        # every listing must match filters
        for it in items[:10]:
            mk = it.get("manufacturer") or it.get("make")
            fu = it.get("fuel_type") or it.get("fuel")
            assert mk == korean_make, f"make mismatch: {mk!r} != {korean_make!r}"
            assert fu in korean_fuels, f"fuel mismatch: {fu!r} not in {korean_fuels}"


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def hyundai_value(sess):
    """Korean value of Hyundai, resolved via /api/meta/resolve."""
    data = sess.get(f"{API}/meta/resolve", params={"make": "hyundai"}).json()
    assert data["make"], "cannot resolve hyundai slug"
    return data["make"]


@pytest.fixture(scope="module")
def hyundai_model_value(sess, hyundai_value):
    """Pick a real model (by Korean value) for the Hyundai make."""
    tax = sess.get(f"{API}/meta/taxonomy",
                   params={"level": 2, "make": hyundai_value, "lang": "en"}).json()
    items = tax.get("items", [])
    # prefer a model with children
    for i in items:
        if i.get("count", 0) > 0 and i.get("slug"):
            return i["value"]
    assert items, "no models for hyundai"
    return items[0]["value"]


# ── merged values must never come back from /meta/resolve ─────────────────────
# The bug this guards: a level-3 document carries `badge` equal to its OWN value, so slug
# uniqueness was scoped per trim and "S63 AMG 4MATIC" / "S63 AMG 4MATIC+" (slugify drops
# "+") both kept `s63-amg-4matic`. Resolve then returned whichever Mongo found first — the
# value the owner had merged away — and the dropdown cleared on Back because the collapsed
# list only offers survivors.
class TestMergedValuesResolve:
    @pytest.fixture(scope="class")
    def overrides(self, sess):
        # A quoted value in .env keeps its quotes when exported by a shell; strip them.
        token = (os.environ.get("ADMIN_TOKEN") or "").strip().strip('"').strip("'")
        if not token:
            pytest.skip("ADMIN_TOKEN not set")
        r = sess.get(f"{API}/admin/taxonomy/overrides", headers={"x-admin-token": token})
        assert r.status_code == 200, r.text
        return [o for o in r.json()["items"] if o.get("target") and int(o["level"]) == 3]

    def test_every_merged_trim_slug_resolves_to_the_survivor(self, sess, overrides):
        if not overrides:
            pytest.skip("no level-3 merges configured")
        folded = {o["value"] for o in overrides}
        checked = 0
        for o in overrides:
            tax = sess.get(f"{API}/meta/taxonomy",
                           params={"level": 3, "make": o["make"], "model": o["model"],
                                   "lang": "en"}).json()["items"]
            by_value = {i["value"]: i for i in tax}
            survivor = by_value.get(o["target"])
            if not survivor or not survivor.get("slug"):
                continue                       # merged into something outside this scope
            got = sess.get(f"{API}/meta/resolve",
                           params={"make": o["make"], "model": o["model"],
                                   "badge": survivor["slug"]}).json()["badge"]
            assert got not in folded, (
                f"{survivor['slug']} resolved to the merged-away {got!r}")
            assert got == o["target"], f"{survivor['slug']} -> {got!r}, want {o['target']!r}"
            checked += 1
        assert checked, "no merged trim could be checked"
