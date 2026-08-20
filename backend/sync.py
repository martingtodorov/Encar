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
import time
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
                if total is None:
                    raise RuntimeError(
                        "the upstream count request failed - aborting so the retire "
                        "pass does not wipe every active listing")
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
                    gone = set()
                    now = datetime.now(timezone.utc)
                    for i, row in enumerate(rows):
                        if skip_row(row):
                            if contracted(row):
                                gone.add(str(row.get("Id")))
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
                    await retire_contracted(db, gone)

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

                # The dropdown tree, its slugs, the year spans and the translated labels,
                # so the first search after a sync is already warm.
                post = await post_crawl(db)
                warm = post.get("warm") or {}
                tax = post.get("taxonomy") or {}

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
# Dealer placeholder ads: the car is real but the fields are sentinels (Price 99,999 or
# 999,999 만원 = KRW 1bn+, Mileage 999,999 km) used to park a listing without a price.
# They priced out at EUR 667,499 / EUR 6.6m in the grid, so they are dropped at import.
PLACEHOLDER_PRICE_MANWON = 99_999      # KRW 999,990,000
PLACEHOLDER_MILEAGE = 999_999


def contracted(row):
    """Encar has a pending sale on this ad (SalesStatus=CONTRACT)."""
    return (row.get("SalesStatus") or "").upper() == "CONTRACT"


async def retire_contracted(db, ids):
    """Take cars Encar has put under contract out of the catalogue at once.

    `skip_row` already refuses to import them, but a car we indexed while it was still on
    sale would otherwise stay visible until the end-of-sweep retire pass — hours away on a
    full crawl, and never on a partial one.
    """
    if not ids:
        return 0
    res = await db.listings.update_many(
        {"_id": {"$in": list(ids)}, "active": True},
        {"$set": {"active": False, "sold": True, "under_contract": True,
                  "sales_status": "CONTRACT",
                  "sold_at": datetime.now(timezone.utc)}})
    return res.modified_count or 0


def skip_row(row):
    """Cars we never carry: lease, rental, anything already under contract on Encar
    (a contract means it is effectively sold, so listing it wastes a buyer's time), and
    placeholder ads whose price or mileage is a sentinel value."""
    if (row.get("SellType") or "") in EXCLUDED_SELL_TYPES:
        return True
    if float(row.get("Price") or 0) >= PLACEHOLDER_PRICE_MANWON:
        return True
    if int(row.get("Mileage") or 0) >= PLACEHOLDER_MILEAGE:
        return True
    return (row.get("SalesStatus") or "").upper() == "CONTRACT"

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


async def _crawl_node(base, dims, count, sink, st, ctx=None):
    """Recursively bisect until the node fits in one request, then fetch it.

    `ctx` makes the walk resumable: `done` holds the slices already indexed in this run
    (skipped outright) and `plan` caches the bisection counts, so a resumed crawl does not
    re-probe upstream to rediscover the same tree.
    """
    if count <= 0:
        return
    clauses = base + _dim_clauses(dims)
    key = _q(clauses)

    if count <= LEAF_MAX:
        if ctx and key in ctx["done"]:
            st["skipped_leaves"] += 1
            return
        data = await encar.search(offset=0, limit=LEAF_MAX, q=key)
        rows = (data or {}).get("SearchResults") or []
        st["leaves"] += 1
        st["rows"] += len(rows)
        st["expected"] += count
        if len(rows) < count:
            # upstream shrank/grew between the count probe and the fetch - benign
            st["short_leaves"] += 1
        await sink(rows)
        if ctx:
            # Only after the rows are written, so a slice is never marked done twice or
            # skipped without having landed in the index.
            ctx["done"].add(key)
            await ctx["flush"]()
        return

    # too big: bisect the first dimension that still has room
    for i, (name, lo, hi) in enumerate(dims):
        if hi <= lo:
            continue
        mid = lo + (hi - lo) // 2
        left = dims[:i] + [(name, lo, mid)] + dims[i + 1:]
        right = dims[:i] + [(name, mid + 1, hi)] + dims[i + 1:]

        lkey = _q(base + _dim_clauses(left))
        lcount = ctx["plan"].get(lkey) if ctx else None
        if lcount is None:
            lcount = await encar.count(lkey)
            st["probes"] += 1
            if lcount is None:
                # A probe failed. Do NOT split on a fabricated count of 0 - that would
                # skip the whole right sibling and pretend the branch is empty. Bubble
                # the failure so the parent scope can be marked failed too.
                st["probe_failures"] = st.get("probe_failures", 0) + 1
                raise RuntimeError(f"count probe failed for {lkey}")
            if ctx:
                ctx["plan"][lkey] = lcount
        rcount = max(count - lcount, 0)   # exact: siblings partition the parent
        await _crawl_node(base, left, lcount, sink, st, ctx)
        await _crawl_node(base, right, rcount, sink, st, ctx)
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


