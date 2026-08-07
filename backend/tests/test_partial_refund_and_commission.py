"""Capturing a pre-authorised reservation deposit, and the EUR 300 commission on the quote.

Two real Stripe test HOLDS are driven through the admin panel:

1. Partial capture — EUR 100 of a larger hold. Stripe must receive exactly that, release the
   remainder for good (no refund object, nothing left capturable), and the car must STAY
   reserved because money has now been taken for it. A second capture, or a release, must be
   refused.
2. Full capture — the whole held amount, which is 10% of a car and therefore almost never a
   round hundred. This is allowed alongside the hundreds, or the last euros could never be
   taken at all.

Regression: /api/deposit/car/{id} and /api/deposit/status/{id} must expose commission_eur.
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
            page.screenshot(path="/app/test_reports/stripe_partial_error.png")
            html = page.content()[:1500]
            browser.close()
            raise AssertionError(f"Stripe checkout did not redirect. URL={page.url}\n{html}")
        browser.close()


def _poll_held(session_id, timeout=90):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = requests.get(f"{BASE_URL}/api/deposit/status/{session_id}", timeout=20)
        if r.status_code == 200:
            last = r.json()
            if last.get("payment_status") in ("authorised", "captured", "paid"):
                return last
        time.sleep(2)
    raise AssertionError(f"deposit never became held within {timeout}s: {last}")


def _mongo():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


# ---------- fixtures ---------------------------------------------------------


@pytest.fixture(scope="module")
def admin():
    return _admin_session()


def _make_held_deposit(car_id):
    session, email = _register_buyer()
    q = session.get(f"{BASE_URL}/api/deposit/car/{car_id}", timeout=20).json()
    if q.get("reserved"):
        pytest.skip(f"car {car_id} already reserved")
    r = session.post(f"{BASE_URL}/api/deposit/checkout",
                     json={"car_id": car_id, "origin_url": BASE_URL}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    _drive_stripe_checkout(body["checkout_url"])
    st = _poll_held(body["session_id"])
    return {"session_id": body["session_id"], "amount": body["amount_eur"],
            "email": email, "buyer": session, "quote": q, "status": st,
            "car_id": car_id}


def _reset_car(car_id, session_id):
    """Give the test its car back.

    A captured hold keeps the car reserved on purpose - that is the product behaviour. But a
    test suite that leaves it reserved can only pass once: every later run skipped with "car
    already reserved" and the capture path stopped being tested at all.
    """
    async def go():
        client, db = _mongo()
        try:
            await db.deposits.delete_one({"session_id": session_id})
            await db.listings.update_one(
                {"_id": car_id},
                {"$unset": {"reserved": "", "reserved_by": "", "reserved_at": ""}})
        finally:
            client.close()

    asyncio.run(go())


@pytest.fixture(scope="module")
def partial_deposit():
    held = _make_held_deposit(CAR_PARTIAL)
    yield held
    _reset_car(CAR_PARTIAL, held["session_id"])


@pytest.fixture(scope="module")
def edge_deposit():
    held = _make_held_deposit(CAR_EDGE)
    yield held
    _reset_car(CAR_EDGE, held["session_id"])


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

# ---------- MAIN JOB: capture part of a hold, in round hundreds ---------------


def test_capture_takes_only_the_hundreds_asked_for(admin, partial_deposit):
    """EUR 100 of a larger hold: Stripe takes exactly that and lets the rest go for good."""
    sid = partial_deposit["session_id"]
    held = partial_deposit["amount"]
    if held < 200:
        pytest.skip(f"hold of EUR {held} is too small to capture a part of")

    st = stripe.checkout.Session.retrieve(sid)
    intent_id = st.payment_intent
    partial_deposit["intent_id"] = intent_id

    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/capture",
                   json={"amount_eur": 100}, timeout=60)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["captured"] is True
    assert out["captured_eur"] == 100
    assert abs(out["released_eur"] - (held - 100)) < 0.01, out

    pi = stripe.PaymentIntent.retrieve(intent_id, expand=["latest_charge"])
    assert pi.status == "succeeded", pi.status
    assert pi.amount_received == 10000, pi.amount_received
    # The uncaptured remainder is released by Stripe, not refunded by us.
    assert (pi.amount_capturable or 0) == 0
    assert pi.latest_charge.amount_captured == 10000
    assert not stripe.Refund.list(payment_intent=intent_id, limit=5).data, \
        "a partial capture must not create a refund object"


def test_capture_persisted_in_mongo(partial_deposit):
    async def check():
        client, db = _mongo()
        try:
            return await db.deposits.find_one({"session_id": partial_deposit["session_id"]})
        finally:
            client.close()

    doc = asyncio.run(check())
    assert doc is not None
    assert doc["payment_status"] == "captured"
    assert doc["captured_eur"] == 100
    assert abs(doc["released_eur"] - (partial_deposit["amount"] - 100)) < 0.01
    assert doc.get("captured_at") and doc.get("captured_by")


def test_car_stays_reserved_after_capture(partial_deposit):
    """We have taken money for this car, so it certainly does not go back on the market."""
    body = requests.get(
        f"{BASE_URL}/api/deposit/car/{partial_deposit['car_id']}", timeout=15).json()
    assert body["reserved"] is True, body


def test_capture_cannot_happen_twice(admin, partial_deposit):
    """Stripe releases the remainder on the first capture: there is nothing left to nibble."""
    r = admin.post(f"{BASE_URL}/api/admin/deposits/{partial_deposit['session_id']}/capture",
                   json={"amount_eur": 100}, timeout=30)
    assert r.status_code == 409, r.text
    r = admin.post(f"{BASE_URL}/api/admin/deposits/{partial_deposit['session_id']}/release",
                   timeout=30)
    assert r.status_code == 409, r.text


# ---------- Full capture: the whole hold, not a round number ------------------


def test_capture_can_take_the_whole_hold(admin, edge_deposit):
    """A deposit is 10% of a car and almost never a round hundred, so the full amount is
    always allowed as well - otherwise the last euros could never be taken."""
    sid = edge_deposit["session_id"]
    held = edge_deposit["amount"]
    st = stripe.checkout.Session.retrieve(sid)
    intent_id = st.payment_intent

    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/capture",
                   json={"amount_eur": held}, timeout=60)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["captured_eur"] == pytest.approx(held)
    assert out["released_eur"] == 0

    pi = stripe.PaymentIntent.retrieve(intent_id)
    assert pi.status == "succeeded"
    assert pi.amount_received == int(round(held * 100)), pi.amount_received


# ---------- Body panels regression ------------------------------------------


def test_body_panels_car_42179408():
    r = requests.get(f"{BASE_URL}/api/car/42179408?lang=en", timeout=20)
    assert r.status_code == 200
    bp = r.json().get("body_panels")
    assert bp is not None and bp.get("available") is True
    slugs = {f["slug"] for f in bp["findings"]}
    expected = {"hood", "rear_door_right", "front_door_right",
                "rear_door_left", "quarter_panel_left", "radiator_support"}
    assert expected.issubset(slugs), f"missing panels: {expected - slugs}"


def test_body_panels_car_42379471_empty():
    r = requests.get(f"{BASE_URL}/api/car/42379471?lang=en", timeout=20)
    assert r.status_code == 200
    bp = r.json().get("body_panels")
    assert bp is not None
    assert bp.get("findings") == []
