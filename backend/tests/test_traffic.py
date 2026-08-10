"""Cookieless visitor counting: the numbers, and the promise the privacy policy makes.

The policy says the fingerprint is irreversible, that the salt is renewed daily so visits cannot
be linked across days, that the raw IP is not stored, and that nothing is written to the
visitor's device. Those are testable claims, so they are tested here rather than trusted.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# The suite's own agent is `python-requests`, which the counter correctly refuses as a robot.
# A test about counting PEOPLE therefore has to arrive looking like a person's browser.
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}



def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _run(fn):
    async def go():
        client, db = _db()
        try:
            return await fn(db)
        finally:
            client.close()

    return asyncio.run(go())


def test_a_ping_is_counted_and_stores_no_address():
    """The policy promises the IP is not kept. A stored address would break that outright."""
    path = f"/test-{uuid.uuid4().hex[:10]}"
    r = requests.post(f"{BASE}/traffic/ping", json={"path": path, "label": "Test page"},
                      timeout=30, headers=UA)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["counted"] is True

    row = _run(lambda db: db.traffic_hits.find_one({"p": path}))
    assert row, "the view was not recorded"
    assert set(row.keys()) == {"_id", "v", "vl", "p", "l", "at"}, row.keys()
    assert row["l"] == "Test page"
    # No field anywhere may hold an address or a user agent.
    blob = str(row)
    assert "Mozilla" not in blob and "." not in row["v"] and "." not in row["vl"]
    assert len(row["v"]) == 20 and all(c in "0123456789abcdef" for c in row["v"])
    assert len(row["vl"]) == 20 and all(c in "0123456789abcdef" for c in row["vl"])
    assert row["v"] != row["vl"], "the two salts must produce different digests"
    _run(lambda db: db.traffic_hits.delete_many({"p": path}))


def test_the_same_visitor_gets_the_same_digest_within_a_day():
    """Otherwise "people" and "views" would be the same number and the metric is a lie."""
    path = f"/test-{uuid.uuid4().hex[:10]}"
    s = requests.Session()
    s.headers.update(UA)
    for _ in range(3):
        s.post(f"{BASE}/traffic/ping", json={"path": path}, timeout=30)

    rows = _run(lambda db: db.traffic_hits.find({"p": path}).to_list(10))
    assert len(rows) == 3
    assert len({r["v"] for r in rows}) == 1, "one visitor was counted as several"
    assert len({r["vl"] for r in rows}) == 1, "one visitor was counted as several (long salt)"
    _run(lambda db: db.traffic_hits.delete_many({"p": path}))


def test_the_long_salt_is_kept_and_expires_by_itself():
    """A separate, longer-lived salt is what makes the week and month counts honest.

    It must still expire on its own so the fingerprints it produced cannot outlive it.
    """
    requests.post(f"{BASE}/traffic/ping", json={"path": "/long-salt-check"}, timeout=30,
                  headers=UA)
    row = _run(lambda db: db.traffic_salt_long.find_one({"_id": "current"}))
    assert row and len(row["salt"]) == 64

    idx = _run(lambda db: db.traffic_salt_long.index_information())
    ttl = [v for v in idx.values() if "expireAfterSeconds" in v]
    assert ttl, "the long-salt collection has no TTL index"
    assert ttl[0]["expireAfterSeconds"] == 45 * 86400
    _run(lambda db: db.traffic_hits.delete_many({"p": "/long-salt-check"}))


def test_todays_salt_is_kept_and_expires_by_itself():
    """A salt that outlived its day would undo the whole point of rotating it."""
    requests.post(f"{BASE}/traffic/ping", json={"path": "/salt-check"}, timeout=30, headers=UA)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = _run(lambda db: db.traffic_salt.find_one({"_id": day}))
    assert row and len(row["salt"]) == 64

    idx = _run(lambda db: db.traffic_salt.index_information())
    ttl = [v for v in idx.values() if "expireAfterSeconds" in v]
    assert ttl, "the salt collection has no TTL index"
    assert ttl[0]["expireAfterSeconds"] == 2 * 86400
    _run(lambda db: db.traffic_hits.delete_many({"p": "/salt-check"}))


def test_hits_expire_by_themselves():
    idx = _run(lambda db: db.traffic_hits.index_information())
    ttl = [v for v in idx.values() if "expireAfterSeconds" in v]
    assert ttl and ttl[0]["expireAfterSeconds"] == 40 * 86400


def test_bots_are_not_counted():
    """A crawler is not a person, and "12 online" must not mean "12 crawlers"."""
    path = f"/test-{uuid.uuid4().hex[:10]}"
    r = requests.post(f"{BASE}/traffic/ping", json={"path": path}, timeout=30,
                      headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"})
    assert r.status_code == 200
    assert r.json()["counted"] is False
    assert _run(lambda db: db.traffic_hits.count_documents({"p": path})) == 0


def test_the_numbers_are_admin_only():
    """Traffic is commercial information: a visitor must not be able to read it."""
    r = requests.get(f"{BASE}/admin/traffic", timeout=30)
    assert r.status_code == 401, r.text[:200]


@pytest.mark.skipif(not ADMIN_TOKEN, reason="no ADMIN_TOKEN in this environment")
def test_the_snapshot_has_every_window():
    r = requests.get(f"{BASE}/admin/traffic", headers={"x-admin-token": ADMIN_TOKEN}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert data["live_minutes"] == 5
    for window in ("day", "week", "month"):
        assert set(data[window]) == {"visitors", "views"}
        # Views can never be fewer than the people who made them.
        assert data[window]["views"] >= data[window]["visitors"]
    assert isinstance(data["pages"], list)


@pytest.mark.skipif(not ADMIN_TOKEN, reason="no ADMIN_TOKEN in this environment")
def test_a_fresh_view_shows_up_as_live():
    path = f"/test-{uuid.uuid4().hex[:10]}"
    label = f"Live {uuid.uuid4().hex[:6]}"
    requests.post(f"{BASE}/traffic/ping", json={"path": path, "label": label}, timeout=30,
                  headers=UA)

    # The snapshot is cached for a few seconds on purpose; wait it out rather than reach in.
    import time

    time.sleep(11)
    data = requests.get(f"{BASE}/admin/traffic", headers={"x-admin-token": ADMIN_TOKEN},
                        timeout=30).json()
    assert data["live"] >= 1
    assert any(p["label"] == label for p in data["pages"]), data["pages"]
    _run(lambda db: db.traffic_hits.delete_many({"p": path}))


def test_history_is_admin_only():
    r = requests.get(f"{BASE}/admin/traffic/history", timeout=30)
    assert r.status_code == 401, r.text[:200]


@pytest.mark.skipif(not ADMIN_TOKEN, reason="no ADMIN_TOKEN in this environment")
def test_history_fills_quiet_days_with_zeros():
    """A chart that silently skips quiet days makes a flat week look like a busy one."""
    marker = f"/test-{uuid.uuid4().hex[:10]}"
    today = datetime.now(timezone.utc)

    async def seed(db):
        await db.traffic_hits.insert_many([
            # two people on the same day, one of them twice
            {"v": "d" * 20, "p": marker, "l": "x", "at": today - timedelta(days=2, hours=1)},
            {"v": "d" * 20, "p": marker, "l": "x", "at": today - timedelta(days=2, hours=2)},
            {"v": "e" * 20, "p": marker, "l": "x", "at": today - timedelta(days=2, hours=3)},
        ])

    _run(seed)
    try:
        r = requests.get(f"{BASE}/admin/traffic/history", params={"days": 7},
                         headers={"x-admin-token": ADMIN_TOKEN}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        rows = r.json()["items"]

        assert len(rows) == 7, "a fixed window must always return the same number of days"
        days = [x["day"] for x in rows]
        assert days == sorted(days), "oldest first"
        assert len(set(days)) == 7, "no day repeated, none missing"

        for row in rows:
            assert row["visitors"] <= row["views"], row

        seeded = [x for x in rows
                  if x["day"] == (today - timedelta(days=2)).strftime("%Y-%m-%d")][0]
        assert seeded["visitors"] >= 2 and seeded["views"] >= 3, seeded
    finally:
        _run(lambda db: db.traffic_hits.delete_many({"p": marker}))


@pytest.mark.skipif(not ADMIN_TOKEN, reason="no ADMIN_TOKEN in this environment")
def test_history_window_is_bounded():
    """`days` comes from a query string, so it has to be clamped rather than trusted."""
    for asked, expected in ((0, 1), (-5, 1), (9999, 40)):
        r = requests.get(f"{BASE}/admin/traffic/history", params={"days": asked},
                         headers={"x-admin-token": ADMIN_TOKEN}, timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert len(r.json()["items"]) == expected, (asked, len(r.json()["items"]))


def test_windows_widen_rather_than_shrink():
    """A day cannot hold more views than the week that contains it."""
    marker = f"/test-{uuid.uuid4().hex[:10]}"

    async def seed(db):
        now = datetime.now(timezone.utc)
        await db.traffic_hits.insert_many([
            {"v": "aaaaaaaaaaaaaaaaaaaa", "p": marker, "l": "old", "at": now - timedelta(days=20)},
            {"v": "bbbbbbbbbbbbbbbbbbbb", "p": marker, "l": "week", "at": now - timedelta(days=3)},
            {"v": "cccccccccccccccccccc", "p": marker, "l": "today", "at": now - timedelta(hours=2)},
        ])

    _run(seed)
    try:
        import traffic

        async def read(db):
            traffic.set_db(db)
            traffic._cache.update({"at": None, "data": None})
            return await traffic.snapshot()

        snap = _run(read)
        assert snap["day"]["views"] <= snap["week"]["views"] <= snap["month"]["views"]
        assert snap["month"]["visitors"] >= 3
    finally:
        _run(lambda db: db.traffic_hits.delete_many({"p": marker}))
