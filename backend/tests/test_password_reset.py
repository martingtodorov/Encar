"""Password reset: a one-shot link, valid for thirty minutes, only for a proved address.

The raw token is a 32-byte secret and is stored hashed, so unlike the six-digit verification
code it cannot be recovered from the database. The suite therefore checks the ISSUING side by
what it writes (a row exists, or it does not) and the SPENDING side against a row it plants
itself with a token it already knows. Nothing about the application is relaxed for this.
"""
import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
PASSWORD = "ResetTest2026!"
NEW_PASSWORD = "ResetTest2026-New!"


def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _run(coro_fn):
    async def go():
        client, db = _db()
        try:
            return await coro_fn(db)
        finally:
            client.close()

    return asyncio.run(go())


def _register():
    s = requests.Session()
    email = f"reset-{uuid.uuid4().hex[:10]}@example.com"
    r = s.post(f"{BASE}/api/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "name": "Reset Test", "lang": "bg"})
    assert r.status_code == 200, r.text[:300]
    return s, email


def _mark_verified(email):
    async def go(db):
        await db.users.update_one({"email_norm": email.lower()},
                                 {"$set": {"email_verified": True}})
    _run(go)


def _reset_rows(email):
    return _run(lambda db: db.password_resets.count_documents({"email": email}))


def _plant(email, minutes=30):
    """Write a reset row with a token we know, exactly as the endpoint would."""
    token = uuid.uuid4().hex + uuid.uuid4().hex

    async def go(db):
        user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
        await db.password_resets.delete_many({"user_id": user["_id"]})
        now = datetime.now(timezone.utc)
        await db.password_resets.insert_one({
            "_id": str(uuid.uuid4()),
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "user_id": user["_id"], "email": email, "lang": "bg",
            "created_at": now, "expires_at": now + timedelta(minutes=minutes)})

    _run(go)
    return token


def _cleanup(email):
    async def go(db):
        user = await db.users.find_one({"email_norm": email.lower()}, {"_id": 1})
        if user:
            await db.sessions.delete_many({"user_id": user["_id"]})
            await db.password_resets.delete_many({"user_id": user["_id"]})
            await db.email_codes.delete_many({"_id": user["_id"]})
            await db.users.delete_one({"_id": user["_id"]})

    _run(go)


@pytest.fixture
def account():
    s, email = _register()
    yield s, email
    _cleanup(email)


def test_unverified_address_gets_no_link(account):
    """The reply is the same, but nothing is issued: an unproved address is not the owner's."""
    s, email = account
    r = s.post(f"{BASE}/api/auth/forgot-password", json={"email": email, "lang": "bg"},
               timeout=30)
    assert r.status_code == 200, r.text[:300]
    assert r.json() == {"sent": True}
    assert _reset_rows(email) == 0


def test_unknown_address_is_indistinguishable(account):
    """No 404, no different wording - the answer must not reveal who has an account."""
    s, _ = account
    r = s.post(f"{BASE}/api/auth/forgot-password",
               json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "lang": "en"},
               timeout=30)
    assert r.status_code == 200
    assert r.json() == {"sent": True}


def test_verified_address_gets_a_link_and_a_cooldown(account):
    s, email = account
    _mark_verified(email)
    r = s.post(f"{BASE}/api/auth/forgot-password", json={"email": email, "lang": "bg"},
               timeout=30)
    assert r.status_code == 200
    assert _reset_rows(email) == 1
    # Asked again straight away: throttled, and the row that already exists is untouched.
    again = s.post(f"{BASE}/api/auth/forgot-password", json={"email": email, "lang": "bg"},
                   timeout=30)
    assert again.status_code == 200
    assert _reset_rows(email) == 1


def test_link_is_checkable_before_the_form(account):
    s, email = account
    _mark_verified(email)
    token = _plant(email)
    ok = s.get(f"{BASE}/api/auth/reset-valid", params={"token": token}, timeout=30)
    assert ok.status_code == 200 and ok.json()["valid"] is True
    bad = s.get(f"{BASE}/api/auth/reset-valid", params={"token": "nonsense" * 4}, timeout=30)
    assert bad.status_code == 200 and bad.json()["valid"] is False


def test_expired_link_is_refused(account):
    s, email = account
    _mark_verified(email)
    token = _plant(email, minutes=-1)
    r = s.post(f"{BASE}/api/auth/reset-password",
               json={"token": token, "password": NEW_PASSWORD}, timeout=30)
    assert r.status_code == 410, r.text[:300]
    assert r.json()["detail"]["code"] == "expired"


def test_short_password_is_refused(account):
    s, email = account
    _mark_verified(email)
    token = _plant(email)
    r = s.post(f"{BASE}/api/auth/reset-password", json={"token": token, "password": "abc"},
               timeout=30)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "too_short"
    # The link survives a rejected password: the buyer gets to try again.
    assert s.get(f"{BASE}/api/auth/reset-valid", params={"token": token},
                 timeout=30).json()["valid"] is True


def test_reset_works_once_and_signs_everything_out(account):
    s, email = account
    _mark_verified(email)
    token = _plant(email)

    r = s.post(f"{BASE}/api/auth/reset-password",
               json={"token": token, "password": NEW_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["reset"] is True
    # The session the reset was requested from is gone too: that is the point of a reset.
    assert s.get(f"{BASE}/api/auth/me", timeout=30).json()["user"] is None

    # Single use.
    twice = s.post(f"{BASE}/api/auth/reset-password",
                   json={"token": token, "password": NEW_PASSWORD}, timeout=30)
    assert twice.status_code == 400
    assert twice.json()["detail"]["code"] == "bad_token"

    # The old password is dead, the new one works.
    fresh = requests.Session()
    old = fresh.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD},
                     timeout=30)
    assert old.status_code == 401
    new = fresh.post(f"{BASE}/api/auth/login",
                     json={"email": email, "password": NEW_PASSWORD}, timeout=30)
    assert new.status_code == 200, new.text[:300]
    assert new.json()["user"]["email"].lower() == email.lower()


def test_reservation_needs_a_proved_address(account):
    """A hold on a card and a car off the market for a week: not for an unproved address."""
    s, _ = account
    found = s.post(f"{BASE}/api/search", json={"page_size": 1}, timeout=60)
    assert found.status_code == 200, found.text[:300]
    rows = found.json().get("items") or []
    assert rows, "no listings to reserve against"
    car_id = rows[0]["id"]
    r = s.post(f"{BASE}/api/deposit/checkout",
               json={"car_id": car_id, "origin_url": f"{BASE}/bg"}, timeout=60)
    assert r.status_code == 403, r.text[:300]
    assert r.json()["detail"]["code"] == "email_unverified"
