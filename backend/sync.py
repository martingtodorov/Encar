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
import os
from datetime import datetime, timezone

from pymongo import UpdateOne

import fx as fx_mod
import pricing
from encar import BASE_Q, encar, normalise_row

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
    # supports the dedupe keep-order (insurance history first, see dedupe_pass)
    await db.listings.create_index([("active", 1), ("has_record", -1),
                                    ("has_inspection", -1), ("photo_count", -1),
                                    ("recency", 1)])
    await db.listings.create_index([("last_crawl", 1)])
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
                        if (row.get("SellType") or "") in EXCLUDED_SELL_TYPES:
                            continue
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


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive partitioned crawler
#
# Why: offset pagination on this API is NOT stable. Measured on Mercedes with a
# 13,065-row result set (well under the 20,000 offset ceiling) a full 500-per-page
# sweep returned 13,500 rows but only 10,444 DISTINCT ids - the ModifiedDate sort
# window shifts under us while we page, so rows are silently skipped/repeated.
# Raising the page count cannot fix that.
#
# So we never paginate. We recursively bisect the result set on numeric facets
# until every leaf holds <= 500 rows, which one single request returns in full.
# Verified exact: for any node, count(left) + count(right) == count(parent), on
# Price, Year and Mileage, and the dimensions compose freely. That lets us take
# the right-hand count by subtraction, so each node costs exactly one request.
# ─────────────────────────────────────────────────────────────────────────────

LEAF_MAX = 500          # a single request returns at most this many rows
DEFAULT_RECENCY = 10_000_000
# 리스 (lease) and 렌트 (rental) cars are owned by a finance/rental company, not the
# seller, so they cannot be exported. They are dropped at import time, never indexed.
EXCLUDED_SELL_TYPES = {"\ub9ac\uc2a4", "\ub80c\ud2b8"}

# Split order. Bounds only control bisection granularity: the lowest band is
# emitted open-ended (`range(..hi)`) and the highest too (`range(lo..)`), so
# values outside these bounds are still captured, never lost.
DIM_ORDER = ["Price", "Year", "Mileage"]
DIM_BOUNDS = {
    "Price": (0, 100_000),          # 만원
    "Year": (198001, 209912),       # YYYYMM
    "Mileage": (0, 2_000_000),      # km
}


def _q(clauses):
    """Build the upstream query from a list of facet clauses, on top of the shared base
    (which already restricts to regular-sale, non-lease, non-rental cars)."""
    body = "".join(f"_.{c}." for c in clauses)
    return f"{BASE_Q[:-1]}{body})"


def _dim_clauses(dims):
    """dims: list of (name, lo, hi). Emit a clause only for narrowed dimensions."""
    out = []
    for name, lo, hi in dims:
        glo, ghi = DIM_BOUNDS[name]
        if lo <= glo and hi >= ghi:
            continue
        if lo <= glo:
            out.append(f"{name}.range(..{hi})")
        elif hi >= ghi:
            out.append(f"{name}.range({lo}..)")
        else:
            out.append(f"{name}.range({lo}..{hi})")
    return out


def _fresh_dims():
    return [(n, DIM_BOUNDS[n][0], DIM_BOUNDS[n][1]) for n in DIM_ORDER]


