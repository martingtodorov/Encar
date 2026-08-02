"""One-off: reprice every listing against the current buffered FX rate.

Needed whenever the FX haircut or the pricing constants change, because listings store a
precomputed sale_eur while detail pages quote live. The fx watchdog does this
automatically on rate drift; this script is the manual trigger.

Run from /app/backend:  python reprice.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
import fx as fx_mod  # noqa: E402
import sync as sync_mod  # noqa: E402


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        rates = await fx_mod.get_rates(db)
        print(f"market  {rates['fx_krw_eur_market']}")
        print(f"haircut {rates['fx_haircut']}")
        print(f"using   {rates['fx_krw_eur']}")
        n = await sync_mod.reprice_all(db)
        print("repriced:", n)
        await db.fx.update_one({"_id": "rates"}, {"$unset": {"reprice_needed": ""}})
    finally:
        client.close()


asyncio.run(main())
