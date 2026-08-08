"""Accounts: password login (Argon2id) + passkeys (WebAuthn/FIDO2).

Design decisions:
  * Sessions are OPAQUE and server-side. Mongo stores only sha256(token); the raw
    token lives solely in an HttpOnly cookie. That gives instant revocation and keeps
    nothing readable in the browser (no JWT in localStorage).
  * Passwords are hashed with Argon2id via pwdlib. Never stored or logged in clear.
  * Passkeys are DISCOVERABLE (resident) credentials, so signing in is one tap with no
    email typed: the authenticator tells us which credential it used and we resolve the
    user from it.
  * The Relying Party ID is derived from the request host at runtime, never hardcoded,
    so the same code works on the preview domain and on a future production domain.
    (A passkey is bound to its RP ID, so moving domains means re-registering it.)
  * IDs are UUID strings, matching the rest of this codebase. No ObjectIds.
"""

import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

import mailer
import twofa
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

log = logging.getLogger("auth")
router = APIRouter()

SESSION_COOKIE = "encar_session"
SESSION_TTL_DAYS = 30
CHALLENGE_TTL_MIN = 5
MIN_PASSWORD = 8
RP_NAME = "Encar Import"

ph = PasswordHash.recommended()
# Verifying against a dummy hash for unknown emails keeps the timing (and therefore the
# answer to "does this account exist?") indistinguishable from a wrong password.
_DUMMY_HASH = ph.hash("unknown-account-placeholder")

_db = None


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


async def ensure_indexes(db):
    await db.users.create_index("email_norm", unique=True)
    await db.webauthn_credentials.create_index("credential_id", unique=True)
    await db.webauthn_credentials.create_index("user_id")
    await db.webauthn_challenges.create_index("expires_at", expireAfterSeconds=0)
    await db.sessions.create_index("token_hash", unique=True)
    await db.sessions.create_index("expires_at", expireAfterSeconds=0)
    # Codes clean themselves up: an expired one must not sit in the database waiting to be
    # tried offline.
    await db.email_codes.create_index("expires_at", expireAfterSeconds=0)
    # Same for reset tokens: a dead one is a liability, not a record.
    await db.password_resets.create_index("token_hash", unique=True)
    await db.password_resets.create_index("expires_at", expireAfterSeconds=0)


async def ensure_owner(db):
    """Make sure the person who owns the install can always get in.

    Idempotent and DELIBERATELY not a reset. The password is written only when the account
    has NONE - a brand new account, or one that has only ever signed in with Google - so a
    password the owner later changes in their profile survives every restart. The admin flag,
    on the other hand, is re-applied every time: that is the whole point of this seed.
    """
    email = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
    password = os.environ.get("OWNER_PASSWORD") or ""
    if not email:
        return
    user = await db.users.find_one({"email_norm": email})
    if not user:
        await db.users.insert_one({
            "_id": str(uuid.uuid4()),
            "email": email,
            "email_norm": email,
            "name": "",
            "password_hash": ph.hash(password) if password else "",
            "webauthn_user_id": bytes_to_base64url(secrets.token_bytes(32)),
            "favourites": [],
            "is_admin": True,
            "created_at": _now(),
        })
        log.info("owner account created: %s", email)
        return
    patch = {}
    if not user.get("is_admin"):
        patch["is_admin"] = True
    if password and not user.get("password_hash"):
        patch["password_hash"] = ph.hash(password)
    if patch:
        await db.users.update_one({"_id": user["_id"]}, {"$set": patch})
        log.info("owner account updated: %s (%s)", email, ", ".join(patch))


