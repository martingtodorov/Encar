"""The terms box on the sign-up form is not decoration.

An account may not be created without an accepted policy version, and what was accepted has to
be recorded — the version AND the moment — so an operator can show which document a buyer agreed
to rather than merely that they agreed to something.
"""
import os
import uuid

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"
PASSWORD = "TermsTest2026!"


def _email():
    return f"terms-{uuid.uuid4().hex[:10]}@example.com"


def test_register_without_accepting_is_refused():
    s = requests.Session()
    # Explicitly empty, so conftest does not fill it in for us.
    r = s.post(f"{API}/auth/register", timeout=30,
               json={"email": _email(), "password": PASSWORD, "terms_version": ""})
    assert r.status_code == 400, r.text
    assert "terms" in r.text.lower() or "privacy" in r.text.lower(), r.text


def test_accepted_version_and_date_are_stored():
    s = requests.Session()
    email = _email()
    r = s.post(f"{API}/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "terms_version": "2026-06-08"})
    assert r.status_code == 200, r.text
    terms = (r.json().get("user") or {}).get("terms") or {}
    assert terms.get("version") == "2026-06-08", terms
    assert terms.get("at"), "the moment of acceptance was not recorded"


def test_billing_typed_at_signup_is_kept():
    """It was collected on the form and then dropped before the request was sent."""
    s = requests.Session()
    email = _email()
    r = s.post(f"{API}/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "terms_version": "2026-06-08",
                     "billing": {"full_name": "Test Buyer", "city": "Sofia", "country": "BG",
                                 "phone": "+359881234567"}})
    assert r.status_code == 200, r.text
    billing = (r.json().get("user") or {}).get("billing") or {}
    if not billing:
        pytest.fail("the sign-up address was not stored on the account")
    assert billing.get("city") == "Sofia", billing
    assert billing.get("phone") == "+359881234567", billing
