"""Operator script: show the live FX bundle and where EUR/KRW came from."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
import fx as fx_mod  # noqa: E402


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        r = await fx_mod.get_rates(db, force=True)
        for k in ("fx_krw_eur_market", "fx_haircut", "fx_krw_eur", "krw_source",
                  "source", "usd_eur", "eur_ron", "manual_overrides"):
            print(f"{k:20s} {r.get(k)}")
    finally:
        client.close()


asyncio.run(main())
