"""Catalogue sync + repricing.

Why a local index at all: user searches must cause ZERO upstream calls, must
support unlimited pagination depth, and must be able to filter/sort by the
computed landed EUR price - something encar.com itself cannot do.

Why it is cheap: the list endpoint accepts limit=500 and has no offset cap, so
the entire ~218k catalogue is ~436 requests, not 218k.

Politeness: one worker, EncarClient enforces the min interval, exponential
backoff on 429/5xx. No IP rotation of any kind.
"""

import asyncio
import logging
from datetime import datetime, timezone

from pymongo import UpdateOne

import fx as fx_mod
import pricing
from encar import encar, normalise_row

log = logging.getLogger("sync")

PAGE = 500
# Transmission is not in the list payload but IS an upstream facet.
MANUAL_Q = "(And.Hidden.N._.CarType.A._.Transmission.\uc218\ub3d9.)"

_lock = asyncio.Lock()


async def get_state(db):
    return await db.sync_state.find_one({"_id": "catalogue"}) or {
        "_id": "catalogue", "status": "idle", "pages_done": 0, "pages_total": 0,
        "listings": 0, "upserted": 0,
    }


async def _set(db, **fields):
    await db.sync_state.update_one({"_id": "catalogue"}, {"$set": fields}, upsert=True)


async def ensure_indexes(db):
    await db.listings.create_index([("active", 1), ("duplicate", 1), ("recency", 1)])
    await db.listings.create_index([("active", 1), ("duplicate", 1), ("sale_eur", 1)])
    await db.listings.create_index([("active", 1), ("duplicate", 1), ("mileage", 1)])
    await db.listings.create_index([("active", 1), ("duplicate", 1), ("form_year", -1)])
    await db.listings.create_index([("vehicle_key", 1), ("recency", 1)])
    await db.listings.create_index([("manufacturer", 1), ("model", 1)])
    await db.listings.create_index([("fuel_type", 1)])
    await db.listings.create_index([("region", 1)])
    await db.listings.create_index([("transmission", 1)])
    await db.listings.create_index([("diagnosed", 1)])
    await db.translations.create_index([("lang", 1)])
    await db.car_details.create_index([("fetched_at", -1)])


def _search_text(doc):
    return " ".join(filter(None, [doc.get("manufacturer"), doc.get("model"),
                                 doc.get("badge"), doc.get("fuel_type")]))


async def run_full_sync(db, max_pages=None, page_size=PAGE):
    """Page the whole catalogue into MongoDB, pricing each listing as we go."""
    if _lock.locked():
        return {"started": False, "reason": "sync already running"}

    async def _job():
        async with _lock:
            started = datetime.now(timezone.utc)
            try:
                await _set(db, status="running", started_at=started, error=None,
                           pages_done=0, upserted=0)
                rates = await fx_mod.get_rates(db)
                sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
                S = pricing.merge_settings(sdoc.get("constants"))

                total = await encar.count()
                pages = (total + page_size - 1) // page_size
                if max_pages:
                    pages = min(pages, max_pages)
                await _set(db, listings_upstream=total, pages_total=pages)
                log.info("full sync: %s listings across %s pages", total, pages)

                seen_ids = set()
                upserted = 0
                for p in range(pages):
                    offset = p * page_size
                    data = await encar.search(offset=offset, limit=page_size)
                    rows = (data or {}).get("SearchResults") or []
                    if not rows:
                        log.info("sync: empty page at offset %s, stopping", offset)
                        break

                    ops = []
                    now = datetime.now(timezone.utc)
                    for i, row in enumerate(rows):
                        doc = normalise_row(row, recency=offset + i)
                        if not doc["_id"] or not doc["price_krw"]:
                            continue
                        landed, sale = pricing.quick_sale_eur(
                            doc["price_krw"], rates["fx_krw_eur"], rates["usd_eur"], S)
                        doc["landed_eur"] = round(landed, 2)
                        doc["sale_eur"] = sale
                        doc["search_text"] = _search_text(doc)
                        doc["last_seen"] = now
                        seen_ids.add(doc["_id"])
                        ops.append(UpdateOne(
                            {"_id": doc["_id"]},
                            {"$set": doc, "$setOnInsert": {"first_seen": now}},
                            upsert=True))
                    if ops:
                        res = await db.listings.bulk_write(ops, ordered=False)
                        upserted += (res.upserted_count or 0) + (res.modified_count or 0)

                    await _set(db, pages_done=p + 1, upserted=upserted,
                               listings=await db.listings.count_documents({}))

                # Sold cars vanish from Encar's search -> retire anything not seen,
                # but ONLY after a complete sweep, never a partial one.
                retired = 0
                if not max_pages:
                    r = await db.listings.update_many(
                        {"_id": {"$nin": list(seen_ids)}, "active": True},
                        {"$set": {"active": False,
                                  "retired_at": datetime.now(timezone.utc)}})
                    retired = r.modified_count

                await tag_transmission(db)
                dedupe = await dedupe_pass(db)

                # Pre-translate the bounded label sets so user searches are pure
                # cache hits (and therefore instant) in all three languages.
                warm = {}
                try:
                    from translate import warm_translations
                    warm = await warm_translations(db)
                except Exception as e:
                    log.warning("warm-up failed: %s", e)

                tax = {}
                try:
                    tax = await build_taxonomy(db)
                except Exception as e:
                    log.warning("taxonomy build failed: %s", e)

                await _set(db, status="idle", finished_at=datetime.now(timezone.utc),
                           retired=retired, dedupe=dedupe, taxonomy=tax,
                           warm_translations={"fields": len(warm)},
                           listings=await db.listings.count_documents({}),
                           active_listings=await db.listings.count_documents({"active": True}),
                           duration_s=(datetime.now(timezone.utc) - started).total_seconds(),
                           encar_stats=dict(encar.stats))
                log.info("full sync done: %s upserted, %s retired", upserted, retired)
            except Exception as e:
                log.exception("sync failed")
                await _set(db, status="error", error=str(e)[:400],
                           finished_at=datetime.now(timezone.utc))

    asyncio.create_task(_job())
    return {"started": True}


