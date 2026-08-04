import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

import archive  # noqa: E402


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    doc = await archive.archive(db, "42259236")
    print("photos archived:", doc["photo_count"], "of", doc["expected_photos"])
    print("first url:", doc["photos"][0] if doc["photos"] else None)
    print("has listing:", bool(doc["listing"]), "has detail:", bool(doc["detail"]))


asyncio.run(main())
