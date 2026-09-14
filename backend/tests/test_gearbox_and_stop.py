"""The gearbox pass, after it stamped the entire catalogue "automatic".

Found in the database: 244,996 listings with `transmission: "auto"` and not ONE manual car,
where about 1,200 are manual. The pass asked Encar for the manual ids and then wrote
"automatic" to `{"_id": {"$nin": manual_ids}}` — and `manual_ids` came back `[]` whenever the
upstream walk failed, because a failed walk and an empty facet were the same value. `$nin: []`
matches every document in the collection, so a single soft block during that phase relabelled
the whole catalogue and the broad `except` reported it as a successful zero.

Plus the operator's other ask: stopping the sync ENTIRELY, so nothing brings it back.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync as sync_mod  # noqa: E402
import syncjob  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# ── a database that only remembers what was asked of it ──────────────────────

class _Result:
    def __init__(self, n):
        self.matched_count = n
        self.modified_count = n


class _Coll:
    def __init__(self, count=0):
        self._count = count
        self.updates = []

    async def update_many(self, q, u):
        self.updates.append((q, u))
        return _Result(self._count)

    async def update_one(self, q, u, upsert=False):
        self.updates.append((q, u))
        return _Result(1)

    async def count_documents(self, q):
        return self._count

    async def find_one(self, *a, **k):
        return None


class _DB:
    def __init__(self, active=245000):
        self.listings = _Coll(active)
        self.sync_state = _Coll(1)


def _wrote_transmission(db):
    return [u for q, u in db.listings.updates if "transmission" in (u.get("$set") or {})]


# ── the walk has to be able to say it failed ─────────────────────────────────

def test_a_failed_count_is_not_an_empty_facet(monkeypatch):
    async def no_answer(q=None, interactive=False):
        return None

    monkeypatch.setattr(sync_mod.encar, "count", no_answer)
    assert asyncio.run(sync_mod._collect_ids("(And.x.)")) is None


def test_an_empty_facet_is_still_an_empty_list(monkeypatch):
    async def zero(q=None, interactive=False):
        return 0

    monkeypatch.setattr(sync_mod.encar, "count", zero)
    assert asyncio.run(sync_mod._collect_ids("(And.x.)")) == []


def test_a_walk_that_breaks_halfway_reports_failure_not_a_partial_list(monkeypatch):
    async def count(q=None, interactive=False):
        return 1200

    calls = {"n": 0}

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"SearchResults": [{"Id": f"{i}"} for i in range(500)]}
        raise RuntimeError("upstream refused the request (HTTP 403)")

    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setattr(sync_mod.encar, "count", count)
    monkeypatch.setattr(sync_mod.encar, "search", search)
    assert asyncio.run(sync_mod._collect_ids("(And.x.)")) is None


def test_a_promise_of_rows_answered_with_none_is_a_block(monkeypatch):
    async def count(q=None, interactive=False):
        return 1200

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        return {"SearchResults": []}

    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setattr(sync_mod.encar, "count", count)
    monkeypatch.setattr(sync_mod.encar, "search", search)
    assert asyncio.run(sync_mod._collect_ids("(And.x.)")) is None


# ── and the pass must not write anything when it did fail ────────────────────

def test_a_failed_walk_writes_no_gearbox_at_all(monkeypatch):
    db = _DB(active=245000)

    async def failed(q):
        return None

    monkeypatch.setattr(sync_mod, "_collect_ids", failed)
    out = asyncio.run(sync_mod.tag_transmission(db))
    assert out["ok"] is False and out["skipped"]
    assert _wrote_transmission(db) == []


def test_no_manual_car_in_a_quarter_million_is_refused_as_implausible(monkeypatch):
    db = _DB(active=245000)

    async def empty(q):
        return []

    monkeypatch.setattr(sync_mod, "_collect_ids", empty)
    out = asyncio.run(sync_mod.tag_transmission(db))
    assert out["ok"] is False
    assert _wrote_transmission(db) == [], "this is what stamped 244,996 cars automatic"


def test_a_good_walk_tags_manual_and_confines_automatic_to_the_crawl_scope(monkeypatch):
    db = _DB(active=245000)

    async def manual(q):
        return ["1", "2", "3"]

    monkeypatch.setattr(sync_mod, "_collect_ids", manual)
    out = asyncio.run(sync_mod.tag_transmission(db))
    assert out["ok"] is True and out["upstream_manual"] == 3

    writes = dict((str(q), u) for q, u in db.listings.updates)
    autos = [q for q, u in db.listings.updates
             if (u.get("$set") or {}).get("transmission") == "auto"]
    manuals = [q for q, u in db.listings.updates
               if (u.get("$set") or {}).get("transmission") == "manual"]
    assert manuals and manuals[0]["_id"]["$in"] == ["1", "2", "3"]
    # The blanket write is scoped: never the whole collection again.
    assert autos and autos[0].get("active") is True
    assert autos[0]["_id"]["$nin"] == ["1", "2", "3"]
    assert writes


def test_a_small_scope_may_legitimately_have_no_manual_car(monkeypatch):
    db = _DB(active=40)

    async def empty(q):
        return []

    monkeypatch.setattr(sync_mod, "_collect_ids", empty)
    out = asyncio.run(sync_mod.tag_transmission(db))
    assert out["ok"] is True
    autos = [q for q, u in db.listings.updates
             if (u.get("$set") or {}).get("transmission") == "auto"]
    assert autos and autos[0].get("active") is True


# ── stopping it entirely ─────────────────────────────────────────────────────

class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


def _db_client():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def test_stopping_by_hand_leaves_it_stopped_and_blocks_the_automatic_resume(monkeypatch):
    async def go():
        client, db = _db_client()
        before = await db.sync_state.find_one({"_id": syncjob.JOB_ID}) or {}
        task = _FakeTask()
        try:
            monkeypatch.setattr(syncjob, "_task", task)

            async def no_wait(tasks, timeout=None):
                return set(), set()

            monkeypatch.setattr(syncjob.asyncio, "wait", no_wait)

            out = await syncjob.stop_by_hand(db)
            assert out["stopped"] and out["was_running"] and task.cancelled

            doc = await db.sync_state.find_one({"_id": syncjob.JOB_ID})
            assert doc["status"] == "stopped" and doc["stopped_by_hand"] is True

            # Nothing brings it back: not a deploy...
            monkeypatch.setattr(syncjob, "_task", None)
            assert await syncjob.resume_if_interrupted(db) is False
            # ...and not the stall self-heal, which has no task to watch.
            assert await syncjob.stalled_for(db) is None
        finally:
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID},
                {"$set": {k: before.get(k) for k in
                          ("status", "error", "finished_at", "stopped_by_hand")}},
                upsert=True)
            client.close()

    asyncio.run(go())


def test_the_panel_can_see_that_it_was_stopped_by_hand(monkeypatch):
    async def go():
        client, db = _db_client()
        before = await db.sync_state.find_one({"_id": syncjob.JOB_ID}) or {}
        try:
            monkeypatch.setattr(syncjob, "_task", None)
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID},
                {"$set": {"status": "stopped", "stopped_by_hand": True}}, upsert=True)
            job = await syncjob.get_job(db)
            assert job["stopped_by_hand"] is True and job["status"] == "stopped"
        finally:
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID},
                {"$set": {k: before.get(k) for k in ("status", "stopped_by_hand")}},
                upsert=True)
            client.close()

    asyncio.run(go())


@pytest.mark.parametrize("status", ["interrupted", "cancelled", "error", "stopped"])
def test_a_hand_start_can_still_pick_up_the_post_crawl_passes(monkeypatch, status):
    """Stopped is not the same as thrown away: pressing Start continues the checkpoint."""
    async def go():
        client, db = _db_client()
        keep_live = await db.sync_state.find_one({"_id": syncjob.LIVE_ID}) or {}
        keep_job = await db.sync_state.find_one({"_id": syncjob.JOB_ID}) or {}
        try:
            monkeypatch.setattr(syncjob, "_task", None)
            await db.sync_state.delete_one({"_id": syncjob.RESUME_ID})
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {"run_id": "pytest-run", "phase": "dedupe",
                          "updated_at": datetime.now(timezone.utc), "leaves": 7}},
                upsert=True)
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID}, {"$set": {"status": status}}, upsert=True)
            ck = await syncjob.find_resumable(db)
            assert ck and ck["run_id"] == "pytest-run" and ck["crawl_done"] is True
        finally:
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {k: keep_live.get(k) for k in
                          ("run_id", "phase", "updated_at", "leaves")}}, upsert=True)
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID}, {"$set": {"status": keep_job.get("status")}},
                upsert=True)
            client.close()

    asyncio.run(go())


# ── and the owner gets told when a facet pass was skipped ────────────────────

class _StateDB:
    """Only what the probe reads: `sync_state.find_one({"_id": ...})`."""

    def __init__(self, docs):
        self.sync_state = self
        self._docs = docs

    async def find_one(self, q):
        return self._docs.get(q["_id"])


def _facets(docs):
    import watchdog
    watchdog._db = _StateDB(docs)
    return watchdog


def test_a_skipped_gearbox_pass_raises_an_alert_with_the_reason():
    """A pass that writes nothing leaves no trace in the catalogue — so it has to be said."""
    wd = _facets({
        "transmission": {"ok": False, "skipped": "upstream walk failed for ALL",
                         "ran_at": datetime.now(timezone.utc)},
        "colors": {"ok": True},
    })
    with pytest.raises(RuntimeError) as e:
        asyncio.run(wd._probe_facets())
    assert "скорости" in str(e.value) and "upstream walk failed" in str(e.value)


def test_both_passes_healthy_reads_as_healthy():
    wd = _facets({"transmission": {"ok": True}, "colors": {"ok": True}})
    detail = asyncio.run(wd._probe_facets())
    assert "скорости" in detail and "цветове" in detail


def test_a_catalogue_that_never_ran_a_facet_pass_is_skipped_not_alarmed():
    import watchdog
    wd = _facets({})
    with pytest.raises(watchdog.Skip):
        asyncio.run(wd._probe_facets())



# ── "from scratch" has to mean from scratch ──────────────────────────────────

def test_start_from_scratch_drops_the_checkpoint_and_does_not_resume(monkeypatch):
    """Reported by the owner: stop the sync entirely, press "Start from scratch", and it
    carried on from the last checkpoint. The panel dropped the flag on the way out, and the
    crawl reads the slice checkpoint itself — so a fresh start has to delete it, not merely
    decline to pass a run id."""
    async def go():
        client, db = _db_client()
        keep = await db.sync_state.find_one({"_id": syncjob.RESUME_ID})
        try:
            monkeypatch.setattr(syncjob, "_task", None)

            async def fake_run(db_, trigger, resume_run_id=None):
                return None

            monkeypatch.setattr(syncjob, "_run", fake_run)
            await db.sync_state.update_one(
                {"_id": syncjob.RESUME_ID},
                {"$set": {"run_id": "pytest-old-run", "done": ["a", "b"], "plan": ["a"],
                          "updated_at": datetime.now(timezone.utc)}}, upsert=True)

            # Default start: the checkpoint is exactly what it is for.
            out = await syncjob.start(db, trigger="manual")
            assert out["resumed_run"] == "pytest-old-run"
            assert await db.sync_state.find_one({"_id": syncjob.RESUME_ID})

            monkeypatch.setattr(syncjob, "_task", None)
            out = await syncjob.start(db, trigger="manual", fresh=True)
            assert out["started"] and out["resumed_run"] is None
            assert await db.sync_state.find_one({"_id": syncjob.RESUME_ID}) is None
        finally:
            await db.sync_state.delete_one({"_id": syncjob.RESUME_ID})
            if keep:
                await db.sync_state.insert_one(keep)
            client.close()

    asyncio.run(go())

