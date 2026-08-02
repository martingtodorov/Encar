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


async def _start_session(response: Response, user_id: str):
    raw = secrets.token_urlsafe(32)
    await _db.sessions.insert_one({
        "_id": str(uuid.uuid4()),
        "token_hash": _hash_token(raw),
        "user_id": user_id,
        "created_at": _now(),
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
        "created_at": user.get("created_at"),
    }


# ── payloads ------------------------------------------------------------------
class Credentials(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


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
async def register(body: Credentials, response: Response):
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
        "created_at": _now(),
    }
    if await _db.users.find_one({"email_norm": email}):
        raise HTTPException(409, "that email is already registered")
    # The first account (or the first one created while no administrator exists) owns
    # the install, so the admin pricing page is reachable without a default password.
    user["is_admin"] = await _db.users.count_documents({"is_admin": True}) == 0
    try:
        await _db.users.insert_one(user)
    except Exception:
        raise HTTPException(409, "that email is already registered")
    await _start_session(response, user["_id"])
    return {"user": _public(user)}


@router.post("/auth/login")
async def login(body: LoginBody, response: Response):
    email = str(body.email).strip().lower()
    user = await _db.users.find_one({"email_norm": email})
    stored = (user or {}).get("password_hash") or _DUMMY_HASH
    try:
        ok = ph.verify(body.password, stored)
    except Exception:
        ok = False
    if not user or not ok:
        raise HTTPException(401, "wrong email or password")
    await _start_session(response, user["_id"])
    n = await _db.webauthn_credentials.count_documents({"user_id": user["_id"]})
    return {"user": _public(user, n)}


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
    await _start_session(response, user["_id"])
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
_SEARCH_KEYS = ("id", "name", "query", "seen_total", "alerts", "created_at")


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
