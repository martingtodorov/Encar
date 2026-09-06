"""The odometer-fingerprint dedupe pass: one physical car, one ad on the site.

`vehicle_key` (the vehicleId embedded in the photo path) only groups a re-registered ad
with the original while the dealer KEEPS the original photo folder. When the photos are
re-uploaded, the new ad's folder is named after its own id, the key falls back to that id,
and both ads stay live — which is how the same car appeared twice in the grid and in
"Picked for you". Make + model + trim + registration month + the exact odometer reading is
the fingerprint that catches those, and it must not touch two genuinely different cars.

Each test owns one `asyncio.run`: motor binds a client to the loop it is created on, and
sharing a loop across fixtures in a suite that also builds its own is how the previous
version of this file ended up talking to a closed one.
"""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

import sync


def _ad(ad_id, **over):
    doc = {"_id": ad_id, "active": True, "vehicle_key": ad_id,
           "manufacturer": "BMW", "model": "M2 (G87)", "badge": "M2 Coupe",
           "year_month": 202403, "mileage": 12_345, "price_krw": 90_000_000,
           "photo_count": 8, "recency": 100,
           "has_record": False, "has_inspection": False, "has_resume": False}
    doc.update(over)
    return doc


def dedupe(ads):
    """Seed a throwaway database, run the real pass, hand back the result and survivors."""
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        name = f"{os.environ['DB_NAME']}_test_dedupe_{os.getpid()}_{id(ads)}"
        db = client[name]
        try:
            await db.listings.insert_many(ads)
            out = await sync.dedupe_pass(db)
            kept = [d async for d in db.listings.find(
                {"active": True, "duplicate": {"$ne": True}}).sort([("_id", 1)])]
            return out, [d["_id"] for d in kept]
        finally:
            await client.drop_database(name)
            client.close()

    return asyncio.run(run())


def test_relisted_ad_with_fresh_photos_is_hidden():
    """Two ads, two photo folders, one car — only the informative one stays visible."""
    out, kept = dedupe([
        _ad("relisted", recency=10),                       # newer ad, no history
        _ad("original", has_record=True, recency=900),     # older ad, carries the history
    ])
    assert out["twins"] == 1
    assert out["unique"] == 1
    # The keep-order is about information, not freshness: the ad with the insurance history
    # is the one a buyer should land on.
    assert kept == ["original"]


def test_different_cars_are_left_alone():
    """Same model and month, different odometer readings: two real cars."""
    out, kept = dedupe([
        _ad("car-a", mileage=12_345),
        _ad("car-b", mileage=40_002),
        _ad("car-c", mileage=12_345, year_month=202312),
        _ad("car-d", mileage=12_345, model="M4 (G82)"),
    ])
    assert out["twins"] == 0
    assert len(kept) == 4


def test_missing_mileage_never_groups():
    """A zero odometer is unknown, not a match — otherwise every such ad would collapse."""
    out, kept = dedupe([
        _ad("no-km-1", mileage=0),
        _ad("no-km-2", mileage=0),
        _ad("no-km-3", mileage=None),
    ])
    assert out["twins"] == 0
    assert len(kept) == 3


def test_vehicle_key_pass_still_runs_first():
    """The original grouping is untouched: a shared vehicle_key still collapses."""
    out, kept = dedupe([
        _ad("ad-1", vehicle_key="99887766", mileage=1_000),
        _ad("ad-2", vehicle_key="99887766", mileage=2_000, has_record=True),
    ])
    assert out["groups"] == 1
    assert kept == ["ad-2"]
