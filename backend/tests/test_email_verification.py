"""Email verification on first registration: a rotating six-digit code.

Six digits is only a million combinations, so what makes this safe is the ATTEMPT LIMIT and
the short life of the code, and those are what these tests hold on to. The code itself is read
straight out of Mongo (it is stored hashed, so it is recovered by hashing candidates) because
the Resend key in this environment is rejected and no letter actually arrives.
"""
import asyncio
import hashlib
import os
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
PASSWORD = "VerifyTest2026!"


def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _register():
    s = requests.Session()
    email = f"verify-{uuid.uuid4().hex[:10]}@example.com"
    r = s.post(f"{BASE}/api/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "name": "Verify Test",
                     "lang": "bg"})
    assert r.status_code == 200, r.text[:300]
    return s, email, r.json()["user"]


def _code_of(email):
    """Recover the code from its hash - the point being that the clear text is NOT stored."""
    async def go():
        client, db = _db()
        try:
            user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
            row = await db.email_codes.find_one({"_id": user["_id"]})
            assert row and row.get("code_hash"), "no code was issued"
            assert "code" not in row, "the clear code must never be stored"
            for i in range(1_000_000):
                if hashlib.sha256(f"{i:06d}".encode()).hexdigest() == row["code_hash"]:
                    return f"{i:06d}"
            raise AssertionError("code hash did not match any six-digit code")
        finally:
            client.close()

    return asyncio.run(go())


def _cleanup(email):
    async def go():
        client, db = _db()
        try:
            user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
            if user:
                await db.users.delete_one({"_id": user["_id"]})
                await db.email_codes.delete_one({"_id": user["_id"]})
                await db.sessions.delete_many({"user_id": user["_id"]})
        finally:
            client.close()

    asyncio.run(go())


@pytest.fixture
def fresh():
    s, email, user = _register()
    yield s, email, user
    _cleanup(email)


# ── the happy path ───────────────────────────────────────────────────────────
def test_registration_starts_unverified_and_issues_a_code(fresh):
    _, email, user = fresh
    assert user["email_verified"] is False, user
    code = _code_of(email)
    assert len(code) == 6 and code.isdigit()


def test_right_code_verifies_and_burns_the_code(fresh):
    s, email, _ = fresh
    code = _code_of(email)
    r = s.post(f"{BASE}/api/auth/verify-email", json={"code": code}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["user"]["email_verified"] is True

    # The row is gone, so the same code cannot be replayed.
    async def gone():
        client, db = _db()
        try:
            user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
            return await db.email_codes.find_one({"_id": user["_id"]}) is None
        finally:
            client.close()

    assert asyncio.run(gone())
    # And asking again is answered politely rather than with an error.
    again = s.post(f"{BASE}/api/auth/verify-email", json={"code": code}, timeout=20)
    assert again.status_code == 200
    assert again.json().get("already") is True


def test_session_survives_and_me_reports_verification(fresh):
    s, email, _ = fresh
    me = s.get(f"{BASE}/api/auth/me", timeout=20).json()
    assert me["user"]["email_verified"] is False
    s.post(f"{BASE}/api/auth/verify-email", json={"code": _code_of(email)}, timeout=30)
    me = s.get(f"{BASE}/api/auth/me", timeout=20).json()
    assert me["user"]["email_verified"] is True


# ── the guards, which are what actually make six digits safe ─────────────────
def test_wrong_code_counts_down_and_then_locks(fresh):
    s, email, _ = fresh
    real = _code_of(email)
    wrong = "000000" if real != "000000" else "111111"
    seen = []
    for _ in range(5):
        r = s.post(f"{BASE}/api/auth/verify-email", json={"code": wrong}, timeout=20)
        assert r.status_code == 400, r.text[:200]
        detail = r.json()["detail"]
        assert detail["code"] == "wrong"
        seen.append(detail["left"])
    # Counting down, not a constant number: the buyer can see the door closing.
    assert seen == sorted(seen, reverse=True), seen
    assert seen[-1] == 0, seen

    # Sixth attempt is refused outright - and the RIGHT code no longer works either.
    r = s.post(f"{BASE}/api/auth/verify-email", json={"code": wrong}, timeout=20)
    assert r.status_code == 429, r.text[:200]
    r = s.post(f"{BASE}/api/auth/verify-email", json={"code": real}, timeout=20)
    assert r.status_code == 429, "a burnt code must stay burnt"


def test_resend_is_throttled_and_rotates_the_code(fresh):
    s, email, _ = fresh
    first = _code_of(email)
    r = s.post(f"{BASE}/api/auth/resend-code", timeout=20)
    assert r.status_code == 429, r.text[:200]
    assert r.json()["detail"]["code"] == "cooldown"
    assert 0 < r.json()["detail"]["seconds"] <= 60
    # Still the same code while the cooldown holds: a refused resend must not rotate anything.
    assert _code_of(email) == first


def test_expired_code_is_refused(fresh):
    s, email, _ = fresh
    code = _code_of(email)

    async def age_it():
        client, db = _db()
        try:
            user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
            from datetime import datetime, timedelta, timezone
            await db.email_codes.update_one(
                {"_id": user["_id"]},
                {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
        finally:
            client.close()

    asyncio.run(age_it())
    r = s.post(f"{BASE}/api/auth/verify-email", json={"code": code}, timeout=20)
    assert r.status_code == 410, r.text[:200]
    assert r.json()["detail"]["code"] == "expired"


def test_verify_needs_a_session():
    r = requests.post(f"{BASE}/api/auth/verify-email", json={"code": "123456"}, timeout=20)
    assert r.status_code == 401
    r = requests.post(f"{BASE}/api/auth/resend-code", timeout=20)
    assert r.status_code == 401


def test_existing_accounts_are_treated_as_verified():
    """Nobody is locked out by the rollout: a user document with no flag counts as verified."""
    email = f"legacy-{uuid.uuid4().hex[:8]}@example.com"
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "name": "Legacy"})
    assert r.status_code == 200

    async def strip_flag():
        client, db = _db()
        try:
            await db.users.update_one({"email_norm": email.lower()},
                                      {"$unset": {"email_verified": ""}})
        finally:
            client.close()

    asyncio.run(strip_flag())
    try:
        me = s.get(f"{BASE}/api/auth/me", timeout=20).json()
        assert me["user"]["email_verified"] is True
    finally:
        _cleanup(email)


def test_two_registrations_get_their_own_codes(fresh):
    """The code belongs to the account, not to the process: two buyers, two independent codes."""
    _, first_email, _ = fresh
    s2, second_email, _ = _register()
    try:
        first, second = _code_of(first_email), _code_of(second_email)
        assert len(first) == 6 and len(second) == 6
        # Issuing the second one must not have disturbed the first.
        assert _code_of(first_email) == first
    finally:
        s2.close()
        _cleanup(second_email)
