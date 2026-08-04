"""Reservation deposits: a buyer holds a car so it stops being shopped around.

The amount is 10% of the car's published EUR price with no floor, and it is computed
HERE, never accepted from the browser. Stripe Checkout takes the payment; the card is kept
with the buyer's Stripe customer (`setup_future_usage`) so a second deposit does not need
the card typed again.

Payment is confirmed server-side: the webhook flips the record, and the buyer's polling
route asks Stripe directly while the record is still pending, so a webhook that never
arrives cannot leave a paid deposit looking unpaid.
"""
import logging
import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import archive
import auth

log = logging.getLogger("deposits")
router = APIRouter()

DEPOSIT_RATE = float(os.environ.get("DEPOSIT_RATE", "0.10"))
# No floor: the deposit is purely proportional to the car.
DEPOSIT_MIN_EUR = float(os.environ.get("DEPOSIT_MIN_EUR", "0"))

_db = None


def set_db(db):
    global _db
    _db = db
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")


def _now():
    return datetime.now(timezone.utc)


def amount_for(price_eur):
    """10% of the car, to the cent. DEPOSIT_MIN_EUR is 0, so there is no floor."""
    return round(max(DEPOSIT_MIN_EUR, (float(price_eur or 0) * DEPOSIT_RATE)), 2)


class CheckoutBody(BaseModel):
    car_id: str
    origin_url: str


async def _car(car_id):
    car = await _db.listings.find_one({"_id": str(car_id)[:40]})
    if not car:
        raise HTTPException(404, "that car is not in the catalogue")
    return car


def _title(car):
    return " ".join(str(x) for x in [car.get("manufacturer_t") or car.get("manufacturer"),
                                     car.get("model_t") or car.get("model")] if x)


@router.get("/deposit/car/{car_id}")
async def deposit_quote(car_id: str, request: Request):
    """What a deposit on this car costs, and whether somebody already holds it."""
    car = await _car(car_id)
    user = await auth.optional_user(request)
    paid = await _db.deposits.find_one({"car_id": car["_id"], "payment_status": "paid"})
    return {
        "configured": bool(stripe.api_key),
        "car_id": car["_id"],
        "price_eur": car.get("sale_eur") or 0,
        "amount_eur": amount_for(car.get("sale_eur")),
        "rate": DEPOSIT_RATE,
        "minimum_eur": DEPOSIT_MIN_EUR,
        "reserved": bool(paid),
        "mine": bool(paid and user and paid.get("user_id") == user["_id"]),
    }


@router.post("/deposit/checkout")
async def deposit_checkout(body: CheckoutBody, user=Depends(auth.current_user)):
    if not stripe.api_key:
        raise HTTPException(503, "card payments are not connected yet")
    car = await _car(body.car_id)
    held = await _db.deposits.find_one({"car_id": car["_id"], "payment_status": "paid"})
    if held and held.get("user_id") != user["_id"]:
        raise HTTPException(409, "another buyer already holds this car")

    amount = amount_for(car.get("sale_eur"))
    origin = body.origin_url.rstrip("/")
    kwargs = dict(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": int(round(amount * 100)),
                "product_data": {"name": f"Reservation deposit — {_title(car)}"},
            },
            "quantity": 1,
        }],
        customer_email=user["email"],
        # Keeps the card on file, so the next deposit is one tap.
        payment_intent_data={"setup_future_usage": "off_session"},
        success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/payment/cancel",
        metadata={"kind": "car_deposit", "car_id": car["_id"], "user_id": user["_id"]},
    )
    try:
        session = stripe.checkout.Session.create(
            **kwargs, automatic_tax={"enabled": True},
            billing_address_collection="required")
    except stripe.error.StripeError as e:
        # Tax calculation needs an origin address on the account; a deposit must still be
        # payable before that is filled in.
        log.warning("automatic tax unavailable, falling back: %s", str(e)[:200])
        session = stripe.checkout.Session.create(**kwargs)

    await _db.deposits.insert_one({
        "session_id": session.id,
        "car_id": car["_id"],
        "car_title": _title(car),
        "user_id": user["_id"],
        "email": user["email"],
        "amount": amount,
        "currency": "eur",
        "car_price_eur": car.get("sale_eur") or 0,
        "status": "initiated",
        "payment_status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"checkout_url": session.url, "session_id": session.id, "amount_eur": amount}


async def _mark_paid(session_id, payment_intent="", payment_status="paid"):
    """Idempotent: the webhook and the buyer's poll race, and whichever lands first wins."""
    result = await _db.deposits.update_one(
        {"session_id": session_id, "payment_status": {"$ne": "paid"}},
        {"$set": {"status": "completed", "payment_status": payment_status,
                  "stripe_payment_intent_id": payment_intent, "updated_at": _now()}})
    if result.modified_count:
        record = await _db.deposits.find_one({"session_id": session_id})
        if record:
            await _db.listings.update_one(
                {"_id": record["car_id"]},
                {"$set": {"reserved": True, "reserved_by": record["user_id"],
                          "reserved_at": _now()}})
            # The buyer now owns a claim on this car, so the ad becomes ours to keep: the
            # listing and every photo are copied to our disk before Encar can withdraw it.
            archive.archive_later(_db, record["car_id"])


@router.get("/deposit/status/{session_id}")
async def deposit_status(session_id: str):
    record = await _db.deposits.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "no such payment")
    if record.get("payment_status") != "paid":
        try:
            s = stripe.checkout.Session.retrieve(session_id)
            if s.payment_status == "paid" or s.status == "complete":
                await _mark_paid(session_id, s.payment_intent or "")
                record = await _db.deposits.find_one({"session_id": session_id})
        except stripe.error.StripeError:
            pass
    return {"session_id": record["session_id"], "status": record["status"],
            "payment_status": record["payment_status"], "amount_eur": record["amount"],
            "car_id": record["car_id"], "car_title": record.get("car_title") or ""}


@router.get("/deposit/mine")
async def my_deposits(user=Depends(auth.current_user)):
    rows = await _db.deposits.find(
        {"user_id": user["_id"], "payment_status": "paid"},
        {"_id": 0, "session_id": 1, "car_id": 1, "car_title": 1, "amount": 1,
         "created_at": 1}).sort("created_at", -1).to_list(50)
    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return {"items": rows}


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, request.headers.get("stripe-signature", ""), secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "invalid signature")
    obj, kind = event["data"]["object"], event["type"]
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        await _mark_paid(obj["id"], obj.get("payment_intent") or "",
                         obj.get("payment_status") or "paid")
    elif kind in ("checkout.session.async_payment_failed", "checkout.session.expired"):
        await _db.deposits.update_one(
            {"session_id": obj["id"]},
            {"$set": {"status": "failed" if "failed" in kind else "expired",
                      "payment_status": "failed" if "failed" in kind else "expired",
                      "updated_at": _now()}})
    elif kind == "charge.refunded":
        record = await _db.deposits.find_one(
            {"stripe_payment_intent_id": obj.get("payment_intent")})
        if record:
            await _db.deposits.update_one(
                {"session_id": record["session_id"]},
                {"$set": {"status": "refunded", "payment_status": "refunded",
                          "updated_at": _now()}})
            await _db.listings.update_one(
                {"_id": record["car_id"]},
                {"$unset": {"reserved": "", "reserved_by": "", "reserved_at": ""}})
    return {"status": "ok"}
