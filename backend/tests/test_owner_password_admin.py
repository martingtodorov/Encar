"""Tests for iteration 31: owner seeding, /auth/password, /admin/users/{email}/admin, gallery arrows (backend regression only)."""
import os
import time
import pytest
import requests

def _read_frontend_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    except Exception:
        pass
    return ""

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_env()).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not found"
API = f"{BASE_URL}/api"

OWNER_EMAIL = "martingtodorov@gmail.com"
OWNER_PASSWORD = "Nero"
ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASSWORD = "AdminTest2026!"
ADMIN_TOKEN = "kR7wZq2mXv9TbNp4LdYs6HcJf1UgE3aQ"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    # Some flows return a 2FA ticket instead of a session. Here we assume no 2FA.
    assert body.get("user"), f"no user returned on login: {body}"
    return s


# ---------- OWNER LOGIN ---------------------------------------------------------
class TestOwnerLogin:
    def test_owner_can_login_with_short_password(self):
        s = _login(OWNER_EMAIL, OWNER_PASSWORD)
        me = s.get(f"{API}/auth/me").json()
        assert me["user"]["email"].lower() == OWNER_EMAIL
        assert me["user"]["is_admin"] is True

    def test_register_still_rejects_short_password(self):
        r = requests.post(f"{API}/auth/register",
                          json={"email": f"TEST_short_{int(time.time())}@example.com",
                                "password": "abc123"}, timeout=15)
        assert r.status_code == 400
        assert "at least" in r.text.lower() or "characters" in r.text.lower()


