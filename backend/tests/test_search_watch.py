"""Instant PUSH alerts for saved searches, checked against the live index.

Email is NOT sent from here any more - the weekly digest owns it (see
test_search_digest.py), so these tests assert on pushes.

Run with: cd /app/backend && python -m pytest tests/test_search_watch.py -q
No pytest-asyncio here (it is not installed) — each test drives its own loop with
asyncio.run, the same pattern the deposit tests use.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
load_dotenv(os.path.join(BACKEND, ".env"))

import mailer                                              # noqa: E402
import notify                                              # noqa: E402
import searchwatch                                         # noqa: E402

QUERY = "make=bmw&price_max=200000"


def _now():
    return datetime.now(timezone.utc)


class Fixture:
    """One throwaway buyer with one saved search, and a push channel that only records."""

    def __init__(self, db, uid, email):
        self.db, self.uid, self.email = db, uid, email
        self.sent = []

    async def run(self, **kw):
        real = notify.push_to_user

        async def fake(uid, title, body, url="", event=""):
            self.sent.append({"uid": uid, "title": title, "body": body,
                              "url": url, "event": event})
            return True

        notify.push_to_user = fake
        try:
            return await searchwatch.run(self.db, **kw)
        finally:
            notify.push_to_user = real


async def _with_buyer(body, alerts=True):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    notify.set_db(db)
    uid = str(uuid.uuid4())
    email = f"watch-{uid[:8]}@example.com"
    await db.users.insert_one({
        "_id": uid, "email": email, "email_norm": email, "created_at": _now(),
        "saved_searches": [{"id": "s_test", "name": "Test search", "lang": "bg",
                            "query": QUERY, "alerts": alerts}],
        # Push is off by default for everybody, and this pass is push-only now.
        # The stored key is `notify`, NOT `notify_prefs` - see notify.prefs_of.
        "notify": {"push": {"enabled": True, "saved_search": True},
                   "email": {"enabled": True, "saved_search": True}},
    })
    f = Fixture(db, uid, email)
    try:
        return await body(f)
    finally:
        await db.users.delete_one({"_id": uid})
        await db.search_watch.delete_many({"user_id": uid})
        client.close()


def test_first_pass_only_sets_a_baseline():
    async def body(f):
        out = await f.run()
        assert out["baselines"] >= 1
        assert f.sent == [], "turning alerts on must not mail out the existing catalogue"
        doc = await f.db.search_watch.find_one({"_id": f"{f.uid}:s_test"})
        assert doc and doc["query"] == QUERY

    asyncio.run(_with_buyer(body))


def test_second_pass_alerts_then_goes_quiet():
    async def body(f):
        await f.run()                                      # baseline
        # Backdate it so cars already in the index count as "arrived since".
        await f.db.search_watch.update_one(
            {"_id": f"{f.uid}:s_test"},
            {"$set": {"at": _now() - timedelta(days=3650)}})

        out = await f.run()
        assert out["matches"] > 0, "BMWs in the index should match make=bmw"
        assert len(f.sent) == 1
        note = f.sent[0]
        assert note["uid"] == f.uid and note["event"] == "saved_search"
        assert "Test search" in note["body"]
        assert note["url"] == "/bg/searches"
        assert out["emails"] == 0, "the weekly digest sends the email, not this pass"

        # The baseline moved with the alert, so nothing is repeated.
        f.sent.clear()
        assert (await f.run())["matches"] == 0
        assert f.sent == []

    asyncio.run(_with_buyer(body))


def test_alerts_off_is_never_checked():
    async def body(f):
        assert (await f.run())["searches"] == 0
        assert f.sent == []

    asyncio.run(_with_buyer(body, alerts=False))


def test_changing_the_filters_rebases():
    async def body(f):
        await f.run()
        await f.db.users.update_one({"_id": f.uid},
                                    {"$set": {"saved_searches.0.query": "make=audi"}})
        out = await f.run()
        assert out["baselines"] >= 1, "a different question needs a fresh baseline"
        assert f.sent == []
        doc = await f.db.search_watch.find_one({"_id": f"{f.uid}:s_test"})
        assert doc["query"] == "make=audi"

    asyncio.run(_with_buyer(body))


def test_stored_slugs_resolve_to_upstream_values():
    async def body(f):
        p = await searchwatch._payload(
            f.db, "make=bmw&fuels=diesel&price_min=10000&year_min=2019&only_inspection=1")
        assert p["makes"] and p["makes"][0] != "bmw", "the make slug must resolve"
        assert p["fuels"] and p["fuels"][0] != "diesel", "the fuel slug must resolve"
        assert p["price_min"] == 10000.0
        assert p["year_min"] == 2019
        assert p["only_inspection"] is True

    asyncio.run(_with_buyer(body))
