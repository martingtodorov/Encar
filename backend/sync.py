"""Catalogue sync + repricing.

Why a local index at all: user searches must cause ZERO upstream calls, must
support unlimited pagination depth, and must be able to filter/sort by the
computed landed EUR price - something encar.com itself cannot do.

Why it is cheap: the list endpoint accepts limit=500 and has no offset cap, so
the entire ~218k catalogue is ~436 requests, not 218k.

Politeness: one worker, EncarClient enforces the min interval, exponential
backoff on 429/5xx. No IP rotation of any kind.

And it is deliberately SLOW. ~436 requests at the client's 1.2s floor is a nine-minute burst,
and a burst is what Encar's WAF answers with 403 — the blocks arrived in runs, right after a
sweep. So the whole sweep is now spread across SYNC_TARGET_SECONDS (two hours by default):
one page roughly every seventeen seconds, jittered, with the database work counted INTO each
page's slot rather than added on top. Nothing is retried harder and no address is rotated; we
simply ask less often.
"""

import asyncio
import contextlib
import logging
import time
import os
import uuid
from datetime import datetime, timezone

from pymongo import UpdateOne

import fx as fx_mod
import pricing
from encar import BASE_Q, EncarUnavailable, encar, normalise_row
import encar as encar_mod

log = logging.getLogger("sync")

PAGE = 500
# How long a FULL catalogue sweep should take, end to end. Two hours for ~420 pages is a page
# every seventeen seconds — slow enough that it does not read as a crawl, fast enough that the
# catalogue is never more than a couple of hours stale. Read at RUNTIME from
# SYNC_TARGET_SECONDS, so the owner can slow it down further from the environment without a
# code deploy (and the tests can turn the waiting off).
SYNC_TARGET_SECONDS = 7200
# Of that budget, the share reserved for the facet passes at the END (gearboxes, colours).
# They used to be unbudgeted: `_collect_ids` opened a FRESH two-hour sweep for every facet
# value, so each of the ~30 colour walks was paced at the 60-second per-request ceiling —
# white alone (80 pages) took eighty minutes and the tail ran for hours. Worse, nothing
# stamped the live document during it, so the stall self-heal restarted a sync that was
# merely crawling politely, and the sync got stuck at "tagging colours" for ever.
SYNC_FACET_SECONDS = int(os.environ.get("SYNC_FACET_SECONDS") or 1200)
# Even a tiny catalogue must not wait forever between pages, and a big one must not be paced
# faster than the client's own floor.
SYNC_PAGE_GAP_MAX = 60
ENCAR_MIN_GAP = 1.2
# A bisecting crawl spends count probes and re-asks split slices, so it makes more requests
# than the leaf-page arithmetic predicts: 200k ads came out as ~1000 slices against 400
# predicted pages. Measured, not guessed, and only a starting estimate — `Sweep` corrects
# itself against the remaining budget on every request.
SYNC_REQUEST_OVERHEAD = 2.5
# Transmission is not in the list payload but IS an upstream facet.
MANUAL_Q = "(And.Hidden.N._.CarType.A._.Transmission.\uc218\ub3d9.)"
# A catalogue bigger than this with not one manual car in it is a failed upstream walk, not
# a fact about Korean cars. Below it (a single-make crawl, a test fixture) zero is believable.
MANUAL_PLAUSIBILITY_FLOOR = int(os.environ.get("MANUAL_PLAUSIBILITY_FLOOR", "5000"))

# Exterior colour is the same story as transmission: the search feed we crawl carries no
# colour at all (only the per-car detail does, via `spec.colorName`, and we hold a detail
# for well under 1% of the catalogue), but colour IS an upstream facet. So the colour of
# every car is obtainable from the SAME endpoint with the SAME politeness — one id-only
# pass per colour value. Because the colours partition the catalogue, the sum of those
# passes is about one extra full sweep (~490 requests), not one per car.
#
# Our slug -> the Korean facet values Encar itself uses. EVERY value below was read out of
# real Encar data (`detail.spec.colorName` across the cars whose detail we hold), never
# guessed: an invented facet value simply returns Count 0 and its cars stay untagged, which
# is why `tag_colors` reports coverage. Grouped the way a buyer thinks — nobody shopping for
# a grey car cares whether Encar filed it as 쥐색 or 은회색. Two-tone variants ride with
# their base colour.
COLOR_GROUPS = {
    "white":  ["흰색", "흰색투톤"],
    "black":  ["검정색", "검정투톤"],
    "grey":   ["쥐색", "은회색"],
    "silver": ["은색", "은색투톤", "명은색", "은하색"],
    "blue":   ["청색", "하늘색", "청옥색"],
    "red":    ["빨간색"],
    "green":  ["녹색", "담녹색", "연두색"],
    "brown":  ["갈색", "갈대색"],
    "yellow": ["노란색"],
    "orange": ["주황색"],
    "purple": ["보라색", "자주색"],
    "pearl":  ["진주색"],
    "gold":   ["금색", "금색투톤", "연금색"],
}
COLOR_OF_RAW = {raw: slug for slug, raws in COLOR_GROUPS.items() for raw in raws}

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
    await db.listings.create_index([("color", 1)])
    await db.listings.create_index([("diagnosed", 1)])
    await db.translations.create_index([("lang", 1)])
    await db.car_details.create_index([("fetched_at", -1)])