# ---------- PASSWORD CHANGE -----------------------------------------------------
class TestPasswordChange:
    def test_password_change_full_flow(self):
        # Two independent sessions for the owner
        jarA = _login(OWNER_EMAIL, OWNER_PASSWORD)
        jarB = _login(OWNER_EMAIL, OWNER_PASSWORD)

        # wrong current
        r = jarA.post(f"{API}/auth/password", json={"current": "WRONG!!!", "new": "NewOwnerPass1!"})
        assert r.status_code == 401
        assert "current password is wrong" in r.text.lower()

        # new too short
        r = jarA.post(f"{API}/auth/password", json={"current": OWNER_PASSWORD, "new": "abc"})
        assert r.status_code == 400

        # new == current
        r = jarA.post(f"{API}/auth/password", json={"current": OWNER_PASSWORD, "new": OWNER_PASSWORD})
        assert r.status_code == 400

        # correct change
        new_pw = "TempOwner2026!"
        r = jarA.post(f"{API}/auth/password", json={"current": OWNER_PASSWORD, "new": new_pw})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["changed"] is True
        assert data["signed_out"] >= 1

        try:
            # jarA still valid
            me = jarA.get(f"{API}/auth/me").json()
            assert me.get("user"), "jar A session died after its own password change"
            assert me["user"]["email"].lower() == OWNER_EMAIL

            # jarB should be dead
            me_b = jarB.get(f"{API}/auth/me").json()
            assert me_b.get("user") is None, f"jar B still alive: {me_b}"

            # Old password now fails
            r = requests.post(f"{API}/auth/login",
                              json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
            assert r.status_code == 401

            # New password works
            s2 = requests.Session()
            r = s2.post(f"{API}/auth/login",
                        json={"email": OWNER_EMAIL, "password": new_pw}, timeout=15)
            assert r.status_code == 200
        finally:
            # RESTORE the owner password directly in mongo — the /auth/password
            # endpoint enforces the 8-char minimum on the NEW password, so a
            # 4-char restore is impossible through the API. Documented as a note.
            import asyncio
            from motor.motor_asyncio import AsyncIOMotorClient
            from argon2 import PasswordHasher
            async def _restore():
                cli = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
                db = cli[os.environ.get("DB_NAME", "test_database")]
                await db.users.update_one(
                    {"email_norm": OWNER_EMAIL},
                    {"$set": {"password_hash": PasswordHasher().hash(OWNER_PASSWORD)}})
                cli.close()
            asyncio.get_event_loop().run_until_complete(_restore()) if False else asyncio.run(_restore())

        # Verify restoration
        r = requests.post(f"{API}/auth/login",
                          json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
        assert r.status_code == 200


# ---------- ADMIN RIGHTS -------------------------------------------------------
class TestAdminRights:
    @pytest.fixture(scope="class")
    def owner_session(self):
        return _login(OWNER_EMAIL, OWNER_PASSWORD)

    @pytest.fixture(scope="class")
    def buyer(self):
        email = f"test_promo_{int(time.time())}@example.com"
        pw = "SecurityTest2026!"
        r = requests.post(f"{API}/auth/register",
                          json={"email": email, "password": pw}, timeout=15)
        assert r.status_code in (200, 201), r.text
        return {"email": email, "password": pw}

    def test_no_auth_returns_401(self, buyer):
        r = requests.put(f"{API}/admin/users/{buyer['email']}/admin",
                         json={"is_admin": True}, timeout=15)
        assert r.status_code == 401

    def test_unknown_email_404(self, owner_session):
        r = owner_session.put(f"{API}/admin/users/nope_{int(time.time())}@example.com/admin",
                              json={"is_admin": True})
        assert r.status_code == 404

    def test_cannot_change_own_flag(self, owner_session):
        r = owner_session.put(f"{API}/admin/users/{OWNER_EMAIL}/admin",
                              json={"is_admin": False})
        assert r.status_code == 400
        assert "own" in r.text.lower()

    def test_promote_and_demote_buyer(self, owner_session, buyer):
        # Promote
        r = owner_session.put(f"{API}/admin/users/{buyer['email']}/admin",
                              json={"is_admin": True})
        assert r.status_code == 200, r.text
        assert r.json()["is_admin"] is True

        # buyer sees is_admin
        bs = _login(buyer["email"], buyer["password"])
        me = bs.get(f"{API}/auth/me").json()
        assert me["user"]["is_admin"] is True
        # Can hit /admin/overview
        r = bs.get(f"{API}/admin/overview")
        assert r.status_code == 200

        # Audit log
        r = owner_session.get(f"{API}/admin/audit?limit=20")
        assert r.status_code == 200
        events = r.json().get("events") or r.json().get("items") or r.json()
        text = str(events).lower()
        assert "made an administrator" in text

        # Demote
        r = owner_session.put(f"{API}/admin/users/{buyer['email']}/admin",
                              json={"is_admin": False})
        assert r.status_code == 200
        assert r.json()["is_admin"] is False

        # buyer is refused now
        bs2 = _login(buyer["email"], buyer["password"])
        r = bs2.get(f"{API}/admin/overview")
        assert r.status_code in (401, 403)

    def test_admin_token_header_works(self, buyer):
        r = requests.put(f"{API}/admin/users/{buyer['email']}/admin",
                         headers={"x-admin-token": ADMIN_TOKEN},
                         json={"is_admin": True}, timeout=15)
        assert r.status_code == 200
        # cleanup
        requests.put(f"{API}/admin/users/{buyer['email']}/admin",
                     headers={"x-admin-token": ADMIN_TOKEN},
                     json={"is_admin": False}, timeout=15)


# ---------- REGRESSION ---------------------------------------------------------
class TestRegression:
    def test_second_admin_still_works(self):
        s = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        r = s.get(f"{API}/admin/overview")
        assert r.status_code == 200

    def test_normal_buyer_cannot_reach_admin(self):
        email = f"test_buyer_{int(time.time())}@example.com"
        pw = "SecurityTest2026!"
        r = requests.post(f"{API}/auth/register",
                          json={"email": email, "password": pw}, timeout=15)
        assert r.status_code in (200, 201)
        s = _login(email, pw)
        r = s.get(f"{API}/admin/overview")
        assert r.status_code in (401, 403)

    def test_buyers_list_includes_is_admin(self):
        s = _login(OWNER_EMAIL, OWNER_PASSWORD)
        r = s.get(f"{API}/admin/buyers")
        assert r.status_code == 200
        data = r.json()
        rows = data if isinstance(data, list) else (data.get("buyers") or data.get("items") or [])
        assert rows, "no buyers returned"
        # at least one row has is_admin key
        keys = set()
        for row in rows[:20]:
            keys.update(row.keys())
        assert "is_admin" in keys, f"is_admin missing from buyers rows: {keys}"