async def _crawl_node(base, dims, count, sink, st):
    """Recursively bisect until the node fits in one request, then fetch it."""
    if count <= 0:
        return
    clauses = base + _dim_clauses(dims)

    if count <= LEAF_MAX:
        data = await encar.search(offset=0, limit=LEAF_MAX, q=_q(clauses))
        rows = (data or {}).get("SearchResults") or []
        st["leaves"] += 1
        st["rows"] += len(rows)
        st["expected"] += count
        if len(rows) < count:
            # upstream shrank/grew between the count probe and the fetch - benign
            st["short_leaves"] += 1
        await sink(rows)
        return

    # too big: bisect the first dimension that still has room
    for i, (name, lo, hi) in enumerate(dims):
        if hi <= lo:
            continue
        mid = lo + (hi - lo) // 2
        left = dims[:i] + [(name, lo, mid)] + dims[i + 1:]
        right = dims[:i] + [(name, mid + 1, hi)] + dims[i + 1:]

        lcount = await encar.count(_q(base + _dim_clauses(left)))
        rcount = max(count - lcount, 0)   # exact: siblings partition the parent
        st["probes"] += 1
        await _crawl_node(base, left, lcount, sink, st)
        await _crawl_node(base, right, rcount, sink, st)
        return

    # every dimension collapsed and still over a page: unsplittable bucket.
    # Page it and accept that the upstream window may not be perfectly stable.
    log.warning("unsplittable partition (%s rows): %s", count, _q(clauses))
    st["unsplittable"] += 1
    for off in range(0, min(count, 20_000), LEAF_MAX):
        data = await encar.search(offset=off, limit=LEAF_MAX, q=_q(clauses))
        rows = (data or {}).get("SearchResults") or []
        if not rows:
            break
        st["rows"] += len(rows)
        await sink(rows)


