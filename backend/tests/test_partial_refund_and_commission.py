"""Iteration 29: partial refund with EUR 300 commission and the commission-swallows-deposit edge case.

Two paid Stripe test deposits are put through the admin refund flow:

1. Partial refund happy path — the Stripe Refund object must equal (deposit - 300) in cents,
   the charge must be PARTIALLY refunded, and our record must show returned + commission.
2. Edge case — the deposit's `amount` is patched to 250 EUR in Mongo BEFORE refund, so the
   commission swallows the whole deposit. There must be NO new Stripe Refund and the car
   must still be released.

Regression: /api/deposit/car/{id} must expose commission_eur.
"""
import asyncio
import os
import time
import uuid

import pytest
import requests
import stripe
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASSWORD = "AdminTest2026!"
BUYER_PASSWORD = "SecurityTest2026!"
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Exclusive with the other Stripe browser suite: see `stripe_e2e_lock` in conftest.
pytestmark = pytest.mark.usefixtures("stripe_e2e_lock")


CAR_PARTIAL = os.environ.get("PARTIAL_CAR_ID", "42370582")   # ~619.90 EUR deposit
CAR_EDGE = os.environ.get("EDGE_CAR_ID", "42462841")         # ~619.90 EUR deposit


# ---------- helpers ----------------------------------------------------------


def _register_buyer():
    email = f"e2e-partial-{uuid.uuid4().hex[:8]}@example.com"
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/register",
               json={"email": email, "password": BUYER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return s, email


def _admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.text}"
    return s


