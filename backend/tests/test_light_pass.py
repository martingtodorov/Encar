"""The light pass: a catalogue that is minutes old instead of a night old.

The full sweep is ~700 paced requests and runs overnight, so by mid-morning the newest cars
on Encar are not on our site at all. Encar answers newest-modified FIRST, so the light pass
reads only the top of that feed and stops as soon as a page holds nothing we did not already
have — two to six requests, cheap enough to run every half hour.

What it must NOT do is retire: a page of the newest ads says nothing about a car that sold,
and a retire pass on a partial read is what once emptied the catalogue day after day. Cars
Encar reports under contract still leave at once — that is a positive statement, not silence.
"""

import asyncio
import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import sync as sync_mod
import syncjob


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"{os.environ['DB_NAME']}_test_light_{os.getpid()}"
    yield client[name]

    async def cleanup():
        await client.drop_database(name)
        client.close()

    asyncio.get_event_loop().run_until_complete(cleanup())


def _row(i, price=3000, mileage=50_000, sell="\uc77c\ubc18", status=None):
    row = {"Id": f"car-{i}", "Manufacturer": "\ubca4\uce20", "Model": "C-Class",
           "Price": price, "Mileage": mileage, "Year": 202001, "FormYear": 2020,
           "Photos": [{"location": f"/carpicture01/pic{i}/{i}_001.jpg"}],
           "Condition": [], "SellType": sell}
    if status:
        row["SalesStatus"] = status
    return row


def _feed(pages):
    """Serve fixed pages, newest first, and count the requests."""
    state = {"requests": 0}

    async def search(offset=0, limit=500, q=None, sort="ModifiedDate", interactive=False):
        state["requests"] += 1
        idx = offset // limit if limit else 0
        rows = pages[idx] if idx < len(pages) else []
        return {"Count": len(rows), "SearchResults": rows}

    return search, state


def _with_upstream(search):
    real = sync_mod.encar.search
    sync_mod.encar.search = search
    return real


