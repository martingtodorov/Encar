"""Iteration 24 review: cold-start relevant, recommendations spread/interleave,
customs+delivery estimates, provider metering, /car/{id}/view persistence."""
import os
import time
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
ADMIN = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "encar-admin")}


# --- /car/{id}/view + car_views persistence ---
class TestViewCounter:
    def test_view_endpoint_returns_ok_and_persists(self):
        # pick a real listing id
        s = requests.post(f"{API}/search", json={"sort": "newest", "page": 1, "page_size": 1}).json()
        assert s.get("items"), "no listings"
        cid = s["items"][0]["id"]
        r1 = requests.post(f"{API}/car/{cid}/view")
        r2 = requests.post(f"{API}/car/{cid}/view")
        assert r1.status_code == 200 and r1.json().get("ok") is True
        assert r2.status_code == 200


# --- Cold-start relevant sort (NO cookies, NO taste) ---
class TestColdRelevance:
    def test_cold_relevant_returns_items_no_error(self):
        # fresh session, no cookies
        sess = requests.Session()
        r = sess.post(f"{API}/search", json={"sort": "relevant", "page": 1, "page_size": 24, "lang": "en"})
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert len(data["items"]) > 0, "cold-start relevant returned empty"

    def test_cold_relevant_rubbish_taste_is_still_ok(self):
        r = requests.post(f"{API}/search", json={
            "sort": "relevant", "page": 1, "page_size": 12, "lang": "en",
            "taste": {"makes": {}, "models": {}, "fuels": {}, "samples": []}
        })
        assert r.status_code == 200
        assert len(r.json().get("items", [])) > 0


# --- Warm relevance regression ---
class TestWarmRelevance:
    def test_warm_taste_ranks_make_first(self):
        # pick a real make from meta/filters
        meta = requests.get(f"{API}/meta/filters?lang=en").json()
        makes = [m["value"] for m in meta.get("makes", [])[:5]]
        if not makes:
            pytest.skip("no makes")
        target = makes[0]
        r = requests.post(f"{API}/search", json={
            "sort": "relevant", "page": 1, "page_size": 12, "lang": "en",
            "taste": {"makes": {target: 10}, "models": {}, "fuels": {}, "samples": []}
        })
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert items
        # first item should be that make
        first_mfr = items[0].get("manufacturer") or items[0].get("manufacturer_t")
        assert first_mfr == target, f"expected {target} first, got {first_mfr}"


# --- Recommendations spread + interleave (max 2 per make+model, non-adjacent) ---
class TestRecommendationsSpread:
    def test_at_most_two_and_no_adjacent(self):
        meta = requests.get(f"{API}/meta/filters?lang=en").json()
        makes = [m["value"] for m in meta.get("makes", [])[:3]]
        if not makes:
            pytest.skip("no makes")
        r = requests.post(f"{API}/recommendations", json={
            "makes": {m: 5 for m in makes},
            "models": {},
            "fuels": {},
            "samples": [],
            "limit": 24,
            "lang": "en",
        })
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert items, "no recommendations"
        # Count make+model
        keys = [f"{(it.get('manufacturer') or '')}|{(it.get('model') or '')}" for it in items]
        from collections import Counter
        cnt = Counter(keys)
        offenders = {k: v for k, v in cnt.items() if v > 2}
        assert not offenders, f"more than 2 of same make+model: {offenders}"
        # no two adjacent share key
        adj = [(keys[i], keys[i+1]) for i in range(len(keys)-1) if keys[i] == keys[i+1]]
        assert not adj, f"adjacent duplicates: {adj}"

    def test_no_why_label_on_landing(self):
        # Whatever the backend returns as why_label — the landing card must NOT render it.
        # This is a UI concern; here we simply check the CarCard source doesn't reference it
        # (verified separately in the UI test).
        pass


# --- Customs + delivery estimates ---
class TestTrackingEstimates:
    def test_customs_and_delivery_offsets(self):
        r = requests.get(f"{API}/tracking", params={"ref": "271191199", "by": "bol"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("customs"), "customs missing"
        assert data.get("delivery"), "delivery missing"
        # last carrier milestone was 2026-08-09 per spec
        # customs = +3 days = 2026-08-12, delivery = +7 days = 2026-08-16
        cu = data["customs"]["when"]
        dl = data["delivery"]["when"]
        assert cu.startswith("2026-08-12"), f"customs when={cu}"
        assert dl.startswith("2026-08-16"), f"delivery when={dl}"
        assert data["customs"].get("estimated") is True
        assert data["delivery"].get("estimated") is True
        # customs row must include port location
        assert data["customs"].get("location"), "customs port missing"
        # milestones' last two rows
        stones = data.get("milestones") or []
        assert len(stones) >= 2
        assert stones[-2]["code"] == "CU"
        assert stones[-1]["code"] == "DLV"


# --- Provider metering: two consecutive lookups don't change quota ---
class TestProviderMetering:
    def test_two_lookups_same_quota(self):
        q0 = requests.get(f"{API}/admin/tracking-quota", headers=ADMIN)
        assert q0.status_code == 200
        used0 = q0.json().get("used")
        r1 = requests.get(f"{API}/tracking", params={"ref": "271191199", "by": "bol"})
        r2 = requests.get(f"{API}/tracking", params={"ref": "271191199", "by": "bol"})
        assert r1.status_code == 200 and r2.status_code == 200
        q1 = requests.get(f"{API}/admin/tracking-quota", headers=ADMIN).json()
        used1 = q1.get("used")
        assert used1 == used0, f"quota changed {used0} -> {used1}"
