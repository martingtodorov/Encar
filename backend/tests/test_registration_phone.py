"""Phone number is mandatory at registration.

The office reaches the buyer through this number to arrange inspection, shipping and
payment. `/auth/register` refuses accounts without a valid E.164 phone; this file is
the sole place that exercises the gate itself (every other suite gets a valid number
injected by `conftest._provides_phone`).
"""

import os
import uuid

import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
PASSWORD = "TestPassPhone1!"


def _fresh_email():
    return f"phone-test-{uuid.uuid4().hex[:10]}@example.com"


def _register(session, **body):
    return session.post(
        f"{BASE}/api/auth/register", timeout=30,
        json={
            "email": _fresh_email(),
            "password": PASSWORD,
            "name": "Phone Test",
            **body,
        })


def test_missing_phone_is_refused():
    """An empty phone reads as `phone_required`, not accepted."""
    s = requests.Session()
    # `_provides_phone` in conftest fills in a default; opt out by passing an explicit
    # empty string, which lets us actually reach the backend gate.
    r = _register(s, phone="")
    assert r.status_code == 400, r.text[:300]
    body = r.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "phone_required"
    else:
        # A non-machine detail is still allowed, but must reference the phone.
        assert "phone" in str(detail).lower()


def test_malformed_phone_is_refused():
    """A number that is not E.164 reads as `phone_invalid`."""
    s = requests.Session()
    r = _register(s, phone="0881234567")   # missing leading '+'
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "phone_invalid"


def test_valid_phone_registers_and_lands_on_user_document():
    """A valid E.164 number lands the account and shows up on the returned user object."""
    s = requests.Session()
    r = _register(s, phone="+359881234567")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["user"]["phone"] == "+359881234567"
