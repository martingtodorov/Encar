"""Three things the owner asked for, each with the failure it came from.

* Old alert messages could not be deleted: `db.incidents` grew for ever and the admin strip
  read as a wall of things that are no longer broken. Closed messages can now be removed one
  by one or all at once, and they expire by themselves after 90 days. An OPEN outage is not
  deletable — hiding the record of something still broken only delays the next reminder.
* A catalogue sweep that stopped moving halfway through held the Sync button until the
  process restarted. It is restartable now, from the last checkpoint, and it self-heals.
* The site went slow during the sweep. The hero counter asked Encar how many ads it lists
  from inside a REQUEST, and that call queued behind the sweep's pacer — gaps of up to a
  minute, taken while holding the single-file lock. Visitor-facing calls skip the pacer.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import encar as encar_mod  # noqa: E402
import notify  # noqa: E402
import sync as sync_mod  # noqa: E402
import syncjob  # noqa: E402
import watchdog  # noqa: E402
from encar import EncarClient  # noqa: E402


def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _now():
    return datetime.now(timezone.utc)


# ── deleting alert messages ──────────────────────────────────────────────────

def test_a_closed_message_can_be_deleted_and_an_open_one_cannot():
    async def go():
        client, db = _db()
        watchdog.set_db(db)
        try:
            closed = await db.incidents.insert_one(
                {"check": "egress", "severity": "critical", "opened_at": _now(),
                 "closed_at": _now(), "reason": "pytest closed"})
            open_one = await db.incidents.insert_one(
                {"check": "egress", "severity": "critical", "opened_at": _now(),
                 "closed_at": None, "reason": "pytest open"})

            assert (await watchdog.delete_incident(closed.inserted_id))["deleted"] == 1
            assert await db.incidents.find_one({"_id": closed.inserted_id}) is None

            refused = await watchdog.delete_incident(open_one.inserted_id)
            assert refused["deleted"] == 0 and refused["reason"]
            assert await db.incidents.find_one({"_id": open_one.inserted_id})

            assert (await watchdog.delete_incident("not-an-object-id"))["deleted"] == 0
        finally:
            await db.incidents.delete_many({"reason": {"$in": ["pytest closed", "pytest open"]}})
            client.close()

    asyncio.run(go())


def test_purge_clears_closed_history_by_age_and_never_an_open_outage():
    async def go():
        client, db = _db()
        watchdog.set_db(db)
        try:
            await db.incidents.insert_many([
                {"check": "sync", "opened_at": _now() - timedelta(days=200),
                 "closed_at": _now() - timedelta(days=200), "reason": "pytest ancient"},
                {"check": "sync", "opened_at": _now(), "closed_at": _now(),
                 "reason": "pytest fresh"},
                {"check": "sync", "opened_at": _now(), "closed_at": None,
                 "reason": "pytest still open"},
            ])
            got = await watchdog.purge_incidents(90)
            assert got["deleted"] >= 1
            assert await db.incidents.find_one({"reason": "pytest ancient"}) is None
            assert await db.incidents.find_one({"reason": "pytest fresh"})
            assert await db.incidents.find_one({"reason": "pytest still open"})

            await watchdog.purge_incidents()
            assert await db.incidents.find_one({"reason": "pytest fresh"}) is None
            assert await db.incidents.find_one({"reason": "pytest still open"})
        finally:
            await db.incidents.delete_many({"reason": {"$regex": "^pytest "}})
            client.close()

    asyncio.run(go())


def test_every_message_carries_an_id_so_the_panel_can_name_the_one_to_delete():
    async def go():
        client, db = _db()
        watchdog.set_db(db)
        notify.set_db(db)
        try:
            await db.incidents.insert_one(
                {"check": "sync", "opened_at": _now(), "closed_at": _now(),
                 "reason": "pytest id"})
            health = await watchdog.health()
            assert all(r.get("id") for r in health["recent"])
            assert all(o.get("id") for o in health["open"])
            assert health["keep_days"] == watchdog.INCIDENT_KEEP_DAYS
            assert health["closed_total"] >= 1
        finally:
            await db.incidents.delete_many({"reason": "pytest id"})
            client.close()

    asyncio.run(go())


# ── restarting a wedged sync ─────────────────────────────────────────────────

class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


def test_a_sync_that_stopped_moving_is_reported_as_stalled(monkeypatch):
    async def go():
        client, db = _db()
        try:
            monkeypatch.setattr(syncjob, "_task", None)
            assert await syncjob.stalled_for(db) is None      # nothing running

            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {"updated_at": _now() - timedelta(minutes=45)}}, upsert=True)
            # Silence is measured from the later of the live stamp and THIS run's start.
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID},
                {"$set": {"started_at": _now() - timedelta(minutes=45)}}, upsert=True)
            assert await syncjob.stalled_for(db) > 40 * 60
        finally:
            client.close()

    asyncio.run(go())


def test_a_stalled_sync_is_cancelled_and_started_again(monkeypatch):
    async def go():
        client, db = _db()
        started = {}
        task = _FakeTask()
        try:
            monkeypatch.setattr(syncjob, "_task", task)
            monkeypatch.setattr(syncjob, "_last_auto_restart", {"at": 0.0})
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {"updated_at": _now() - timedelta(hours=2)}}, upsert=True)
            await db.sync_state.update_one(
                {"_id": syncjob.JOB_ID},
                {"$set": {"started_at": _now() - timedelta(hours=2)}}, upsert=True)

            async def fake_start(db_, trigger="manual", resume_run_id=None, fresh=False):
                started.update(trigger=trigger, fresh=fresh)
                return {"started": True, "trigger": trigger}

            async def no_wait(tasks, timeout=None):
                return set(), set()

            monkeypatch.setattr(syncjob, "start", fake_start)
            monkeypatch.setattr(syncjob.asyncio, "wait", no_wait)

            assert await syncjob.restart_if_stalled(db) is True
            assert task.cancelled
            assert started["trigger"] == "auto-restart"
            job = await db.sync_state.find_one({"_id": syncjob.JOB_ID})
            assert "without progress" in (job.get("error") or "")

            # A wedge that comes straight back must not turn into a restart loop.
            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            assert await syncjob.restart_if_stalled(db) is False
        finally:
            client.close()

    asyncio.run(go())


def test_a_hand_restart_cancels_and_hands_the_fresh_flag_on(monkeypatch):
    """Dropping the checkpoint lives in `start` — every fresh path goes through it, and a
    fresh start that left the checkpoint behind was how "from scratch" became a resume."""
    async def go():
        client, db = _db()
        asked = []
        try:
            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            monkeypatch.setattr(syncjob.asyncio, "wait",
                                lambda tasks, timeout=None: _done())
            await db.sync_state.update_one(
                {"_id": syncjob.RESUME_ID},
                {"$set": {"run_id": "pytest-run", "updated_at": _now()}}, upsert=True)

            async def fake_start(db_, trigger="manual", resume_run_id=None, fresh=False):
                asked.append(fresh)
                return {"started": True, "trigger": trigger, "fresh": fresh}

            monkeypatch.setattr(syncjob, "start", fake_start)

            out = await syncjob.restart(db, fresh=False)
            assert out["started"] and out["stopped"] and asked == [False]

            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            await syncjob.restart(db, fresh=True)
            assert asked == [False, True]
        finally:
            await db.sync_state.delete_one({"_id": syncjob.RESUME_ID})
            client.close()

    async def _done():
        return set(), set()

    asyncio.run(go())


# ── the sweep must not slow a visitor down ───────────────────────────────────

def test_a_visitor_facing_count_skips_the_sweep_pacer():
    """The hero counter is the one upstream call a page waits on. While the sweep is paced
    at a minute a request, that wait belongs to the crawl — not to whoever opened the site."""
    def handler(request):
        return httpx.Response(200, json={"Count": 244996})

    async def go():
        c = EncarClient(min_interval=0)
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                      headers=encar_mod.HEADERS)
        c.pacer = lambda: 60.0                      # a sweep is running
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        assert await c.count(interactive=True) == 244996
        interactive = loop.time() - t0
        assert interactive < 1.0, interactive
        return interactive

    encar_mod.set_route("auto")
    asyncio.run(go())


def test_the_sweep_itself_is_still_paced(monkeypatch):
    """The other half of the same promise: nothing about the bypass loosens the crawl."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    def handler(request):
        return httpx.Response(200, json={"Count": 1})

    async def go():
        c = EncarClient(min_interval=0)
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                      headers=encar_mod.HEADERS)
        c.pacer = lambda: 17.0
        c._last = encar_mod.time.monotonic()
        monkeypatch.setattr(encar_mod.asyncio, "sleep", fake_sleep)
        await c.count()                              # the crawl's own call
        assert slept and max(slept) > 10, slept

    encar_mod.set_route("auto")
    asyncio.run(go())


@pytest.mark.parametrize("expected", [400, 1000])
def test_the_pacer_is_only_installed_while_a_sweep_runs(expected):
    async def go():
        async with sync_mod.paced_sweep(expected):
            assert encar_mod.encar.pacer is not None
        assert encar_mod.encar.pacer is None

    asyncio.run(go())
