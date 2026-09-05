"""The car page must not wait on the four side documents.

Upstream is paced at one request every 1.2 seconds GLOBALLY, so fetching the insurance
record, the inspection sheet, the diagnosis and the factory options before answering cost a
cold car 5 to 16 seconds of spinner (measured on production). None of that is above the
fold, so `car_detail` now answers as soon as it has the car itself, marks the payload
`sections_pending` and finishes the rest in the background.

These tests call the endpoint function directly with a fake upstream, because the point
being proved is WHEN it answers, not what the HTTP layer does with it.
"""
import asyncio
import time

import pytest
from starlette.requests import Request

import server

SECTION_DELAY = 0.6           # stands in for the 1.2s upstream pacing per document
TEST_ID = "pytest-two-phase"


def _request():
    return Request({"type": "http", "method": "GET", "path": f"/api/car/{TEST_ID}",
                    "headers": [], "query_string": b"", "client": ("127.0.0.1", 0)})


class FakeEncar:
    """`detail` is instant; every side document is slow, exactly like the real pacing."""

    def __init__(self, detail):
        self._detail = detail
        self.calls = []

    async def detail(self, listing_id):
        self.calls.append("detail")
        return self._detail

    async def _slow(self, name, value):
        self.calls.append(name)
        await asyncio.sleep(SECTION_DELAY)
        return value

    async def record(self, vid, vno=""):
        return await self._slow("record", {"accidentCnt": 0, "myAccidentCnt": 0,
                                           "otherAccidentCnt": 0, "ownerChangeCnt": 1})

    async def inspection(self, vid):
        return await self._slow("inspection", {"master": {"detail": {}}})

    async def diagnosis(self, vid):
        return await self._slow("diagnosis", None)

    async def choice_options(self, vid):
        return await self._slow("choice_options", [])


@pytest.fixture(scope="module")
def loop():
    """One loop for the whole module: motor binds its client to the first loop it sees, so
    a fresh loop per test makes the second one fail with "attached to a different loop"."""
    made = asyncio.new_event_loop()
    yield made
    made.close()


@pytest.fixture
def seeded(monkeypatch, loop):
    """A synthetic listing carrying a real `detail` document, cleaned up afterwards."""

    async def setup():
        source = await server.db.car_details.find_one({"detail": {"$exists": True}})
        listing = await server.db.listings.find_one({"active": True})
        if not source or not listing:
            return None
        row = dict(listing)
        row["_id"] = TEST_ID
        await server.db.listings.delete_one({"_id": TEST_ID})
        await server.db.car_details.delete_one({"_id": TEST_ID})
        await server.db.listings.insert_one(row)
        return source["detail"]

    detail = loop.run_until_complete(setup())
    if not detail:
        pytest.skip("no cached car detail in this database to build a fake from")

    fake = FakeEncar(detail)
    monkeypatch.setattr(server, "encar", fake)
    # Keep the test hermetic: option dictionaries and make/model translation must not reach
    # out to anything.
    monkeypatch.setattr(server, "option_dicts_cached",
                        lambda *a, **k: _resolved({"standard": {}, "tuning": {},
                                                   "metas": {}}))
    monkeypatch.setattr(server, "translate_many", lambda *a, **k: _resolved({}))
    monkeypatch.setattr(server, "schedule_translation", lambda *a, **k: None)

    yield loop, fake

    async def cleanup():
        await server.db.listings.delete_one({"_id": TEST_ID})
        await server.db.car_details.delete_one({"_id": TEST_ID})

    loop.run_until_complete(cleanup())


def _resolved(value):
    async def done():
        return value
    return done()


def test_cold_car_answers_before_the_sections_arrive(seeded):
    loop, fake = seeded
    started = time.monotonic()
    payload = loop.run_until_complete(server.car_detail(TEST_ID, _request(), lang="bg"))
    elapsed = time.monotonic() - started

    # One upstream call, not five: the page is not paying for the history.
    assert fake.calls[0] == "detail"
    assert elapsed < SECTION_DELAY, f"answered in {elapsed:.2f}s — it waited"
    assert payload["sections_pending"] is True
    # The car itself is all there.
    assert payload["photo_count"] >= 1
    assert payload["title"]
    # ...and the history is honestly absent rather than wrongly declared empty.
    assert payload["insurance"] is None

    # The document is written straight away, so the NEXT visitor does not refetch `detail`.
    doc = loop.run_until_complete(server.db.car_details.find_one({"_id": TEST_ID}))
    assert doc and doc.get("sections_pending") is True
    assert doc.get("detail")


def test_sections_land_in_the_background_and_clear_the_flag(seeded):
    loop, fake = seeded
    loop.run_until_complete(server.car_detail(TEST_ID, _request(), lang="bg"))
    # The background task lives on the loop that started it.
    loop.run_until_complete(asyncio.sleep(SECTION_DELAY + 0.6))

    doc = loop.run_until_complete(server.db.car_details.find_one({"_id": TEST_ID}))
    assert doc.get("record"), "the insurance record never landed"
    assert "sections_pending" not in doc, "the pending flag was never cleared"

    payload = loop.run_until_complete(server.car_detail(TEST_ID, _request(), lang="bg"))
    assert payload["sections_pending"] is False
    assert payload["insurance"], "the second read must carry the history"
    # And it came from the cache: still exactly one `detail` call in this test's lifetime.
    assert fake.calls.count("detail") == 1


def test_a_pending_document_is_retried_rather_than_left_broken(seeded):
    """Upstream unwell mid-flight must not freeze a car without its history forever."""
    loop, fake = seeded

    async def unavailable(*a, **k):
        fake.calls.append("record")
        raise server.EncarUnavailable("upstream circuit open")

    original = fake.record
    fake.record = unavailable
    loop.run_until_complete(server.car_detail(TEST_ID, _request(), lang="bg"))
    loop.run_until_complete(asyncio.sleep(SECTION_DELAY + 0.4))

    doc = loop.run_until_complete(server.db.car_details.find_one({"_id": TEST_ID}))
    assert doc.get("sections_pending") is True, "a failed fetch must stay pending"
    assert not doc.get("record"), "an incomplete section set must not be stored"

    # Upstream recovers; the next read re-arms the fetch on its own.
    fake.record = original
    loop.run_until_complete(server.car_detail(TEST_ID, _request(), lang="bg"))
    loop.run_until_complete(asyncio.sleep(SECTION_DELAY + 0.6))
    doc = loop.run_until_complete(server.db.car_details.find_one({"_id": TEST_ID}))
    assert doc.get("record"), "the retry never completed the document"
    assert "sections_pending" not in doc
