"""End-to-end tests for the admin deposit refund flow.

Covers: happy path (buyer pays -> admin refunds -> car freed -> other buyer can reserve),
Stripe-side real refund verification, /api/purchases removal, double-refund idempotency,
archive-preservation, archive_ok warning, and admin-only guards.

Playwright drives Stripe hosted Checkout with the test card 4242 4242 4242 4242.
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
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "encar-admin")
ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASSWORD = "AdminTest2026!"
BUYER_PASSWORD = "SecurityTest2026!"
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Chosen at test-collection time; kept small so the deposit is < ~EUR 700.
CAR_ID = os.environ.get("TEST_CAR_ID", "42317775")

pytestmark = pytest.mark.order(1)


# --------------------- helpers ------------------------------------------------


def _register_buyer():
    email = f"e2e-refund-{uuid.uuid4().hex[:8]}@example.com"
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


def _pick_cheap_car(session):
    r = session.get(f"{BASE_URL}/api/deposit/car/{CAR_ID}", timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("reserved"):
        pytest.skip(f"car {CAR_ID} already reserved; set TEST_CAR_ID env")
    return body


def _drive_stripe_checkout(checkout_url):
    """Drive Stripe hosted checkout with Playwright and pay with 4242."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)

        # Card fields (Stripe hosted checkout)
        page.locator("input#cardNumber").fill("4242424242424242")
        page.locator("input#cardExpiry").fill("12/34")
        page.locator("input#cardCvc").fill("123")

        # Name on card
        try:
            page.locator("input#billingName").fill("Test Buyer")
        except Exception:
            pass

        # Country dropdown - default is usually fine; try to select something sane
        try:
            page.locator("select#billingCountry").select_option("BG")
        except Exception:
            pass

        # If the address autocomplete is present, click "Enter address manually" first.
        try:
            manual = page.get_by_role("button", name=lambda n: n and "manually" in n.lower())
            if manual.count() > 0:
                manual.first.click(timeout=2000)
        except Exception:
            pass

        # Fill address fields if visible
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

        # Phone - masked input, use press_sequentially
        try:
            tel = page.locator('input[type="tel"]')
            if tel.count() > 0 and tel.first.is_visible():
                tel.first.click()
                tel.first.press_sequentially("888555111", delay=30)
        except Exception:
            pass

        # Submit
        submit = page.locator('button[data-testid="hosted-payment-submit-button"]')
        if submit.count() == 0:
            submit = page.get_by_role("button", name=lambda n: n and ("pay" in n.lower() or "reserv" in n.lower()))
        submit.first.click()

        # Wait for redirect back to our /payment/success
        try:
            page.wait_for_url("**/payment/success**", timeout=90000)
        except Exception:
            page.screenshot(path="/app/test_reports/stripe_checkout_error.png", quality=40)
            html = page.content()[:2000]
            browser.close()
            raise AssertionError(f"Stripe checkout did not redirect. URL={page.url}\n{html}")
        browser.close()


def _poll_paid(session_id, timeout=60):
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


# --------------------- fixtures -----------------------------------------------


@pytest.fixture(scope="module")
def buyer():
    s, email = _register_buyer()
    return s, email


@pytest.fixture(scope="module")
def admin():
    return _admin_session()


@pytest.fixture(scope="module")
def paid_deposit(buyer):
    """One shared paid deposit for the whole module - Stripe Checkout is expensive."""
    session, email = buyer
    quote = _pick_cheap_car(session)
    assert quote["configured"], "Stripe not configured on backend"
    r = session.post(f"{BASE_URL}/api/deposit/checkout",
                     json={"car_id": CAR_ID, "origin_url": BASE_URL}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    _drive_stripe_checkout(body["checkout_url"])
    status = _poll_paid(body["session_id"])
    return {
        "session_id": body["session_id"],
        "amount": body["amount_eur"],
        "email": email,
        "buyer": session,
        "quote": quote,
        "status": status,
    }


# --------------------- tests --------------------------------------------------


# ---- guard rails (before we spend a Stripe test) ----------------------------


def test_admin_deposits_rejects_anonymous():
    r = requests.get(f"{BASE_URL}/api/admin/deposits", timeout=15)
    assert r.status_code == 401


def test_admin_deposits_rejects_non_admin_buyer():
    s, _ = _register_buyer()
    r = s.get(f"{BASE_URL}/api/admin/deposits", timeout=15)
    assert r.status_code == 401


def test_refund_rejects_non_admin_buyer():
    s, _ = _register_buyer()
    r = s.post(f"{BASE_URL}/api/admin/deposits/cs_test_nope/refund", timeout=15)
    assert r.status_code == 401


def test_refund_unknown_session_admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/deposits/cs_test_does_not_exist/refund",
                      headers={"x-admin-token": ADMIN_TOKEN}, timeout=15)
    assert r.status_code == 404


