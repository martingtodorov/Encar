"""The retire safety guard: a silent Encar failure must not wipe the local catalogue.

Before this guard, an `encar.count()` that returned 0 (transport hiccup, soft-block,
DNS blip) walked zero rows AND still ran the retire pass, which flipped every
`active: True` listing to `active: False`. Day after day, the visible inventory
shrank. Two lines of defence now:

1. `encar.count()` returns None on transport failure (not 0), and the crawler aborts
   before touching the catalogue.
2. Even if a caller passes a genuinely empty scope, the retire pass refuses to run
   when the crawl covered fewer than `RETIRE_MIN_COVERAGE` of the previously-active
   scope.
"""

import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import sync


@pytest.fixture
def db():
    """A throwaway Mongo database, isolated from anything else running against the pod."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"{os.environ['DB_NAME']}_test_retire_{os.getpid()}"
    yield client[name]
    async def cleanup():
        await client.drop_database(name)
        client.close()
    asyncio.get_event_loop().run_until_complete(cleanup())


async def _seed_active(db, n=1000):
    """Pretend a previous healthy crawl left the catalogue in `active: True`."""
    docs = [{"_id": f"car-{i}", "active": True, "manufacturer": "\ubca4\uce20",
             "price_krw": 10_000_000, "last_crawl": "previous-run"} for i in range(n)]
    await db.listings.insert_many(docs)


def _stub_upstream(count_value, rows=None):
    """Make encar.count/search deterministic without touching the network."""
    rows = rows or []

    async def fake_count(q=sync.BASE_Q):
        return count_value

    async def fake_search(offset=0, limit=500, q=sync.BASE_Q, sort="ModifiedDate"):
        if count_value is None:
            return None
        return {"Count": count_value, "SearchResults": rows}

    sync.encar.count = fake_count
    sync.encar.search = fake_search


def test_upstream_failure_aborts_before_retire(db):
    """encar.count returns None (transport failure). The crawl must refuse to proceed."""

    async def go():
        await sync.ensure_indexes(db)
        await _seed_active(db, n=1000)
        real_count, real_search = sync.encar.count, sync.encar.search
        try:
            _stub_upstream(count_value=None)
            with pytest.raises(RuntimeError, match="upstream count request"):
                await sync.crawl_partitioned(db, manufacturers=None, retire=True)
        finally:
            sync.encar.count, sync.encar.search = real_count, real_search
        still_active = await db.listings.count_documents({"active": True})
        assert still_active == 1000, "the catalogue must survive an aborted crawl"

    asyncio.get_event_loop().run_until_complete(go())


def test_empty_upstream_does_not_wipe_catalogue(db):
    """Encar legitimately reports 0 matches. The retire safety net still kicks in."""

    async def go():
        await sync.ensure_indexes(db)
        await _seed_active(db, n=1000)
        real_count, real_search = sync.encar.count, sync.encar.search
        try:
            _stub_upstream(count_value=0)
            result = await sync.crawl_partitioned(db, manufacturers=None, retire=True)
        finally:
            sync.encar.count, sync.encar.search = real_count, real_search
        assert result["retire_skipped"] is True
        assert result["retired"] == 0
        still_active = await db.listings.count_documents({"active": True})
        assert still_active == 1000

    asyncio.get_event_loop().run_until_complete(go())


def test_healthy_crawl_still_retires(db):
    """A crawl that re-sees the whole catalogue retires anything genuinely gone."""

    async def go():
        await sync.ensure_indexes(db)
        await _seed_active(db, n=200)
        rows = [{"Id": f"car-{i}", "Manufacturer": "\ubca4\uce20", "Model": "C-Class",
                 "Price": 3000, "Mileage": 50000, "Year": 202001, "FormYear": 2020,
                 "Photos": [{"location": f"/carpicture01/pic{i}/{i}_001.jpg"}],
                 "Condition": [], "SellType": "\uc77c\ubc18"} for i in range(180)]
        real_count, real_search = sync.encar.count, sync.encar.search
        try:
            _stub_upstream(count_value=180, rows=rows)
            result = await sync.crawl_partitioned(db, manufacturers=None, retire=True)
        finally:
            sync.encar.count, sync.encar.search = real_count, real_search
        assert result["retire_skipped"] is False
        still_active = await db.listings.count_documents({"active": True})
        assert still_active == 180

    asyncio.get_event_loop().run_until_complete(go())