# ── relying party -------------------------------------------------------------
def _rp(request: Request):
    """(rp_id, origin) for this request. Derived, never hardcoded."""
    origin = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
    if not origin:
        host = (request.headers.get("x-forwarded-host")
                or request.headers.get("host") or "").split(",")[0].strip()
        proto = (request.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
        origin = f"{proto}://{host}"
    rp_id = urlparse(origin).hostname
    if not rp_id:
        raise HTTPException(500, "cannot determine relying party host")
    return rp_id, origin


def _expected_origins(request: Request, origin: str):
    """Accept the browser's own Origin header when it is the same host, because the
    ingress may present http/https or an extra port that we cannot infer."""
    origins = {origin}
    sent = (request.headers.get("origin") or "").rstrip("/")
    if sent and urlparse(sent).hostname == urlparse(origin).hostname:
        origins.add(sent)
    return list(origins)


# ── sessions ------------------------------------------------------------------
def _hash_token(raw: str):
    return hashlib.sha256(raw.encode()).hexdigest()


# ── email verification codes --------------------------------------------------
# A fresh six-digit code on every send, hashed at rest, dead after fifteen minutes or five
# wrong guesses. Six digits is only a million combinations, so the ATTEMPT LIMIT is what makes
# it safe, not the length: without it a code like this is guessable.
VERIFY_TTL_MINUTES = 15
VERIFY_MAX_ATTEMPTS = 5
VERIFY_RESEND_SECONDS = 60
VERIFY_MAX_SENDS = 8

# ── password reset ------------------------------------------------------------
# A long random token, hashed at rest, single use, dead after thirty minutes. Unlike the
# verification code this is NOT six digits: it arrives as a link and is the only thing
# standing between a stranger and an account, so it has to be unguessable outright.
RESET_TTL_MINUTES = 30
RESET_COOLDOWN_SECONDS = 60
RESET_MAX_PER_DAY = 5


def _lang(value):
    """Kept local on purpose: importing server.norm_lang here would be a circular import."""
    got = (value or "").strip().lower()[:2]
    return got if got in ("bg", "ro", "en") else "en"


def _new_code():
    # secrets, not random: this is a credential.
    return f"{secrets.randbelow(1_000_000):06d}"


async def _issue_code(user, lang="en"):
    """Replace whatever code was outstanding and email the new one.

    Replacing is deliberate - an old code stops working the moment a new one is asked for, so
    a code read over someone's shoulder yesterday is worthless today.
    """
    code = _new_code()
    now = _now()
    existing = await _db.email_codes.find_one({"_id": user["_id"]}) or {}
    await _db.email_codes.update_one(
        {"_id": user["_id"]},
        {"$set": {"code_hash": _hash_token(code), "expires_at": now + timedelta(
            minutes=VERIFY_TTL_MINUTES), "attempts": 0, "sent_at": now,
            "email": user["email"], "lang": lang},
         "$inc": {"sends": 1}},
        upsert=True)
    sent = await mailer.send_verify_code(user["email"], code,
                                         user.get("name") or "", lang)
    if not sent:
        # Loudly: a buyer staring at a code screen with no letter coming is the worst possible
        # silence, and right now the Resend key in this environment is rejected.
        log.error("verification code for %s could not be emailed - check RESEND_API_KEY",
                  user["email"])
    return bool(existing)


def _aware(value):
    """Mongo hands back naive UTC; comparing that to an aware `now` raises."""
    if value and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _verified(user):
    """Accounts created before this existed are trusted: nobody gets locked out by a rollout."""
    return bool(user.get("email_verified", True))


async def _start_session(response: Response, user_id: str, request: Request = None):
    raw = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent", "") if request else ""
    # Behind the ingress the real client address arrives in X-Forwarded-For; the first hop
    # is the visitor, the rest are proxies.
    forwarded = (request.headers.get("x-forwarded-for", "") if request else "").split(",")
    ip = (forwarded[0].strip() if forwarded[0].strip()
          else (request.client.host if request and request.client else ""))
    marks = twofa.device(ua)
    await _db.sessions.insert_one({
        "_id": str(uuid.uuid4()),
        "token_hash": _hash_token(raw),
        "user_id": user_id,
        "created_at": _now(),
        "last_seen": _now(),
        "user_agent": ua[:400],
        "ip": ip[:64],
        "browser": marks["browser"],
        "os": marks["os"],
        "label": marks["label"],
        "expires_at": _now() + timedelta(days=SESSION_TTL_DAYS),
    })
    response.set_cookie(
        SESSION_COOKIE, raw, httponly=True, secure=True, samesite="lax",
        path="/", max_age=SESSION_TTL_DAYS * 86400,
    )


async def _user_from_request(request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    session = await _db.sessions.find_one(
        {"token_hash": _hash_token(raw), "expires_at": {"$gt": _now()}})
    if not session:
        return None
    # "Last active" only has to be roughly right, and writing it on every request would be
    # one Mongo write per page view.
    last = session.get("last_seen") or session.get("created_at")
    if not last or (_now() - last.replace(tzinfo=timezone.utc)).total_seconds() > 300:
        await _db.sessions.update_one({"_id": session["_id"]},
                                     {"$set": {"last_seen": _now()}})
    return await _db.users.find_one({"_id": session["user_id"]})


async def current_user(request: Request):
    """Dependency for routes that REQUIRE a signed-in user."""
    user = await _user_from_request(request)
    if not user:
        raise HTTPException(401, "not authenticated")
    return user


async def optional_user(request: Request):
    """Dependency for routes that behave differently when signed in (e.g. enquiries)."""
    return await _user_from_request(request)


async def current_admin(request: Request):
    """Dependency for the pricing/settings pages."""
    user = await current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "this area is for administrators")
    return user


def _public(user, passkeys=0):
    return {
        "id": user["_id"],
        "email": user["email"],
        "name": user.get("name") or "",
        "has_password": bool(user.get("password_hash")),
        "passkeys": passkeys,
        "favourites": user.get("favourites") or [],
        "saved_searches": user.get("saved_searches") or [],
        "is_admin": bool(user.get("is_admin")),
        "email_verified": _verified(user),
        "billing": user.get("billing") or {},
        # One phone for the UI to prefill with: the number kept for notifications wins over the
        # billing one, because it is the one the buyer keeps current.
        "phone": user.get("phone") or (user.get("billing") or {}).get("phone") or "",
        "consent": user.get("consent") or "",
        "consent_record": user.get("consent_record") or {},
        "twofa": bool((user.get("totp") or {}).get("enabled")),
        "recovery_codes_left": sum(
            1 for c in (user.get("recovery_codes") or []) if not c.get("used")),
        "taste": user.get("taste") or {},
        "created_at": user.get("created_at"),
    }


# ── payloads ------------------------------------------------------------------
class Billing(BaseModel):
    """Where the car is finally delivered. Optional everywhere, and only ever the
    minimum needed to drive a lorry to the buyer's door and raise an invoice."""
    full_name: str = ""
    street: str = ""
    city: str = ""
    post_code: str = ""
    country: str = ""
    phone: str = ""

    def clean(self):
        out = {
            "full_name": self.full_name.strip()[:120],
            "street": self.street.strip()[:160],
            "city": self.city.strip()[:80],
            "post_code": self.post_code.strip()[:16],
            "country": self.country.strip().upper()[:2],
            "phone": self.phone.strip()[:32],
        }
        return out if any(out.values()) else {}


class Credentials(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    lang: str = ""
    billing: Billing | None = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class CeremonyBody(BaseModel):
    flow_id: str
    credential: dict


class FavouritesBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


class SavedSearchesBody(BaseModel):
    items: list[dict] = Field(default_factory=list)


# ── password auth -------------------------------------------------------------
@router.post("/auth/register")
async def register(body: Credentials, request: Request, response: Response):
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(400, f"password must be at least {MIN_PASSWORD} characters")
    email = str(body.email).strip().lower()
    user = {
        "_id": str(uuid.uuid4()),
        "email": email,
        "email_norm": email,
        "name": body.name.strip(),
        "password_hash": ph.hash(body.password),
        # opaque handle given to authenticators, never the email
        "webauthn_user_id": bytes_to_base64url(secrets.token_bytes(32)),
        "favourites": [],
        "is_admin": False,
        # New accounts start unproven. Accounts that existed before verification did are
        # trusted by `_verified()`, so nobody is locked out by the rollout.
        "email_verified": False,
        "created_at": _now(),
    }
    # Stored only when the buyer actually filled it in: an empty form leaves no address
    # behind, and `PUT /auth/billing` can add or erase it later.
    billing = body.billing.clean() if body.billing else {}
    if billing:
        user["billing"] = billing
    if await _db.users.find_one({"email_norm": email}):
        raise HTTPException(409, "that email is already registered")
    # The first account (or the first one created while no administrator exists) owns
    # the install, so the admin pricing page is reachable without a default password.
    user["is_admin"] = await _db.users.count_documents({"is_admin": True}) == 0
    try:
        await _db.users.insert_one(user)
    except Exception:
        raise HTTPException(409, "that email is already registered")
    await _start_session(response, user["_id"], request)
    # The address has to be proved before it is trusted with a reset link or a reservation,
    # so a fresh code goes out now. The session still starts: making someone verify before
    # they can even look around loses the buyer, and nothing sensitive is reachable unverified.
    await _issue_code(user, _lang(body.lang))
    return {"user": _public(user)}


class CodeBody(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@router.post("/auth/verify-email")
async def verify_email(body: CodeBody, user=Depends(current_user)):
    """Prove the address. Wrong guesses are counted, and five of them burn the code."""
    if _verified(user):
        return {"user": _public(user), "already": True}
    record = await _db.email_codes.find_one({"_id": user["_id"]})
    if not record or _aware(record.get("expires_at")) and _aware(record["expires_at"]) < _now():
        raise HTTPException(410, {"code": "expired"})
    if (record.get("attempts") or 0) >= VERIFY_MAX_ATTEMPTS:
        raise HTTPException(429, {"code": "too_many_attempts"})
    if not secrets.compare_digest(_hash_token(body.code.strip()),
                                  record.get("code_hash") or ""):
        await _db.email_codes.update_one({"_id": user["_id"]}, {"$inc": {"attempts": 1}})
        left = VERIFY_MAX_ATTEMPTS - (record.get("attempts") or 0) - 1
        # A machine-readable detail: the buyer reads this on a Bulgarian or Romanian page, so
        # the wording belongs in the frontend's own dictionary, not in an English string here.
        raise HTTPException(400, {"code": "wrong", "left": max(0, left)})

    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"email_verified": True,
                                         "email_verified_at": _now()}})
    await _db.email_codes.delete_one({"_id": user["_id"]})
    log.info("email verified for %s", user["email"])
    fresh = await _db.users.find_one({"_id": user["_id"]})
    return {"user": _public(fresh), "verified": True}


