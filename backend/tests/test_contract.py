"""Contract on the payment page: rendering, buyer details, the Word file, admin template.

Run with: cd /app/backend && python -m pytest tests/test_contract.py -q
"""
import io
import os
import sys
import uuid
import zipfile
from datetime import datetime, timezone

import pytest
import requests

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)


def _env(key):
    for line in open(os.path.join(BACKEND, ".env")):
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


API = f"{_env('PUBLIC_SITE_URL') or os.environ.get('REACT_APP_BACKEND_URL')}/api"
ADMIN = {"x-admin-token": _env("ADMIN_TOKEN")}
PASSWORD = "SecurityTest2026!"


@pytest.fixture(scope="module")
def buyer():
    """A throwaway account holding a paid deposit on a real car with a VIN."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio

    email = f"contract-{uuid.uuid4().hex[:8]}@example.com"
    s = requests.Session()
    r = s.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    session_id = f"cs_test_{uuid.uuid4().hex}"

    async def seed():
        client = AsyncIOMotorClient(_env("MONGO_URL"))
        db = client[_env("DB_NAME")]
        # A car we have already archived, so the Korean plate is on file. Encar publishes no
        # VIN at all, which is why the contract carries the plate and leaves the VIN blank.
        archived = await db.purchased_listings.find_one({"detail.vehicleNo": {"$nin": [None, ""]}},
                                                       {"detail.vehicleNo": 1})
        car = await db.listings.find_one({"_id": archived["_id"]}, {"_id": 1, "sale_eur": 1})
        car["plate"] = archived["detail"]["vehicleNo"]
        car["sale_eur"] = car.get("sale_eur") or 49199
        user = await db.users.find_one({"email": email})
        await db.deposits.insert_one({
            "session_id": session_id, "car_id": car["_id"],
            "car_title": "Mercedes-Benz C-Class W205", "user_id": user["_id"], "email": email,
            "amount": round(car["sale_eur"] * 0.1, 2), "currency": "eur",
            "car_price_eur": car["sale_eur"], "lang": "bg", "status": "completed",
            "payment_status": "paid", "created_at": datetime.now(timezone.utc),
        })
        client.close()
        return car, user["_id"]

    car, uid = asyncio.run(seed())
    yield {"session": s, "email": email, "session_id": session_id,
           "car": car, "user_id": uid}

    async def clean():
        client = AsyncIOMotorClient(_env("MONGO_URL"))
        db = client[_env("DB_NAME")]
        await db.deposits.delete_one({"session_id": session_id})
        await db.users.delete_one({"_id": uid})
        client.close()

    asyncio.run(clean())


def test_contract_renders_with_ad_and_account_data(buyer):
    r = buyer["session"].get(f"{API}/contract/{buyer['session_id']}", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["lang"] == "bg", "the contract speaks the language the deposit was paid in"
    assert d["contract_no"], "every contract needs a number"
    text = d["text"]
    assert buyer["car"]["plate"] in text, "the Korean plate must come off the ad"
    assert "Mercedes-Benz C-Class W205" in text
    assert buyer["email"] in text, "the account's email is a party detail"
    assert "208414795" in text, "the seller's company number is in the parties block"
    # Nothing the buyer has not filled in yet is invented.
    assert set(d["missing"]) == {"buyer_name", "buyer_egn", "buyer_id_no", "buyer_id_date",
                                "buyer_id_issuer", "buyer_address", "buyer_phone"}
    assert "\u2026" in text, "an unfilled field shows as the dotted blank of the paper form"


def test_buyer_details_are_saved_and_appear(buyer):
    details = {
        "buyer_name": "Иван Иванов Иванов",
        "buyer_egn": "8001011234",
        "buyer_id_no": "123456789",
        "buyer_id_date": "01.02.2020",
        "buyer_id_issuer": "МВР София",
        "buyer_address": "гр. София, ул. Тест 1",
        "buyer_phone": "+359888123456",
    }
    r = buyer["session"].put(f"{API}/contract/{buyer['session_id']}", json=details, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["missing"] == [], "nothing should be missing once every field is answered"
    for value in details.values():
        assert value in d["text"], f"{value} is not in the contract"

    # Saved on the account, so it survives a reload and the next purchase.
    again = buyer["session"].get(f"{API}/contract/{buyer['session_id']}", timeout=30).json()
    assert again["buyer"]["buyer_egn"] == details["buyer_egn"]


def test_word_file_is_a_real_docx_carrying_the_text(buyer):
    r = buyer["session"].get(f"{API}/contract/{buyer['session_id']}/docx", timeout=60)
    assert r.status_code == 200, r.text
    assert "wordprocessingml" in r.headers["content-type"]
    assert ".docx" in r.headers.get("content-disposition", "")
    z = zipfile.ZipFile(io.BytesIO(r.content))          # a docx is a zip; a broken one raises
    xml = z.read("word/document.xml").decode("utf-8")
    assert "Иван Иванов Иванов" in xml
    assert buyer["car"]["plate"] in xml


def test_language_can_be_switched(buyer):
    ro = buyer["session"].get(f"{API}/contract/{buyer['session_id']}",
                              params={"lang": "ro"}, timeout=30).json()
    assert ro["lang"] == "ro"
    assert "BENEFICIAR" in ro["text"]
    en = buyer["session"].get(f"{API}/contract/{buyer['session_id']}",
                              params={"lang": "en"}, timeout=30).json()
    assert "CLIENT" in en["text"]


def test_a_stranger_cannot_read_someone_elses_contract(buyer):
    other = requests.Session()
    email = f"nosy-{uuid.uuid4().hex[:8]}@example.com"
    other.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD}, timeout=30)
    r = other.get(f"{API}/contract/{buyer['session_id']}", timeout=30)
    assert r.status_code == 404, "another buyer's contract must not be readable"
    assert requests.get(f"{API}/contract/{buyer['session_id']}", timeout=30).status_code == 401


class TestAdminTemplate:
    def test_read(self):
        r = requests.get(f"{API}/admin/contract-template", headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d["langs"]) == {"bg", "ro", "en"}
        assert "vin" in d["placeholders"] and "buyer_egn" in d["placeholders"]
        assert d["seller"]["eik"] == "208414795"

    def test_edit_then_reset(self, buyer):
        marker = f"КЛАУЗА-ТЕСТ-{uuid.uuid4().hex[:6]}"
        body = requests.get(f"{API}/admin/contract-template",
                            headers=ADMIN, timeout=30).json()["bodies"]["bg"]
        r = requests.put(f"{API}/admin/contract-template", headers=ADMIN, timeout=30,
                         json={"bodies": {"bg": body + f"\n{marker} {{{{plate}}}}\n"}})
        assert r.status_code == 200, r.text

        seen = buyer["session"].get(f"{API}/contract/{buyer['session_id']}", timeout=30).json()
        assert marker in seen["text"], "an edited template must reach the buyer at once"
        assert seen["text"].count(buyer["car"]["plate"]) >= 2, "the new placeholder must fill in"

        requests.post(f"{API}/admin/contract-template/reset", headers=ADMIN,
                      params={"lang": "bg"}, timeout=30)
        after = buyer["session"].get(f"{API}/contract/{buyer['session_id']}", timeout=30).json()
        assert marker not in after["text"], "reset must restore the shipped wording"

    def test_unauthenticated_cannot_edit(self):
        assert requests.put(f"{API}/admin/contract-template",
                            json={"bodies": {"bg": "hijacked"}}, timeout=30).status_code == 401
