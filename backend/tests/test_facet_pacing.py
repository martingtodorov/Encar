"""Why the sync kept getting stuck at the end.

The owner's words: "We keep on getting stuck at the end. Ie tagging colors tagging
gearboxes." Two faults, compounding:

1. Every facet walk opened its OWN sweep with the FULL two-hour budget. `_collect_ids` is
   called once per Encar colour value (~30 of them) plus once for the manual gearbox facet,
   and a fresh budget of 7200s against the 80 pages of, say, white works out at the
   60-second per-request ceiling — eighty minutes for one colour, hours for the tail. The
   crawl had been fixed to share one budget; the passes that run AFTER it had not.
2. Nothing stamped the live document during those passes. The stall self-heal added in this
   same session watches that timestamp, so a tail that was merely being polite looked
   wedged after thirty minutes and got restarted — straight back into the same phase.

So: the tail has its own share of the target (`SYNC_FACET_SECONDS`, taken OUT of the crawl's
share so the whole sync still lands on two hours), every facet walk joins that one budget,
and each page beats the live document.
"""
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync as sync_mod  # noqa: E402
import syncjob  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


class _Coll:
    def __init__(self, count=0):
        self._count = count
        self.updates = []

    async def count_documents(self, q):
        return self._count

    async def update_many(self, q, u):
        self.updates.append((q, u))
        return type("R", (), {"matched_count": 0, "modified_count": 0})()

    async def update_one(self, q, u, upsert=False):
        self.updates.append((q, u))
        return None

    async def find_one(self, *a, **k):
        return None


class _DB:
    def __init__(self, active=245000):
        self.listings = _Coll(active)
        self.sync_state = _Coll(1)


# ── the budget ───────────────────────────────────────────────────────────────

def test_the_tail_is_paid_for_out_of_the_two_hours_not_added_to_them(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "7200")
    monkeypatch.setenv("SYNC_FACET_SECONDS", "1200")
    assert sync_mod.facet_budget() == 1200
    assert sync_mod.crawl_budget() == 6000
    assert sync_mod.crawl_budget() + sync_mod.facet_budget() == 7200


def test_the_tail_cannot_eat_more_than_half_the_sync(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "600")
    monkeypatch.setenv("SYNC_FACET_SECONDS", "99999")
    assert sync_mod.facet_budget() == 300
    assert sync_mod.crawl_budget() == 300


def test_the_estimate_counts_a_page_per_five_hundred_cars_plus_the_facet_values():
    est = asyncio.run(sync_mod.facet_requests(_DB(active=245000)))
    assert 450 < est < 650, est


# ── one budget for the whole tail ────────────────────────────────────────────

def test_every_facet_walk_joins_one_budget_instead_of_starting_its_own(monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "7200")
    monkeypatch.setenv("SYNC_FACET_SECONDS", "1200")

    async def go():
        db = _DB(active=245000)
        est = await sync_mod.facet_requests(db)
        async with sync_mod.paced_sweep(est, target=sync_mod.facet_budget()) as outer:
            assert sync_mod._sweep["active"] is outer
            # What the colour pass does for every one of its ~30 values.
            for _ in range(5):
                async with sync_mod.paced_sweep(80,
                                                target=sync_mod.facet_budget()) as inner:
                    assert inner is outer, "a nested walk must not start a second budget"
            gaps = [outer.gap() for _ in range(40)]
            # ~500 requests over 1200s is a couple of seconds each — not the 60-second
            # ceiling a fresh two-hour budget handed out for the same 80 pages.
            assert max(gaps) < 10, max(gaps)
        assert sync_mod._sweep["active"] is None
        assert sync_mod.encar.pacer is None

    asyncio.run(go())


def test_the_old_shape_is_what_made_one_colour_take_eighty_minutes(monkeypatch):
    """Kept as evidence: 80 pages against the full two hours = the per-request ceiling."""
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "7200")
    assert sync_mod._sweep_gap(80, 7200) == sync_mod.SYNC_PAGE_GAP_MAX
    assert sync_mod._sweep_gap(80, 1200) < 20


def test_a_walk_on_its_own_still_finishes_inside_the_tail_budget(monkeypatch):
    """Eighty pages — one big colour — land on the tail budget, not on eighty minutes.

    Time has to be simulated: the gap is recomputed from what is LEFT of the budget, so a
    loop that never waits sees the whole budget still available every time round.
    """
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "7200")
    monkeypatch.setenv("SYNC_FACET_SECONDS", "1200")
    clock = [0.0]
    monkeypatch.setattr(sync_mod.time, "monotonic", lambda: clock[0])

    sweep = sync_mod.Sweep(expected=80, target=sync_mod.facet_budget())
    sweep.deadline = 1200.0
    for _ in range(80):
        clock[0] += sweep.gap()
    assert clock[0] <= 1200 + sync_mod.ENCAR_MIN_GAP, clock[0]
    assert clock[0] > 1000, clock[0]

    # And the shape the bug had: the same eighty pages against a fresh two-hour budget sat
    # on the per-request ceiling, which is eighty minutes for ONE colour.
    clock[0] = 0.0
    old = sync_mod.Sweep(expected=80, target=7200)
    old.deadline = 7200.0
    for _ in range(80):
        clock[0] += old.gap()
    assert clock[0] > 3600, clock[0]


# ── and it says "still working" while it does it ─────────────────────────────

class _FakeTask:
    def done(self):
        return False

    def cancel(self):
        pass