def _search_text(doc):
    return " ".join(filter(None, [doc.get("manufacturer"), doc.get("model"),
                                 doc.get("badge"), doc.get("fuel_type")]))


class Sweep:
    """One time budget for a WHOLE sweep, however many requests it turns out to need.

    The crawl bisects, so the request count is not known in advance: 200k ads came out as
    ~1000 slices plus probes, two and a half times the 400 leaf pages the arithmetic
    predicted. A fixed gap per request therefore ran two and a half hours long — and because
    the budget used to be installed around EACH partition, every manufacturer got its own
    two hours and the whole thing landed at four.

    So the gap is recomputed before every request from what is left of the budget divided by
    the requests still expected. Ahead of schedule it waits longer, behind schedule it drops
    to the client's floor, and the sweep lands on the deadline instead of a multiple of it.
    """

    def __init__(self, expected, target):
        self.expected = max(int(expected), 1)
        self.done = 0
        self.target = target
        self.deadline = time.monotonic() + target
        # Widened when upstream blocks us: walking into "three blocks in five minutes" is
        # what turns a 25-second cooldown into three minutes on every route.
        self.penalty = 1.0
        # One count per facet per sweep. The plan and the bisection ask for the same node.
        self.counts = {}
        # How much of the WORK is done, if the caller knows (cars indexed / cars upstream).
        # A better estimator than any request-count arithmetic: the crawl reports it as it
        # goes, so an estimate that is out by two still lands on the deadline.
        self.fraction = 0.0

    def penalise(self):
        """Back off for the rest of the sweep after a block, instead of walking into more."""
        self.penalty = min(self.penalty * 1.5, 8.0)
        log.warning("upstream blocked us — the rest of this sweep slows down %.1fx",
                    self.penalty)

    def expect(self, requests):
        """Refine the estimate once the real numbers are known."""
        self.expected = max(int(requests), self.done + 1)

    def progress(self, fraction):
        """How far through the catalogue the crawl is, 0..1."""
        if 0 < fraction <= 1:
            self.fraction = fraction

    def _remaining(self):
        by_count = max(self.expected - self.done, 1)
        # Once there is real progress to measure, trust it over the arithmetic: the
        # request-count estimate is a guess about a bisecting crawl, while cars-indexed over
        # cars-upstream is a fact. Trusting the guess is how a sweep either sprinted through
        # in forty minutes or ran four hours long.
        if self.fraction < 0.02 or self.done < 20:
            return by_count
        return max(round(self.done * (1 - self.fraction) / self.fraction), 1)

    def gap(self):
        self.done += 1
        left_time = self.deadline - time.monotonic()
        if left_time <= 0:
            return ENCAR_MIN_GAP                    # over budget: as fast as politeness allows
        gap = left_time / self._remaining()
        # Never spend more than a twentieth of what is left on ONE wait. Early on, before
        # there is any progress to measure, the estimate can be far too small — and without
        # this the first request of a small crawl would sit on most of the budget and the
        # sweep would still run past it. Erring the other way only finishes early, which for
        # a catalogue that needs few requests is the right answer anyway.
        base = max(ENCAR_MIN_GAP, min(gap, SYNC_PAGE_GAP_MAX, left_time / 20))
        # The penalty is applied AFTER the caps, so backing off after a block can actually
        # slow us below the normal ceiling. Finishing late beats finishing blocked.
        return min(base * self.penalty, SYNC_PAGE_GAP_MAX * 4)


# The sweep in force, if any. A facet pass nested inside a crawl must SHARE the crawl's
# budget, not start a second two-hour one of its own.
_sweep = {"active": None}


def _sweep_gap(requests_expected, target=None):
    """The gap a sweep of this size starts out with. Kept for the admin display and the
    log line; the live gap comes from `Sweep.gap` and changes as the crawl learns."""
    target = target or int(os.environ.get("SYNC_TARGET_SECONDS") or SYNC_TARGET_SECONDS)
    gap = target / max(requests_expected, 1)
    return max(ENCAR_MIN_GAP, min(gap, SYNC_PAGE_GAP_MAX))


def _target():
    return int(os.environ.get("SYNC_TARGET_SECONDS") or SYNC_TARGET_SECONDS)


def crawl_budget():
    """The crawl's share: the whole target minus what the facet passes at the end need.

    The promise is that a sync takes two hours — all of it, tail included. Giving the crawl
    the full two hours and then starting the facet passes is how it became two hours plus
    however long the tail felt like.
    """
    return max(_target() - facet_budget(), 60)


