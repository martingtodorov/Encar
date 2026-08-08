"""Why does BL 272520178 come back `found: false` when the provider answers 200?

Calls the tracking layer in-process and prints each stage, so the answer is observed rather
than guessed.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import jsoncargo  # noqa: E402
import tracking  # noqa: E402

REF = os.environ.get("REF", "272520178")


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    tracking.set_db(db) if hasattr(tracking, "set_db") else None

    boxes = await jsoncargo.containers_for_bol(db, REF, refresh=False)
    print("containers_for_bol ->", boxes)
    snap = None
    if boxes:
        snap = await jsoncargo.container(db, boxes[0] if isinstance(boxes[0], str)
                                        else boxes[0].get("number"), refresh=False)
    print("container snapshot ->", type(snap).__name__)
    if isinstance(snap, dict):
        print("  keys:", list(snap)[:16])
        print("  route:", jsoncargo.route(snap))
        for e in jsoncargo.to_events(snap):
            print("   ", {k: e.get(k) for k in ("code", "text", "when", "location",
                                                "estimated")})

    out = await tracking.track(db, REF, "bol", refresh=False)
    print("\ntracking.track -> found:", out.get("found"), "| status:", out.get("status"))
    print("  milestones:", len(out.get("milestones") or []))
    print("  customs:", out.get("customs"))
    print("  keys:", list(out))


if __name__ == "__main__":
    asyncio.run(main())
