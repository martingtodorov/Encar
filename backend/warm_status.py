"""Translation coverage per field and language.

Counts DISTINCT values, not taxonomy nodes: level 3/4 store one node per
make/model/badge/sub-trim PATH, so the same trim string appears under many paths and
counting nodes badly overstates the work left.

Run from /app/backend:  python warm_status.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
import translate as T  # noqa: E402

FIELDS = ((1, "manufacturer"), (2, "model"), (3, "badge"), (4, "badge_detail"))


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        total_missing = 0
        for level, field in FIELDS:
            values = sorted({d["value"] async for d in
                             db.taxonomy.find({"level": level}, {"value": 1})
                             if d.get("value")})
            nodes = await db.taxonomy.count_documents({"level": level})
            for lang in T.LANGS:
                cached = await T.translate_cached_only(db, values, lang)
                missing = len(values) - len(cached)
                total_missing += missing
                flag = "" if missing == 0 else "   <-- run warm.py"
                print(f"{field:14s} {lang}  {len(cached):5d}/{len(values):5d} distinct "
                      f"cached, {missing:5d} missing{flag}")
            print(f"{'':14s}    ({nodes} taxonomy paths collapse to "
                  f"{len(values)} distinct values)")
        print()
        print("translations cached total:", await db.translations.count_documents({}))
        print("COMPLETE" if total_missing == 0 else f"{total_missing} strings outstanding")
    finally:
        client.close()


asyncio.run(main())
