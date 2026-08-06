"""Shared test setup.

The API now rejects any unsafe request that does not carry a CSRF token (see `csrf.py`), which
is exactly what a browser client does and what these suites did not. Rather than sprinkle a
token fetch through twenty files, the `requests` session is wrapped once here: every unsafe
call to /api first asks `/api/csrf` **through the same session**, so it inherits that test's
cookies and gets a token bound to the right identity - a pre-auth one when nobody is signed in,
a session one when they are. The extra round trip is invisible in a test run.

Nothing about the application is relaxed for tests.
"""
import os

import pytest
import requests

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
HEADER = "X-CSRF-Token"

_original = requests.sessions.Session.request


def _wants_token(method, url, headers):
    if method.upper() not in UNSAFE or "/api/" not in url:
        return False
    if url.rstrip("/").endswith("/api/stripe/webhook"):
        return False                                   # signed by Stripe, exempt by design
    lowered = {k.lower() for k in (headers or {})}
    # A shared admin secret in a header cannot be forged from another site, so the API exempts
    # it - and so must we, or we would mask that path never being exercised.
    return not ({"x-admin-token", HEADER.lower()} & lowered)


def _patched(self, method, url, **kwargs):
    if _wants_token(method, url, kwargs.get("headers")):
        base = url.split("/api/")[0]
        try:
            got = _original(self, "GET", f"{base}/api/csrf", timeout=15)
            token = got.json().get("token") if got.ok else None
        except Exception:                              # noqa: BLE001 - let the real call fail
            token = None
        if token:
            headers = dict(kwargs.get("headers") or {})
            headers[HEADER] = token
            kwargs["headers"] = headers
    return _original(self, method, url, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def _csrf_aware_requests():
    requests.sessions.Session.request = _patched
    try:
        yield
    finally:
        requests.sessions.Session.request = _original


@pytest.fixture(scope="session", autouse=True)
def _env():
    """A couple of suites read these directly; fail loudly rather than mysteriously."""
    for key in ("MONGO_URL", "DB_NAME"):
        if not os.environ.get(key):
            pytest.skip(f"{key} is not set - run from /app/backend with .env loaded")