@router.post("/auth/resend-code")
async def resend_code(request: Request, user=Depends(current_user)):
    """A new code, with a cooldown so the button cannot be used as a mail cannon."""
    if _verified(user):
        return {"already": True}
    record = await _db.email_codes.find_one({"_id": user["_id"]}) or {}
    sent_at = _aware(record.get("sent_at"))
    if sent_at:
        waited = (_now() - sent_at).total_seconds()
        if waited < VERIFY_RESEND_SECONDS:
            raise HTTPException(
                429, {"code": "cooldown", "seconds": int(VERIFY_RESEND_SECONDS - waited)})
    if (record.get("sends") or 0) >= VERIFY_MAX_SENDS:
        raise HTTPException(429, {"code": "too_many_sends"})
    await _issue_code(user, _lang(request.query_params.get("lang") or record.get("lang")))
    return {"sent": True, "cooldown": VERIFY_RESEND_SECONDS}


class ForgotBody(BaseModel):
    email: EmailStr
    lang: str = "en"


class ResetBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str


def _site_base(request: Request):
    """Where the link in the letter should point.

    PUBLIC_SITE_URL wins when it is set, because a letter outlives the request that made it
    and must land on the real domain. With nothing configured we fall back to the host the
    request came in on, which keeps the flow usable on a preview deployment.
    """
    base = (os.environ.get("PUBLIC_SITE_URL") or "").strip().rstrip("/")
    if base:
        return base
    return _rp(request)[1]


