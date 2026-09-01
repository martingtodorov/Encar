"""Iteration 36 — GDPR follow-ups.

Coverage:
* GET /api/admin/consent — admin only, shape, sort, admin's own row present.
* GET /api/account/export — auth required, keys present, secrets absent, per-user isolation.
* DELETE /api/account — password + confirmation guards; correct call actually deletes.
* Deletion guard on live deposit — /api/admin/users/{email} refuses with paid deposit,
  allows when it is refunded. Uses direct DB writes to fabricate the deposit.
* Post code 1766 present in the footer/policies (frontend HTML has the address string).
"""
import os
import uuid
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD", "")
PASSWORD = "SecurityTest2026!"


def _new_email(prefix="iter36"):
    # Backend lower-cases emails, so keep them lower here to match everywhere.
    return f"test_{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def _login(session, email, password):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r


def _register(session, email, password=PASSWORD):
    r = session.post(f"{BASE_URL}/api/auth/register",
                     json={"email": email, "password": password})
    assert r.status_code in (200, 201), f"register {email} failed: {r.status_code} {r.text}"
    return r


# ── /api/admin/consent ───────────────────────────────────────────────────────
class TestAdminConsent:
    def test_admin_consent_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/consent")
        assert r.status_code in (401, 403), \
            f"guest must be refused, got {r.status_code}"

    def test_admin_consent_refuses_customer(self):
        s = requests.Session()
        email = _new_email("cust")
        _register(s, email)
        _login(s, email, PASSWORD)
        r = s.get(f"{BASE_URL}/api/admin/consent")
        assert r.status_code in (401, 403), \
            f"non-admin must be refused, got {r.status_code}: {r.text[:200]}"
        # And crucially: no other customer emails leaked
        assert "email" not in r.text or r.status_code != 200

    def test_admin_consent_shape(self):
        s = requests.Session()
        _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        r = s.get(f"{BASE_URL}/api/admin/consent")
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert "items" in data and "total" in data and "with_record" in data
        assert isinstance(data["items"], list) and len(data["items"]) > 0
        # every row has these keys
        row = data["items"][0]
        for k in ("email", "summary", "version", "categories",
                  "decided_at", "has_record"):
            assert k in row, f"missing {k} in row"

    def test_admin_consent_has_record_sort(self):
        s = requests.Session()
        _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        r = s.get(f"{BASE_URL}/api/admin/consent")
        items = r.json()["items"]
        # accounts with a record must appear before those without
        seen_no = False
        for it in items:
            if not it["has_record"]:
                seen_no = True
            elif seen_no:
                pytest.fail("has_record=True after has_record=False — sort broken")


# ── /api/account/export ──────────────────────────────────────────────────────
EXPORT_KEYS = {"generated_at", "account", "deposits", "enquiries", "shipments",
               "sessions", "push_devices", "price_alerts", "saved_search_alerts"}
FORBIDDEN_ACCOUNT = {"password_hash", "totp", "recovery_codes", "webauthn_user_id"}


class TestAccountExport:
    def test_export_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/account/export")
        assert r.status_code in (401, 403), \
            f"guest must be refused, got {r.status_code}"

    def test_export_has_all_keys_and_no_secrets(self):
        s = requests.Session()
        email = _new_email("exp")
        _register(s, email)
        _login(s, email, PASSWORD)
        r = s.get(f"{BASE_URL}/api/account/export")
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        missing = EXPORT_KEYS - set(data.keys())
        assert not missing, f"missing keys: {missing}"
        # This user's own email present
        assert data["account"].get("email") == email
        # Secrets stripped from account
        leaked = FORBIDDEN_ACCOUNT & set(data["account"].keys())
        assert not leaked, f"account leaks secret fields: {leaked}"
        # No token_hash in sessions
        for sess in data.get("sessions", []):
            assert "token_hash" not in sess, "session leaks token_hash"
        # No raw push subscription
        for dev in data.get("push_devices", []):
            assert "subscription" not in dev, "push leaks subscription"

    def test_export_isolated_per_user(self):
        s_a = requests.Session()
        s_b = requests.Session()
        email_a = _new_email("isoa")
        email_b = _new_email("isob")
        _register(s_a, email_a)
        _register(s_b, email_b)
        _login(s_a, email_a, PASSWORD)
        _login(s_b, email_b, PASSWORD)
        data_a = s_a.get(f"{BASE_URL}/api/account/export").json()
        assert data_a["account"]["email"] == email_a
        # Serialize whole export and ensure user B's email nowhere in it
        assert email_b not in str(data_a), "user A export leaks user B email"


