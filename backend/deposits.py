"""Reservation deposits: a buyer holds a car so it stops being shopped around.

The money is only ever HELD, never taken at checkout. Stripe authorises the amount
(`capture_method="manual"`), the car is reserved on that authorisation alone, and the
operator later captures whatever the deal actually needs — in EUR 100 steps — from the
admin panel. Anything not captured is released by Stripe automatically.

A card authorisation lives for AUTH_DAYS (7) days and then the card network releases it.
So an authorisation that nobody captured is not left dangling: `sweep_expired` cancels it
and puts the car back on the market, and Stripe's own `payment_intent.canceled` does the
same two writes when it expires on their side first.

The amount is 10% of the car's published EUR price with no floor, and it is computed HERE,
never accepted from the browser. The card is kept with the buyer's Stripe customer
(`setup_future_usage`) so a second deposit does not need the card typed again.

State is confirmed server-side: the webhook flips the record, and the buyer's polling route
asks Stripe directly while the record is still pending, so a webhook that never arrives
cannot leave a held car looking unpaid.

`payment_status` values: pending → authorised → captured | released | expired.
"paid" belongs to the older immediate-charge deposits and is still honoured everywhere a
held car matters, so records taken before this change keep working.
"""
import logging
import asyncio
import os
from datetime import datetime, timedelta, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import archive
import auth
import translate
import mailer

log = logging.getLogger("deposits")
router = APIRouter()

DEPOSIT_RATE = float(os.environ.get("DEPOSIT_RATE", "0.10"))
# No floor: the deposit is purely proportional to the car.
DEPOSIT_MIN_EUR = float(os.environ.get("DEPOSIT_MIN_EUR", "0"))
# The deposit is not a holding fee - we buy the car with it. It is returned once the buyer
# wires the balance, less this commission, which is what the business earns on the deal.
COMMISSION_EUR = float(os.environ.get("DEPOSIT_COMMISSION_EUR", "300"))
# A card authorisation is released by the network after this long. It is Stripe's documented
# window for cards, not a preference of ours, which is why it is not configurable.
AUTH_DAYS = 7
# The operator captures in round hundreds; a stray cent in a capture box is a typo waiting
# to happen.
CAPTURE_STEP_EUR = 100
# A car is off the market while the deposit is in any of these states. "paid" is the older
# immediate-charge flow: those deposits still hold their car.
HELD_STATES = ("authorised", "captured", "paid")

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


async def _english_title(car):
    """The same title, but never in Korean.

    `_car` reads the listing straight from Mongo, where make and model are still Korean —
    the `_t` variants are attached by the translation layer on the way to a page, which a
    Stripe line item never passes through. So a buyer saw "푸조 5008 2세대" on the payment
    page and on their card receipt. Resolved synchronously (make and model are cached
    permanently, so this costs one provider call per model ever) and never allowed to
    break a checkout.
    """
    try:
        await translate.translate_listings(_db, [car], "en",
                                          fields=("manufacturer", "model"),
                                          background=False)
    except Exception as e:                          # noqa: BLE001 - a name is not worth a 500
        log.warning("could not translate %s for Stripe: %s", car.get("_id"), str(e)[:140])
    return _title(car)


@router.get("/deposit/car/{car_id}")
async def deposit_quote(car_id: str, request: Request):
    """What a deposit on this car costs, and whether somebody already holds it."""
    car = await _car(car_id)
    user = await auth.optional_user(request)
    paid = await _db.deposits.find_one({"car_id": car["_id"],
                                        "payment_status": {"$in": list(HELD_STATES)}})
    return {
        "configured": bool(stripe.api_key),
        "car_id": car["_id"],
        "price_eur": car.get("sale_eur") or 0,
        "amount_eur": amount_for(car.get("sale_eur")),
        "rate": DEPOSIT_RATE,
        "minimum_eur": DEPOSIT_MIN_EUR,
        "commission_eur": COMMISSION_EUR,
        "hold_days": AUTH_DAYS,
        "reserved": bool(paid),
        "mine": bool(paid and user and paid.get("user_id") == user["_id"]),
    }


