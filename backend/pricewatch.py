"""Price-drop watch for saved cars.

A saved car is a car somebody is still thinking about, and the thing that ends the
thinking is usually the price moving. This keeps a per-person baseline of what each of
their saved cars cost and tells them when it falls.

The baseline is the KRW price, deliberately. Our EUR figures are derived through the
exchange rate, so watching them would fire "the price dropped!" every time the won moved
against the euro overnight — noise that would teach people to ignore the alerts. The won
price only changes when the seller actually changes it. The message still speaks in euros,
because that is the number the buyer cares about.
"""
import asyncio
import logging

import mailer
import notify
import translate

log = logging.getLogger("pricewatch")

# Ignore rounding-level moves: a seller nudging a car by a few thousand won is not news.
MIN_DROP_KRW = 100_000


async def _english(db, cars):
    try:
        await translate.translate_listings(db, cars, "en",
                                          fields=("manufacturer", "model"),
                                          background=False)
    except Exception as e:                          # noqa: BLE001 - a name is not the point
        log.warning("could not translate cars for the price alert: %s", str(e)[:140])


def _title(car):
    return " ".join(str(x) for x in [car.get("manufacturer_t") or car.get("manufacturer"),
                                     car.get("model_t") or car.get("model")] if x)


async def run(db, notify_first_seen=False):
    """Compare every saved car against its baseline and alert on real drops.

    A car seen for the first time only gets a baseline: alerting on it would mean everyone
    is told about a "drop" the moment they save something. A price that ROSE quietly moves
    the baseline up, so a later dip is measured against what the car actually costs now.
    """
    sent = drops = baselines = 0

    async for user in db.users.find({"favourites": {"$exists": True, "$ne": []}}):
        ids = [str(i) for i in (user.get("favourites") or [])]
        if not ids:
            continue
        cars = await db.listings.find(
            {"_id": {"$in": ids}},
            # `photos`, `year_month` and `mileage` are here for the email: it shows the car's
            # own photo and the same facts as the weekly digest, not just a line of text.
            {"manufacturer": 1, "model": 1, "manufacturer_t": 1, "model_t": 1,
             "price_krw": 1, "sale_eur": 1, "active": 1,
             "photos": 1, "year_month": 1, "mileage": 1}).to_list(len(ids))

        fallen = []
        for car in cars:
            krw = car.get("price_krw")
            if not krw or not car.get("active"):
                continue
            key = f"{user['_id']}:{car['_id']}"
            seen = await db.price_watch.find_one({"_id": key})
            if not seen:
                await db.price_watch.update_one(
                    {"_id": key},
                    {"$set": {"user_id": user["_id"], "car_id": car["_id"],
                              "price_krw": krw, "updated_at": notify._now()}},
                    upsert=True)
                baselines += 1
                if not notify_first_seen:
                    continue
            was = (seen or {}).get("price_krw") or krw
            if krw > was:                            # went up: rebase quietly
                await db.price_watch.update_one(
                    {"_id": key}, {"$set": {"price_krw": krw, "updated_at": notify._now()}})
                continue
            if was - krw < MIN_DROP_KRW:
                continue
            fallen.append({"car": car, "was_krw": was, "now_krw": krw})
            await db.price_watch.update_one(
                {"_id": key},
                {"$set": {"price_krw": krw, "updated_at": notify._now(),
                          "notified_at": notify._now()}})

        if not fallen:
            continue
        drops += len(fallen)
        await _english(db, [f["car"] for f in fallen])
        rows = [{"title": _title(f["car"]) or f["car"]["_id"],
                 "car_id": f["car"]["_id"],
                 # Same keys the digest's car block reads, so both emails render identically.
                 "image": mailer.car_thumb(f["car"].get("photos")),
                 "price_eur": f["car"].get("sale_eur") or 0,
                 "year": (f["car"].get("year_month") or 0) // 100 or None,
                 "mileage": f["car"].get("mileage"),
                 "cut_pct": round((f["was_krw"] - f["now_krw"]) / f["was_krw"] * 100, 1)}
                for f in fallen]

        if notify.wants(user, "email", "price_drop") and user.get("email"):
            await mailer.send_price_drop(user["email"], rows)
            sent += 1
        if notify.wants(user, "push", "price_drop"):
            first = rows[0]
            await notify.push_to_user(
                user["_id"],
                "A saved car got cheaper",
                f"{first['title']} is down {first['cut_pct']}%"
                + (f" and {len(rows) - 1} more" if len(rows) > 1 else ""),
                url=f"/en/car/{first['car_id']}",
                event="price_drop")

    log.info("price watch: %s baselines, %s drops, %s emails", baselines, drops, sent)
    return {"baselines": baselines, "drops": drops, "emails": sent}


def run_later(db):
    """Fire and forget after a sync: nobody is waiting on this."""
    async def go():
        try:
            await run(db)
        except Exception as e:                       # noqa: BLE001
            log.exception("price watch failed: %s", str(e)[:200])

    asyncio.create_task(go())
