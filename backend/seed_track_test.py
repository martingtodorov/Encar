"""Seed one synthetic public-track payload so the Track page can be rendered end to end.

Test scaffolding only — run `python seed_track_test.py --clear` to remove it again.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
import maersk_public as mp  # noqa: E402

REF = "MSKU5285725"
PAYLOAD = {"containers": [{
    "container_id": REF, "bill_of_lading": "271191199",
    "last_vessel_name": "MAERSK SELETAR", "eta_final_destination": "2026-07-20 06:00",
    "events": [
        {"event": "Gate in at first POL", "date": "2026-06-16 09:12",
         "location": {"city": "Busan", "country": "Korea", "unlocode": "KRPUS"}},
        {"activity": "Load on vessel", "actual_date": "2026-06-17 17:28",
         "location": {"city": "Busan", "unlocode": "KRPUS"},
         "vessel": {"name": "MAERSK SELETAR", "imo": "9525338"}, "voyage": "0054E"},
        {"event": "Vessel departure", "actual_date": "2026-06-17 22:40",
         "location": {"city": "Busan", "unlocode": "KRPUS"},
         "vessel": {"name": "MAERSK SELETAR", "imo": "9525338"}},
        {"event": "Vessel arrival", "actual_date": "2026-07-02 11:00",
         "location": {"city": "Singapore", "country": "Singapore", "unlocode": "SGSIN"},
         "vessel": {"name": "MAERSK SELETAR", "imo": "9525338"}},
        {"event": "Vessel arrival", "estimated_date": "2026-07-20 06:00",
         "location": {"city": "Piraeus", "country": "Greece", "unlocode": "GRPIR"},
         "vessel": {"name": "MAERSK SELETAR", "imo": "9525338"}},
        {"event": "Gate out for delivery", "estimated_date": "2026-07-22 08:00",
         "location": {"city": "Piraeus", "unlocode": "GRPIR"}}]}]}


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if "--clear" in sys.argv:
        await db.tracking_cache.delete_many({"seeded_test": True})
        await db.shipments.delete_many({"note": "seeded test shipment"})
        await db.users.update_many({}, {"$pull": {"tracked_shipments": {"ref": REF}}})
        print("cleared")
        return
    events = mp.to_events(PAYLOAD)
    await db.tracking_cache.replace_one(
        {"_id": f"pub:{REF}"},
        {"_id": f"pub:{REF}", "stored_at": datetime.now(timezone.utc), "raw": PAYLOAD,
         "payload": {"empty": False, "events": events}, "seeded_test": True}, upsert=True)
    print(f"seeded {len(events)} events for {REF}; first country={events[0]['country']!r}")

asyncio.run(main())
