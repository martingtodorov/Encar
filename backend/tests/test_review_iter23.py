"""Iteration 23 review tests:
- Registration with billing (present + empty)
- /auth/me returns billing
- Tracking DLV delivery step (+7 days)
- Provider caching for 271191199 (quota does not budge across calls)
- Relevant sort behaviour
- Admin buyers listing
- /auth/taste unauthenticated => 401
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_TOKEN = "encar-admin"


def _sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def new_user():
    """Register a fresh user with billing address."""
    s = _sess()
    email = f"TEST_billing_{uuid.uuid4().hex[:8]}@example.com"
    pw = "TestPass2026!"
    billing = {
        "full_name": "Ivan Test",
        "street": "ul Vitosha 12",
        "city": "Sofia",
        "post_code": "1000",
        "country": "BG",
        "phone": "+359888000000",
    }
    r = s.post(f"{BASE}/api/auth/register",
               json={"email": email, "password": pw, "name": "Ivan", "billing": billing})
    assert r.status_code == 200, r.text
    return {"session": s, "email": email, "password": pw, "billing": billing}


class TestRegistrationBilling:
    def test_register_stores_billing(self, new_user):
        r = new_user["session"].get(f"{BASE}/api/auth/me")
        assert r.status_code == 200
        u = r.json()["user"]
        assert u is not None
        b = u.get("billing") or {}
        assert b.get("city") == "Sofia"
        assert b.get("country") == "BG"
        assert b.get("full_name") == "Ivan Test"

    def test_register_empty_billing_ok(self):
        s = _sess()
        email = f"TEST_nobill_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{BASE}/api/auth/register",
                   json={"email": email, "password": "TestPass2026!",
                         "name": "NoAddr", "billing": {
                             "full_name": "", "street": "", "city": "",
                             "post_code": "", "country": "", "phone": ""}})
        assert r.status_code == 200, r.text
        me = s.get(f"{BASE}/api/auth/me").json()["user"]
        assert (me.get("billing") or {}) == {}


class TestTasteAuth:
    def test_taste_requires_auth(self):
        r = requests.post(f"{BASE}/api/auth/taste",
                          json={"makes": {"BMW": 1}}, timeout=10)
        assert r.status_code == 401


class TestDeliveryStep:
    def test_delivery_7_days_after_last(self):
        r = requests.get(f"{BASE}/api/tracking",
                         params={"ref": "271191199", "by": "bol"}, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("found"), data
        stones = data.get("milestones") or []
        assert stones, "no milestones"
        assert stones[-1].get("code") == "DLV", stones[-1]
        delivery = data.get("delivery")
        assert delivery, "delivery missing"
        assert delivery["code"] == "DLV"
        # Verify +7 day relationship
        from datetime import datetime, timedelta
        real = [s for s in stones if s["code"] != "DLV"]
        last_when = max(s["when"] for s in real)
        base = datetime.fromisoformat(last_when)
        dlv = datetime.fromisoformat(delivery["when"])
        # Allow same day/time; ~7 days
        assert (dlv - base).days == 7, (base, dlv)


class TestProviderCaching:
    def test_two_calls_do_not_increase_quota(self):
        # First fetch to warm cache
        r1 = requests.get(f"{BASE}/api/tracking",
                          params={"ref": "271191199", "by": "bol"}, timeout=60)
        assert r1.status_code == 200
        # Quota before
        q1 = requests.get(f"{BASE}/api/admin/tracking-quota",
                          headers={"x-admin-token": ADMIN_TOKEN}, timeout=30).json()
        # Second fetch
        t0 = time.time()
        r2 = requests.get(f"{BASE}/api/tracking",
                          params={"ref": "271191199", "by": "bol"}, timeout=60)
        elapsed = time.time() - t0
        assert r2.status_code == 200
        # Quota after
        q2 = requests.get(f"{BASE}/api/admin/tracking-quota",
                          headers={"x-admin-token": ADMIN_TOKEN}, timeout=30).json()
        # If configured, compare used counter
        used1 = (q1 or {}).get("used")
        used2 = (q2 or {}).get("used")
        if used1 is not None and used2 is not None:
            assert used2 == used1, f"quota grew from {used1} -> {used2}"
        assert elapsed < 10, f"cached call was slow: {elapsed:.1f}s"


class TestRelevantSort:
    def test_relevant_with_taste(self):
        body = {"sort": "relevant", "page_size": 12, "lang": "en",
                "taste": {"makes": {"BMW": 5}, "models": {"5 Series (G30)": 3},
                          "fuels": {}, "samples": [[30000, 50000, 2.0]]}}
        r = requests.post(f"{BASE}/api/search", json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("items"), "no items"
        # First few should skew BMW
        makes = [(it.get("manufacturer_t") or it.get("manufacturer") or "").lower()
                 for it in d["items"][:6]]
        assert any("bmw" in m for m in makes), makes

    def test_relevant_no_taste_falls_back(self):
        r = requests.post(f"{BASE}/api/search",
                          json={"sort": "relevant", "page_size": 12, "lang": "en"},
                          timeout=30)
        assert r.status_code == 200
        assert r.json().get("items"), "no fallback items"

    def test_relevant_rubbish_no_500(self):
        r = requests.post(f"{BASE}/api/search",
                          json={"sort": "relevant", "page_size": 5, "lang": "en",
                                "taste": {"makes": {"": -999.9, "X" * 500: 1},
                                          "models": {}, "samples": [[-1, "bad", None]]}},
                          timeout=30)
        assert r.status_code in (200, 422), r.status_code


class TestAdminBuyers:
    def test_admin_buyers_lists(self, new_user):
        # Log in as new user, put some taste
        r = new_user["session"].post(f"{BASE}/api/auth/taste", json={
            "makes": {"BMW": 3}, "models": {"5 Series": 2},
            "samples": [[30000, 50000, 2.0], [32000, 60000, 2.5]],
            "events": 5, "consent": "all"})
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE}/api/admin/buyers",
                         headers={"x-admin-token": ADMIN_TOKEN}, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json().get("items") or []
        found = [x for x in items if x["email"].lower() == new_user["email"].lower()]
        assert found, f"buyer not listed: {new_user['email']}"
        me = found[0]
        assert "BMW" in me["makes"]
        assert me["price_low"] is not None and me["price_high"] is not None