@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotBody, request: Request):
    """Ask for a reset link.

    The answer is ALWAYS the same, whether or not the address exists, is verified or has a
    password: a different reply here is a free tool for working out who has an account.
    A link is only ever sent to an address that has been PROVED - otherwise a reset email
    would go to whoever happens to own an address the account never confirmed.
    """
    email = str(body.email).strip().lower()
    lang = _lang(body.lang)
    user = await _db.users.find_one({"email_norm": email})
    if user and _verified(user):
        now = _now()
        last = await _db.password_resets.find_one({"user_id": user["_id"]},
                                                  sort=[("created_at", -1)])
        recent = await _db.password_resets.count_documents(
            {"user_id": user["_id"], "created_at": {"$gte": now - timedelta(days=1)}})
        waited = (now - _aware(last["created_at"])).total_seconds() if last else None
        if recent >= RESET_MAX_PER_DAY or (waited is not None
                                           and waited < RESET_COOLDOWN_SECONDS):
            log.info("reset link for %s throttled", email)
            return {"sent": True}
        # Any older link stops working the moment a new one is asked for.
        await _db.password_resets.delete_many({"user_id": user["_id"]})
        raw = secrets.token_urlsafe(32)
        await _db.password_resets.insert_one({
            "_id": str(uuid.uuid4()),
            "token_hash": _hash_token(raw),
            "user_id": user["_id"],
            "email": user["email"],
            "lang": lang,
            "created_at": now,
            "expires_at": now + timedelta(minutes=RESET_TTL_MINUTES),
        })
        link = f"{_site_base(request)}/{lang}/reset-password?token={raw}"
        sent = await mailer.send_password_reset(user["email"], link,
                                               user.get("name") or "", lang,
                                               RESET_TTL_MINUTES)
        if not sent:
            log.error("reset link for %s could not be emailed - check RESEND_API_KEY", email)
    else:
        log.info("reset asked for %s: no account, or the address was never confirmed", email)
    return {"sent": True}


@router.post("/auth/reset-password")
async def reset_password(body: ResetBody, request: Request):
    """Spend the link. It works once, and every other session is dropped with it."""
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(400, {"code": "too_short", "min": MIN_PASSWORD})
    record = await _db.password_resets.find_one({"token_hash": _hash_token(body.token.strip())})
    if not record:
        raise HTTPException(400, {"code": "bad_token"})
    if _aware(record.get("expires_at")) and _aware(record["expires_at"]) < _now():
        await _db.password_resets.delete_one({"_id": record["_id"]})
        raise HTTPException(410, {"code": "expired"})
    user = await _db.users.find_one({"_id": record["user_id"]})
    if not user:
        await _db.password_resets.delete_one({"_id": record["_id"]})
        raise HTTPException(400, {"code": "bad_token"})
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"password_hash": ph.hash(body.password)}})
    # Single use, and gone from the database rather than merely flagged.
    await _db.password_resets.delete_many({"user_id": user["_id"]})
    # Whoever knew the old password - or was sitting in a stolen session - is now out.
    gone = await _db.sessions.delete_many({"user_id": user["_id"]})
    log.info("password reset for %s (%s sessions dropped)", user["email"], gone.deleted_count)
    return {"reset": True, "signed_out": gone.deleted_count}


@router.get("/auth/reset-valid")
async def reset_valid(token: str):
    """So the page can say "this link is dead" before the buyer types a new password."""
    record = await _db.password_resets.find_one({"token_hash": _hash_token(token.strip())})
    if not record:
        return {"valid": False}
    if _aware(record.get("expires_at")) and _aware(record["expires_at"]) < _now():
        return {"valid": False}
    return {"valid": True, "email": record.get("email", "")}


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    email = str(body.email).strip().lower()
    user = await _db.users.find_one({"email_norm": email})
    stored = (user or {}).get("password_hash") or _DUMMY_HASH
    try:
        ok = ph.verify(body.password, stored)
    except Exception:
        ok = False
    if not user or not ok:
        raise HTTPException(401, "wrong email or password")
    # With a second factor on, the password alone buys a 10-minute ticket, never a session.
    if (user.get("totp") or {}).get("enabled"):
        pending_id = secrets.token_urlsafe(24)
        await _db.mfa_pending.insert_one({
            "_id": pending_id, "user_id": user["_id"], "attempts": 0,
            "created_at": _now(), "expires_at": _now() + timedelta(minutes=10)})
        return {"mfa_required": True, "pending_id": pending_id}
    await _start_session(response, user["_id"], request)
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}


class ChangePasswordBody(BaseModel):
    current: str = ""
    new: str