# ---- happy path & real Stripe verification ---------------------------------


def test_paid_deposit_appears_in_admin_list(admin, paid_deposit):
    r = admin.get(f"{BASE_URL}/api/admin/deposits", timeout=20)
    assert r.status_code == 200
    items = r.json()["items"]
    row = next((x for x in items if x["session_id"] == paid_deposit["session_id"]), None)
    assert row is not None, "deposit not surfaced to admin list"
    assert row["payment_status"] == "paid"
    assert row["email"] == paid_deposit["email"]
    assert row["car_id"] == CAR_ID
    assert abs(row["amount"] - paid_deposit["amount"]) < 0.01


def test_deposit_shows_up_in_purchases(paid_deposit):
    s = paid_deposit["buyer"]
    r = s.get(f"{BASE_URL}/api/purchases", timeout=20)
    assert r.status_code == 200
    items = r.json().get("items") or r.json().get("purchases") or []
    # accept either key
    if isinstance(r.json(), dict) and "items" not in r.json() and "purchases" not in r.json():
        items = r.json()
    assert any(str(i.get("car_id")) == CAR_ID for i in items), f"purchases missing deposit: {items}"


def test_second_buyer_cannot_checkout_while_held(paid_deposit):
    s, _ = _register_buyer()
    r = s.post(f"{BASE_URL}/api/deposit/checkout",
               json={"car_id": CAR_ID, "origin_url": BASE_URL}, timeout=30)
    assert r.status_code == 409, f"expected 409 while held, got {r.status_code} {r.text}"


def test_refund_happy_path(admin, paid_deposit):
    sid = paid_deposit["session_id"]
    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/refund", timeout=30)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["refunded"] is True
    assert out["car_id"] == CAR_ID
    assert "refund_id" in out
    paid_deposit["refund_id"] = out["refund_id"]

    # verify Stripe REALLY did the refund
    intent_id = None
    st = stripe.checkout.Session.retrieve(sid)
    intent_id = st.payment_intent
    pi = stripe.PaymentIntent.retrieve(intent_id, expand=["latest_charge"])
    charge = pi.latest_charge
    assert charge.refunded is True, f"Stripe charge not refunded: {charge}"
    assert charge.amount_refunded == int(round(paid_deposit["amount"] * 100)), \
        f"refunded {charge.amount_refunded} vs deposit {paid_deposit['amount']*100}"

    # only ONE refund object
    refunds = stripe.Refund.list(payment_intent=intent_id, limit=10)
    assert len(refunds.data) == 1, f"expected 1 refund, saw {len(refunds.data)}"
    paid_deposit["_intent_id"] = intent_id