@router.post("/deposit/checkout")
async def deposit_checkout(body: CheckoutBody, user=Depends(auth.current_user)):
    if not stripe.api_key:
        raise HTTPException(503, "card payments are not connected yet")
    car = await _car(body.car_id)
    held = await _db.deposits.find_one({"car_id": car["_id"],
                                        "payment_status": {"$in": list(HELD_STATES)}})
    if held and held.get("user_id") != user["_id"]:
        raise HTTPException(409, "another buyer already holds this car")

    amount = amount_for(car.get("sale_eur"))
    title = await _english_title(car)
    origin = body.origin_url.rstrip("/")
    kwargs = dict(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": int(round(amount * 100)),
                "product_data": {"name": f"Reservation deposit — {title}"},
            },
            "quantity": 1,
        }],
        customer_email=user["email"],
        # Cards only: they are the one method that can hold an amount without taking it.
        payment_method_types=["card"],
        # HOLD, do not charge. The operator captures later, and keeping the card on file
        # means the next deposit is one tap.
        payment_intent_data={"capture_method": "manual",
                             "setup_future_usage": "off_session"},
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
        "car_title": title,
        "user_id": user["_id"],
        "email": user["email"],
        "amount": amount,
        "currency": "eur",
        "car_price_eur": car.get("sale_eur") or 0,
        # Which skin they bought from, so a later refund email speaks their language.
        "lang": (origin.rsplit("/", 1)[-1] or "en")[:2].lower(),
        "status": "initiated",
        "payment_status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"checkout_url": session.url, "session_id": session.id, "amount_eur": amount}


async def _settle(session_id, payment_intent="", payment_status="authorised", extra=None):
    """Idempotent: the webhook and the buyer's poll race, and whichever lands first wins.

    Reserving the car on an AUTHORISATION is deliberate - the owner's decision: the held
    amount is guarantee enough, so the buyer does not lose the car while we confirm it.
    """
    result = await _db.deposits.update_one(
        {"session_id": session_id, "payment_status": {"$nin": list(HELD_STATES)}},
        {"$set": {"status": "completed", "payment_status": payment_status,
                  "stripe_payment_intent_id": payment_intent,
                  "authorised_at": _now(),
                  "expires_at": _now() + timedelta(days=AUTH_DAYS),
                  "updated_at": _now(), **(extra or {})}})
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
    if record.get("payment_status") not in HELD_STATES:
        try:
            s = stripe.checkout.Session.retrieve(session_id)
            # With manual capture the session's payment_status stays "unpaid" until we
            # capture, so "complete" alone must NOT be read as money taken. The intent is
            # the truth: `requires_capture` means the funds are held.
            if s.payment_status == "paid":
                await _settle(session_id, s.payment_intent or "", "paid")
            elif s.payment_intent:
                pi = stripe.PaymentIntent.retrieve(s.payment_intent)
                if pi.status == "requires_capture":
                    await _settle(session_id, pi.id, "authorised")
                elif pi.status == "succeeded":
                    await _settle(session_id, pi.id, "captured",
                                  {"captured_eur": (pi.amount_received or 0) / 100.0})
            record = await _db.deposits.find_one({"session_id": session_id})
        except stripe.error.StripeError:
            pass
    return {"session_id": record["session_id"], "status": record["status"],
            "payment_status": record["payment_status"], "amount_eur": record["amount"],
            "commission_eur": COMMISSION_EUR, "hold_days": AUTH_DAYS,
            "expires_at": record.get("expires_at"),
            "captured_eur": record.get("captured_eur"),
            "car_id": record["car_id"], "car_title": record.get("car_title") or ""}


@router.get("/deposit/mine")
async def my_deposits(user=Depends(auth.current_user)):
    rows = await _db.deposits.find(
        {"user_id": user["_id"], "payment_status": {"$in": list(HELD_STATES)}},
        {"_id": 0, "session_id": 1, "car_id": 1, "car_title": 1, "amount": 1,
         "created_at": 1, "payment_status": 1, "expires_at": 1, "captured_eur": 1}
    ).sort("created_at", -1).to_list(50)
    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
        r["expires_at"] = r["expires_at"].isoformat() if r.get("expires_at") else None
    return {"items": rows}