@router.post("/auth/password")
async def change_password(body: ChangePasswordBody, request: Request,
                          user=Depends(current_user)):
    """Set a new password, proving the current one first.

    An account created through Google has no password to prove, so it can add one straight
    away - the signed-in session is the proof there. Every OTHER session is dropped
    afterwards: if the reason for the change is that somebody else knew the old password,
    that is what actually puts them out.
    """
    if user.get("password_hash") and not _check_password(user, body.current):
        raise HTTPException(401, "the current password is wrong")
    if len(body.new) < MIN_PASSWORD:
        raise HTTPException(400, f"password must be at least {MIN_PASSWORD} characters")
    if body.current and body.new == body.current:
        raise HTTPException(400, "that is the password you already have")
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"password_hash": ph.hash(body.new)}})
    raw = request.cookies.get(SESSION_COOKIE) or ""
    gone = await _db.sessions.delete_many(
        {"user_id": user["_id"], "token_hash": {"$ne": _hash_token(raw) if raw else ""}})
    return {"changed": True, "signed_out": gone.deleted_count}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        await _db.sessions.delete_one({"token_hash": _hash_token(raw)})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(request: Request):
    user = await _user_from_request(request)
    if not user:
        return {"user": None}
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}


# ── Google sign-in (Emergent-managed OAuth) -----------------------------------
# The buyer is sent to Emergent's hosted Google flow and comes back carrying a one-time
# `session_id` in the URL fragment, which the frontend hands to this endpoint. The exchange
# with Emergent happens HERE, server side, so the provider's token never reaches the
# browser. The account is then given one of OUR OWN sessions — same HttpOnly cookie, same
# "active devices" list, same instant revocation as a password sign-in. Google identifies
# the person; it does not run our sessions.
EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


class GoogleSessionBody(BaseModel):
    session_id: str


async def _emergent_identity(session_id: str):
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        log.warning("google session exchange refused: %s %s", r.status_code, r.text[:200])
        raise HTTPException(401, "that Google sign-in has expired, please try again")
    return r.json()


@router.post("/auth/google/session")
async def google_session(body: GoogleSessionBody, request: Request, response: Response):
    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(400, "missing session id")
    data = await _emergent_identity(session_id)
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "Google did not return an email address")

    user = await _db.users.find_one({"email_norm": email})
    if not user:
        user = {
            "_id": str(uuid.uuid4()),
            "email": email,
            "email_norm": email,
            "name": (data.get("name") or "").strip()[:120],
            # No password_hash: this account signs in through Google. The buyer can still
            # add a passkey afterwards, exactly like any other account.
            "webauthn_user_id": bytes_to_base64url(secrets.token_bytes(32)),
            "favourites": [],
            # Same rule as /auth/register: whoever creates the first account owns the install.
            "is_admin": await _db.users.count_documents({"is_admin": True}) == 0,
            "google_id": data.get("id") or "",
            "picture": data.get("picture") or "",
            "created_at": _now(),
        }
        await _db.users.insert_one(user)
    else:
        # An existing email is the SAME person, so the Google account is linked to it rather
        # than a second account being created.
        patch = {"google_id": data.get("id") or ""}
        if data.get("picture"):
            patch["picture"] = data["picture"]
        if not (user.get("name") or "").strip() and (data.get("name") or "").strip():
            patch["name"] = data["name"].strip()[:120]
        await _db.users.update_one({"_id": user["_id"]}, {"$set": patch})
        user.update(patch)

    # A second factor the owner switched on is still owed: Google proves who they are, it
    # does not replace the code. Same 10-minute ticket the password path issues.
    if (user.get("totp") or {}).get("enabled"):
        pending_id = secrets.token_urlsafe(24)
        await _db.mfa_pending.insert_one({
            "_id": pending_id, "user_id": user["_id"], "attempts": 0,
            "created_at": _now(), "expires_at": _now() + timedelta(minutes=10)})
        return {"mfa_required": True, "pending_id": pending_id}

    await _start_session(response, user["_id"], request)
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}



# ── passkey registration (requires an existing session) -----------------------
@router.post("/auth/passkey/register/options")
async def passkey_register_options(request: Request, user=Depends(current_user)):
    rp_id, _ = _rp(request)
    existing = await _db.webauthn_credentials.find(
        {"user_id": user["_id"]}, {"credential_id": 1}).to_list(50)
    challenge = secrets.token_bytes(32)
    flow_id = secrets.token_urlsafe(24)

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=base64url_to_bytes(user["webauthn_user_id"]),
        user_name=user["email"],
        user_display_name=user.get("name") or user["email"],
        challenge=challenge,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]))
            for c in existing
        ],
        # resident/discoverable key = the authenticator remembers the account, which is
        # what makes one-tap sign-in (no email typed) possible.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    await _db.webauthn_challenges.insert_one({
        "_id": flow_id,
        "user_id": user["_id"],
        "purpose": "registration",
        "challenge": bytes_to_base64url(challenge),
        "expires_at": _now() + timedelta(minutes=CHALLENGE_TTL_MIN),
    })
    return {"flow_id": flow_id, "options": json.loads(options_to_json(options))}