async def tag_transmission(db):
    """Only ~1,200 of ~218,000 cars are manual, so we fetch just the manual ones
    (3 requests) and treat everything else as automatic. Cheap and exact, with no
    per-car enrichment."""
    try:
        manual_ids = []
        total = await encar.count(MANUAL_Q)
        pages = max((total + PAGE - 1) // PAGE, 1)
        for p in range(pages):
            data = await encar.search(offset=p * PAGE, limit=PAGE, q=MANUAL_Q)
            rows = (data or {}).get("SearchResults") or []
            if not rows:
                break
            manual_ids += [str(r.get("Id")) for r in rows if r.get("Id")]

        if manual_ids:
            await db.listings.update_many({"_id": {"$in": manual_ids}},
                                          {"$set": {"transmission": "manual"}})
        await db.listings.update_many(
            {"_id": {"$nin": manual_ids}},
            {"$set": {"transmission": "auto"}})
        log.info("transmission tagged: %s manual", len(manual_ids))
        return len(manual_ids)
    except Exception as e:
        log.warning("transmission tagging failed: %s", e)
        return 0


async def dedupe_pass(db):
    """Encar carries many duplicate ads for the same physical car (dealers re-register
    listings under fresh IDs). Roughly 30% of rows are duplicates, so without this the
    grid shows the same car several times.

    We group by `vehicle_key` (parsed from the photo path, which embeds the underlying
    vehicleId) and keep the FRESHEST ad - lowest `recency`, since the catalogue is paged
    newest-first. The rest stay in the collection but are flagged and hidden from search.
    """
    try:
        await db.listings.update_many({}, {"$set": {"duplicate": False}})

        pipe = [
            {"$match": {"active": True}},
            {"$sort": {"recency": 1}},
            {"$group": {"_id": "$vehicle_key",
                        "keep": {"$first": "$_id"},
                        "ids": {"$push": "$_id"},
                        "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]

        losers = []
        groups = 0
        async for g in db.listings.aggregate(pipe, allowDiskUse=True):
            groups += 1
            losers += [i for i in g["ids"] if i != g["keep"]]
            if len(losers) >= 5000:
                await db.listings.update_many({"_id": {"$in": losers}},
                                              {"$set": {"duplicate": True}})
                losers = []
        if losers:
            await db.listings.update_many({"_id": {"$in": losers}},
                                          {"$set": {"duplicate": True}})

        hidden = await db.listings.count_documents({"active": True, "duplicate": True})
        unique = await db.listings.count_documents({"active": True, "duplicate": False})
        log.info("dedupe: %s duplicate groups, %s ads hidden, %s unique cars",
                 groups, hidden, unique)
        return {"groups": groups, "hidden": hidden, "unique": unique}
    except Exception as e:
        log.warning("dedupe failed: %s", e)
        return {"error": str(e)}


TAXONOMY_TTL_DAYS = 7


async def build_taxonomy(db):
    """Precompute the Make -> Model -> Trim -> Sub-trim tree into its own collection.

    Doing this on demand meant ~20s per dropdown (a full aggregation over the whole
    listings collection plus blocking translation). Precomputed + indexed, each level
    is a single indexed lookup, so the dropdowns open instantly. Refreshed on every
    sync and at most weekly on demand.
    """
    levels = [
        (1, ["manufacturer"]),
        (2, ["manufacturer", "model"]),
        (3, ["manufacturer", "model", "badge"]),
        (4, ["manufacturer", "model", "badge", "badge_detail"]),
    ]
    total = 0
    docs = []
    for level, fields in levels:
        match = {"active": True, "duplicate": {"$ne": True}}
        for f in fields:
            match[f] = {"$nin": [None, ""]}
        pipe = [
            {"$match": match},
            {"$group": {"_id": {f: f"${f}" for f in fields}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        async for d in db.listings.aggregate(pipe, allowDiskUse=True):
            key = d["_id"]
            leaf = fields[-1]
            docs.append({
                "level": level,
                "value": key[leaf],
                "count": d["count"],
                "make": key.get("manufacturer", ""),
                "model": key.get("model", ""),
                "badge": key.get("badge", ""),
                "badge_detail": key.get("badge_detail", ""),
            })
            total += 1
            if len(docs) >= 4000:
                await db.taxonomy_new.insert_many(docs, ordered=False)
                docs = []
    if docs:
        await db.taxonomy_new.insert_many(docs, ordered=False)

    # atomic-ish swap so the dropdowns never see a half-built tree
    await db.taxonomy_new.create_index([("level", 1), ("make", 1), ("model", 1),
                                       ("badge", 1), ("count", -1)])
    try:
        await db.taxonomy.drop()
    except Exception:
        pass
    await db.taxonomy_new.rename("taxonomy", dropTarget=True)
    await db.taxonomy.create_index([("level", 1), ("make", 1), ("model", 1),
                                   ("badge", 1), ("count", -1)])
    await db.sync_state.update_one(
        {"_id": "taxonomy"},
        {"$set": {"built_at": datetime.now(timezone.utc), "nodes": total}},
        upsert=True)
    log.info("taxonomy built: %s nodes", total)
    return {"nodes": total}


async def taxonomy_is_stale(db):
    doc = await db.sync_state.find_one({"_id": "taxonomy"})
    if not doc or not doc.get("built_at"):
        return True
    age = datetime.now(timezone.utc) - doc["built_at"].replace(tzinfo=timezone.utc)
    return age.days >= TAXONOMY_TTL_DAYS


async def reprice_all(db, batch=5000):
    """Landed price is derived from FX + editable constants, so it must be recomputed
    whenever either changes. ~218k docs in one sweep."""
    rates = await fx_mod.get_rates(db)
    sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
    S = pricing.merge_settings(sdoc.get("constants"))

    updated = 0
    ops = []
    cursor = db.listings.find({}, {"price_krw": 1})
    async for doc in cursor:
        krw = doc.get("price_krw") or 0
        if not krw:
            continue
        landed, sale = pricing.quick_sale_eur(krw, rates["fx_krw_eur"], rates["usd_eur"], S)
        ops.append(UpdateOne({"_id": doc["_id"]},
                             {"$set": {"landed_eur": round(landed, 2), "sale_eur": sale}}))
        if len(ops) >= batch:
            await db.listings.bulk_write(ops, ordered=False)
            updated += len(ops)
            ops = []
    if ops:
        await db.listings.bulk_write(ops, ordered=False)
        updated += len(ops)

    await db.settings.update_one(
        {"_id": "pricing"},
        {"$set": {"last_repriced_at": datetime.now(timezone.utc),
                  "last_repriced_count": updated,
                  "last_repriced_rates": {k: rates[k] for k in ("fx_krw_eur", "usd_eur")}}},
        upsert=True)
    log.info("repriced %s listings", updated)
    return updated