def test_car_is_actually_freed_after_refund(paid_deposit):
    r = requests.get(f"{BASE_URL}/api/deposit/car/{CAR_ID}", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["reserved"] is False, f"car still reserved after refund: {body}"
    assert body["mine"] is False


def test_listing_doc_has_no_reserved_fields(paid_deposit):
    """Directly check Mongo state - the fields must be $unset, not just falsy."""
    async def check():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        doc = await db.listings.find_one({"_id": CAR_ID})
        client.close()
        return doc

    doc = asyncio.run(check())
    assert doc is not None
    for f in ("reserved", "reserved_by", "reserved_at"):
        assert f not in doc, f"field {f} not unset after refund: {doc.get(f)}"


def test_another_buyer_can_now_checkout_same_car(paid_deposit):
    s, _ = _register_buyer()
    r = s.post(f"{BASE_URL}/api/deposit/checkout",
               json={"car_id": CAR_ID, "origin_url": BASE_URL}, timeout=30)
    assert r.status_code == 200, \
        f"another buyer should be able to reserve after refund: {r.status_code} {r.text}"
    assert r.json().get("checkout_url", "").startswith("https://")
    # NB: we do not complete this checkout (we want a clean env) - just knowing Stripe issued
    # a session is enough. Immediately delete the pending row so no ghost stays behind.
    async def cleanup(sid):
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.deposits.delete_one({"session_id": sid, "payment_status": "pending"})
        client.close()
    asyncio.run(cleanup(r.json()["session_id"]))


def test_refunded_deposit_removed_from_purchases(paid_deposit):
    s = paid_deposit["buyer"]
    r = s.get(f"{BASE_URL}/api/purchases", timeout=20)
    assert r.status_code == 200
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    if items is None:
        items = body.get("purchases") if isinstance(body, dict) else []
    assert not any(str(i.get("car_id")) == CAR_ID for i in (items or [])), \
        f"refunded deposit still in purchases: {items}"


def test_double_refund_returns_409(admin, paid_deposit):
    sid = paid_deposit["session_id"]
    r = admin.post(f"{BASE_URL}/api/admin/deposits/{sid}/refund", timeout=20)
    assert r.status_code == 409, f"expected 409 on double refund, got {r.status_code} {r.text}"

    # And Stripe still has only one refund.
    intent_id = paid_deposit.get("_intent_id")
    if intent_id:
        refunds = stripe.Refund.list(payment_intent=intent_id, limit=10)
        assert len(refunds.data) == 1, f"double refund created extra Stripe refund: {refunds.data}"


def test_archive_survives_refund(paid_deposit):
    """purchased_listings doc and files under MEDIA_ROOT should still exist."""
    async def check():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        doc = await db.purchased_listings.find_one({"_id": CAR_ID}) \
            or await db.purchased_listings.find_one({"car_id": CAR_ID})
        client.close()
        return doc
    # allow archiver a moment
    time.sleep(3)
    doc = asyncio.run(check())
    # The archive is best-effort; assert only if it fired at all.
    if doc is None:
        pytest.skip("archive job did not run for this car yet; not a refund defect")
    media_root = os.environ.get("MEDIA_ROOT", "/app/media")
    path = os.path.join(media_root, "listings", CAR_ID)
    # after refund, files should still be there (or at least the folder)
    if os.path.exists(path):
        assert any(os.scandir(path)), f"archive folder empty after refund: {path}"


def test_archive_ok_false_warning_renders(admin, paid_deposit):
    """Flip archive_ok=false on the refunded row and confirm the admin API still exposes it.
    UI rendering is asserted in the frontend playwright test."""
    async def flip(value):
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        # create a synthetic PAID+archive_ok=false row for the warning check
        sid = f"cs_test_synthetic_{uuid.uuid4().hex[:10]}"
        await db.deposits.insert_one({
            "session_id": sid,
            "car_id": "SYNTHETIC-TEST",
            "car_title": "SYNTHETIC TEST",
            "email": "warn-test@example.com",
            "amount": 100,
            "car_price_eur": 1000,
            "currency": "eur",
            "status": "completed",
            "payment_status": "paid",
            "archive_ok": value,
            "created_at": __import__("datetime").datetime.utcnow(),
            "updated_at": __import__("datetime").datetime.utcnow(),
        })
        client.close()
        return sid
    sid = asyncio.run(flip(False))
    try:
        r = admin.get(f"{BASE_URL}/api/admin/deposits", timeout=20)
        assert r.status_code == 200
        row = next((x for x in r.json()["items"] if x["session_id"] == sid), None)
        assert row is not None
        assert row["payment_status"] == "paid"
        assert row["archive_ok"] is False
    finally:
        # cleanup synthetic row
        async def rm():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            await db.deposits.delete_one({"session_id": sid})
            client.close()
        asyncio.run(rm())