async def _free_car(car_id):
    """Put the car back on the market: it is only held while a deposit stands."""
    await _db.listings.update_one(
        {"_id": car_id},
        {"$unset": {"reserved": "", "reserved_by": "", "reserved_at": ""}})


async def list_for_admin(limit=200):
    """Every deposit that reached Stripe, newest first: what is held, and what to do next."""
    rows = await _db.deposits.find(
        {"payment_status": {"$in": ["authorised", "captured", "released", "expired",
                                    "paid", "refunded"]}}
    ).sort("updated_at", -1).to_list(limit)
    return [{
        "session_id": r.get("session_id"),
        "car_id": r.get("car_id"),
        "car_title": r.get("car_title") or "",
        "email": r.get("email") or "",
        "amount": r.get("amount") or 0,
        "captured_eur": r.get("captured_eur"),
        "released_eur": r.get("released_eur"),
        "returned_eur": r.get("returned_eur"),
        "commission_eur": r.get("commission_eur"),
        "car_price_eur": r.get("car_price_eur") or 0,
        "payment_status": r.get("payment_status"),
        "archive_ok": r.get("archive_ok"),
        "paid_at": r.get("created_at"),
        "authorised_at": r.get("authorised_at"),
        "expires_at": r.get("expires_at"),
        "captured_at": r.get("captured_at"),
        "captured_by": r.get("captured_by") or "",
        "released_at": r.get("released_at"),
        "refunded_at": r.get("refunded_at"),
        "refunded_by": r.get("refunded_by") or "",
        "capture_step_eur": CAPTURE_STEP_EUR,
    } for r in rows]


async def capture(session_id, amount_eur, admin_email=""):
    """Take part (or all) of a held amount. Stripe releases whatever is left, for good.

    Partial capture is one-shot on Stripe's side: the uncaptured remainder is returned to the
    buyer and CANNOT be captured later, so the operator is told the number they are settling
    on rather than being allowed to nibble at it twice.
    """
    record = await _db.deposits.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "no such deposit")
    if record.get("payment_status") != "authorised":
        raise HTTPException(409, "only a held (authorised) deposit can be captured")
    intent = record.get("stripe_payment_intent_id")
    if not intent:
        raise HTTPException(409, "Stripe never reported an authorisation for that deposit")

    held = float(record.get("amount") or 0)
    take = round(float(amount_eur or 0), 2)
    if take <= 0:
        raise HTTPException(400, "the amount to capture must be positive")
    if take > held + 0.005:
        raise HTTPException(400, f"only €{held:,.2f} is held on that card")
    # Round hundreds, or the whole hold. A deposit is 10% of a car and almost never a round
    # number, so demanding hundreds alone would make it impossible to take the full amount.
    if take % CAPTURE_STEP_EUR and abs(take - held) > 0.005:
        raise HTTPException(
            400, f"capture in steps of €{CAPTURE_STEP_EUR:.0f}, or the full €{held:,.2f}")

    try:
        pi = stripe.PaymentIntent.capture(
            intent, amount_to_capture=int(round(take * 100)),
            idempotency_key=f"deposit-capture-{session_id}-{int(round(take * 100))}")
    except stripe.error.InvalidRequestError as e:
        raise HTTPException(400, str(e.user_message or e)[:200])
    except stripe.error.StripeError as e:
        raise HTTPException(502, str(e.user_message or e)[:200])

    released = round(max(0.0, held - take), 2)
    await _db.deposits.update_one(
        {"session_id": session_id},
        {"$set": {"payment_status": "captured", "status": "captured",
                  "captured_eur": take, "released_eur": released,
                  "captured_at": _now(), "captured_by": admin_email or "admin token",
                  "updated_at": _now()}})
    asyncio.create_task(mailer.send_deposit_captured(
        record.get("email"), record.get("car_title") or record["car_id"],
        take, released, record.get("lang") or "en"))
    log.info("captured %s EUR of the %s EUR hold %s (released %s), car %s stays reserved",
             take, held, session_id, released, record["car_id"])
    return {"captured": True, "captured_eur": take, "released_eur": released,
            "held_eur": held, "status": pi.status, "car_id": record["car_id"],
            "email": record.get("email") or ""}