def test_the_light_pass_indexes_new_cars_and_new_prices(db, monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setenv("SYNC_RECENT_SECONDS", "0")

    async def go():
        await sync_mod.ensure_indexes(db)
        # Yesterday's catalogue: two cars, one of them cheaper than it is today.
        search, state = _feed([[_row(1, price=3000), _row(2, price=4000)]])
        real = _with_upstream(search)
        try:
            first = await sync_mod.crawl_recent(db)
            assert first["new"] == 2, first
            # Now car 1 has a new price and car 3 has appeared.
            search2, state2 = _feed([[_row(3, price=2500), _row(1, price=2800)],
                                     [_row(2, price=4000)]])
            sync_mod.encar.search = search2
            second = await sync_mod.crawl_recent(db)
        finally:
            sync_mod.encar.search = real

        assert second["new"] == 1, second
        assert second["changed"] == 1, second
        got = {d["_id"]: d async for d in db.listings.find({})}
        assert set(got) == {"car-1", "car-2", "car-3"}
        assert got["car-1"]["price_krw"] == 2800 * 10_000
        assert got["car-1"]["sale_eur"] > 0, "a changed price must be re-quoted in EUR"
        assert all(d["active"] for d in got.values())
        assert state["requests"] >= 1 and state2["requests"] >= 1

    asyncio.get_event_loop().run_until_complete(go())


def test_it_stops_at_the_first_page_that_holds_nothing_new(db, monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setenv("SYNC_RECENT_SECONDS", "0")

    async def go():
        await sync_mod.ensure_indexes(db)
        pages = [[_row(i) for i in range(5)],
                 [_row(i) for i in range(5, 10)],
                 [_row(i) for i in range(10, 15)]]
        search, state = _feed(pages)
        real = _with_upstream(search)
        try:
            await sync_mod.crawl_recent(db, max_pages=6)     # learns all three pages
            asked = state["requests"]
            again = await sync_mod.crawl_recent(db, max_pages=6)
            spent = state["requests"] - asked
        finally:
            sync_mod.encar.search = real

        assert again["new"] == 0 and again["changed"] == 0, again
        assert spent == 1, f"a second pass over an unchanged feed cost {spent} requests"
        assert again["pages"] == 1

    asyncio.get_event_loop().run_until_complete(go())


def test_the_light_pass_never_retires_a_car_it_simply_did_not_see(db, monkeypatch):
    """The dangerous mistake. It reads the TOP of the feed; everything else is not "gone"."""
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setenv("SYNC_RECENT_SECONDS", "0")

    async def go():
        await sync_mod.ensure_indexes(db)
        await db.listings.insert_many([
            {"_id": f"old-{i}", "active": True, "manufacturer": "\ubca4\uce20",
             "price_krw": 30_000_000, "last_crawl": "nightly"} for i in range(500)])
        search, _ = _feed([[_row(1)]])
        real = _with_upstream(search)
        try:
            await sync_mod.crawl_recent(db)
        finally:
            sync_mod.encar.search = real

        assert await db.listings.count_documents({"active": True}) == 501
        assert await db.listings.count_documents({"active": False}) == 0

    asyncio.get_event_loop().run_until_complete(go())


def test_a_car_under_contract_leaves_at_once(db, monkeypatch):
    monkeypatch.setenv("SYNC_TARGET_SECONDS", "0")
    monkeypatch.setenv("SYNC_RECENT_SECONDS", "0")

    async def go():
        await sync_mod.ensure_indexes(db)
        search, _ = _feed([[_row(7)]])
        real = _with_upstream(search)
        try:
            await sync_mod.crawl_recent(db)
            sync_mod.encar.search = _feed([[_row(7, status="CONTRACT")]])[0]
            out = await sync_mod.crawl_recent(db)
        finally:
            sync_mod.encar.search = real

        assert out["contracted"] == 1, out
        doc = await db.listings.find_one({"_id": "car-7"})
        assert doc["active"] is False and doc["under_contract"] is True

    asyncio.get_event_loop().run_until_complete(go())


# ── the switch and the schedule ──────────────────────────────────────────────

def test_the_light_pass_is_off_until_it_is_turned_on(db):
    async def go():
        cfg = await syncjob.get_light(db)
        assert cfg["enabled"] is False
        assert cfg["mode"] == "interval"
        assert cfg["next_run_at"] is None
        assert cfg["last"] is None

    asyncio.get_event_loop().run_until_complete(go())


def test_the_interval_and_the_named_hours_are_both_settable(db):
    async def go():
        cfg = await syncjob.set_light(db, True, "interval", 30, [], "Europe/Sofia", 4)
        assert cfg["enabled"] and cfg["every_min"] == 30 and cfg["max_pages"] == 4
        assert cfg["next_run_at"], "an enabled interval must name its next run"

        cfg = await syncjob.set_light(db, True, "times", 60, ["9:5", "18:00", "09:05"],
                                      "Europe/Bucharest", 6)
        assert cfg["mode"] == "times"
        assert cfg["times"] == ["09:05", "18:00"], cfg["times"]
        assert cfg["tz"] == "Europe/Bucharest"
        assert cfg["next_run_at"]

    asyncio.get_event_loop().run_until_complete(go())


def test_nonsense_settings_are_refused_rather_than_stored(db):
    async def go():
        for bad in (
            lambda: syncjob.set_light(db, True, "whenever", 30, [], "Europe/Sofia", 4),
            lambda: syncjob.set_light(db, True, "interval", 1, [], "Europe/Sofia", 4),
            lambda: syncjob.set_light(db, True, "interval", 5000, [], "Europe/Sofia", 4),
            lambda: syncjob.set_light(db, True, "interval", 30, [], "Europe/Sofia", 99),
            lambda: syncjob.set_light(db, True, "times", 30, [], "Europe/Sofia", 4),
            lambda: syncjob.set_light(db, True, "times", 30, ["12:00"], "Mars/Olympus", 4),
            lambda: syncjob.set_light(db, True, "times", 30, ["25:00"], "Europe/Sofia", 4),
        ):
            with pytest.raises(Exception):
                await bad()
        stored = await db.settings.find_one({"_id": syncjob.LIGHT_ID})
        assert stored is None, "a refused setting must not be half-written"

    asyncio.get_event_loop().run_until_complete(go())


def test_the_light_pass_stands_down_while_the_full_sync_runs(db, monkeypatch):
    async def go():
        monkeypatch.setattr(syncjob, "is_running", lambda db=None: True)
        out = await syncjob.run_light(db, trigger="interval")
        assert out["started"] is False
        assert "пълната" in out["reason"]

    asyncio.get_event_loop().run_until_complete(go())


def test_the_interval_mode_waits_out_its_gap(db, monkeypatch):
    """Two scheduler ticks a second apart must not mean two passes."""
    from datetime import timedelta
    fired = []

    async def go():
        await syncjob.set_light(db, True, "interval", 60, [], "Europe/Sofia", 4)
        monkeypatch.setattr(syncjob, "is_running", lambda db=None: False)

        async def fake_run(database, trigger="manual"):
            fired.append(trigger)
            await database.settings.update_one({"_id": syncjob.LIGHT_ID},
                                               {"$set": {"last_run_at": syncjob._now()}})
            return {"started": True}

        monkeypatch.setattr(syncjob, "run_light", fake_run)
        task = asyncio.get_running_loop().create_task(syncjob.light_scheduler(db, period=0))
        await asyncio.sleep(0.25)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert fired == ["interval"], fired

        # An hour later it fires again.
        await db.settings.update_one(
            {"_id": syncjob.LIGHT_ID},
            {"$set": {"last_run_at": syncjob._now() - timedelta(minutes=61)}})
        task = asyncio.get_running_loop().create_task(syncjob.light_scheduler(db, period=0))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert fired == ["interval", "interval"], fired

    asyncio.get_event_loop().run_until_complete(go())