async def crawl_partitioned(db, manufacturers=None, run_id=None, retire=True,
                            progress_key="catalogue_partition"):
    """Index a scope (whole catalogue, or a list of manufacturers) exactly.

    Lease cars are dropped. Listings that exist in our index for the crawled scope
    but no longer come back from upstream are marked inactive, so sold cars leave
    the search results.
    """
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rates = await fx_mod.get_rates(db)
    sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
    S = pricing.merge_settings(sdoc.get("constants"))

    st = {"leaves": 0, "probes": 0, "rows": 0, "expected": 0, "short_leaves": 0,
          "unsplittable": 0, "excluded_skipped": 0, "written": 0}
    seen = set()

    async def sink(rows):
        ops = []
        now = datetime.now(timezone.utc)
        for row in rows:
            if (row.get("SellType") or "") in EXCLUDED_SELL_TYPES:
                st["excluded_skipped"] += 1
                continue
            doc = normalise_row(row)
            if not doc["_id"] or not doc["price_krw"]:
                continue
            landed, sale = pricing.quick_sale_eur(
                doc["price_krw"], rates["fx_krw_eur"], rates["usd_eur"], S)
            doc["landed_eur"] = round(landed, 2)
            doc["sale_eur"] = sale
            doc["search_text"] = _search_text(doc)
            doc["last_seen"] = now
            doc["last_crawl"] = run_id
            doc.pop("retired_at", None)
            seen.add(doc["_id"])
            ops.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": doc,
                 "$setOnInsert": {"first_seen": now, "recency": DEFAULT_RECENCY}},
                upsert=True))
        if ops:
            await db.listings.bulk_write(ops, ordered=False)
            st["written"] += len(ops)

    scope = list(manufacturers) if manufacturers else [None]
    per_make = {}
    started = datetime.now(timezone.utc)

    for mfr in scope:
        base = [f"Manufacturer.{mfr}"] if mfr else []
        total = await encar.count(_q(base))
        before = len(seen)
        before_excluded = st["excluded_skipped"]
        await _set(db, **{f"{progress_key}_current": mfr or "ALL"})
        log.info("partition crawl start: %s upstream=%s", mfr or "ALL", total)

        await _crawl_node(base, _fresh_dims(), total, sink, st)

        got = len(seen) - before
        excluded = st["excluded_skipped"] - before_excluded
        # lease/rental cars are intentionally dropped, so completeness is measured
        # against the exportable subset of the upstream count
        reachable = max(total - excluded, 0)
        per_make[mfr or "ALL"] = {
            "upstream": total, "excluded_skipped": excluded, "reachable": reachable,
            "distinct_kept": got,
            "coverage": round(got / reachable, 4) if reachable else 0,
        }
        log.info("partition crawl done: %s upstream=%s excluded=%s distinct=%s leaves=%s",
                 mfr or "ALL", total, excluded, got, st["leaves"])
        await db.sync_state.update_one(
            {"_id": progress_key},
            {"$set": {"run_id": run_id, "stats": st, "per_make": per_make,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True)

    retired = 0
    if retire:
        scope_q = {"active": True, "last_crawl": {"$ne": run_id}}
        if manufacturers:
            scope_q["manufacturer"] = {"$in": list(manufacturers)}
        r = await db.listings.update_many(
            scope_q, {"$set": {"active": False,
                               "retired_at": datetime.now(timezone.utc)}})
        retired = r.modified_count

    result = {
        "run_id": run_id, "stats": st, "per_make": per_make,
        "distinct_ids": len(seen), "retired": retired,
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "encar_requests": encar.stats["requests"],
    }
    await db.sync_state.update_one(
        {"_id": progress_key},
        {"$set": {**result, "finished_at": datetime.now(timezone.utc)}}, upsert=True)
    return result


async def tag_transmission(db, manufacturers=None):
    """Only ~1,200 of ~218,000 cars are manual, so we fetch just the manual ones
    (3 requests) and treat everything else as automatic. Cheap and exact, with no
    per-car enrichment."""
    try:
        manual_ids = []
        scopes = list(manufacturers) if manufacturers else [None]
        for mfr in scopes:
            q = (MANUAL_Q if not mfr else
                 _q([f"Manufacturer.{mfr}", "Transmission.\uc218\ub3d9"]))
            manual_ids += await _collect_manual(q)

        if manual_ids:
            await db.listings.update_many({"_id": {"$in": manual_ids}},
                                          {"$set": {"transmission": "manual"}})
        untagged = {"_id": {"$nin": manual_ids}}
        if manufacturers:
            untagged["manufacturer"] = {"$in": list(manufacturers)}
        await db.listings.update_many(untagged, {"$set": {"transmission": "auto"}})
        log.info("transmission tagged: %s manual", len(manual_ids))
        return len(manual_ids)
    except Exception as e:
        log.warning("transmission tagging failed: %s", e)
        return 0


async def _collect_manual(q):
    ids = []
    total = await encar.count(q)
    pages = max((total + PAGE - 1) // PAGE, 1)
    for p in range(pages):
        data = await encar.search(offset=p * PAGE, limit=PAGE, q=q)
        rows = (data or {}).get("SearchResults") or []
        if not rows:
            break
        ids += [str(r.get("Id")) for r in rows if r.get("Id")]
    return ids


async def dedupe_pass(db):
    """Encar carries many duplicate ads for the same physical car (dealers re-register
    listings under fresh IDs). Roughly 30% of rows are duplicates, so without this the
    grid shows the same car several times.

    We group by `vehicle_key` (parsed from the photo path, which embeds the underlying
    vehicleId) and keep the MOST INFORMATIVE ad, not merely the newest one. Duplicate
    ads for one physical car are not equivalent: typically only one of them carries the
    insurance history (`Record`), and the other shows nothing on the detail page. So the
    keep-order is:
        1. has insurance history       (Record)
        2. has inspection report       (Inspection)
        3. has performance/resume doc  (Resume)
        4. most photos
        5. freshest ad (lowest `recency`)
    The rest stay in the collection but are flagged and hidden from search.
    """
    try:
        await db.listings.update_many({}, {"$set": {"duplicate": False}})

        pipe = [
            {"$match": {"active": True}},
            {"$sort": {"has_record": -1, "has_inspection": -1, "has_resume": -1,
                       "photo_count": -1, "recency": 1}},
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


# The catalogue is continuously re-crawled, so dropdown counts drift within hours.
# A weekly TTL froze them at whatever the first build of the week saw.
TAXONOMY_TTL_HOURS = float(os.environ.get("TAXONOMY_TTL_HOURS", "6"))
_TAX_BUILDING = {"on": False}


BRAND_COVERAGE_KEY = "brand_coverage"
_COVERAGE_RUNNING = {"on": False}


async def refresh_brand_coverage(db):
    """True per-brand coverage: our indexed count vs Encar's own live count.

    One count-only upstream request per make (~60 requests, politely paced). The base
    query already excludes lease/rental, so `upstream` is the exportable population and
    the ratio is honest rather than flattered by cars we deliberately skip.
    """
    if _COVERAGE_RUNNING["on"]:
        return {"running": True}
    _COVERAGE_RUNNING["on"] = True
    started = datetime.now(timezone.utc)
    await db.sync_state.update_one(
        {"_id": BRAND_COVERAGE_KEY},
        {"$set": {"status": "running", "started_at": started, "brands": [],
                  "done": 0, "total": 0}},
        upsert=True)
    try:
        pipe = [
            {"$match": {"active": True, "manufacturer": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$manufacturer",
                        "ads": {"$sum": 1},
                        "unique": {"$sum": {"$cond": [{"$eq": ["$duplicate", True]}, 0, 1]}}}},
            {"$sort": {"ads": -1}},
        ]
        ours = [d async for d in db.listings.aggregate(pipe, allowDiskUse=True)]
        await db.sync_state.update_one({"_id": BRAND_COVERAGE_KEY},
                                       {"$set": {"total": len(ours)}})
        brands = []
        for i, row in enumerate(ours):
            make = row["_id"]
            try:
                upstream = await encar.count(_q([f"Manufacturer.{make}"]))
            except Exception as e:
                log.warning("brand count failed for %s: %s", make, str(e)[:120])
                upstream = None
            brands.append({
                "make": make,
                "upstream": upstream,
                "ads": row["ads"],
                "unique": row["unique"],
                "coverage": round(row["ads"] / upstream, 4) if upstream else None,
            })
            await db.sync_state.update_one(
                {"_id": BRAND_COVERAGE_KEY},
                {"$set": {"brands": brands, "done": i + 1}})
        await db.sync_state.update_one(
            {"_id": BRAND_COVERAGE_KEY},
            {"$set": {"status": "idle", "finished_at": datetime.now(timezone.utc),
                      "duration_s": round(
                          (datetime.now(timezone.utc) - started).total_seconds(), 1)}})
        log.info("brand coverage refreshed for %s makes", len(brands))
        return {"brands": len(brands)}
    except Exception as e:
        log.warning("brand coverage refresh failed: %s", e)
        await db.sync_state.update_one({"_id": BRAND_COVERAGE_KEY},
                                       {"$set": {"status": "error", "error": str(e)[:300]}})
        return {"error": str(e)[:300]}
    finally:
        _COVERAGE_RUNNING["on"] = False


async def get_brand_coverage(db):
    doc = await db.sync_state.find_one({"_id": BRAND_COVERAGE_KEY})
    if not doc:
        return {"status": "never", "brands": [], "done": 0, "total": 0}
    return {k: v for k, v in doc.items() if k != "_id"}


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
    return age.total_seconds() >= TAXONOMY_TTL_HOURS * 3600


async def refresh_taxonomy_if_stale(db):
    """Keep dropdown counts fresh without ever making a user wait for the rebuild.

    A rebuild is a full aggregation over ~212k listings, so it runs in the background
    and the (slightly older) tree keeps serving meanwhile. Only a completely missing
    taxonomy is built inline, because there is nothing to serve otherwise.
    """
    if not await taxonomy_is_stale(db):
        return
    if await db.taxonomy.estimated_document_count() == 0:
        await build_taxonomy(db)
        return
    if _TAX_BUILDING["on"]:
        return

    async def _job():
        _TAX_BUILDING["on"] = True
        try:
            await build_taxonomy(db)
        except Exception as e:
            log.warning("background taxonomy rebuild failed: %s", e)
        finally:
            _TAX_BUILDING["on"] = False

    asyncio.get_running_loop().create_task(_job())


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