async def release(session_id, admin_email="", reason="requested_by_customer",
                  payment_status="released"):
    """Let a hold go without taking a cent, and put the car back on the market."""
    record = await _db.deposits.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "no such deposit")
    if record.get("payment_status") == "paid":
        raise HTTPException(409, "that deposit was charged, not held — refund it instead")
    if record.get("payment_status") != "authorised":
        raise HTTPException(409, "only a held (authorised) deposit can be released")
    intent = record.get("stripe_payment_intent_id")
    settle = {"payment_status": payment_status, "status": payment_status,
              "released_eur": float(record.get("amount") or 0), "captured_eur": 0.0,
              "released_at": _now(), "released_by": admin_email or "admin token",
              "updated_at": _now()}
    if intent:
        try:
            stripe.PaymentIntent.cancel(intent, cancellation_reason=reason,
                                        idempotency_key=f"deposit-release-{session_id}")
        except stripe.error.InvalidRequestError as e:
            # Already cancelled - by the network at expiry, or on the dashboard. Our record
            # is simply behind, and the car must not stay held because of it.
            log.info("release %s: Stripe says %s", session_id, str(e)[:140])
        except stripe.error.StripeError as e:
            raise HTTPException(502, str(e.user_message or e)[:200])

    await _db.deposits.update_one({"session_id": session_id}, {"$set": settle})
    await _free_car(record["car_id"])
    asyncio.create_task(mailer.send_deposit_released(
        record.get("email"), record.get("car_title") or record["car_id"],
        float(record.get("amount") or 0), payment_status, record.get("lang") or "en"))
    log.info("released the %s EUR hold %s (%s) and put car %s back on the market",
             record.get("amount"), session_id, payment_status, record["car_id"])
    return {"released": True, "released_eur": settle["released_eur"],
            "payment_status": payment_status, "car_id": record["car_id"],
            "email": record.get("email") or ""}


async def sweep_expired():
    """Hand back every hold the network is about to drop, and re-list the car.

    Stripe cancels an uncaptured authorisation itself after AUTH_DAYS and tells us through
    `payment_intent.canceled`. This sweep is the belt to that braces: a webhook we never
    received must not leave a car reserved for a hold that no longer exists.
    """
    due = await _db.deposits.find(
        {"payment_status": "authorised", "expires_at": {"$lte": _now()}}
    ).to_list(100)
    for record in due:
        try:
            await release(record["session_id"], "expiry sweep",
                          reason="abandoned", payment_status="expired")
        except HTTPException as e:
            log.warning("could not expire %s: %s", record.get("session_id"), e.detail)
    return len(due)


async def scheduler(period=1800):
    """One sweep every half hour: an expiry is never more than that late."""
    while True:
        try:
            await sweep_expired()
        except Exception as e:                      # noqa: BLE001 - a loop must not die
            log.warning("deposit expiry sweep: %s", str(e)[:200])
        await asyncio.sleep(period)