# ── DELETE /api/account guards ───────────────────────────────────────────────
class TestAccountDeletion:
    def test_wrong_password_refused(self):
        s = requests.Session()
        email = _new_email("delp")
        _register(s, email)
        _login(s, email, PASSWORD)
        r = s.request("DELETE", f"{BASE_URL}/api/account",
                      json={"password": "WRONG-Password-2026!",
                            "confirm": "DELETE"})
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:200]}"
        # account still exists — login should still work
        s2 = requests.Session()
        r2 = s2.post(f"{BASE_URL}/api/auth/login",
                     json={"email": email, "password": PASSWORD})
        assert r2.status_code == 200, "account was deleted despite wrong password"

    def test_wrong_confirmation_refused(self):
        s = requests.Session()
        email = _new_email("delc")
        _register(s, email)
        _login(s, email, PASSWORD)
        r = s.request("DELETE", f"{BASE_URL}/api/account",
                      json={"password": PASSWORD, "confirm": "yes"})
        assert r.status_code == 400, f"expected 400, got {r.status_code}"
        # still there
        s2 = requests.Session()
        r2 = s2.post(f"{BASE_URL}/api/auth/login",
                     json={"email": email, "password": PASSWORD})
        assert r2.status_code == 200

    def test_correct_delete_removes_account(self):
        s = requests.Session()
        email = _new_email("delok")
        _register(s, email)
        _login(s, email, PASSWORD)
        r = s.request("DELETE", f"{BASE_URL}/api/account",
                      json={"password": PASSWORD, "confirm": "DELETE"})
        assert r.status_code == 200, r.text[:300]
        # login must fail
        s2 = requests.Session()
        r2 = s2.post(f"{BASE_URL}/api/auth/login",
                     json={"email": email, "password": PASSWORD})
        assert r2.status_code in (401, 400), \
            f"account still logs in after delete: {r2.status_code}"


# ── Admin deletion guard on paid deposit ─────────────────────────────────────
@pytest.mark.asyncio
class TestAdminDeleteDepositGuard:
    async def test_paid_blocks_refunded_allows(self):
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]

        s = requests.Session()
        email = _new_email("gdep")
        _register(s, email)
        _login(s, email, PASSWORD)

        # Find the user's _id
        user = await db.users.find_one({"email": email})
        assert user, "user not seeded"
        uid = user["_id"]

        # Fabricate a paid deposit
        dep_id = f"dep_iter36_{uuid.uuid4().hex[:8]}"
        await db.deposits.insert_one({
            "_id": dep_id,
            "user_id": uid,
            "payment_status": "paid",
            "amount": 300,
            "currency": "eur",
        })

        # Admin session
        admin_s = requests.Session()
        _login(admin_s, ADMIN_EMAIL, ADMIN_PASSWORD)

        # Attempt delete → must refuse
        r = admin_s.delete(f"{BASE_URL}/api/admin/users/{email}")
        assert r.status_code == 400, \
            f"expected 400, got {r.status_code}: {r.text[:200]}"
        assert "refund" in r.text.lower() or "deposit" in r.text.lower(), \
            f"error message must mention refund/deposit: {r.text[:200]}"

        # Mark refunded
        await db.deposits.update_one({"_id": dep_id},
                                     {"$set": {"payment_status": "refunded"}})

        # Now delete allowed
        r2 = admin_s.delete(f"{BASE_URL}/api/admin/users/{email}")
        assert r2.status_code == 200, \
            f"refunded deposit should not block delete: {r2.status_code} {r2.text[:200]}"

        # cleanup: remove the deposit we fabricated
        await db.deposits.delete_one({"_id": dep_id})
        client.close()


# ── Post code 1766 in footer/policy HTML ────────────────────────────────────
class TestPostCode:
    """The company address string is a client-side constant; we assert the
    /api-served/ HTML surface contains it OR the JS bundle does — the frontend
    static test is via Playwright separately. Here we just fetch a policy page
    (server-rendered head + hydrated) and check the compiled JS bundle text."""
    def test_bundle_has_post_code(self):
        # index HTML
        r = requests.get(f"{BASE_URL}/en/privacy")
        assert r.status_code == 200
        # Whether SSR or hydrated, the string must live somewhere reachable —
        # follow one .js bundle to check.
        # (kept lenient: we just check some JS file contains "1766" and "Бяла река")
        # Try main bundle by scanning HTML
        html = r.text
        import re
        js_urls = re.findall(r'src="(/static/js/[^"]+\.js)"', html)
        assert js_urls, "no JS bundle URLs found in HTML"
        found_pc = False
        found_st = False
        for u in js_urls[:10]:
            js = requests.get(f"{BASE_URL}{u}").text
            if "1766" in js:
                found_pc = True
            if "Бяла река" in js or "\\u0411\\u044f\\u043b\\u0430" in js:
                found_st = True
            if found_pc and found_st:
                break
        assert found_pc, "'1766' not found in any JS bundle"
        assert found_st, "'Бяла река' not found in any JS bundle"
