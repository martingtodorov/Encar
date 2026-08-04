"""Keep a purchased car forever, on our own disk.

Once a buyer pays a deposit, the ad stops being Encar's to withdraw: their listing can
disappear the same week, and the buyer would be left with a receipt for a car they can no
longer look at. So at the moment the deposit lands we copy the listing data AND every photo
to our own storage, and the purchases page reads only from that copy.

Photos are fetched once and never again: the files are immutable, so an archive that already
has them is left alone.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

import encar
from encar import encar as client

log = logging.getLogger("archive")

MEDIA_ROOT = Path(os.environ["MEDIA_ROOT"])
MEDIA_URL = "/api/media"
PARALLEL_DOWNLOADS = 6


def _dir(car_id):
    return MEDIA_ROOT / "listings" / str(car_id)


async def _download(client, path, target):
    if target.exists() and target.stat().st_size > 0:
        return True
    url = encar.image_url(path, 1600, 1200)
    try:
        r = await client.get(url, headers=encar.HEADERS, timeout=30)
        r.raise_for_status()
    except (httpx.HTTPError, httpx.StreamError) as e:
        log.warning("photo %s failed: %s", path, str(e)[:120])
        return False
    tmp = target.with_suffix(".part")
    tmp.write_bytes(r.content)
    # Renamed only once it is whole, so a half-written file is never served.
    tmp.rename(target)
    return True


async def archive(db, car_id):
    """Copy one listing and its photos to our storage. Safe to call again."""
    car_id = str(car_id)
    listing = await db.listings.find_one({"_id": car_id})
    if not listing:
        log.warning("nothing to archive for %s", car_id)
        return None

    cached = await db.car_details.find_one({"_id": car_id})
    detail = (cached or {}).get("detail") or {}
    if not detail:
        # The buyer paid without the detail ever being opened, or the cache was cleared.
        detail = await client.detail(car_id) or {}

    paths = encar.detail_photo_paths(detail)
    folder = _dir(car_id)
    folder.mkdir(parents=True, exist_ok=True)

    saved = []
    limit = asyncio.Semaphore(PARALLEL_DOWNLOADS)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def one(index, path):
            async with limit:
                name = f"{index:03d}.jpg"
                ok = await _download(client, path, folder / name)
                return name if ok else None

        results = await asyncio.gather(
            *(one(i + 1, p) for i, p in enumerate(paths)), return_exceptions=True)
    saved = [f"{MEDIA_URL}/listings/{car_id}/{r}"
             for r in results if isinstance(r, str) and r]

    doc = {
        "_id": car_id,
        "listing": listing,
        "detail": detail,
        "record": (cached or {}).get("record"),
        "inspection": (cached or {}).get("inspection"),
        "diagnosis": (cached or {}).get("diagnosis"),
        "choice_options": (cached or {}).get("choice_options") or [],
        "photos": saved,
        "photo_count": len(saved),
        "expected_photos": len(paths),
        "archived_at": datetime.now(timezone.utc),
    }
    await db.purchased_listings.update_one({"_id": car_id}, {"$set": doc}, upsert=True)
    log.info("archived %s: %d/%d photos", car_id, len(saved), len(paths))
    return doc


def archive_later(db, car_id):
    """Fire and forget: a webhook must answer Stripe now, not after 20 photo downloads."""
    async def run():
        ok = False
        try:
            doc = await archive(db, car_id)
            ok = bool(doc and doc.get("photo_count"))
        except Exception as e:                      # noqa: BLE001 - never break the payment
            log.exception("archiving %s failed: %s", car_id, e)
        # A paid deposit whose archive failed is otherwise invisible: the buyer's car would
        # quietly lose its page the day Encar withdraws the ad. Recorded on the deposit so
        # a query finds it, rather than only a line in the log.
        await db.deposits.update_many({"car_id": str(car_id)},
                                      {"$set": {"archive_ok": ok}})

    asyncio.create_task(run())
