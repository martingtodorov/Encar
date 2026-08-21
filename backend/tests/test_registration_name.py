"""Name is mandatory at registration.

Every contract and every email greets the buyer by name — "Dear ," in a legal document
is a bad look. `/auth/register` refuses accounts with a blank name; this file is the
sole place that exercises the gate itself (every other suite gets a default name
injected by `conftest._provides_name`).
"""

import os
import uuid

import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
PASSWORD = "TestPassName1!"


def _fresh_email():
    return f"name-test-{uuid.uuid4().hex[:10]}@example.com"


def _register(session, **body):
    return session.post(
        f"{BASE}/api/auth/register", timeout=30,
        json={"email": _fresh_email(), "password": PASSWORD, **body})


def test_missing_name_is_refused():
    """No name at all reads as `name_required`."""
    s = requests.Session()
    # Opt out of the conftest shim by sending an explicit empty string.
    r = _register(s, name="")
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "name_required"


def test_whitespace_only_name_is_refused():
    """A string of spaces is not a name."""
    s = requests.Session()
    r = _register(s, name="   ")
    assert r.status_code == 400, r.text[:300]


def test_valid_name_registers_and_lands_on_user_document():
    """A trimmed name lands on the returned user object."""
    s = requests.Session()
    r = _register(s, name="  Ivan Petrov  ")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["user"]["name"] == "Ivan Petrov"
