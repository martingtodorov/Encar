"""Can Maersk's own page give us the full point-by-point history? Test before promising.

JSONCargo only holds a summary — probed and confirmed — so this is the only source for the
gate-in / load / discharge / gate-out detail the owner wants shown.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ["MAERSK_PUBLIC_TRACK"] = "1"          # the point of the test

import maersk_public  # noqa: E402

REF = os.environ.get("REF", "272520178")


async def main():
    print("enabled:", maersk_public.enabled())
    raw = await maersk_public.read(REF)
    if not raw:
        print("no answer from the public page")
        return
    print("keys:", list(raw)[:12] if isinstance(raw, dict) else type(raw).__name__)
    events = raw.get("events") or raw.get("milestones") or [] if isinstance(raw, dict) else []
    print("events:", len(events))
    for e in events:
        print("  ", json.dumps(e, ensure_ascii=False, default=str)[:170])
    if isinstance(raw, dict):
        for k in ("route", "destination", "pod", "final_destination", "vessel"):
            if raw.get(k):
                print(f"{k}:", json.dumps(raw[k], ensure_ascii=False, default=str)[:200])


if __name__ == "__main__":
    asyncio.run(main())
