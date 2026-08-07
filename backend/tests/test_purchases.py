"""Archive on deposit, and the purchases page that reads it."""
import os
import re
import time

import requests
from conftest import mark_verified
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


def _base():
    env = open("/app/frontend/.env").read()
    return re.search(r"REACT_APP_BACKEND_URL=(\S+)", env).group(1).rstrip("/")


ROOT = _base()
BASE = ROOT + "/api"
PASSWORD = "SecurityTest2026!"
CAR = "42259236"


def test_archived_photos_are_served_from_our_own_disk():
    r = requests.get(f"{ROOT}/api/media/listings/{CAR}/001.jpg", timeout=30)
    assert r.status_code == 200, r.status_code
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 20000, len(r.content)


def test_purchases_lists_the_archived_car():
    s = requests.Session()
    email = f"buy-{int(time.time())}@example.com"
    assert s.post(f"{BASE}/auth/register",
                  json={"email": email, "password": PASSWORD}).status_code == 200
    # A reservation needs a confirmed address; no letter arrives here, so prove it directly.
    mark_verified(email)

    assert s.get(f"{BASE}/purchases").json()["items"] == []

    started = s.post(f"{BASE}/deposit/checkout",
                     json={"car_id": CAR, "origin_url": "https://example.com/en"}).json()

    # Stripe's hosted card form cannot be driven from here, so the payment is confirmed the
    # way the webhook does it, through the same idempotent path.
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db.deposits.update_one({"session_id": started["session_id"]},
                           {"$set": {"payment_status": "paid", "status": "completed"}})
    db.listings.update_one({"_id": CAR}, {"$set": {"reserved": True}})

    rows = s.get(f"{BASE}/purchases").json()["items"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["car_id"] == CAR
    assert row["deposit_eur"] == started["amount_eur"]
    assert row["archived"] is True and row["photo_count"] == 18
    assert row["photo"] == f"/api/media/listings/{CAR}/001.jpg"
    assert row["title"] and row["price_eur"] > 0
    assert row["ref"] == ""            # no bill of lading assigned yet

    # A signed-out visitor has no purchases page at all.
    s.post(f"{BASE}/auth/logout")
    assert s.get(f"{BASE}/purchases").status_code == 401

    db.deposits.delete_many({"session_id": started["session_id"]})
    db.users.delete_one({"email": email})
    db.listings.update_one({"_id": CAR}, {"$unset": {"reserved": "", "reserved_by": ""}})