def test_a_polite_tail_is_not_mistaken_for_a_wedged_sync(monkeypatch):
    """The self-heal reads the live document. The tail used to stamp nothing for an hour."""
    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        keep = await db.sync_state.find_one({"_id": syncjob.LIVE_ID})
        try:
            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {"updated_at": datetime.now(timezone.utc) - timedelta(hours=2)}},
                upsert=True)
            assert await syncjob.stalled_for(db) > 3600      # looks wedged

            await sync_mod.beat(db)                          # one facet page
            assert await syncjob.stalled_for(db) < 5
            assert await syncjob.restart_if_stalled(db) is False
        finally:
            if keep:
                await db.sync_state.replace_one({"_id": syncjob.LIVE_ID}, keep, upsert=True)
            client.close()

    asyncio.run(go())


def test_each_facet_page_beats_the_live_document(monkeypatch):
    """One beat per page, not one per pass: a single colour can be eighty pages long."""
    beats = []

    async def fake_beat(db, progress_key="catalogue_partition"):
        beats.append(1)

    async def count(q=None, interactive=False):
        return 1200                                          # three pages

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        return {"SearchResults": [{"Id": f"{offset}-{i}"} for i in range(500)]}

    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setattr(sync_mod, "beat", fake_beat)
    monkeypatch.setattr(sync_mod.encar, "count", count)
    monkeypatch.setattr(sync_mod.encar, "search", search)

    got = asyncio.run(sync_mod._collect_ids("(And.Color.x.)", db=_DB()))
    assert len(got) == 1500
    assert len(beats) == 3


@pytest.mark.parametrize("target", ["7200", "600"])
def test_the_pacer_always_comes_off_afterwards(target, monkeypatch):
    """Left installed, the tail's pacer would slow every later request — including the ones
    a visitor's page waits on."""
    monkeypatch.setenv("SYNC_TARGET_SECONDS", target)

    async def go():
        async with sync_mod.paced_sweep(10, target=sync_mod.facet_budget()):
            assert sync_mod.encar.pacer is not None
        assert sync_mod.encar.pacer is None

    asyncio.run(go())


# ── a closed door is not a wedge ─────────────────────────────────────────────

def test_an_automatic_start_stands_down_while_encar_refuses_every_route(monkeypatch):
    """"Двучасов бюджет хубаво, ама от 30 минути не е мръднало" — with every route shut out,
    a crawl aborts on its first count probe. Starting it again on a timer just repeats that."""
    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            monkeypatch.setattr(syncjob, "_task", None)
            monkeypatch.setattr(syncjob.encar_mod, "all_blocked", lambda: True)
            monkeypatch.setattr(syncjob.encar_mod, "blocked_reason",
                                lambda: "HTTP 403 from upstream (още 180s)")

            started = []

            async def fake_run(db_, trigger, resume_run_id=None):
                started.append(trigger)

            monkeypatch.setattr(syncjob, "_run", fake_run)

            for trigger in ("schedule", "resume", "auto-restart"):
                out = await syncjob.start(db, trigger=trigger)
                assert out["started"] is False and "Encar" in out["reason"]
            assert started == []

            # By hand is the operator's call and is never refused.
            out = await syncjob.start(db, trigger="manual")
            await asyncio.sleep(0)                  # let the detached task actually start
            assert out["started"] is True and started == ["manual"]
        finally:
            client.close()

    asyncio.run(go())


def test_a_stall_with_the_upstream_down_stops_the_sync_instead_of_looping(monkeypatch):
    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        keep_live = await db.sync_state.find_one({"_id": syncjob.LIVE_ID})
        keep_job = await db.sync_state.find_one({"_id": syncjob.JOB_ID})
        restarted = []
        try:
            monkeypatch.setattr(syncjob, "_task", _FakeTask())
            monkeypatch.setattr(syncjob, "_last_auto_restart", {"at": 0.0})
            monkeypatch.setattr(syncjob.encar_mod, "all_blocked", lambda: True)
            monkeypatch.setattr(syncjob.encar_mod, "blocked_reason", lambda: "TimeoutError")

            async def no_wait(tasks, timeout=None):
                return set(), set()

            async def fake_restart(*a, **k):
                restarted.append(1)

            monkeypatch.setattr(syncjob.asyncio, "wait", no_wait)
            monkeypatch.setattr(syncjob, "restart", fake_restart)
            await db.sync_state.update_one(
                {"_id": syncjob.LIVE_ID},
                {"$set": {"updated_at": datetime.now(timezone.utc) - timedelta(hours=2)}},
                upsert=True)

            assert await syncjob.restart_if_stalled(db) is False
            assert restarted == [], "restarting into a closed door is the loop"
            job = await db.sync_state.find_one({"_id": syncjob.JOB_ID})
            assert "Encar не отговаря" in (job.get("error") or "")
        finally:
            for doc_id, keep in ((syncjob.LIVE_ID, keep_live), (syncjob.JOB_ID, keep_job)):
                if keep:
                    await db.sync_state.replace_one({"_id": doc_id}, keep, upsert=True)
            client.close()

    asyncio.run(go())


def test_the_bisection_publishes_progress_on_probes_not_only_on_written_rows(monkeypatch):
    """A deep walk down the tree spends paced probes without writing a car. With nothing
    published the panel froze — which is what "не е мръднало въобще" looked like."""
    beats = []

    async def count(q=None, interactive=False):
        return 900                                    # forces one split, then two leaves

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        return {"SearchResults": [{"Id": "1"}]}

    async def sink(rows):
        return None

    async def beat():
        beats.append(1)

    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setattr(sync_mod.encar, "count", count)
    monkeypatch.setattr(sync_mod.encar, "search", search)

    st = defaultdict(int)
    st["retry_leaves"] = []
    ctx = {"plan": {}, "done": set(), "flush": beat, "beat": beat}
    asyncio.run(sync_mod._crawl_node([], sync_mod._fresh_dims(), 5000, sink, st, ctx))
    assert st["probes"] >= 1
    assert len(beats) >= st["probes"], (beats, st["probes"])

