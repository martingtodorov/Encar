"""Operator script: how much of the visible Korean label set is still untranslated."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
import translate as T  # noqa: E402


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for level, field in ((1, "manufacturer"), (2, "model"), (3, "badge"), (4, "badge_detail")):
        values = [d["value"] async for d in db.taxonomy.find({"level": level}, {"value": 1})]
        for lang in T.LANGS:
            cached = await T.translate_cached_only(db, values, lang)
            print(f"{field:14s} {lang}  {len(cached):5d}/{len(values):5d} cached, "
                  f"{len(values) - len(cached):5d} missing")
    print("translations cached total:", await db.translations.count_documents({}))


asyncio.run(main())
