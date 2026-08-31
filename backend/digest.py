"""The weekly saved-search digest.

One email a week per buyer, on Saturday afternoon, covering every saved search that has
picked something up since the last digest - with the cars' own photos, because a buyer decides
from the picture long before they read the mileage.

Why a digest instead of the instant mail it replaces: the catalogue syncs daily, so a standing
search on a common car used to mean an email a day, each with one or two cars in it. The same
news arrives here as one letter worth opening.

The window is per (person, search) and stored separately from the alert baseline
(`search_watch.digest_at` next to `at`): push notifications still go out as soon as a car
appears, and their marker moves with every sync, so the digest cannot share it or it would
only ever see the last few hours.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import mailer
import notify
import searchwatch
import translate

log = logging.getLogger("digest")

# Saturday at 15:00 in Sofia, as the owner asked. Monday is 0, so Saturday is 5.
WEEKDAY = 5
HOUR = 15
MINUTE = 0
TZ = "Europe/Sofia"

SETTINGS_ID = "search_digest"
# Twelve cars per search with a photo each keeps the letter around a few hundred kilobytes,
# which is well inside what Gmail will show without clipping it.
PER_SEARCH = 12
# A first digest for a brand-new search looks back a week rather than at the whole catalogue.
FIRST_WINDOW = timedelta(days=7)

FIELDS = {"manufacturer": 1, "model": 1, "manufacturer_t": 1, "model_t": 1,
          "sale_eur": 1, "year_month": 1, "mileage": 1, "photos": 1}


def _now():
    return datetime.now(timezone.utc)


async def _new_cars(db, saved, since):
    """The cars this saved search has picked up since `since`, newest first."""
    import server                                     # deferred: server imports this module

    params = await searchwatch._payload(db, saved.get("query") or "")
    q = server.build_query(params)
    q["first_seen"] = {"$gt": since}
    cars = await db.listings.find(q, FIELDS).sort("first_seen", -1).limit(PER_SEARCH) \
        .to_list(PER_SEARCH)
    total = await db.listings.count_documents(q) if cars else 0
    return cars, total


async def top_viewed(db, limit=6, days=7):
    """The week's most opened ads, counted by DISTINCT people.

    The owner's rule: one buyer refreshing an ad two hundred times must not put it in the
    email. `car_views.u` is the distinct-viewer count that `_first_view_today` maintains, so
    that rule holds here for free. We over-fetch and then filter, because the most looked-at
    car of the week is often the one that has just been sold.
    """
    since = (_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = await db.car_views.aggregate([
        {"$match": {"day": {"$gte": since}}},
        {"$group": {"_id": "$car_id", "people": {"$sum": {"$ifNull": ["$u", "$n"]}}}},
        {"$sort": {"people": -1}},
        {"$limit": limit * 6},
    ]).to_list(limit * 6)
    if not rows:
        return []
    seen = {r["_id"]: r["people"] for r in rows}
    cars = await db.listings.find(
        {"_id": {"$in": list(seen)}, "sold": {"$ne": True}}, FIELDS).to_list(limit * 6)
    cars.sort(key=lambda c: seen.get(c["_id"], 0), reverse=True)
    cars = cars[:limit]
    if not cars:
        return []
    await searchwatch._english(db, cars)
    return [{
        "car_id": c["_id"],
        "title": searchwatch._title(c) or c["_id"],
        "image": mailer.car_thumb(c.get("photos")),
        "price_eur": c.get("sale_eur") or 0,
        "year": (c.get("year_month") or 0) // 100 or None,
        "mileage": c.get("mileage"),
        "people": seen.get(c["_id"], 0),
    } for c in cars]


async def run(db, force=False):
    """Send this week's digest. Returns a small report for the admin screen and the tests."""
    users = mails = groups_sent = 0
    now = _now()
    # Same list for everybody: it is the week's news, not a personal recommendation, and one
    # aggregation is cheaper than one per buyer.
    popular = await top_viewed(db)

    async for user in db.users.find({"saved_searches": {"$exists": True, "$ne": []}}):
        if not (user.get("email") and notify.wants(user, "email", "saved_search")):
            continue
        users += 1
        groups, touched, lang = [], [], "en"

        for saved in user.get("saved_searches") or []:
            if not (saved.get("alerts") and saved.get("id")):
                continue
            key = f"{user['_id']}:{saved['id']}"
            mark = await db.search_watch.find_one({"_id": key}) or {}
            since = mark.get("digest_at") or (now - FIRST_WINDOW)
            try:
                cars, total = await _new_cars(db, saved, since)
            except Exception as e:                     # noqa: BLE001 - one bad query, not all
                log.warning("digest: search %s unreadable: %s", saved["id"], str(e)[:140])
                continue
            touched.append(key)
            if not cars:
                continue
            await searchwatch._english(db, cars)
            lang = saved.get("lang") or lang
            groups.append({
                "name": saved.get("name") or "",
                "total": total,
                "cars": [{
                    "car_id": c["_id"],
                    "title": searchwatch._title(c) or c["_id"],
                    "image": mailer.car_thumb(c.get("photos")),
                    "price_eur": c.get("sale_eur") or 0,
                    "year": (c.get("year_month") or 0) // 100 or None,
                    "mileage": c.get("mileage"),
                } for c in cars],
            })

        # Nothing new means no letter: an empty digest teaches people to ignore the next one.
        if not groups:
            continue
        await mailer.send_search_digest(user["email"], groups, lang, popular=popular)
        mails += 1
        groups_sent += len(groups)
        # Only advance the window for searches we actually reported on, so a car that arrived
        # while the mail was going out is in the NEXT digest rather than lost.
        for key in touched:
            await db.search_watch.update_one({"_id": key}, {"$set": {"digest_at": now}},
                                             upsert=True)

    log.info("saved-search digest: %s buyers, %s emails, %s searches reported",
             users, mails, groups_sent)
    return {"buyers": users, "emails": mails, "searches": groups_sent,
            "at": now.isoformat()}


async def scheduler(db, period=45):
    """Fire once on the chosen local weekday and minute.

    The date guard is what makes it once-a-week rather than once-a-minute for an hour: the run
    is stamped, and a stamp from today is enough to skip.
    """
    while True:
        await asyncio.sleep(period)
        try:
            local = datetime.now(ZoneInfo(TZ))
            if local.weekday() != WEEKDAY or local.hour != HOUR or local.minute != MINUTE:
                continue
            today = local.date().isoformat()
            doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
            if doc.get("last_run_date") == today:
                continue
            await db.settings.update_one({"_id": SETTINGS_ID},
                                        {"$set": {"last_run_date": today}}, upsert=True)
            log.info("weekly saved-search digest firing for %s", today)
            result = await run(db)
            await db.settings.update_one({"_id": SETTINGS_ID},
                                        {"$set": {"last_result": result}}, upsert=True)
        except Exception as e:                         # noqa: BLE001 - a loop must not die
            log.warning("digest scheduler: %s", str(e)[:200])


def next_run_at():
    """When the next digest goes out, for the admin dashboard."""
    local = datetime.now(ZoneInfo(TZ))
    target = local.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    days = (WEEKDAY - local.weekday()) % 7
    target += timedelta(days=days)
    if target <= local:
        target += timedelta(days=7)
    return target.astimezone(timezone.utc).isoformat()
