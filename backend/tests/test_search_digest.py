"""The weekly saved-search digest, checked against the live index.

Run with: cd /app/backend && python -m pytest tests/test_search_digest.py -q
No pytest-asyncio here (it is not installed) - each test drives its own loop with asyncio.run,
the same pattern the other suites use.
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

import digest                                              # noqa: E402
import mailer                                              # noqa: E402
import notify                                              # noqa: E402

QUERY = "make=bmw&price_max=200000"


def _now():
    return datetime.now(timezone.utc)


class Fixture:
    """One throwaway buyer with two saved searches, and a mailer that only records."""

    def __init__(self, db, uid, email):
        self.db, self.uid, self.email = db, uid, email
        self.sent = []

    async def run(self):
        real = mailer.send_search_digest

        async def fake(to, groups, lang="en", popular=None):
            # Only OUR buyer: a digest run sweeps every account, including whatever another
            # suite is running in parallel, and those letters are not this test's business.
            if to == self.email:
                self.sent.append({"to": to, "groups": groups, "lang": lang,
                                  "popular": popular or []})
            return True

        mailer.send_search_digest = fake
        try:
            return await digest.run(self.db)
        finally:
            mailer.send_search_digest = real

    async def mark(self, sid="s_one"):
        return await self.db.search_watch.find_one({"_id": f"{self.uid}:{sid}"})


async def _with_buyer(body, alerts=True, email_on=True):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    notify.set_db(db)
    uid = str(uuid.uuid4())
    email = f"digest-{uid[:8]}@example.com"
    await db.users.insert_one({
        "_id": uid, "email": email, "email_norm": email, "created_at": _now(),
        "saved_searches": [
            {"id": "s_one", "name": "BMW under 200k", "lang": "bg", "query": QUERY,
             "alerts": alerts},
            {"id": "s_two", "name": "Nothing ever", "lang": "bg",
             "query": "make=bmw&year_min=2099", "alerts": alerts},
        ],
        # The stored key is `notify`, NOT `notify_prefs` - see notify.prefs_of.
        "notify": {"email": {"enabled": email_on, "saved_search": True},
                   "push": {"enabled": False, "saved_search": True}},
    })
    f = Fixture(db, uid, email)
    try:
        return await body(f)
    finally:
        await db.users.delete_one({"_id": uid})
        await db.search_watch.delete_many({"user_id": uid})
        await db.search_watch.delete_many({"_id": {"$in": [f"{uid}:s_one", f"{uid}:s_two"]}})
        client.close()


def test_one_email_covers_every_search_with_news():
    async def body(f):
        await f.run()
        assert len(f.sent) == 1, "one letter per buyer, not one per search"
        mail = f.sent[0]
        assert mail["to"] == f.email and mail["lang"] == "bg"
        # The impossible search must not appear at all.
        names = [g["name"] for g in mail["groups"]]
        assert names == ["BMW under 200k"], names
        cars = mail["groups"][0]["cars"]
        assert cars and len(cars) <= digest.PER_SEARCH
        assert all(c["title"] and c["car_id"] for c in cars)
        assert all(c["image"] and c["image"].startswith("http") for c in cars), \
            "every car needs an absolute photo URL, or the email shows a broken box"

    asyncio.run(_with_buyer(body))


def test_nothing_new_means_no_email():
    async def body(f):
        await f.run()                                      # first digest reports and stamps
        f.sent.clear()
        await f.run()
        assert f.sent == [], "an empty digest must never be sent"

    asyncio.run(_with_buyer(body))


def test_window_advances_only_for_reported_searches():
    async def body(f):
        await f.run()
        one, two = await f.mark("s_one"), await f.mark("s_two")
        assert one and one.get("digest_at"), "the reported search must be stamped"
        assert two and two.get("digest_at"), "a checked search is stamped even with no cars"
        # Backdating the window brings the same cars back into scope.
        await f.db.search_watch.update_one(
            {"_id": f"{f.uid}:s_one"},
            {"$set": {"digest_at": _now() - timedelta(days=3650)}})
        f.sent.clear()
        await f.run()
        assert len(f.sent) == 1

    asyncio.run(_with_buyer(body))


def test_alerts_off_and_email_off_are_both_respected():
    async def body(f):
        await f.run()
        assert f.sent == []

    asyncio.run(_with_buyer(body, alerts=False))
    asyncio.run(_with_buyer(body, email_on=False))


def test_digest_html_carries_photos_titles_prices_and_links():
    groups = [{
        "name": "Пети клас",
        "total": 14,
        "cars": [{"car_id": "42000001", "title": "BMW 5 Series",
                  "image": "https://ci.encar.com/pic/42000001_001.jpg",
                  "price_eur": 31999, "year": 2021, "mileage": 48000}],
    }]
    sent = {}

    async def capture(to, subject, html):
        sent.update({"to": to, "subject": subject, "html": html})
        return True

    real = mailer._send
    mailer._send = capture
    try:
        asyncio.run(mailer.send_search_digest("buyer@example.com", groups, "bg"))
    finally:
        mailer._send = real

    html = sent["html"]
    assert "Пети клас" in html and "BMW 5 Series" in html
    assert "31,999" in html and "48,000 km" in html
    assert 'src="https://ci.encar.com/pic/42000001_001.jpg"' in html, "the photo must be there"
    assert "/bg/car/42000001" in html, "the title must link to the ad"
    assert "и още 13" in html, "the tail count must be shown"
    assert "14" in html


def test_popular_section_is_rendered_and_counted_by_people():
    groups = [{"name": "Пети клас", "total": 1,
               "cars": [{"car_id": "42000001", "title": "BMW 5 Series",
                         "image": "https://ci.encar.com/pic/1.jpg",
                         "price_eur": 31999, "year": 2021, "mileage": 48000}]}]
    popular = [{"car_id": "42122129", "title": "Mercedes-Benz C-Class W205",
                "image": "https://ci.encar.com/pic/2.jpg", "price_eur": 21500,
                "year": 2019, "mileage": 60000, "people": 29}]
    sent = {}

    async def capture(to, subject, html):
        sent["html"] = html
        return True

    real = mailer._send
    mailer._send = capture
    try:
        asyncio.run(mailer.send_search_digest("buyer@example.com", groups, "bg",
                                              popular=popular))
    finally:
        mailer._send = real

    html = sent["html"]
    assert "Най-гледаните тази седмица" in html
    assert "Mercedes-Benz C-Class W205" in html
    assert "/bg/car/42122129" in html


def test_top_viewed_counts_distinct_people_not_refreshes():
    """A single buyer hammering refresh (high `n`, `u` of 1) must lose to two real people."""
    async def body():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        day = _now().strftime("%Y-%m-%d")
        hammered, honest = "t_hammer", "t_honest"
        try:
            await db.listings.insert_many([
                {"_id": hammered, "manufacturer": "BMW", "model": "X", "sale_eur": 1,
                 "photos": ["a.jpg"]},
                {"_id": honest, "manufacturer": "Audi", "model": "Y", "sale_eur": 1,
                 "photos": ["b.jpg"]}])
            await db.car_views.insert_many([
                {"_id": f"{hammered}:{day}", "car_id": hammered, "day": day,
                 "n": 99999, "u": 1},
                {"_id": f"{honest}:{day}", "car_id": honest, "day": day,
                 "n": 8, "u": 8}])
            top = await digest.top_viewed(db, limit=5000)
            by_id = {c["car_id"]: c["people"] for c in top}
            # The refresher counts once; the eight real people count eight, so the honest car
            # is ahead of the hammered one despite 99,999 raw hits.
            assert by_id.get(hammered) == 1, by_id.get(hammered)
            assert by_id.get(honest) == 8
            order = [c["car_id"] for c in top]
            assert order.index(honest) < order.index(hammered)
        finally:
            await db.listings.delete_many({"_id": {"$in": [hammered, honest]}})
            await db.car_views.delete_many({"car_id": {"$in": [hammered, honest]}})
            client.close()

    asyncio.run(body())


def test_next_run_is_a_saturday_afternoon_in_sofia():
    from zoneinfo import ZoneInfo

    nxt = datetime.fromisoformat(digest.next_run_at()).astimezone(ZoneInfo(digest.TZ))
    assert nxt.weekday() == digest.WEEKDAY and nxt.hour == digest.HOUR
    assert nxt > datetime.now(ZoneInfo(digest.TZ))