@router.post("/auth/passkey/register/verify")
async def passkey_register_verify(body: CeremonyBody, request: Request,
                                  user=Depends(current_user)):
    rp_id, origin = _rp(request)
    ch = await _db.webauthn_challenges.find_one_and_delete({
        "_id": body.flow_id, "user_id": user["_id"], "purpose": "registration",
        "expires_at": {"$gt": _now()},
    })
    if not ch:
        raise HTTPException(400, "this passkey setup expired, please try again")
    try:
        v = verify_registration_response(
            credential=json.dumps(body.credential),
            expected_challenge=base64url_to_bytes(ch["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=_expected_origins(request, origin),
            require_user_verification=False,
        )
    except Exception as e:
        log.warning("passkey registration rejected: %s", str(e)[:200])
        raise HTTPException(400, "could not register that passkey")

    await _db.webauthn_credentials.insert_one({
        "_id": str(uuid.uuid4()),
        "user_id": user["_id"],
        "credential_id": bytes_to_base64url(v.credential_id),
        "public_key": bytes_to_base64url(v.credential_public_key),
        "sign_count": v.sign_count or 0,
        "device_type": getattr(v, "credential_device_type", None) and
        str(v.credential_device_type),
        "created_at": _now(),
        "last_used_at": None,
    })
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"ok": True, "passkeys": n}


# ── passkey sign-in (one tap, no email) ---------------------------------------
@router.post("/auth/passkey/login/options")
async def passkey_login_options(request: Request):
    rp_id, _ = _rp(request)
    challenge = secrets.token_bytes(32)
    flow_id = secrets.token_urlsafe(24)
    # No allow_credentials: the authenticator offers whatever discoverable passkey it
    # holds for this site, so the user never types an email.
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    await _db.webauthn_challenges.insert_one({
        "_id": flow_id,
        "user_id": None,
        "purpose": "authentication",
        "challenge": bytes_to_base64url(challenge),
        "expires_at": _now() + timedelta(minutes=CHALLENGE_TTL_MIN),
    })
    return {"flow_id": flow_id, "options": json.loads(options_to_json(options))}


@router.post("/auth/passkey/login/verify")
async def passkey_login_verify(body: CeremonyBody, request: Request, response: Response):
    rp_id, origin = _rp(request)
    ch = await _db.webauthn_challenges.find_one_and_delete({
        "_id": body.flow_id, "purpose": "authentication", "expires_at": {"$gt": _now()},
    })
    if not ch:
        raise HTTPException(400, "this sign-in attempt expired, please try again")

    raw_id = body.credential.get("rawId") or body.credential.get("id")
    cred = await _db.webauthn_credentials.find_one({"credential_id": raw_id})
    if not cred:
        raise HTTPException(401, "that passkey is not registered here")

    try:
        v = verify_authentication_response(
            credential=json.dumps(body.credential),
            expected_challenge=base64url_to_bytes(ch["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=_expected_origins(request, origin),
            credential_public_key=base64url_to_bytes(cred["public_key"]),
            credential_current_sign_count=cred.get("sign_count") or 0,
            require_user_verification=False,
        )
    except Exception as e:
        log.warning("passkey assertion rejected: %s", str(e)[:200])
        raise HTTPException(401, "passkey sign-in failed")

    await _db.webauthn_credentials.update_one(
        {"_id": cred["_id"]},
        {"$set": {"sign_count": v.new_sign_count, "last_used_at": _now()}})

    user = await _db.users.find_one({"_id": cred["user_id"]})
    if not user:
        raise HTTPException(401, "the account for that passkey no longer exists")
    # A passkey is already a stronger factor than a six-digit code, so it is not asked for.
    await _start_session(response, user["_id"], request)
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}


@router.get("/auth/passkeys")
async def list_passkeys(user=Depends(current_user)):
    rows = await _db.webauthn_credentials.find(
        {"user_id": user["_id"]},
        {"created_at": 1, "last_used_at": 1, "device_type": 1}).to_list(50)
    return {"passkeys": [{"id": r["_id"], "created_at": r.get("created_at"),
                          "last_used_at": r.get("last_used_at"),
                          "device_type": r.get("device_type")} for r in rows]}


@router.delete("/auth/passkeys/{passkey_id}")
async def delete_passkey(passkey_id: str, user=Depends(current_user)):
    if not user.get("password_hash"):
        n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
        if n <= 1:
            raise HTTPException(
                400, "set a password first - this is your only way to sign in")
    r = await _db.webauthn_credentials.delete_one(
        {"_id": passkey_id, "user_id": user["_id"]})
    if not r.deleted_count:
        raise HTTPException(404, "passkey not found")
    return {"ok": True}


# ── favourites, synced to the account ----------------------------------------
class TasteIn(BaseModel):
    """The interest profile a browser has built up. Small, and never trusted blindly."""
    makes: dict[str, float] = {}
    models: dict[str, float] = {}
    fuels: dict[str, float] = {}
    samples: list[list[float]] = []
    events: int = 0
    consent: str = ""
    # The full decision, so we can show WHAT was agreed and WHEN (ePrivacy/GDPR proof of
    # consent): {"v": policy version, "ts": ISO timestamp, "cats": {category: bool}}.
    consent_record: dict = {}


@router.post("/auth/taste")
async def put_taste(body: TasteIn, user=Depends(current_user)):
    """Mirror the browser's profile onto the account.

    Kept so recommendations follow the buyer between devices and so the operator can see
    what each customer is actually shopping for. Capped on the way in.
    """
    taste = {
        "makes": dict(list(body.makes.items())[:8]),
        "models": dict(list(body.models.items())[:8]),
        "fuels": dict(list(body.fuels.items())[:6]),
        "samples": [[float(x) for x in row[:3]] for row in body.samples[:12]
                    if isinstance(row, list) and row],
        "events": min(int(body.events or 0), 100000),
        "updated_at": _now(),
    }
    update = {"taste": taste}
    if body.consent:
        update["consent"] = str(body.consent)[:64]
    rec = body.consent_record or {}
    if isinstance(rec.get("cats"), dict):
        # Stored as sent by the browser, plus the moment WE saw it, so the record cannot be
        # backdated by a client.
        update["consent_record"] = {
            "v": str(rec.get("v") or "")[:32],
            "ts": str(rec.get("ts") or "")[:40],
            "cats": {str(k)[:32]: bool(v) for k, v in list(rec["cats"].items())[:10]},
            "recorded_at": _now(),
        }
    await _db.users.update_one({"_id": user["_id"]}, {"$set": update})
    return {"saved": True}


@router.get("/auth/favourites")
async def get_favourites(user=Depends(current_user)):
    return {"ids": user.get("favourites") or []}


@router.put("/auth/favourites")
async def put_favourites(body: FavouritesBody, user=Depends(current_user)):
    """Whole-list replace. The client owns the list; this is just durable storage so it
    follows the user between devices."""
    ids = list(dict.fromkeys(body.ids))[:2000]
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"favourites": ids, "favourites_at": _now()}})
    return {"ids": ids}


