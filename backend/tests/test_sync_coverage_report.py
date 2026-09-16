"""Where the gap between Encar's total and our indexed count goes.

The owner's question: "the crawl says finished after 191 thousand cars indexed even though
there are 196 thousand". Most of that gap is deliberate — lease and rental cars cannot be
exported, cars already under contract are effectively sold, and dealer placeholder ads carry
sentinel prices — but nothing in the panel said so, so a healthy crawl and a broken one
looked identical.

Worse, the numbers were read from `catalogue_job.result`, and a RESUMED run whose crawl had
already finished reports `{"crawl": "already complete"}` with no numbers at all. So the one
case where somebody asks the question is the case where the answer was missing.
"""

import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import syncjob


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"{os.environ['DB_NAME']}_test_cov_{os.getpid()}"
    yield client[name]

    async def cleanup():
        await client.drop_database(name)
        client.close()

    asyncio.get_event_loop().run_until_complete(cleanup())


async def _plant(db, **over):
    scope = {"upstream": 196_340, "excluded_skipped": 4_812, "reachable": 191_528,
             "distinct_kept": 191_491, "coverage": 0.9998}
    scope.update(over)
    await db.sync_state.update_one(
        {"_id": "catalogue_partition"},
        {"$set": {"run_id": "r1", "per_make": {"ALL": scope},
                  "stats": {"leaves": 620, "probes": 470, "short_leaves": 3,
                            "dropped_no_price": 34},
                  "retired": 1_204, "retire_skipped": False}},
        upsert=True)


def test_the_breakdown_is_reported_after_a_crawl(db):
    async def go():
        await _plant(db)
        cov = await syncjob.last_crawl(db)
        assert cov["upstream"] == 196_340
        assert cov["excluded"] == 4_812
        # The honest denominator: the exportable subset, not Encar's headline number.
        assert cov["reachable"] == 191_528
        assert cov["indexed"] == 191_491
        assert cov["short_leaves"] == 3
        assert cov["retired"] == 1_204

    asyncio.get_event_loop().run_until_complete(go())


def test_a_resumed_run_still_reports_the_coverage(db):
    """The actual defect: `result` carries nothing when the crawl was already complete."""
    async def go():
        await _plant(db)
        await db.sync_state.update_one(
            {"_id": syncjob.JOB_ID},
            {"$set": {"status": "done", "result": {"crawl": "already complete",
                                                   "active": 191_491}}},
            upsert=True)
        job = await syncjob.get_job(db)
        assert job["result"].get("per_make") is None, "the premise of the bug"
        assert job["crawl"]["indexed"] == 191_491, "and the panel still gets its numbers"

    asyncio.get_event_loop().run_until_complete(go())


def test_nothing_is_claimed_when_no_crawl_has_run(db):
    async def go():
        assert await syncjob.last_crawl(db) is None
        await db.sync_state.update_one({"_id": "catalogue_partition"},
                                       {"$set": {"per_make": {}}}, upsert=True)
        assert await syncjob.last_crawl(db) is None

    asyncio.get_event_loop().run_until_complete(go())


def test_a_refused_retire_pass_is_carried_to_the_panel(db):
    async def go():
        await _plant(db, distinct_kept=900)
        await db.sync_state.update_one(
            {"_id": "catalogue_partition"},
            {"$set": {"retire_skipped": True,
                      "retire_skip_reason": "crawl covered only 900 of 190000"}})
        cov = await syncjob.last_crawl(db)
        assert cov["retire_skipped"] is True
        assert "900" in cov["retire_skip_reason"]

    asyncio.get_event_loop().run_until_complete(go())
