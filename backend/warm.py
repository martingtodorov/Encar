"""One-off translation cache warm-up (operator script).

Pre-translates the bounded label sets (makes, models, submodels, fuels, regions) in
every language so the dropdowns and search results are pure cache hits.

Usage (from /app/backend):
    python warm.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

from translate import warm_translations  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "encar_skin")]
    try:
        stats = await warm_translations(db)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        print("translations cached:", await db.translations.count_documents({}))
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