@router.post("/auth/favourites/merge")
async def merge_favourites(body: FavouritesBody, user=Depends(current_user)):
    """Called right after sign-in: whatever the browser saved while logged out is folded
    into the account rather than being thrown away."""
    merged = list(dict.fromkeys((user.get("favourites") or []) + body.ids))[:2000]
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"favourites": merged, "favourites_at": _now()}})
    return {"ids": merged}


# ── saved searches, synced to the account -------------------------------------
_SEARCH_KEYS = ("id", "name", "query", "seen_total", "alerts", "created_at", "lang")


def _clean_searches(items):
    out, seen = [], set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        sid, query = str(raw.get("id") or "")[:64], str(raw.get("query") or "")[:2000]
        if not sid or sid in seen:
            continue
        seen.add(sid)
        item = {k: raw.get(k) for k in _SEARCH_KEYS if k in raw}
        item["id"], item["query"] = sid, query
        item["name"] = str(raw.get("name") or "")[:120]
        item["alerts"] = bool(raw.get("alerts"))
        # The language the search was saved in, so the alert email speaks it.
        item["lang"] = str(raw.get("lang") or "")[:2].lower() or "en"
        out.append(item)
    return out[:60]


@router.get("/auth/saved-searches")
async def get_saved_searches(user=Depends(current_user)):
    return {"items": user.get("saved_searches") or []}


@router.put("/auth/saved-searches")
async def put_saved_searches(body: SavedSearchesBody, user=Depends(current_user)):
    items = _clean_searches(body.items)
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"saved_searches": items, "searches_at": _now()}})
    return {"items": items}


@router.post("/auth/saved-searches/merge")
async def merge_saved_searches(body: SavedSearchesBody, user=Depends(current_user)):
    """Sign-in: fold in whatever was saved while logged out, newest first, no duplicates."""
    stored = user.get("saved_searches") or []
    by_query = {s.get("query"): s for s in stored}
    incoming = [s for s in _clean_searches(body.items) if s["query"] not in by_query]
    items = _clean_searches(incoming + stored)
    await _db.users.update_one({"_id": user["_id"]},
                               {"$set": {"saved_searches": items, "searches_at": _now()}})
    return {"items": items}


# ── active sessions -----------------------------------------------------------
def _session_out(row, current_hash):
    return {
        "id": row["_id"],
        "label": row.get("label") or twofa.device(row.get("user_agent"))["label"],
        "browser": row.get("browser") or "",
        "os": row.get("os") or "",
        "ip": row.get("ip") or "",
        "created_at": row.get("created_at"),
        "last_seen": row.get("last_seen") or row.get("created_at"),
        "current": row.get("token_hash") == current_hash,
    }


@router.get("/auth/sessions")
async def list_sessions(request: Request, user=Depends(current_user)):
    """Every device currently signed in to this account, most recently active first."""
    raw = request.cookies.get(SESSION_COOKIE) or ""
    current = _hash_token(raw) if raw else ""
    rows = await _db.sessions.find(
        {"user_id": user["_id"], "expires_at": {"$gt": _now()}}
    ).sort("last_seen", -1).to_list(100)
    return {"items": [_session_out(r, current) for r in rows]}


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request, user=Depends(current_user)):
    raw = request.cookies.get(SESSION_COOKIE) or ""
    row = await _db.sessions.find_one({"_id": session_id, "user_id": user["_id"]})
    if not row:
        raise HTTPException(404, "that device is not signed in")
    if raw and row.get("token_hash") == _hash_token(raw):
        raise HTTPException(400, "use sign out for this device")
    await _db.sessions.delete_one({"_id": session_id, "user_id": user["_id"]})
    return {"ok": True}