async def refund(session_id, admin_email=""):
    """Refund a deposit in full and release the car.

    The `charge.refunded` webhook does the same two writes, so this is deliberately
    idempotent: whichever lands first wins and the second is a no-op. The Stripe call
    carries an idempotency key on the session id, so a double-clicked button cannot
    refund twice.
    """
    record = await _db.deposits.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "no such deposit")
    if record.get("payment_status") == "refunded":
        raise HTTPException(409, "that deposit is already refunded")
    if record.get("payment_status") != "paid":
        raise HTTPException(409, "only a paid deposit can be refunded")
    intent = record.get("stripe_payment_intent_id")
    if not intent:
        raise HTTPException(409, "Stripe never reported a payment for that deposit")

    deposit = float(record.get("amount") or 0)
    give_back = round(max(0.0, deposit - COMMISSION_EUR), 2)
    settle = {"status": "refunded", "payment_status": "refunded",
              "returned_eur": give_back, "commission_eur": round(deposit - give_back, 2),
              "refunded_at": _now(), "refunded_by": admin_email or "admin token",
              "updated_at": _now()}

    if give_back <= 0:
        # The commission swallows the whole deposit, and Stripe rejects a zero refund.
        # Nothing to send back, but the car must still be released.
        await _db.deposits.update_one({"session_id": session_id}, {"$set": settle})
        await _free_car(record["car_id"])
        return {"refunded": True, "returned_eur": 0.0,
                "commission_eur": settle["commission_eur"], "car_id": record["car_id"],
                "email": record.get("email") or ""}

    try:
        out = stripe.Refund.create(
            payment_intent=intent,
            amount=int(round(give_back * 100)),
            metadata={"kind": "car_deposit", "car_id": record["car_id"],
                      "commission_eur": settle["commission_eur"],
                      "refunded_by": admin_email or "admin token"},
            idempotency_key=f"deposit-refund-{session_id}")
    except stripe.error.InvalidRequestError as e:
        # Refunded straight on the Stripe dashboard: our record is simply behind, so
        # settle it here rather than leaving the car held for ever.
        if "already been refunded" in (str(e) or "").lower():
            await _db.deposits.update_one(
                {"session_id": session_id},
                {"$set": {**settle, "refunded_by": admin_email or "stripe"}})
            await _free_car(record["car_id"])
            return {"refunded": True, "already": True, "car_id": record["car_id"]}
        raise HTTPException(400, str(e.user_message or e)[:200])
    except stripe.error.StripeError as e:
        raise HTTPException(502, str(e.user_message or e)[:200])

    await _db.deposits.update_one(
        {"session_id": session_id},
        {"$set": {**settle, "stripe_refund_id": out.id}})
    await _free_car(record["car_id"])
    # The buyer should hear it from us, not from their bank statement. Fire and forget: a
    # mail outage must not turn a completed refund into an error.
    asyncio.create_task(mailer.send_deposit_returned(
        record.get("email"), record.get("car_title") or record["car_id"],
        give_back, settle["commission_eur"], record.get("lang") or "en"))
    log.info("returned %s EUR of the %s EUR deposit %s (kept %s commission) and released "
             "car %s", give_back, deposit, session_id, settle["commission_eur"],
             record["car_id"])
    return {"refunded": True, "refund_id": out.id, "status": out.status,
            "returned_eur": give_back, "commission_eur": settle["commission_eur"],
            "amount_eur": deposit, "car_id": record["car_id"],
            "email": record.get("email") or ""}



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
        # With manual capture the session reports "unpaid" here on purpose: the money is
        # HELD, not taken. Reading it as paid was the bug this whole flow turns on.
        await _settle(obj["id"], obj.get("payment_intent") or "",
                      "paid" if obj.get("payment_status") == "paid" else "authorised")
    elif kind == "payment_intent.amount_capturable_updated":
        record = await _db.deposits.find_one({"stripe_payment_intent_id": obj.get("id")})
        if not record and obj.get("metadata", {}).get("kind") == "car_deposit":
            record = await _db.deposits.find_one({"car_id": obj["metadata"].get("car_id"),
                                                  "payment_status": "pending"})
        if record:
            await _settle(record["session_id"], obj.get("id") or "", "authorised")
    elif kind == "payment_intent.succeeded":
        record = await _db.deposits.find_one({"stripe_payment_intent_id": obj.get("id")})
        if record and record.get("payment_status") in ("authorised", "pending"):
            await _db.deposits.update_one(
                {"session_id": record["session_id"]},
                {"$set": {"payment_status": "captured", "status": "captured",
                          "captured_eur": (obj.get("amount_received") or 0) / 100.0,
                          "captured_at": _now(), "updated_at": _now()}})
    elif kind == "payment_intent.canceled":
        # The hold is gone - cancelled by us, on the dashboard, or by the network at expiry.
        # Either way the car cannot stay reserved for money that is no longer held.
        record = await _db.deposits.find_one({"stripe_payment_intent_id": obj.get("id")})
        if record and record.get("payment_status") == "authorised":
            expired = (obj.get("cancellation_reason") or "") in ("abandoned", "automatic")
            await _db.deposits.update_one(
                {"session_id": record["session_id"]},
                {"$set": {"payment_status": "expired" if expired else "released",
                          "status": "expired" if expired else "released",
                          "released_eur": float(record.get("amount") or 0),
                          "captured_eur": 0.0, "released_at": _now(),
                          "released_by": "stripe", "updated_at": _now()}})
            await _free_car(record["car_id"])
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
