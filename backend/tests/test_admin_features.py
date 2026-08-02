"""Backend tests for admin surface and enquiry email hook."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": "encar-admin"}


class TestAdminAuth:
    def test_overview_401_without_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/overview")
        assert r.status_code == 401

    def test_overview_200_with_token(self):
        r = requests.get(f"{BASE_URL}/api/admin/overview", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["listings_total"] > 100000
        assert data["unique_cars"] > 100000
        assert data["translations_cached"] > 18000
        assert "email" in data
        assert data["email"]["shared_sender"] is True

    def test_coverage_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/coverage")
        assert r.status_code == 401

    def test_coverage_returns_brands_with_latin_labels(self):
        r = requests.get(f"{BASE_URL}/api/admin/coverage", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        brands = data.get("brands") or data.get("rows") or data
        assert isinstance(brands, list)
        assert len(brands) >= 50
        # Check most brands have latin label (non-hangul)
        latin_labels = 0
        for b in brands:
            label = b.get("label") or b.get("make") or ""
            if label and not any('\uac00' <= c <= '\ud7a3' for c in label):
                latin_labels += 1
        assert latin_labels >= 50, f"Only {latin_labels} latin-labeled brands"

    def test_enquiries_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/enquiries")
        assert r.status_code == 401

    def test_enquiries_list(self):
        r = requests.get(f"{BASE_URL}/api/admin/enquiries", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items") or data.get("enquiries") or data
        assert isinstance(items, list)
        assert len(items) >= 7


class TestEnquiryEmailHook:
    def test_enquiry_create_still_works(self):
        # Get a listing id via POST /api/search
        r = requests.post(f"{BASE_URL}/api/search", json={"page": 1, "per_page": 1}, timeout=15)
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("items") or r.json().get("results") or []
        assert items, "no listings found for enquiry test"
        listing_id = items[0].get("listing_id") or items[0].get("id") or items[0].get("_id")
        car_title = items[0].get("title") or items[0].get("name") or "TEST car"
        payload = {
            "listing_id": str(listing_id),
            "car_title": car_title,
            "name": "TEST_Buyer",
            "email": "test_buyer@example.com",
            "phone": "",
            "message": "TEST enquiry from backend test suite",
            "lang": "bg",
        }
        r = requests.post(f"{BASE_URL}/api/enquiry", json=payload, timeout=15)
        assert r.status_code in (200, 201), f"got {r.status_code} body={r.text[:400]}"

    def test_enquiry_appears_in_admin_list(self):
        r = requests.get(f"{BASE_URL}/api/admin/enquiries?q=TEST_Buyer", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        items = r.json().get("items") or r.json().get("enquiries") or []
        assert any("TEST_Buyer" in (it.get("name") or "") for it in items)


class TestEnquiryStatusPatch:
    def test_patch_status_flow(self):
        r = requests.get(f"{BASE_URL}/api/admin/enquiries", headers=ADMIN_HEADERS)
        items = r.json().get("items") or []
        assert items
        eid = items[0].get("id") or items[0].get("_id")
        assert eid
        # to contacted
        r2 = requests.patch(f"{BASE_URL}/api/admin/enquiries/{eid}",
                            json={"status": "contacted"}, headers=ADMIN_HEADERS)
        assert r2.status_code in (200, 204)
        # back to new
        r3 = requests.patch(f"{BASE_URL}/api/admin/enquiries/{eid}",
                            json={"status": "new"}, headers=ADMIN_HEADERS)
        assert r3.status_code in (200, 204)