def _drive_stripe_checkout(checkout_url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        # The card field, not "networkidle": Stripe holds connections open, so idle never
        # arrives while the other xdist worker is busy.
        page.locator("input#cardNumber").wait_for(state="visible", timeout=60000)

        page.locator("input#cardNumber").fill("4242424242424242")
        page.locator("input#cardExpiry").fill("12/34")
        page.locator("input#cardCvc").fill("123")
        try:
            page.locator("input#billingName").fill("Test Buyer")
        except Exception:
            pass
        try:
            page.locator("select#billingCountry").select_option("BG")
        except Exception:
            pass
        # click "Enter address manually" if the autocomplete widget is present
        try:
            manual = page.get_by_role("button",
                                      name=lambda n: n and "manually" in n.lower())
            if manual.count() > 0:
                manual.first.click(timeout=2000)
        except Exception:
            pass
        for sel, val in [
            ("input#billingAddressLine1", "1 Test St"),
            ("input#billingLocality", "Sofia"),
            ("input#billingPostalCode", "1000"),
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.fill(val)
            except Exception:
                pass
        try:
            tel = page.locator('input[type="tel"]')
            if tel.count() > 0 and tel.first.is_visible():
                tel.first.click()
                tel.first.press_sequentially("888555111", delay=30)
        except Exception:
            pass

        submit = page.locator('button[data-testid="hosted-payment-submit-button"]')
        if submit.count() == 0:
            submit = page.get_by_role(
                "button",
                name=lambda n: n and ("pay" in n.lower() or "reserv" in n.lower()))
        submit.first.click()

        try:
            page.wait_for_url("**/payment/success**", timeout=90000)
        except Exception:
            page.screenshot(path="/app/test_reports/stripe_partial_error.png", quality=40)
            html = page.content()[:1500]
            browser.close()
            raise AssertionError(f"Stripe checkout did not redirect. URL={page.url}\n{html}")
        browser.close()


def _poll_paid(session_id, timeout=90):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = requests.get(f"{BASE_URL}/api/deposit/status/{session_id}", timeout=20)
        if r.status_code == 200:
            last = r.json()
            if last.get("payment_status") == "paid":
                return last
        time.sleep(2)
    raise AssertionError(f"deposit never became paid within {timeout}s: {last}")


def _mongo():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


# ---------- fixtures ---------------------------------------------------------


@pytest.fixture(scope="module")
def admin():
    return _admin_session()


def _make_paid_deposit(car_id):
    session, email = _register_buyer()
    q = session.get(f"{BASE_URL}/api/deposit/car/{car_id}", timeout=20).json()
    if q.get("reserved"):
        pytest.skip(f"car {car_id} already reserved")
    r = session.post(f"{BASE_URL}/api/deposit/checkout",
                     json={"car_id": car_id, "origin_url": BASE_URL}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    _drive_stripe_checkout(body["checkout_url"])
    st = _poll_paid(body["session_id"])
    return {"session_id": body["session_id"], "amount": body["amount_eur"],
            "email": email, "buyer": session, "quote": q, "status": st,
            "car_id": car_id}


@pytest.fixture(scope="module")
def partial_deposit():
    return _make_paid_deposit(CAR_PARTIAL)


@pytest.fixture(scope="module")
def edge_deposit():
    return _make_paid_deposit(CAR_EDGE)


# ---------- Regression: commission_eur exposed on quote ---------------------


def test_deposit_car_route_returns_commission_eur():
    for cid in (CAR_PARTIAL, CAR_EDGE, "42179408", "42379471"):
        r = requests.get(f"{BASE_URL}/api/deposit/car/{cid}", timeout=15)
        assert r.status_code == 200, f"{cid}: {r.status_code} {r.text}"
        body = r.json()
        assert "commission_eur" in body, f"{cid}: missing commission_eur"
        assert body["commission_eur"] == 300.0, f"{cid}: {body['commission_eur']}"


def test_deposit_status_returns_commission_eur(partial_deposit):
    r = requests.get(
        f"{BASE_URL}/api/deposit/status/{partial_deposit['session_id']}", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body.get("commission_eur") == 300.0


# ---------- MAIN JOB: partial refund keeps EUR 300 commission ---------------


def test_partial_refund_returns_deposit_minus_commission(admin, partial_deposit):
    sid = partial_deposit["session_id"]
    amount = partial_deposit["amount"]

    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/refund", timeout=60)
    assert r.status_code == 200, r.text
    out = r.json()
    print(f"[PARTIAL] session={sid} car={partial_deposit['car_id']} "
          f"amount_eur={amount} refund_id={out.get('refund_id')} "
          f"returned_eur={out.get('returned_eur')} commission={out.get('commission_eur')}")

    # API response asserts
    assert out["refunded"] is True
    assert abs(out["returned_eur"] - (amount - 300)) < 0.01, \
        f"returned {out['returned_eur']} vs expected {amount - 300}"
    assert out["commission_eur"] == 300.0
    assert out.get("refund_id"), "no refund_id returned"
    partial_deposit["refund_id"] = out["refund_id"]

    # Stripe assertions - PARTIAL refund
    st = stripe.checkout.Session.retrieve(sid)
    intent_id = st.payment_intent
    partial_deposit["intent_id"] = intent_id
    pi = stripe.PaymentIntent.retrieve(intent_id, expand=["latest_charge"])
    charge = pi.latest_charge

    expected_cents = int(round((amount - 300) * 100))
    print(f"[PARTIAL] Stripe charge.amount_refunded={charge.amount_refunded} cents, "
          f"expected={expected_cents}, charge.refunded(full?)={charge.refunded}")

    assert charge.amount_refunded == expected_cents, \
        f"Stripe refunded {charge.amount_refunded} cents, expected {expected_cents} " \
        f"(deposit {amount * 100} - 30000). FULL REFUND DETECTED - HIGH PRIORITY BUG"
    # Partial refund - charge.refunded should be False (only True when 100% refunded)
    assert charge.refunded is False, \
        f"charge.refunded=True means Stripe treated this as a FULL refund " \
        f"(amount_refunded={charge.amount_refunded}, captured={charge.amount})"

    refunds = stripe.Refund.list(payment_intent=intent_id, limit=10)
    assert len(refunds.data) == 1
    assert refunds.data[0].amount == expected_cents
    assert refunds.data[0].id == out["refund_id"]


def test_partial_refund_persisted_in_mongo(partial_deposit):
    sid = partial_deposit["session_id"]

    async def check():
        client, db = _mongo()
        try:
            return await db.deposits.find_one({"session_id": sid})
        finally:
            client.close()

    doc = asyncio.run(check())
    assert doc is not None
    assert doc["payment_status"] == "refunded"
    assert abs(doc["returned_eur"] - (partial_deposit["amount"] - 300)) < 0.01
    assert doc["commission_eur"] == 300.0


def test_partial_refund_releases_car(partial_deposit):
    r = requests.get(
        f"{BASE_URL}/api/deposit/car/{partial_deposit['car_id']}", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["reserved"] is False, f"car still reserved: {body}"


def test_different_buyer_can_reserve_after_partial_refund(partial_deposit):
    s, _ = _register_buyer()
    r = s.post(f"{BASE_URL}/api/deposit/checkout",
               json={"car_id": partial_deposit["car_id"], "origin_url": BASE_URL},
               timeout=30)
    assert r.status_code == 200, \
        f"another buyer should reserve after refund, got {r.status_code}: {r.text}"

    async def cleanup(sid):
        client, db = _mongo()
        try:
            await db.deposits.delete_one({"session_id": sid, "payment_status": "pending"})
        finally:
            client.close()

    asyncio.run(cleanup(r.json()["session_id"]))


# ---------- EDGE CASE: commission >= deposit --------------------------------


def test_edge_case_commission_swallows_deposit(admin, edge_deposit):
    """Deposit is patched to 250 EUR in Mongo. Refund must NOT hit Stripe."""
    sid = edge_deposit["session_id"]
    car_id = edge_deposit["car_id"]

    # Patch amount to 250 (below 300 commission)
    async def patch():
        client, db = _mongo()
        try:
            await db.deposits.update_one(
                {"session_id": sid}, {"$set": {"amount": 250}})
        finally:
            client.close()

    asyncio.run(patch())

    # Get the payment intent BEFORE refund so we can prove no new Stripe refund was made
    st = stripe.checkout.Session.retrieve(sid)
    intent_id = st.payment_intent
    refunds_before = stripe.Refund.list(payment_intent=intent_id, limit=10)
    n_before = len(refunds_before.data)

    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/refund", timeout=30)
    assert r.status_code == 200, r.text
    out = r.json()
    print(f"[EDGE] session={sid} car={car_id} returned={out.get('returned_eur')} "
          f"commission={out.get('commission_eur')} refund_id={out.get('refund_id')}")

    assert out["refunded"] is True
    assert out["returned_eur"] == 0
    assert out["commission_eur"] == 250
    # No stripe refund_id should be reported
    assert "refund_id" not in out or not out.get("refund_id"), \
        f"edge case must not create a Stripe refund but got refund_id={out.get('refund_id')}"

    # NO new Stripe Refund
    refunds_after = stripe.Refund.list(payment_intent=intent_id, limit=10)
    assert len(refunds_after.data) == n_before, \
        f"edge case created a Stripe refund: {len(refunds_after.data)} vs before {n_before}"

    # Mongo shows refunded status
    async def check():
        client, db = _mongo()
        try:
            return await db.deposits.find_one({"session_id": sid})
        finally:
            client.close()

    doc = asyncio.run(check())
    assert doc["payment_status"] == "refunded"
    assert doc["returned_eur"] == 0
    assert doc["commission_eur"] == 250

    # Car still released
    q = requests.get(f"{BASE_URL}/api/deposit/car/{car_id}", timeout=15).json()
    assert q["reserved"] is False, f"edge case car still reserved: {q}"


# ---------- Body panels regression ------------------------------------------


def test_body_panels_car_42179408():
    r = requests.get(f"{BASE_URL}/api/car/42179408?lang=en", timeout=20)
    assert r.status_code == 200
    bp = r.json().get("body_panels")
    assert bp is not None and bp.get("available") is True
    slugs = {f["slug"] for f in bp["findings"]}
    # Expected findings per problem statement
    expected = {"hood", "rear_door_right", "front_door_right",
                "rear_door_left", "quarter_panel_left", "radiator_support"}
    assert expected.issubset(slugs), f"missing panels: {expected - slugs}"


def test_body_panels_car_42379471_empty():
    r = requests.get(f"{BASE_URL}/api/car/42379471?lang=en", timeout=20)
    assert r.status_code == 200
    bp = r.json().get("body_panels")
    assert bp is not None
    assert bp.get("findings") == []
