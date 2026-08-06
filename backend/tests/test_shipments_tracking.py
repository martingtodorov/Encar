"""Backend tests for admin shipments + public tracking (iteration 21)."""
import os
import subprocess
import sys
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": os.environ.get("ADMIN_TOKEN", ""),
                 "Content-Type": "application/json"}

TEST_REF = "TESTU1112223"
NEVER_REF = "MSKU9999999"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def seeded_container():
    """The synthetic container the Track page was built against.

    It used to be seeded by hand and the test simply assumed it was still there, so the suite
    started failing the first time the database was reset. The seed script owns the payload,
    so the test runs it and cleans up after itself.

    The payload is served through the Maersk public reader's cache, so with
    `MAERSK_PUBLIC_TRACK=0` (the owner turned the browser reader off) there is no route to it
    and the test has nothing to prove.
    """
    sys.path.insert(0, BACKEND)
    import maersk_public

    if not maersk_public.enabled():
        pytest.skip("MAERSK_PUBLIC_TRACK is off, so the public-cache route is disabled")
    subprocess.run([sys.executable, "seed_track_test.py"], cwd=BACKEND, check=True,
                   capture_output=True, timeout=120)
    yield
    subprocess.run([sys.executable, "seed_track_test.py", "--clear"], cwd=BACKEND,
                   check=False, capture_output=True, timeout=120)


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
        assert data.get("configured") is True
        # This is a REAL bill of lading: whether the carrier has anything on it today is not
        # ours to decide, so the contract checked here is the shape, not the outcome.
        assert data.get("reference") == "271191199" and data.get("by") == "bol"
        if data.get("found"):
            assert data.get("milestones"), "found with no milestones"
            assert data.get("status") in ("booked", "in_transit", "delivered")
        else:
            assert not (data.get("milestones") or []), "must not invent milestones"

    def test_seeded_MSKU5285725(self, seeded_container):
        r = requests.get(f"{BASE}/api/tracking", params={"ref": "MSKU5285725"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data.get("found") is True, data
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
        # Must not block on the 30-second browser read; a provider HTTP lookup for a
        # reference nobody has ever shipped still costs a few seconds upstream.
        assert dt < 15.0, f"first lookup took {dt:.1f}s, expected a quick answer"
        # Either "we asked and there is nothing" or "no container provider is configured";
        # what must never happen is invented milestones or a found=true.
        assert data.get("found") in (False, None), data
        assert not (data.get("milestones") or []), "must not invent milestones"
