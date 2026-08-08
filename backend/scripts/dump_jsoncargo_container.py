"""What does JSONCargo actually hold for this container? Every field, no truncation.

One live call, so the answer is the provider's own words rather than a guess.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import jsoncargo  # noqa: E402

BOX = os.environ.get("BOX", "MRKU3210827")


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    snap = await jsoncargo.container(db, BOX, refresh=True)
    print("=== raw container snapshot ===")
    print(json.dumps(snap, ensure_ascii=False, indent=1, default=str))
    print("\n=== what route() makes of it ===")
    print(json.dumps(jsoncargo.route(snap), ensure_ascii=False, indent=1))
    print("\n=== what to_events() makes of it ===")
    for e in jsoncargo.to_events(snap):
        print(" ", json.dumps(e, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