async def post_crawl(db):
    """Everything that has to be rebuilt after cars change, in the order it has to happen.

    Whichever way the catalogue was crawled, this is what makes the site fast for the FIRST
    visitor: the dropdown tree, its URL slugs, the model year spans, and the translated
    labels. Without it the first search pays for translating a thousand model names while
    somebody waits. Imported locally to keep the module graph flat.
    """
    out = {}
    from translate import warm_translations
    import slugs as slugs_mod
    import curate

    for name, job in (
        ("taxonomy", lambda: build_taxonomy(db)),
        ("slugs", lambda: slugs_mod.ensure_taxonomy_slugs(db, force=True)),
        ("years", lambda: curate.ensure_years(db, force=True)),
        # The facet counts are not refreshed here: /meta/filters serves the cached ones
        # instantly and refreshes behind the visitor, so nobody ever waits for them.
        # Last: it reads the values the steps above have just settled.
        ("warm", lambda: warm_translations(db)),
    ):
        try:
            out[name] = await job()
        except Exception as e:
            log.warning("post-crawl %s failed: %s", name, str(e)[:200])
            out[name] = {"error": str(e)[:200]}
    log.info("post-crawl done: %s", {k: str(v)[:80] for k, v in out.items()})
    return out


async def crawl_partitioned(db, manufacturers=None, run_id=None, retire=True,
                            progress_key="catalogue_partition", resume=False):
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
          "unsplittable": 0, "excluded_skipped": 0, "written": 0, "skipped_leaves": 0}
    seen = set()

    # Resume state, keyed by run_id. `done` is the slices already written, `plan` the
    # bisection counts already probed. Dots are illegal in Mongo field names and every key
    # here is a query string full of them, so both go in as pair arrays.
    resume_id = f"{progress_key}_resume"
    plan, done = {}, set()
    # Cars indexed by the interrupted process. `seen` is per-process, so without this the
    # progress bar would jump backwards on a resume.
    already = 0
    if resume:
        rdoc = await db.sync_state.find_one({"_id": resume_id}) or {}
        if rdoc.get("run_id") == run_id:
            plan = {k: v for k, v in (rdoc.get("plan") or [])}
            done = set(rdoc.get("done") or [])
            already = await db.listings.count_documents({"last_crawl": run_id})
            log.info("resuming crawl %s: %s slices already indexed (%s cars), %s counts "
                     "cached", run_id, len(done), already, len(plan))
        else:
            log.info("no resume state for run %s; crawling from the start", run_id)
    rstate = {"last": 0.0}

    # Live progress for the admin panel. Written at most every few seconds: a crawl does
    # thousands of batches and one write each would cost more than the crawl.
    live_id = f"{progress_key}_live"
    live = {"upstream": 0, "last_write": 0.0}

    async def publish(phase, force=False):
        now = time.monotonic()
        if not force and now - live["last_write"] < 3:
            return
        live["last_write"] = now
        await db.sync_state.update_one(
            {"_id": live_id},
            {"$set": {"phase": phase, "run_id": run_id, "upstream": live["upstream"],
                      "seen": already + len(seen), "written": already + st["written"],
                      "leaves": len(done) or st["leaves"],
                      "probes": st["probes"], "excluded": st["excluded_skipped"],
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True)

    async def sink(rows):
        ops = []
        gone = set()
        now = datetime.now(timezone.utc)
        for row in rows:
            if skip_row(row):
                st["excluded_skipped"] += 1
                if contracted(row):
                    gone.add(str(row.get("Id")))
                continue
            doc = normalise_row(row)
            if not doc["_id"]:
                # Silently dropped upstream rows without an Id were showing up as an
                # unexplained 0.3-0.5% gap between `reachable` and `distinct_kept`. Counting
                # them exposes the number and stops the coverage math from looking wrong.
                st["dropped_no_id"] = st.get("dropped_no_id", 0) + 1
                continue
            if not doc["price_krw"]:
                st["dropped_no_price"] = st.get("dropped_no_price", 0) + 1
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
        await retire_contracted(db, gone)
        await publish("crawl")

    async def flush_resume(force=False):
        now = time.monotonic()
        if not force and now - rstate["last"] < 1:
            return
        rstate["last"] = now
        await db.sync_state.update_one(
            {"_id": resume_id},
            {"$set": {"run_id": run_id, "updated_at": datetime.now(timezone.utc),
                      "plan": [[k, v] for k, v in plan.items()],
                      "done": sorted(done)}},
            upsert=True)

    ctx = {"plan": plan, "done": done, "flush": flush_resume}

    scope = list(manufacturers) if manufacturers else [None]
    per_make = {}
    started = datetime.now(timezone.utc)

    for mfr in scope:
        base = [f"Manufacturer.{mfr}"] if mfr else []
        scope_key = _q(base)
        total = plan.get(scope_key)
        if total is None:
            total = await encar.count(scope_key)
            if total is None:
                # Upstream refused to answer at all (soft-block, 407, network cut). A
                # zero here would silently wipe every listing in this scope — abort so
                # the retire pass never gets the chance.
                raise RuntimeError(
                    f"the upstream count request for {mfr or 'ALL'} failed - aborting "
                    "before the retire pass can run")
            plan[scope_key] = total
        live["upstream"] += total
        await publish("crawl", force=True)
        before = len(seen)
        before_excluded = st["excluded_skipped"]
        await _set(db, **{f"{progress_key}_current": mfr or "ALL"})
        log.info("partition crawl start: %s upstream=%s", mfr or "ALL", total)

        try:
            await _crawl_node(base, _fresh_dims(), total, sink, st, ctx)
        finally:
            # Checkpoint whatever landed, including when the crawl is cancelled by a
            # shutdown: without this the last few seconds of slices are crawled again.
            await flush_resume(force=True)

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
        log.info("partition crawl done: %s upstream=%s excluded=%s distinct=%s leaves=%s "
                 "skipped=%s", mfr or "ALL", total, excluded, got, st["leaves"],
                 st["skipped_leaves"])
        await flush_resume(force=True)
        await db.sync_state.update_one(
            {"_id": progress_key},
            {"$set": {"run_id": run_id, "stats": st, "per_make": per_make,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True)

    # The crawl finished, so there is nothing left to resume from.
    await db.sync_state.delete_one({"_id": resume_id})

    # Sanity gate before retire. If Encar hiccups (429s, DNS, a soft-blocked IP), the
    # count probe silently returns 0 and the crawl indexes nothing - but retire would
    # then mark EVERY active listing inactive. That is what shrank the catalogue day
    # after day. Refuse to retire when the crawl clearly did not cover the scope.
    scope_prev_active_q = {"active": True}
    if manufacturers:
        scope_prev_active_q["manufacturer"] = {"$in": list(manufacturers)}
    scope_prev_active = await db.listings.count_documents(scope_prev_active_q)
    covered = len(seen)
    # Genuine day-over-day catalogue churn is single-digit percent, so the floor is
    # generous. Below ~50% coverage the crawl is almost certainly broken, not the
    # inventory that halved overnight.
    RETIRE_MIN_COVERAGE = float(os.environ.get("RETIRE_MIN_COVERAGE", "0.5"))
    coverage_ratio = covered / scope_prev_active if scope_prev_active else 1.0
    retire_skipped = False
    retire_skip_reason = None
    if retire and scope_prev_active >= 100 and coverage_ratio < RETIRE_MIN_COVERAGE:
        retire_skipped = True
        retire_skip_reason = (
            f"crawl covered only {covered} of {scope_prev_active} previously-active "
            f"listings ({coverage_ratio:.1%}); refusing to retire")
        log.error(retire_skip_reason)
        retire = False

    retired = 0
    if retire:
        scope_q = {"active": True, "last_crawl": {"$ne": run_id}}
        if manufacturers:
            scope_q["manufacturer"] = {"$in": list(manufacturers)}
        r = await db.listings.update_many(
            scope_q, {"$set": {"active": False,
                               "retired_at": datetime.now(timezone.utc)}})
        retired = r.modified_count

    await publish("retire" if retire else "crawl", force=True)
    result = {
        "run_id": run_id, "stats": st, "per_make": per_make,
        "distinct_ids": len(seen), "retired": retired,
        "scope_prev_active": scope_prev_active,
        "coverage_ratio": round(coverage_ratio, 4),
        "retire_skipped": retire_skipped,
        "retire_skip_reason": retire_skip_reason,
        "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "encar_requests": encar.stats["requests"],
    }
    await db.sync_state.update_one(
        {"_id": progress_key},
        {"$set": {**result, "finished_at": datetime.now(timezone.utc)}}, upsert=True)
    # The cars have changed, so the dropdowns, slugs, year spans and labels are stale. This
    # is what stops the first search after a crawl from being the slow one.
    result["post_crawl"] = await post_crawl(db)
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
    if not total:                                    # None (failure) or 0 (empty)
        return ids
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
    # A leftover staging collection (crashed build, or two rebuilds overlapping) would be
    # inserted into again and every node would appear twice in the dropdowns.
    try:
        await db.taxonomy_new.drop()
    except Exception:
        pass

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


async def reprice_if_fx_drifted(db):
    """Reprice the catalogue when fx.get_rates flagged a meaningful rate move.

    Listings store a precomputed sale_eur while detail pages quote live, so a rate move
    that is not followed by a reprice makes the price visibly jump when a buyer clicks
    a search row. Runs at most one pass at a time.
    """
    doc = await db.fx.find_one({"_id": "rates"})
    if not (doc or {}).get("reprice_needed"):
        return {"repriced": 0}
    if _REPRICING["on"]:
        return {"running": True}

    async def _job():
        _REPRICING["on"] = True
        try:
            n = await reprice_all(db)
            await db.fx.update_one({"_id": "rates"}, {"$unset": {"reprice_needed": ""}})
            log.info("fx drift reprice done: %s listings", n)
        except Exception as e:
            log.warning("fx drift reprice failed: %s", e)
        finally:
            _REPRICING["on"] = False

    asyncio.get_running_loop().create_task(_job())
    return {"started": True}


_REPRICING = {"on": False}


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