@router.post("/auth/sessions/revoke-others")
async def revoke_other_sessions(request: Request, user=Depends(current_user)):
    """Sign out everywhere else, keeping the device asking. Deleting the record IS the
    revocation here: sessions are looked up by token hash on every request."""
    raw = request.cookies.get(SESSION_COOKIE) or ""
    result = await _db.sessions.delete_many(
        {"user_id": user["_id"], "token_hash": {"$ne": _hash_token(raw) if raw else ""}})
    return {"signed_out": result.deleted_count}


# ── two-factor authentication -------------------------------------------------
class CodeBody(BaseModel):
    code: str = ""


class MfaLoginBody(BaseModel):
    pending_id: str
    code: str
    recovery: bool = False


class PasswordBody(BaseModel):
    password: str


def _check_password(user, password):
    try:
        return bool(ph.verify(password, user.get("password_hash") or _DUMMY_HASH))
    except Exception:
        return False


@router.post("/auth/2fa/setup")
async def twofa_setup(user=Depends(current_user)):
    """A secret and its QR, held server-side until a real code proves the app has it."""
    if (user.get("totp") or {}).get("enabled"):
        raise HTTPException(409, "two-factor authentication is already on")
    secret = twofa.new_secret()
    await _db.totp_setup.replace_one(
        {"_id": user["_id"]},
        {"_id": user["_id"], "secret": twofa.encrypt(secret), "created_at": _now()},
        upsert=True)
    uri = twofa.provisioning_uri(secret, user["email"])
    return {"otpauth_uri": uri, "qr_data_url": twofa.qr_data_url(uri),
            "manual_key": secret}


@router.post("/auth/2fa/enable")
async def twofa_enable(body: CodeBody, user=Depends(current_user)):
    pending = await _db.totp_setup.find_one({"_id": user["_id"]})
    if not pending or (_now() - pending["created_at"].replace(tzinfo=timezone.utc)
                       ).total_seconds() > 900:
        raise HTTPException(400, "that setup expired, please start again")
    secret = twofa.decrypt(pending["secret"])
    if not twofa.valid_code(secret, body.code):
        raise HTTPException(400, "that code is not right")
    plain, stored = twofa.new_recovery_codes()
    await _db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"totp": {"enabled": True, "secret": pending["secret"],
                           "last_counter": twofa.counter(secret), "enabled_at": _now()},
                  "recovery_codes": stored}})
    await _db.totp_setup.delete_one({"_id": user["_id"]})
    # The only time these are ever readable.
    return {"enabled": True, "recovery_codes": plain}


@router.post("/auth/2fa/disable")
async def twofa_disable(body: PasswordBody, user=Depends(current_user)):
    if not _check_password(user, body.password):
        raise HTTPException(401, "wrong password")
    await _db.users.update_one({"_id": user["_id"]},
                              {"$unset": {"totp": "", "recovery_codes": ""}})
    return {"enabled": False}


@router.post("/auth/2fa/recovery-codes")
async def twofa_new_recovery_codes(body: PasswordBody, user=Depends(current_user)):
    if not (user.get("totp") or {}).get("enabled"):
        raise HTTPException(400, "two-factor authentication is off")
    if not _check_password(user, body.password):
        raise HTTPException(401, "wrong password")
    plain, stored = twofa.new_recovery_codes()
    await _db.users.update_one({"_id": user["_id"]},
                              {"$set": {"recovery_codes": stored}})
    return {"recovery_codes": plain}


@router.post("/auth/2fa/login")
async def twofa_login(body: MfaLoginBody, request: Request, response: Response):
    """Second step of a password sign-in: a code from the app, or a recovery code."""
    pending = await _db.mfa_pending.find_one({"_id": body.pending_id})
    if not pending or pending["expires_at"].replace(tzinfo=timezone.utc) < _now():
        raise HTTPException(401, "that sign-in expired, please start again")
    if pending.get("attempts", 0) >= 6:
        await _db.mfa_pending.delete_one({"_id": pending["_id"]})
        raise HTTPException(429, "too many attempts, please sign in again")
    await _db.mfa_pending.update_one({"_id": pending["_id"]}, {"$inc": {"attempts": 1}})

    user = await _db.users.find_one({"_id": pending["user_id"]})
    totp = (user or {}).get("totp") or {}
    ok = False
    if not user:
        raise HTTPException(401, "that sign-in expired, please start again")

    if body.recovery:
        index = twofa.match_recovery(body.code, user.get("recovery_codes"))
        if index is not None:
            # Consumed atomically, so the same code cannot be spent twice in parallel.
            spent = await _db.users.update_one(
                {"_id": user["_id"], f"recovery_codes.{index}.used": False},
                {"$set": {f"recovery_codes.{index}.used": True,
                          f"recovery_codes.{index}.used_at": _now()}})
            ok = spent.modified_count == 1
    elif totp.get("enabled"):
        secret = twofa.decrypt(totp["secret"])
        if twofa.valid_code(secret, body.code):
            # A code is good for its 30-second window ONCE.
            now_counter = twofa.counter(secret)
            if totp.get("last_counter") != now_counter:
                await _db.users.update_one({"_id": user["_id"]},
                                          {"$set": {"totp.last_counter": now_counter}})
                ok = True

    if not ok:
        raise HTTPException(401, "that code is not right")
    await _db.mfa_pending.delete_one({"_id": pending["_id"]})
    await _start_session(response, user["_id"], request)
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}