def facet_budget():
    return max(min(int(os.environ.get("SYNC_FACET_SECONDS") or SYNC_FACET_SECONDS),
                   _target() // 2), 30)


async def facet_requests(db, manufacturers=None, full=True):
    """How many upstream requests the gearbox and colour passes will need, roughly.

    A FULL colour pass is one id-only page per 500 cars (the colours partition the catalogue)
    plus a count per facet value. An incremental one only walks the top of each facet, so it
    is a handful of pages per value — which is the whole point of doing it that way.
    """
    scopes = max(len(manufacturers or []), 1)
    values = (len(COLOR_OF_RAW) + 1) * scopes
    if not full:
        return int(values * (COLOR_STOP_PAGES + 2) + 4)
    q = {"active": True}
    if manufacturers:
        q["manufacturer"] = {"$in": list(manufacturers)}
    cars = await db.listings.count_documents(q) or 0
    return int(cars / PAGE + values + 4)


async def beat(db, progress_key="catalogue_partition"):
    """Say "still working" to the live document.

    The stall self-heal watches this timestamp. The crawl stamps it every three seconds, but
    the facet passes at the end used to stamp nothing for an hour at a time — so a healthy,
    deliberately slow tail looked exactly like a wedged sync and got restarted, again and
    again, which is why the sync kept "getting stuck at the end".
    """
    await db.sync_state.update_one({"_id": f"{progress_key}_live"},
                                   {"$set": {"updated_at": datetime.now(timezone.utc)}},
                                   upsert=True)


@contextlib.asynccontextmanager
async def paced_sweep(requests_expected, target=None):
    """Spread every upstream call of a sweep across SYNC_TARGET_SECONDS, then put the client
    back as it was.

    One knob instead of a sleep at each of the half-dozen places that page through Encar: the
    client asks the installed pacer how long to wait before each non-interactive call, so the
    leaf pages, the bisection probes and the facet passes are all paced by the same budget,
    and the database work between two calls counts into the gap instead of being added on top.

    A visitor opening an uncached car is NOT slowed: interactive calls take the concurrency
    semaphore and skip that throttle entirely.
    """
    if _sweep["active"] is not None:
        # Nested: share the budget already running.
        yield _sweep["active"]
        return
    target = target or int(os.environ.get("SYNC_TARGET_SECONDS") or SYNC_TARGET_SECONDS)
    sweep = Sweep(requests_expected, target)
    _sweep["active"] = sweep
    encar.pacer = sweep.gap
    encar.on_block = sweep.penalise
    log.info("sweep paced: ~%s expected requests over %d min (a request every %.1fs to "
             "start with)", sweep.expected, target / 60,
             _sweep_gap(requests_expected, target))
    try:
        yield sweep
    finally:
        encar.pacer = None
        encar.on_block = None
        _sweep["active"] = None
        log.info("sweep finished: %s requests in %d min (pacing %.1fx after blocks)",
                 sweep.done, (target - (sweep.deadline - time.monotonic())) / 60,
                 sweep.penalty)


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
                pages_full = (total + page_size - 1) // page_size
                pages = min(pages_full, max_pages) if max_pages else pages_full
                # Paced off the FULL page count, so a short test run is exactly as polite
                # per page as the real sweep.
                gap = _sweep_gap(pages_full)
                await _set(db, listings_upstream=total, pages_total=pages,
                           page_gap_s=round(gap, 1), eta_s=round(gap * pages))
                log.info("full sync: %s listings across %s pages, a page every %.1fs "
                         "(~%d min in total)", total, pages, gap, gap * pages / 60)

                seen_ids = set()
                upserted = 0
                # `paced_sweep` raises the client's own minimum gap for the length of the
                # loop, so the request itself, the bulk_write and the state update all count
                # into each page's slot. Visitors are untouched: their calls are interactive
                # and skip that throttle.
                async with paced_sweep(pages_full):
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
                            doc["price_krw"], rates["fx_krw_eur"], rates["usd_eur"], S,
                            is_ev=pricing.is_ev_fuel(doc.get("fuel_type")))
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
                await tag_colors(db)
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


async def _count(q):
    """Count a facet once per sweep.

    The plan and the bisection ask about the same node, and every duplicate is a request
    spent on an answer we already had — which is a request closer to a block.
    """
    sweep = _sweep["active"]
    if sweep is None:
        return await encar.count(q)
    if q in sweep.counts:
        return sweep.counts[q]
    n = await encar.count(q)
    if n is not None:
        sweep.counts[q] = n
    return n


async def _count_patient(q, tries=3):
    """The count that decides whether a whole sweep happens at all — worth waiting for.

    This is the sync's FIRST upstream call, and a raise here kills a two-hour job before it
    indexes a single car. With the automatic resume in place, that then repeated the same
    first request every few minutes, and a run of blocks is exactly what escalates Encar's
    cooldown from twenty-five seconds to three minutes on every route. So a block at the
    starting line is waited out — bounded, and only here.
    """
    for attempt in range(tries):
        try:
            return await _count(q)
        except EncarUnavailable as e:
            if attempt == tries - 1:
                raise
            wait = min(max(encar_mod.blocked_for(), 10) + 2, 120)
            log.warning("the opening count was refused (%s) — waiting %.0fs for a route to "
                        "open rather than abandoning the sweep", str(e)[:120], wait)
            await asyncio.sleep(wait)
    return None


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
            # Save the slice so the second-pass sweep can try again with a different
            # sort key. The window drift is time-dependent, so re-fetching a minute
            # later often catches the rows the first pass missed.
            st.setdefault("retry_leaves", []).append({"key": key, "expected": count})
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
            lcount = await _count(lkey)
            st["probes"] += 1
            # Say "still working" on every PROBE too, not only when rows land. A deep
            # bisection can spend many paced probes without writing a single car, and with
            # nothing stamped the panel froze and the stall self-heal restarted a crawl that
            # was simply working its way down the tree.
            if ctx and ctx.get("beat"):
                await ctx["beat"]()
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
    # Filled in once the sweep's budget exists (below); `publish` reports progress into it so
    # the pacing corrects itself against real work done rather than a predicted request count.
    pace = {"sweep": None}

    async def publish(phase, force=False):
        now = time.monotonic()
        if pace["sweep"] and live["upstream"]:
            pace["sweep"].progress((already + len(seen)) / live["upstream"])
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
                doc["price_krw"], rates["fx_krw_eur"], rates["usd_eur"], S,
                is_ev=pricing.is_ev_fuel(doc.get("fuel_type")))
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

    ctx = {"plan": plan, "done": done, "flush": flush_resume,
           # A heartbeat the bisection can call: progress is published on probes as well as
           # on written rows, so a long walk down the tree still looks alive.
           "beat": lambda: publish("crawl")}

    scope = list(manufacturers) if manufacturers else [None]
    per_make = {}
    started = datetime.now(timezone.utc)

    # ONE budget for the whole crawl, not one per manufacturer: installed around every
    # partition, each make got its own two hours and a 200k sweep landed at four. Seeded from
    # the local catalogue (within a percent of upstream) and refined below as each partition
    # reports its real count; the gap is recomputed per request either way, so the estimate
    # only affects the shape of the pacing, not the total.
    seed = await db.listings.count_documents({"active": True}) or 0
    expected_requests = max(seed // LEAF_MAX, 1) * SYNC_REQUEST_OVERHEAD
    # The crawl gets the target MINUS the facet passes' share, so the whole sync — crawl and
    # tail together — lands on the two hours the owner asked for.
    sweep_cm = paced_sweep(expected_requests, target=crawl_budget())
    sweep = await sweep_cm.__aenter__()
    pace["sweep"] = sweep
    expected_seen = 0

    try:
      for mfr in scope:
        base = [f"Manufacturer.{mfr}"] if mfr else []
        scope_key = _q(base)
        total = plan.get(scope_key)
        if total is None:
            total = await _count_patient(scope_key)
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
            # Now that this partition's real size is known, tell the budget: a bisecting
            # crawl of 200k came out at ~1000 slices, two and a half times the leaf pages
            # the arithmetic predicts, and the pacer needs to know before it hands out the
            # early gaps rather than sprinting at the end.
            expected_seen += max((total + LEAF_MAX - 1) // LEAF_MAX, 1) * SYNC_REQUEST_OVERHEAD
            sweep.expect(expected_seen)
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
    finally:
        # The pacer must come off whatever happens: left installed, a failed crawl would
        # leave every later request — including the detail fetches a visitor's page waits
        # on — paced at seventeen seconds.
        await sweep_cm.__aexit__(None, None, None)

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
    """Which cars are manual. Only ~1,200 of ~245,000 are, so the manual ones are fetched
    (three requests) and everything else in the SAME crawl scope is automatic.

    Written after finding all 244,996 listings stamped `auto` and not one manual car in the
    catalogue. The pass used to say `update_many({"_id": {"$nin": manual_ids}}, auto)` — and
    `manual_ids` was `[]` whenever the upstream walk failed, because a failed walk and an
    empty facet looked identical. `$nin: []` matches EVERY document, so one soft block
    during this phase relabelled the whole catalogue, silently, and the broad `except`
    reported it as a successful zero.

    So: a failed walk aborts the pass without a single write, an empty manual set on a large
    catalogue is refused as implausible, and the blanket write is confined to the crawl
    scope instead of the whole collection.
    """
    started = datetime.now(timezone.utc)

    async def record(result):
        await db.sync_state.update_one({"_id": "transmission"},
                                       {"$set": {**result, "ran_at": started}}, upsert=True)
        return result

    try:
        manual_ids = []
        scopes = list(manufacturers) if manufacturers else [None]
        async with paced_sweep(await facet_requests(db, manufacturers),
                               target=facet_budget()):
            for mfr in scopes:
                q = (MANUAL_Q if not mfr else
                     _q([f"Manufacturer.{mfr}", "Transmission.\uc218\ub3d9"]))
                got = await _collect_ids(q, db=db)
                if got is None:
                    log.error("gearbox tagging skipped: the upstream walk for %s failed — "
                              "nothing written (a partial list would have stamped every "
                              "other car automatic)", mfr or "ALL")
                    return await record({"ok": False, "manual": 0, "auto": 0,
                                         "skipped": f"upstream walk failed for "
                                                    f"{mfr or 'ALL'}"})
                manual_ids += got

        scope_q = {"active": True}
        if manufacturers:
            scope_q["manufacturer"] = {"$in": list(manufacturers)}
        in_scope = await db.listings.count_documents(scope_q)

        if not manual_ids and in_scope > MANUAL_PLAUSIBILITY_FLOOR:
            log.error("gearbox tagging skipped: upstream reported NO manual car among %s "
                      "in scope, which it never is — nothing written", in_scope)
            return await record({"ok": False, "manual": 0, "auto": 0, "in_scope": in_scope,
                                 "skipped": "no manual car found in a catalogue this size"})

        manual = 0
        if manual_ids:
            r = await db.listings.update_many({"_id": {"$in": manual_ids}},
                                              {"$set": {"transmission": "manual"}})
            manual = r.matched_count
        # Confined to the scope this crawl actually covered: retired rows and cars outside
        # the scope keep whatever the crawl that DID cover them decided.
        auto = await db.listings.update_many(
            {**scope_q, "_id": {"$nin": manual_ids}},
            {"$set": {"transmission": "auto"}})
        log.info("transmission tagged: %s manual, %s automatic of %s in scope",
                 manual, auto.matched_count, in_scope)
        return await record({"ok": True, "manual": manual, "auto": auto.matched_count,
                             "in_scope": in_scope, "upstream_manual": len(manual_ids)})
    except Exception as e:                                  # noqa: BLE001
        log.warning("transmission tagging failed: %s", str(e)[:200])
        return await record({"ok": False, "manual": 0, "auto": 0, "error": str(e)[:200]})


# Colour never changes for a car, and a facet page comes back newest-modified first — so the
# cars whose colour we do not know yet are on the FIRST pages. An incremental pass stops once
# the pages stop telling us anything new; a full pass still happens, but weekly.
COLOR_FULL_EVERY_H = int(os.environ.get("COLOR_FULL_EVERY_H") or 168)
COLOR_STOP_PAGES = int(os.environ.get("COLOR_STOP_PAGES") or 2)
# The facet passes learn fields that do not change for a car, so they are worth at most once
# a day however often the sync itself runs.
FACET_EVERY_H = int(os.environ.get("FACET_EVERY_H") or 24)


async def facet_due(db, key, hours=None):
    """Has enough time passed since this facet pass last SUCCEEDED?"""
    state = await db.sync_state.find_one({"_id": key}) or {}
    if not state.get("ok"):
        return True, "last pass did not succeed"
    ran = state.get("ran_at")
    if not ran:
        return True, "never run"
    if ran.tzinfo is None:
        ran = ran.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - ran).total_seconds() / 3600
    if age_h >= (hours if hours is not None else FACET_EVERY_H):
        return True, f"{age_h:.0f}h since the last pass"
    return False, f"only {age_h:.1f}h since the last pass"


async def _collect_new_ids(q, db):
    """Ids from the top of a facet, stopping when the pages hold nothing we did not know.

    Walking all eighty pages of "white" to re-learn colours we already hold cost a full extra
    pass over the catalogue on EVERY sync — about 490 of the ~1750 requests, for a field that
    cannot change. Each page is checked against what we already have; two consecutive pages
    with nothing new and the walk is done. In the steady state that is one or two pages per
    colour value instead of eighty.

    Cars we do not hold at all count as new, so a page of them keeps the walk going.
    """
    total = await _count(q)
    if total is None:
        log.warning("colour walk aborted: the count request failed for %s", q[:120])
        return None
    if not total:
        return []
    pages = max((total + PAGE - 1) // PAGE, 1)
    ids, quiet, walked = [], 0, 0
    for p in range(pages):
        try:
            data = await encar.search(offset=p * PAGE, limit=PAGE, q=q)
        except Exception as e:                       # noqa: BLE001
            log.warning("colour walk aborted at page %s of %s: %s", p + 1, pages, str(e)[:160])
            return None
        rows = (data or {}).get("SearchResults") or []
        if not rows:
            if not ids:
                log.warning("colour walk aborted: %s promised %s rows and returned none",
                            q[:120], total)
                return None
            break
        page_ids = [str(r.get("Id")) for r in rows if r.get("Id")]
        ids += page_ids
        walked += 1
        known = await db.listings.count_documents(
            {"_id": {"$in": page_ids}, "color": {"$nin": [None, ""]}})
        quiet = quiet + 1 if known >= len(page_ids) else 0
        await beat(db)
        if quiet >= COLOR_STOP_PAGES:
            break
    if walked < pages:
        log.info("colour walk stopped after %s of %s pages (nothing new): %s",
                 walked, pages, q[:80])
    return ids


async def _colour_mode(db, scope_q, full=None):
    """Full pass or incremental? By time alone: full weekly, incremental in between.

    Deliberately not "full when too many cars lack a colour" — the owner asked for the
    decision to be a clock, not a percentage, so a day with a lot of new stock cannot
    quietly turn into a second full sweep.
    """
    if full is not None:
        return bool(full), "asked for"
    state = await db.sync_state.find_one({"_id": "colors"}) or {}
    last_full = state.get("full_at")
    if last_full and last_full.tzinfo is None:
        last_full = last_full.replace(tzinfo=timezone.utc)
    if not last_full:
        return True, "no full pass on record"
    age_h = (datetime.now(timezone.utc) - last_full).total_seconds() / 3600
    if age_h >= COLOR_FULL_EVERY_H:
        return True, f"last full pass {age_h:.0f}h ago"
    return False, f"last full pass {age_h:.0f}h ago"


async def tag_colors(db, manufacturers=None, full=None):
    """Exterior colour for the whole catalogue, from the same search endpoint.

    One id-only pass per Encar colour value. The colours partition the catalogue, so a FULL
    job costs about one extra sweep (~490 paced requests) rather than one request per car —
    which is what asking the per-car detail for `spec.colorName` would have meant (245 000
    requests, three days of pacing, and a rate limit we have no business testing).

    That full pass does not need to happen every sync: colour does not change, and the cars
    we have not coloured yet are the newest ones, which sit on the first page of each facet.
    So the normal run walks the top of each facet and stops when it stops learning anything
    (~30-90 requests), and a full pass runs weekly, or sooner if too many cars lack a colour.

    Rows an unknown colour value would have covered stay UNTAGGED rather than being called
    "other": coverage is reported so a missing value shows up as evidence instead of a lie.
    """
    started = datetime.now(timezone.utc)
    per_color, tagged_total = {}, 0
    scope_q = {"active": True, "duplicate": {"$ne": True}}
    if manufacturers:
        scope_q["manufacturer"] = {"$in": list(manufacturers)}
    is_full, why = await _colour_mode(db, scope_q, full)
    log.info("colour pass: %s (%s)", "full" if is_full else "incremental", why)
    # Free first, upstream second: fold in every colour we already hold from a car's own
    # detail. It costs nothing, and if the facet passes then fail (a 407, an outage) the
    # local work is already saved instead of being lost with the exception.
    from_details = await _colors_from_details(db, manufacturers)
    try:
        scopes = list(manufacturers) if manufacturers else [None]
        async with paced_sweep(await facet_requests(db, manufacturers, full=is_full),
                               target=facet_budget()):
            for slug, raws in COLOR_GROUPS.items():
                ids = []
                for raw in raws:
                    for mfr in scopes:
                        clauses = [f"Color.{raw}"]
                        if mfr:
                            clauses.insert(0, f"Manufacturer.{mfr}")
                        got = (await _collect_ids(_q(clauses), db=db) if is_full
                               else await _collect_new_ids(_q(clauses), db))
                        if not got:
                            continue
                        ids += got
                if ids:
                    r = await db.listings.update_many(
                        {"_id": {"$in": ids}},
                        {"$set": {"color": slug, "color_at": started}})
                    per_color[slug] = r.matched_count
                    tagged_total += r.matched_count
                else:
                    per_color[slug] = 0
                await beat(db)
        total = await db.listings.count_documents(scope_q)
        known = await db.listings.count_documents({**scope_q, "color": {"$nin": [None, ""]}})
        result = {"per_color": per_color, "tagged": tagged_total, "known": known,
                  "total": total, "from_details": from_details, "full": is_full,
                  "mode": "full" if is_full else "incremental", "why": why,
                  "coverage": round(known * 100.0 / total, 1) if total else 0.0,
                  "ran_at": started, "ok": True}
        if is_full:
            # Only a completed FULL pass resets the weekly clock.
            result["full_at"] = started
        log.info("colours tagged (%s): %s of %s cars (%.1f%%) %s", result["mode"],
                 known, total, result["coverage"], per_color)
    except Exception as e:                                  # noqa: BLE001
        # A failed colour pass must never fail the sync: the catalogue is still correct,
        # it just has no colour on the new rows.
        log.warning("colour tagging failed: %s", str(e)[:200])
        result = {"per_color": per_color, "tagged": tagged_total, "ok": False,
                  "from_details": from_details, "error": str(e)[:200], "ran_at": started,
                  "mode": "full" if is_full else "incremental"}
    await db.sync_state.update_one({"_id": "colors"}, {"$set": result}, upsert=True)
    return result


async def _colors_from_details(db, manufacturers=None):
    """Colour taken from the details we already hold. No upstream request at all."""
    by_slug = {}
    async for doc in db.car_details.find({}, {"detail.spec.colorName": 1}):
        raw = (((doc.get("detail") or {}).get("spec")) or {}).get("colorName")
        slug = COLOR_OF_RAW.get(str(raw or "").strip())
        if slug:
            by_slug.setdefault(slug, []).append(doc["_id"])
    written = 0
    for slug, ids in by_slug.items():
        # Never overwrite: a facet pass and a detail are equally authoritative, and the
        # facet pass is the one that just ran.
        q = {"_id": {"$in": ids}, "color": {"$in": [None, ""]}}
        if manufacturers:
            q["manufacturer"] = {"$in": list(manufacturers)}
        r = await db.listings.update_many(
            q, {"$set": {"color": slug, "color_at": datetime.now(timezone.utc)}})
        written += r.modified_count
    if written:
        log.info("colours from cached details: %s rows", written)
    return written


async def _collect_ids(q, db=None):
    """Every upstream id matching a facet query, or None if the walk did not complete.

    None is the whole point. A partial or empty list is indistinguishable from "there are
    no such cars", and a caller that believes it then writes the opposite of the truth onto
    the whole catalogue — which is exactly what happened to the gearbox pass (see
    `tag_transmission`). Failure has to be sayable.
    """
    ids = []
    total = await _count(q)
    if total is None:                                # upstream refused to answer at all
        log.warning("facet walk aborted: the count request failed for %s", q[:120])
        return None
    if not total:
        return ids                                   # a genuinely empty facet
    pages = max((total + PAGE - 1) // PAGE, 1)
    # The facet passes page through Encar exactly like the main sweep does, and they run back
    # to back with it — same pacing, or the burst simply moves here. When a facet budget is
    # already open (the normal case) this JOINS it instead of starting a second one.
    async with paced_sweep(pages, target=facet_budget()):
        for p in range(pages):
            try:
                data = await encar.search(offset=p * PAGE, limit=PAGE, q=q)
            except Exception as e:                   # noqa: BLE001
                log.warning("facet walk aborted at page %s of %s: %s", p + 1, pages,
                            str(e)[:160])
                return None
            rows = (data or {}).get("SearchResults") or []
            if not rows:
                if not ids:
                    # Upstream said there are matches and then handed back nothing: a block,
                    # not an answer.
                    log.warning("facet walk aborted: %s promised %s rows and returned none",
                                q[:120], total)
                    return None
                break                                # short last page: upstream counts drift
            ids += [str(r.get("Id")) for r in rows if r.get("Id")]
            if db is not None:
                await beat(db)                       # a slow tail is not a wedged one
    return ids


async def _flag_duplicates(db, group_by, extra=None):
    """Flag every ad but the most informative one in each group. Returns the group count.

    `group_by` is whatever `$group._id` should be — a single field path or a compound
    document. Only rows still marked as keepers are considered, so a second pass never
    reconsiders an ad the first one already hid.
    """
    match = {"active": True, "duplicate": {"$ne": True}}
    match.update(extra or {})
    pipe = [
        {"$match": match},
        {"$sort": {"has_record": -1, "has_inspection": -1, "has_resume": -1,
                   "photo_count": -1, "recency": 1}},
        {"$group": {"_id": group_by,
                    "keep": {"$first": "$_id"},
                    "ids": {"$push": "$_id"},
                    "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]
    losers, groups = [], 0
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
    return groups


async def dedupe_pass(db):
    """Encar carries many duplicate ads for the same physical car (dealers re-register
    listings under fresh IDs). Roughly 30% of rows are duplicates, so without this the
    grid shows the same car several times.

    We group by `vehicle_key` (parsed from the photo path, which embeds the underlying
    vehicleId) and keep the MOST INFORMATIVE ad, not merely the newest one. Duplicate
    ads for one physical car are not equivalent: typically only one of them carries the
    insurance history (`Record`), and the other shows nothing on the detail page. So the
    keep-order is:        1. has insurance history       (Record)
        2. has inspection report       (Inspection)
        3. has performance/resume doc  (Resume)
        4. most photos
        5. freshest ad (lowest `recency`)
    The rest stay in the collection but are flagged and hidden from search.

    Two passes run: the `vehicle_key` one above, then an odometer-fingerprint one for the
    re-listings whose photos were re-uploaded (see the comment on the second pass below).
    """
    try:
        await db.listings.update_many({}, {"$set": {"duplicate": False}})

        groups = await _flag_duplicates(db, "$vehicle_key")
        # SECOND PASS — the odometer fingerprint.
        #
        # `vehicle_key` only works while the re-registered ad KEEPS the original photo
        # folder; when the dealer re-uploads the pictures the new ad gets a folder named
        # after its own id, the key falls back to that id, and the two ads for one car both
        # stay live. That is how the same car showed up twice in "Picked for you" and in the
        # grid. Make + model + trim + registration month + the EXACT odometer reading is a
        # fingerprint no two different cars realistically share (kilometres to the single
        # km), so the second of them is hidden by the same keep-order as above. Ads with no
        # mileage are left alone — a zero would group every one of them together.
        fingerprint = {"make": "$manufacturer", "model": "$model", "badge": "$badge",
                       "ym": "$year_month", "km": "$mileage"}
        twins = await _flag_duplicates(db, fingerprint, extra={"mileage": {"$gt": 0}})

        hidden = await db.listings.count_documents({"active": True, "duplicate": True})
        unique = await db.listings.count_documents({"active": True, "duplicate": False})
        log.info("dedupe: %s vehicle-key groups, %s odometer twins, %s ads hidden, "
                 "%s unique cars", groups, twins, hidden, unique)
        return {"groups": groups, "twins": twins, "hidden": hidden, "unique": unique}
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


_TAX_LOCKS: dict = {}


def _tax_lock():
    """One build lock per event loop.

    A module-level `asyncio.Lock()` binds to whichever loop touches it first, which makes it
    unusable from a second loop (a test suite, or a one-off script). Keyed by the running
    loop it behaves the same in the server, where there is only ever one.
    """
    loop = asyncio.get_running_loop()
    lock = _TAX_LOCKS.get(loop)
    if lock is None:
        lock = _TAX_LOCKS[loop] = asyncio.Lock()
    return lock


async def build_taxonomy(db):
    """Precompute the Make -> Model -> Trim -> Sub-trim tree into its own collection.

    Doing this on demand meant ~20s per dropdown (a full aggregation over the whole
    listings collection plus blocking translation). Precomputed + indexed, each level
    is a single indexed lookup, so the dropdowns open instantly. Refreshed on every
    sync and at most weekly on demand.

    Two builds must never overlap. They used to be able to: the nightly sync calls this
    directly while `refresh_taxonomy_if_stale` can fire it from a request, both wrote into
    the same fixed staging collection, and the result was EVERY node stored twice — 2 630
    entries in sitemap-models.xml for 1 315 landings, and doubled dropdown options. So the
    build now takes a lock AND stages into a collection named after this build alone, which
    makes an interleaved write impossible rather than merely unlikely.
    """
    async with _tax_lock():
        return await _build_taxonomy(db)


async def _build_taxonomy(db):
    staging = f"taxonomy_build_{uuid.uuid4().hex[:12]}"
    stage = db[staging]
    # Sweep up staging collections a crashed build left behind. Safe under the lock: no
    # other build can be running in this process, and one is never left mid-flight across
    # processes because the swap is a single rename.
    for name in await db.list_collection_names():
        if name.startswith("taxonomy_build_") and name != staging:
            try:
                await db[name].drop()
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
                await stage.insert_many(docs, ordered=False)
                docs = []
    if docs:
        await stage.insert_many(docs, ordered=False)

    # atomic-ish swap so the dropdowns never see a half-built tree
    await stage.create_index([("level", 1), ("make", 1), ("model", 1),
                             ("badge", 1), ("count", -1)])
    await stage.rename("taxonomy", dropTarget=True)
    await db.taxonomy.create_index([("level", 1), ("make", 1), ("model", 1),
                                   ("badge", 1), ("count", -1)])
    # Slugs are part of BUILDING the tree, not an optional extra step.
    #
    # A rebuild recreates every document from the aggregation, so the tree comes out with no
    # `slug` field at all — and `refresh_taxonomy_if_stale` (which fires from a request when
    # the tree is a few hours old) called the build without ever re-assigning them. Every
    # /bg/bmw style landing page — 1 315 of them — silently 404'd until the next full sync
    # got round to the separate "slugs" step. Doing it here makes that impossible.
    import slugs as slugs_mod
    slugged = await slugs_mod.ensure_taxonomy_slugs(db, force=True)
    await db.sync_state.update_one(
        {"_id": "taxonomy"},
        {"$set": {"built_at": datetime.now(timezone.utc), "nodes": total}},
        upsert=True)
    log.info("taxonomy built: %s nodes, %s slugs", total, slugged)
    return {"nodes": total, "slugs": slugged}


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
    # `fuel_type` is needed for the EV surcharge — cheap projection.
    cursor = db.listings.find({}, {"price_krw": 1, "fuel_type": 1})
    async for doc in cursor:
        krw = doc.get("price_krw") or 0
        if not krw:
            continue
        landed, sale = pricing.quick_sale_eur(
            krw, rates["fx_krw_eur"], rates["usd_eur"], S,
            is_ev=pricing.is_ev_fuel(doc.get("fuel_type")))
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
