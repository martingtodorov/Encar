"""Backend tests for admin shipments + public tracking (iteration 21)."""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": "encar-admin", "Content-Type": "application/json"}

TEST_REF = "TESTU1112223"
NEVER_REF = "MSKU9999999"


# --- admin shipments CRUD ---
class TestAdminShipments:
    def test_list_shipments(self):
        r = requests.get(f"{BASE}/api/admin/shipments", headers=ADMIN_HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_assign_unknown_email_returns_404(self):
        r = requests.post(
            f"{BASE}/api/admin/shipments",
            json={"email": "nobody-xyz-9999@example.com", "ref": "ZZZU0000001", "by": "container"},
            headers=ADMIN_HEADERS, timeout=30,
        )
        assert r.status_code == 404, r.text
        body = r.json()
        # ensure clear error message
        msg = (body.get("detail") or body.get("message") or "").lower()
        assert "account" in msg or "not found" in msg or "no account" in msg

    def test_assign_then_delete(self):
        # cleanup first
        requests.delete(f"{BASE}/api/admin/shipments/{TEST_REF}", headers=ADMIN_HEADERS, timeout=30)

        r = requests.post(
            f"{BASE}/api/admin/shipments",
            json={"email": "admin@encarskin.com", "ref": TEST_REF, "by": "container",
                  "vessel_name": "TEST VESSEL", "note": "pytest"},
            headers=ADMIN_HEADERS, timeout=30,
        )
        assert r.status_code in (200, 201), r.text

        r = requests.get(f"{BASE}/api/admin/shipments", headers=ADMIN_HEADERS, timeout=30)
        assert r.status_code == 200
        refs = [it["ref"] for it in r.json().get("items", [])]
        assert TEST_REF in refs

        r = requests.delete(f"{BASE}/api/admin/shipments/{TEST_REF}", headers=ADMIN_HEADERS, timeout=30)
        assert r.status_code in (200, 204), r.text

        r = requests.get(f"{BASE}/api/admin/shipments", headers=ADMIN_HEADERS, timeout=30)
        refs = [it["ref"] for it in r.json().get("items", [])]
        assert TEST_REF not in refs


# --- public tracking ---
class TestTracking:
    def test_bol_271191199_no_crash(self):
        r = requests.get(f"{BASE}/api/tracking", params={"ref": "271191199", "by": "bol"}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("found") is False
        assert data.get("configured") is True

    def test_seeded_MSKU5285725(self):
        r = requests.get(f"{BASE}/api/tracking", params={"ref": "MSKU5285725"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data.get("found") is True
        assert data.get("status") == "in_transit"
        eta = data.get("eta") or {}
        assert "2026-07-20" in (eta.get("when") or "")
        assert "Piraeus" in (eta.get("location") or "")
        last = data.get("last") or {}
        assert "Singapore" in (last.get("location") or "")
        milestones = data.get("milestones") or []
        assert len(milestones) >= 6, f"expected >=6 milestones got {len(milestones)}"

    def test_unknown_ref_returns_checking_fast(self):
        # first hit should be fast: schedules background read
        t0 = time.time()
        r = requests.get(f"{BASE}/api/tracking", params={"ref": NEVER_REF}, timeout=10)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        data = r.json()
        # Must not block 30s
        assert dt < 8.0, f"first lookup took {dt:.1f}s, expected fast return"
        # Must be either found=false with checking:true OR at least not fake milestones
        assert data.get("found") is False
        assert not (data.get("milestones") or []), "must not invent milestones"
