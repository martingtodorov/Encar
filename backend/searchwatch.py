"""New-match alerts for saved searches.

A saved search is a standing order: "tell me when a car like this turns up". The stored
query is a URL query string full of English slugs (the same string the page reads), so it
is resolved back to the upstream values the index speaks and re-run after every catalogue
sync, filtered to ads we indexed for the FIRST time since the last check.

`first_seen` is the marker, not `last_seen` or the crawl id: a car that was already in the
index and simply got re-crawled is not news, and a re-registered duplicate is hidden by
`build_query` anyway.

The baseline is per (person, search) and is set WITHOUT alerting on the first pass —
otherwise turning alerts on would mail out the whole catalogue.
"""
import asyncio
import logging
from urllib.parse import parse_qs

import mailer
import notify
import slugs as slugs_mod
import translate

log = logging.getLogger("searchwatch")

# Enough to be useful in one email without turning it into a catalogue.
MAX_ROWS = 6
FLAGS = ("only_inspection", "only_record", "only_diagnosed")
INTS = ("year_min", "year_max", "mileage_min", "mileage_max")
FLOATS = ("price_min", "price_max")


def _num(raw, cast):
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return None


async def _payload(db, query):
    """A stored query string -> the search parameters `build_query` understands."""
    p = parse_qs(query or "")

    def one(key):
        return (p.get(key) or [""])[0].strip()

    tax = await slugs_mod.resolve_taxonomy(
        db, one("make"), one("model"), one("badge"), one("badgeDetail"))

    async def flat(dim, raw):
        tokens = [t for t in raw.split("~") if t]
        if not tokens:
            return []
        by_slug, _ = await slugs_mod.facet_slugs(db, dim)
        return [by_slug.get(t, t) for t in tokens]

    out = {
        "makes": [tax["make"]] if tax.get("make") else [],
        "models": [tax["model"]] if tax.get("model") else [],
        "badges": [tax["badge"]] if tax.get("badge") else [],
        "badge_details": [tax["badge_detail"]] if tax.get("badge_detail") else [],
        "fuels": await flat("fuel", one("fuels")),
        "regions": await flat("region", one("regions")),
        # Transmission is stored raw — it has no slug dimension.
        "transmissions": [t for t in one("transmissions").split("~") if t],
    }
    for key in INTS:
        out[key] = _num(one(key), int)
    for key in FLOATS:
        out[key] = _num(one(key), float)
    for key in FLAGS:
        out[key] = one(key) == "1"
    return out


def _title(car):
    return " ".join(str(x) for x in [car.get("manufacturer_t") or car.get("manufacturer"),
                                     car.get("model_t") or car.get("model")] if x)


async def run(db, notify_first_seen=False):
    """Alert every buyer whose saved search has picked up cars since the last check."""
    import server                                    # deferred: server imports this module

    checked = matched = sent = baselines = 0
    now = notify._now()

    async for user in db.users.find({"saved_searches": {"$exists": True, "$ne": []}}):
        wants_email = notify.wants(user, "email", "saved_search") and user.get("email")
        wants_push = notify.wants(user, "push", "saved_search")
        if not (wants_email or wants_push):
            continue

        for saved in user.get("saved_searches") or []:
            if not (saved.get("alerts") and saved.get("id")):
                continue
            checked += 1
            key = f"{user['_id']}:{saved['id']}"
            seen = await db.search_watch.find_one({"_id": key})
            # A search whose filters were changed starts over: the old baseline described a
            # different question.
            if not seen or seen.get("query") != (saved.get("query") or ""):
                await db.search_watch.update_one(
                    {"_id": key},
                    {"$set": {"user_id": user["_id"], "search_id": saved["id"],
                              "query": saved.get("query") or "", "at": now}},
                    upsert=True)
                baselines += 1
                if not notify_first_seen:
                    continue
            since = (seen or {}).get("at") or now

            try:
                params = await _payload(db, saved.get("query") or "")
            except Exception as e:                    # noqa: BLE001 - one bad query, not all
                log.warning("saved search %s could not be read: %s", saved["id"], str(e)[:140])
                continue
            q = server.build_query(params)
            q["first_seen"] = {"$gt": since}
            cars = await db.listings.find(
                q, {"manufacturer": 1, "model": 1, "manufacturer_t": 1, "model_t": 1,
                    "sale_eur": 1, "year_month": 1, "mileage": 1}
            ).sort("first_seen", -1).limit(MAX_ROWS).to_list(MAX_ROWS)
            total = await db.listings.count_documents(q)
            await db.search_watch.update_one({"_id": key}, {"$set": {"at": now}})
            if not cars:
                continue
            matched += total

            await _english(db, cars)
            rows = [{"title": _title(c) or c["_id"], "car_id": c["_id"],
                     "price_eur": c.get("sale_eur") or 0,
                     "year": (c.get("year_month") or 0) // 100 or None,
                     "mileage": c.get("mileage")} for c in cars]
            lang = saved.get("lang") or "en"
            name = saved.get("name") or ""

            if wants_email:
                await mailer.send_new_matches(user["email"], name, rows, total, lang)
                sent += 1
            if wants_push:
                await notify.push_to_user(
                    user["_id"],
                    "New cars match your search",
                    f"{total} new for “{name}”" if name else f"{total} new cars match",
                    url=f"/{lang}/searches", event="saved_search")

    log.info("search watch: %s searches, %s baselines, %s new cars, %s emails",
             checked, baselines, matched, sent)
    return {"searches": checked, "baselines": baselines, "matches": matched, "emails": sent}


async def _english(db, cars):
    """Makes and models are proper nouns — always the English cache, never localised."""
    try:
        await translate.translate_listings(db, cars, "en",
                                          fields=("manufacturer", "model"), background=False)
    except Exception as e:                            # noqa: BLE001 - a name is not the point
        log.warning("could not translate cars for the match alert: %s", str(e)[:140])


def run_later(db):
    """Fire and forget after a sync: nobody is waiting on this."""
    async def go():
        try:
            await run(db)
        except Exception as e:                        # noqa: BLE001
            log.exception("search watch failed: %s", str(e)[:200])

    asyncio.create_task(go())
