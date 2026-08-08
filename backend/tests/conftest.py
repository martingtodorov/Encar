"""Shared test setup.

The API now rejects any unsafe request that does not carry a CSRF token (see `csrf.py`), which
is exactly what a browser client does and what these suites did not. Rather than sprinkle a
token fetch through twenty files, the `requests` session is wrapped once here: every unsafe
call to /api first asks `/api/csrf` **through the same session**, so it inherits that test's
cookies and gets a token bound to the right identity - a pre-auth one when nobody is signed in,
a session one when they are. The extra round trip is invisible in a test run.

Nothing about the application is relaxed for tests.
"""
import fcntl
import os
import time

import pytest
import requests
from dotenv import load_dotenv

# Load the app's own .env here, once, so a suite behaves the same run alone as it does in the
# full run. Without this, files that never called load_dotenv themselves were SKIPPED when run
# on their own and only failed when some other file happened to load the environment first.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
# The suites talk to the app through its real public URL, which only the frontend env knows.
load_dotenv("/app/frontend/.env")

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


def _token_for(self, base):
    """Fetch a token, twice if need be: one dropped connection must not read as a CSRF bug.

    A failed fetch used to send the real call with no token at all, which the API answers with
    a truthful 403 - and the suite then blamed CSRF for what was a saturated backend.
    """
    for attempt in (1, 2):
        try:
            got = _original(self, "GET", f"{base}/api/csrf", timeout=20)
            if got.ok:
                return got.json().get("token")
        except Exception:                              # noqa: BLE001 - let the real call fail
            pass
        if attempt == 1:
            time.sleep(1)
    return None


def _accepts_terms(url, kwargs):
    """Tick the terms box for a registration, the way the sign-up form does.

    `POST /auth/register` now refuses an account with no accepted policy version, which is the
    point of it. Sixteen call sites across a dozen files should not each have to know that, so
    the body is completed here when the test has not said otherwise. Nothing is relaxed: the
    gate itself is exercised for real in test_terms_acceptance.py.
    """
    if "/auth/register" not in url:
        return
    body = kwargs.get("json")
    if isinstance(body, dict) and "terms_version" not in body:
        body["terms_version"] = "test"


def _patched(self, method, url, **kwargs):
    _accepts_terms(url, kwargs)
    if _wants_token(method, url, kwargs.get("headers")):
        base = url.split("/api/")[0]
        token = _token_for(self, base)
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



def mark_verified(email):
    """Prove a freshly registered test address, the way a buyer would with the emailed code.

    A reservation now requires a CONFIRMED address, and no letter arrives in this environment,
    so suites that register a throwaway buyer and then reserve have to pass that gate. This is
    the only shortcut taken: the gate itself is exercised for real in test_password_reset.py.
    """
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient

    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            await client[os.environ["DB_NAME"]].users.update_one(
                {"email_norm": email.strip().lower()}, {"$set": {"email_verified": True}})
        finally:
            client.close()

    asyncio.run(go())


@pytest.fixture(scope="module")
def stripe_e2e_lock():
    """Only one Stripe browser suite at a time, whichever xdist worker it lands on.

    Two of these suites drive real hosted-checkout pages with Playwright. Run at the same time
    they saturate the single preview backend, and the failures that came out - connection
    timeouts, a login answered with 403 because the CSRF fetch never completed - all pointed
    at the application rather than at the load the tests were putting on it. `--dist loadscope`
    cannot express "these two modules are exclusive", so a file lock does.
    """
    with open("/tmp/encar-stripe-e2e.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
