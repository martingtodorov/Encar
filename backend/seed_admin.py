"""Seed the admin test account used by the testing agent. Idempotent.

Run from /app/backend:  python seed_admin.py
"""
import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from webauthn.helpers import bytes_to_base64url

load_dotenv(Path(__file__).parent / ".env")
from auth import ph  # noqa: E402

# NOTE: not a .test/.local address - pydantic's EmailStr rejects reserved TLDs, so a
# seeded account on one of those can never actually sign in through /api/auth/login.
EMAIL = "admin@encarskin.com"
# Kept in backend/.env (ADMIN_SEED_PASSWORD), never in source. No default on purpose: a
# missing value should stop the seed rather than quietly create a guessable account.
PASSWORD = os.environ["ADMIN_SEED_PASSWORD"]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        existing = await db.users.find_one({"email_norm": EMAIL})
        doc = {
            "email": EMAIL,
            "email_norm": EMAIL,
            "name": "Admin (test)",
            "password_hash": ph.hash(PASSWORD),
            "is_admin": True,
        }
        if existing:
            await db.users.update_one({"_id": existing["_id"]}, {"$set": doc})
            print("updated existing admin:", existing["_id"])
        else:
            doc.update({
                "_id": str(uuid.uuid4()),
                "webauthn_user_id": bytes_to_base64url(secrets.token_bytes(32)),
                "favourites": [],
                "created_at": datetime.now(timezone.utc),
            })
            await db.users.insert_one(doc)
            print("created admin:", doc["_id"])
        print("email:", EMAIL)
    finally:
        client.close()


asyncio.run(main())
