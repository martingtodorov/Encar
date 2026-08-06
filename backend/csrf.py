"""Cross-site request forgery protection: a real per-session token.

The threat this closes: another site cannot read our pages, but it CAN make your browser send
a request to us with your session cookie attached. `SameSite=Lax` blocks the obvious form of
that and is kept, but it is defence in depth - it says nothing about a state-changing request
from a sibling subdomain, and it is one browser setting away from not being there.

So every unsafe request must also carry a secret the attacking page has no way of learning:
a token issued by `GET /api/csrf` to the current session and sent back in `X-CSRF-Token`. A
cross-origin page cannot read our JSON and cannot set a custom header, so it cannot forge it.

The token is a SYNCHRONISER token, not a double-submit cookie: only its SHA-256 lives on the
server (in the session document), so a database leak does not hand over usable browser tokens.
It is per session rather than single-use per request - consuming a token on every request
breaks two tabs, a retry and an upload, which is how CSRF protection ends up switched off.

Sign-in and registration need protecting too, and they have no session yet, so a visitor
without one gets a short-lived PRE-AUTH token keyed by its own HttpOnly cookie. A pre-auth
record is never promoted to a session: the session is minted fresh by `auth._start_session`.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

log = logging.getLogger("csrf")

HEADER = "x-csrf-token"
PRE_COOKIE = "encar_pre"
PRE_MINUTES = 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths that must never require a browser token, because the caller is not a browser and has
# its own, stronger proof of who it is.
EXEMPT_PATHS = {
    "/api/csrf",                  # issues the token; a GET anyway, listed for clarity
    "/api/stripe/webhook",        # Stripe signs the raw body - it cannot read our cookies
}

_db = None


def set_db(db):
    global _db
    _db = db


async def ensure_indexes(db):
    """Pre-auth records expire by themselves; nothing here is worth keeping."""
    await db.csrf_pre.create_index("expires_at", expireAfterSeconds=0)


def _now():
    return datetime.now(timezone.utc)


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _matches(supplied, stored_hash):
    if not supplied or not stored_hash:
        return False
    return hmac.compare_digest(_digest(supplied), stored_hash)


async def _session(request):
    """The caller's session document, found the same way auth.py finds it."""
    import auth

    raw = request.cookies.get(auth.SESSION_COOKIE)
    if not raw:
        return None
    return await _db.sessions.find_one(
        {"token_hash": _digest(raw), "expires_at": {"$gt": _now()}})


async def issue(request: Request, response: Response):
    """Mint a token for whoever is asking, and store only its hash.

    A signed-in caller gets one bound to their session; anyone else gets a pre-auth one so
    that logging in and registering are protected as well.
    """
    token = secrets.token_urlsafe(32)
    session = await _session(request)
    if session:
        await _db.sessions.update_one({"_id": session["_id"]},
                                     {"$set": {"csrf_hash": _digest(token)}})
        return token, "session"

    # Reuse the visitor's pre-auth cookie if they have one, so opening two tabs does not
    # leave the first one holding a token that has been overwritten.
    raw = request.cookies.get(PRE_COOKIE) or secrets.token_urlsafe(32)
    await _db.csrf_pre.update_one(
        {"_id": _digest(raw)},
        {"$set": {"csrf_hash": _digest(token),
                  "expires_at": _now() + timedelta(minutes=PRE_MINUTES)}},
        upsert=True)
    response.set_cookie(PRE_COOKIE, raw, httponly=True, secure=True, samesite="lax",
                        path="/", max_age=PRE_MINUTES * 60)
    return token, "pre"


async def check(request: Request):
    """True when this unsafe request carries the token it was issued."""
    supplied = request.headers.get(HEADER)
    if not supplied:
        return False
    session = await _session(request)
    if session:
        return _matches(supplied, session.get("csrf_hash"))
    raw = request.cookies.get(PRE_COOKIE)
    if not raw:
        return False
    row = await _db.csrf_pre.find_one({"_id": _digest(raw),
                                       "expires_at": {"$gt": _now()}})
    return bool(row) and _matches(supplied, row.get("csrf_hash"))


def exempt(request: Request) -> bool:
    """Callers that are not a browser session, and therefore cannot be forged through one."""
    path = request.url.path
    if request.method in SAFE_METHODS or path in EXEMPT_PATHS:
        return True
    if not path.startswith("/api/"):
        return True
    # A shared admin secret in a header is itself unforgeable from another site: a cross-origin
    # page cannot set custom headers. This is how the deploy and seed scripts call us.
    if request.headers.get("x-admin-token"):
        return True
    # Deliberately NOT exempt: a request with no cookies at all. Signing in is itself worth
    # forging (an attacker can try to log you into THEIR account and watch what you do next),
    # so login and registration must carry a pre-auth token too. The browser client fetches
    # one automatically before its first unsafe request.
    return False


async def guard(request: Request):
    """Raise 403 on an unsafe request without a valid token. Used by the middleware."""
    if exempt(request):
        return
    if not await check(request):
        raise HTTPException(403, "csrf token missing or stale")
