"""Notifications, contact phone and the right to be forgotten.

Push and email both answer to the SAME per-event switches, so a buyer who turns off "price
drop" stops hearing about price drops everywhere. Nothing is sent to a channel the buyer has
not switched on: the defaults below are what a new account gets, and every one of them is
something they asked for by registering (a car they saved, a search they built, a shipment
they own).

Delivery is a courtesy, never a guarantee: a dead push endpoint is pruned on the spot (404 or
410 from the push service), and a failed email is logged rather than retried into a loop.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush

import auth
import phones

log = logging.getLogger("notify")
router = APIRouter()

EVENTS = ("saved_search", "price_drop", "shipment", "enquiry", "deposit")
DEFAULTS = {
    "email": {"enabled": True, **{e: True for e in EVENTS}},
    "push": {"enabled": False, **{e: True for e in EVENTS}},
}
# The operator's own alerts. A buyer never has these switched on because a buyer never has a
# subscription for them: they are only ever sent to accounts with is_admin.
ADMIN_EVENTS = ("enquiry", "deposit")

_db = None


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


def prefs_of(user):
    """Stored preferences layered over the defaults, so a new switch is never missing."""
    stored = user.get("notify") or {}
    out = {}
    for channel, defaults in DEFAULTS.items():
        saved = stored.get(channel) or {}
        out[channel] = {key: bool(saved.get(key, value)) for key, value in defaults.items()}
    return out


def wants(user, channel, event):
    channel_prefs = prefs_of(user).get(channel) or {}
    return bool(channel_prefs.get("enabled") and channel_prefs.get(event, True))


class ChannelPrefs(BaseModel):
    enabled: bool = False
    saved_search: bool = True
    price_drop: bool = True
    shipment: bool = True
    enquiry: bool = True
    deposit: bool = True


class PrefsBody(BaseModel):
    email: ChannelPrefs
    push: ChannelPrefs


class PhoneBody(BaseModel):
    phone: str = Field(default="", max_length=32)
    lang: str = Field(default="", max_length=5)


class SubscriptionBody(BaseModel):
    endpoint: str = Field(min_length=12, max_length=1000)
    keys: dict = {}


class TestBody(BaseModel):
    pass


class DeleteAccountBody(BaseModel):
    password: str
    confirm: str


@router.get("/notifications")
async def get_prefs(user=Depends(auth.current_user)):
    devices = await _db.push_subscriptions.count_documents({"user_id": user["_id"]})
    return {"prefs": prefs_of(user), "phone": user.get("phone") or "",
            "devices": devices, "events": list(EVENTS)}


@router.put("/notifications")
async def put_prefs(body: PrefsBody, user=Depends(auth.current_user)):
    prefs = {"email": body.email.model_dump(), "push": body.push.model_dump()}
    await _db.users.update_one({"_id": user["_id"]},
                              {"$set": {"notify": prefs, "notify_at": _now()}})
    return {"prefs": prefs}


@router.put("/phone")
async def put_phone(body: PhoneBody, user=Depends(auth.current_user)):
    """Kept for billing and for reaching a buyer about a deal already struck. Nothing else."""
    raw = " ".join(body.phone.split())[:32]
    # Stored in E.164, so the office can dial it without guessing the country. Clearing the
    # field is allowed; a number that cannot be dialled is not.
    phone = phones.clean(raw, body.lang)
    if raw and not phone:
        raise HTTPException(400, "that does not look like a phone number we can dial")
    await _db.users.update_one({"_id": user["_id"]}, {"$set": {"phone": phone}})
    return {"phone": phone}


# ── web push ─────────────────────────────────────────────────────────────────
@router.get("/push/key")
async def push_key():
    """The PUBLIC half of the VAPID pair. The private half never leaves this process."""
    return {"key": os.environ.get("VAPID_PUBLIC_KEY", "")}


@router.post("/push/subscribe")
async def push_subscribe(body: SubscriptionBody, request: Request,
                         user=Depends(auth.current_user)):
    keys = body.keys or {}
    if not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(400, "that subscription is incomplete")
    # One record per endpoint: a browser that re-subscribes must not multiply.
    await _db.push_subscriptions.update_one(
        {"_id": body.endpoint},
        {"$set": {"user_id": user["_id"], "keys": keys,
                  "user_agent": request.headers.get("user-agent", "")[:300],
                  "updated_at": _now()},
         "$setOnInsert": {"created_at": _now()}},
        upsert=True)
    prefs = prefs_of(user)
    if not prefs["push"]["enabled"]:
        prefs["push"]["enabled"] = True
        await _db.users.update_one({"_id": user["_id"]}, {"$set": {"notify": prefs}})
    return {"ok": True, "prefs": prefs}


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: SubscriptionBody, user=Depends(auth.current_user)):
    await _db.push_subscriptions.delete_one({"_id": body.endpoint,
                                            "user_id": user["_id"]})
    left = await _db.push_subscriptions.count_documents({"user_id": user["_id"]})
    if not left:
        prefs = prefs_of(user)
        prefs["push"]["enabled"] = False
        await _db.users.update_one({"_id": user["_id"]}, {"$set": {"notify": prefs}})
    return {"ok": True, "devices": left}


def _send_one(subscription, payload):
    """Synchronous by nature; always called through a thread so the loop keeps serving."""
    webpush(
        subscription_info={"endpoint": subscription["_id"], "keys": subscription["keys"]},
        data=json.dumps(payload),
        vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
        # Recreated per call: pywebpush mutates the claims it is handed.
        vapid_claims={"sub": os.environ["VAPID_SUBJECT"]},
        ttl=60 * 60,
        timeout=10,
    )


async def push_to_user(user_id, title, body, url="/", event=None):
    """Push to every device of one buyer. Returns how many were delivered."""
    user = await _db.users.find_one({"_id": user_id})
    if not user:
        return 0
    if event and not wants(user, "push", event):
        return 0

    payload = {"title": title, "body": body, "url": url}
    sent = 0
    async for subscription in _db.push_subscriptions.find({"user_id": user_id}):
        try:
            await asyncio.to_thread(_send_one, subscription, payload)
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                # The browser threw the subscription away; so do we.
                await _db.push_subscriptions.delete_one({"_id": subscription["_id"]})
            else:
                log.warning("push failed (%s): %s", status, str(e)[:160])
        except Exception as e:                       # noqa: BLE001
            log.warning("push error: %s", str(e)[:160])
    return sent


async def push_to_admins(title, body, url="/", event=None):
    """Tell the operators something happened on the shop floor.

    Enquiries and deposits were invisible until someone opened the admin panel: a buyer who
    just put money on hold could sit there for a day. Every admin account is reached, each on
    its own devices, and each can still switch the event off for itself.
    """
    admins = await _db.users.find({"is_admin": True}, {"_id": 1}).to_list(50)
    sent = 0
    for admin in admins:
        sent += await push_to_user(admin["_id"], title, body, url, event)
    if not sent:
        log.info("no admin device could be reached for %s", event or "notice")
    return sent


def push_to_admins_later(title, body, url="/", event=None):
    """Fire and forget: an operator's alert must never slow down or fail a buyer's request."""
    async def job():
        try:
            await push_to_admins(title, body, url, event)
        except Exception as e:                        # noqa: BLE001
            log.warning("admin push failed: %s", str(e)[:160])

    try:
        asyncio.get_running_loop().create_task(job())
    except RuntimeError:
        pass


@router.post("/push/test")
async def push_test(body: TestBody, user=Depends(auth.current_user)):
    sent = await push_to_user(user["_id"], "Encar",
                              "Push notifications are working on this device.", "/")
    if not sent:
        raise HTTPException(400, "no device could be reached — try turning push on again")
    return {"sent": sent}


# ── GDPR erasure ─────────────────────────────────────────────────────────────
@router.get("/account/export")
async def export_account(user=Depends(auth.current_user)):
    """Everything we hold about this person, in one machine-readable file.

    GDPR Art. 15 (access) and Art. 20 (portability) in one download. Secrets are the ONE thing
    left out: the password hash, the TOTP seed, recovery-code hashes and public keys are
    credentials, not personal data the buyer needs a copy of, and handing them over would only
    make an exported file worth stealing.
    """
    uid = user["_id"]
    secrets_out = ("password_hash", "totp", "recovery_codes", "webauthn_user_id")
    account = {k: v for k, v in user.items() if k not in secrets_out}
    account["id"] = account.pop("_id", uid)

    async def rows(collection, query, drop=()):
        out = []
        async for doc in _db[collection].find(query):
            doc["id"] = doc.pop("_id", None)
            for k in drop:
                doc.pop(k, None)
            out.append(doc)
        return out

    return {
        "generated_at": datetime.now(timezone.utc),
        "about": "Every record held about your account. Ask us at any time for an explanation "
                 "of a field: see the privacy policy for what each one is used for.",
        "account": account,
        "deposits": await rows("deposits", {"user_id": uid}),
        "enquiries": await rows("enquiries", {"$or": [{"user_id": uid},
                                                     {"email": user.get("email")}]}),
        "shipments": await rows("shipments", {"user_id": uid}),
        # The token hash is what makes a session usable; the device details are the useful part.
        "sessions": await rows("sessions", {"user_id": uid}, drop=("token_hash",)),
        "push_devices": await rows("push_subscriptions", {"user_id": uid},
                                   drop=("subscription",)),
        "price_alerts": await rows("price_watch", {"user_id": uid}),
        "saved_search_alerts": await rows("search_watch", {"user_id": uid}),
    }


@router.delete("/account")
async def delete_account(body: DeleteAccountBody, request: Request, response: Response,
                         user=Depends(auth.current_user)):
    """Erase the account and everything personal attached to it.

    Deposits are kept, with the buyer detached: they are accounting records of money that
    actually moved, and a paid deposit still belongs in the books after the person is gone.
    """
    if body.confirm.strip().upper() not in ("ИЗТРИЙ", "DELETE", "STERGE", "ȘTERGE"):
        raise HTTPException(400, "type the confirmation word to continue")
    # pwdlib RETURNS False on a mismatch rather than raising, so the result must be checked.
    # Trusting the absence of an exception here meant a wrong password still erased the
    # account — the one place where that is least forgivable.
    try:
        ok = bool(auth.ph.verify(body.password,
                                 user.get("password_hash") or auth._DUMMY_HASH))
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(401, "wrong password")

    uid = user["_id"]
    for collection, key in (("sessions", "user_id"), ("push_subscriptions", "user_id"),
                            ("webauthn_credentials", "user_id"), ("enquiries", "user_id"),
                            ("saved_searches", "user_id"), ("favourites", "user_id")):
        await _db[collection].delete_many({key: uid})
    await _db.deposits.update_many({"user_id": uid},
                                   {"$set": {"user_id": None, "email": "deleted"}})
    await _db.shipments.update_many({"user_id": uid}, {"$set": {"user_id": None}})
    await _db.users.delete_one({"_id": uid})
    # The session rows are already gone, so the cookie is inert — but leaving it in the
    # browser means the next visit looks signed in until a request comes back.
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"deleted": True}
