"""Alarms that are not alarms, and an alarm that could not be turned off.

Three complaints, all of them fair:

* "Синхронизация на каталога — никога не е завършвал успешно — статус never", open since
  05/09, twenty-two reminders, and no way to get rid of it. The probe read the LEGACY
  `sync_state._id = "catalogue"` document from the old full sweep — which nothing writes any
  more — so on a host where that sweep never ran it reported "never" for ever and no amount
  of successful syncing could close it.
* "Политика на маршрутизиране — правилата бяха изтрити и върнати преди 239 мин ... Това дори
  не е авария а warning." The guard had already repaired it and traffic never stopped.
* "Encar прокси — работят: residential_proxy ... падналo: home_exit: 403 ... 23 напомняния,
  а то работи перфектно." One tier of a fallback chain refusing is what the chain is FOR.

So: probes can now raise `Info` — said out loud, in the panel and the log, waking nobody —
and any open alert can be dismissed by hand, which mutes that check until it passes again.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notify  # noqa: E402
import syncjob  # noqa: E402
import watchdog  # noqa: E402


def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    watchdog.set_db(db)
    notify.set_db(db)
    return client, db


def _now():
    return datetime.now(timezone.utc)


# ── the alarm that would not go away ─────────────────────────────────────────

class _FakeColl:
    """Just enough of a collection for the sync probe: one document per id."""

    def __init__(self, docs=None):
        self._docs = dict(docs or {})

    async def find_one(self, q):
        return self._docs.get(q["_id"])

    async def update_one(self, q, u, upsert=False):
        self._docs.setdefault(q["_id"], {})
        self._docs[q["_id"]].update(u.get("$set") or {})
        return None


class _FakeDB:
    """Kept off the shared dev database on purpose: two test files fighting over
    `catalogue_job` is a flake, not a finding."""

    def __init__(self, sync_state=None, settings=None):
        self.sync_state = _FakeColl(sync_state)
        self.settings = _FakeColl(settings)


def _probe_sync_with(sync_state, settings=None):
    # The daily schedule has to be ON, or the probe answers "разписанието е изключено" and
    # never reaches the staleness question at all.
    settings = settings or {syncjob.SCHEDULE_ID: {"enabled": True, "times": ["03:30"],
                                                  "tz": "Europe/Sofia"}}
    watchdog._db = _FakeDB(sync_state, settings)
    return asyncio.run(watchdog._probe_sync())


def test_the_sync_check_reads_the_document_the_sync_actually_writes():
    """`catalogue_job` is where a sync records itself. Reading `catalogue` instead is why an
    alarm from 05/09 was still open on 14/09 with the sync running fine every night."""
    detail = _probe_sync_with({
        syncjob.JOB_ID: {"status": "done", "finished_at": _now(),
                         "stopped_by_hand": False, "error": None},
    })
    assert "последен успешен" in detail


def test_a_sync_stopped_on_purpose_is_not_an_outage():
    with pytest.raises(watchdog.Info):
        _probe_sync_with({syncjob.JOB_ID: {"status": "stopped", "stopped_by_hand": True}})


def test_a_sync_that_really_never_finished_is_still_an_alarm():
    with pytest.raises(RuntimeError) as e:
        _probe_sync_with({syncjob.JOB_ID: {"status": "interrupted", "finished_at": None,
                                           "stopped_by_hand": False,
                                           "started_at": _now()}})
    assert "никога не е завършвал" in str(e.value)


def test_a_stale_successful_sync_is_an_alarm():
    with pytest.raises(RuntimeError) as e:
        _probe_sync_with({syncjob.JOB_ID: {
            "status": "done", "finished_at": _now() - timedelta(days=9)}})
    assert "преди 9д" in str(e.value)


# ── information, not emergencies ─────────────────────────────────────────────

def test_one_dead_proxy_tier_while_another_carries_the_traffic_is_information(monkeypatch):
    import encar as encar_mod
    monkeypatch.setenv("ENCAR_RESIDENTIAL_PROXY_URL", "http://user:pass@proxy.example:8080")
    monkeypatch.setenv("ENCAR_HOME_EXIT_URL", "http://10.0.0.2:8080")

    class _Resp:
        status_code = 200
        text = "ip=169.224.26.110\n"

    class _Client:
        def __init__(self, *a, **k):
            self._proxy = k.get("proxy") or ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if "10.0.0.2" in self._proxy:
                raise RuntimeError("403 Filtered")
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(encar_mod, "route_mode", lambda: "auto")

    with pytest.raises(watchdog.Info) as e:
        asyncio.run(watchdog._probe_proxy())
    assert "работят" in str(e.value) and "не отговаря" in str(e.value)


def test_no_tier_working_at_all_is_still_an_emergency(monkeypatch):
    import encar as encar_mod
    monkeypatch.setenv("ENCAR_RESIDENTIAL_PROXY_URL", "http://user:pass@proxy.example:8080")

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise RuntimeError("connection refused")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(encar_mod, "route_mode", lambda: "auto")

    with pytest.raises(RuntimeError) as e:
        asyncio.run(watchdog._probe_proxy())
    assert not isinstance(e.value, watchdog.Info)


def test_a_repaired_routing_rule_is_reported_without_waking_anyone(tmp_path, monkeypatch):
    state = tmp_path / "nat.json"
    state.write_text('{"at": %s, "egress_ok": true, "repaired_at": %s, "repairs": 3, '
                     '"handshake_age_s": 12}' % (time.time(), time.time() - 3600))
    monkeypatch.setenv("NAT_GUARD_STATE", str(state))
    with pytest.raises(watchdog.Info) as e:
        asyncio.run(watchdog._probe_nat())
    said = str(e.value)
    assert "1 ч 0 мин" in said and "3 поправки" in said and "?" not in said


def test_a_guard_that_stopped_running_is_a_real_alarm(tmp_path, monkeypatch):
    state = tmp_path / "nat.json"
    state.write_text('{"at": %s, "egress_ok": true}' % (time.time() - 9999))
    monkeypatch.setenv("NAT_GUARD_STATE", str(state))
    with pytest.raises(RuntimeError) as e:
        asyncio.run(watchdog._probe_nat())
    assert not isinstance(e.value, watchdog.Info)


def test_an_info_outcome_opens_nothing_and_closes_what_was_open(monkeypatch):
    async def go():
        client, db = _db()
        try:
            await db.incidents.delete_many({"check": "pytest_info"})
            watchdog.CHECKS["pytest_info"] = ("warning", 60, "Тестова проверка", "")
            await db.incidents.insert_one({"check": "pytest_info", "severity": "warning",
                                          "opened_at": _now(), "closed_at": None,
                                          "reason": "was failing"})
            sent = []

            async def fake_alert(check, reason, reminder=False, resolved=False):
                sent.append((check, resolved))

            async def info_probe():
                raise watchdog.Info("one tier down, traffic fine")

            monkeypatch.setattr(watchdog, "_alert", fake_alert)
            watchdog.PROBES["pytest_info"] = info_probe
            assert await watchdog.probe_one("pytest_info") == "info"
            doc = await db.incidents.find_one({"check": "pytest_info"})
            assert doc["closed_at"] is not None
            assert all(resolved for _, resolved in sent)
        finally:
            watchdog.PROBES.pop("pytest_info", None)
            watchdog.CHECKS.pop("pytest_info", None)
            await db.incidents.delete_many({"check": "pytest_info"})
            client.close()

    asyncio.run(go())


# ── dismissing an open alert ─────────────────────────────────────────────────

def test_dismissing_an_open_alert_closes_it_and_mutes_the_check(monkeypatch):
    async def go():
        client, db = _db()
        try:
            await db.incidents.delete_many({"check": "pytest_mute"})
            watchdog.CHECKS["pytest_mute"] = ("critical", 60, "Тестова проверка", "")
            ins = await db.incidents.insert_one(
                {"check": "pytest_mute", "severity": "critical", "opened_at": _now(),
                 "closed_at": None, "reason": "cannot be fixed today"})

            out = await watchdog.dismiss_incident(ins.inserted_id)
            assert out["dismissed"] and out["check"] == "pytest_mute"
            assert await watchdog.is_muted("pytest_mute")
            doc = await db.incidents.find_one({"_id": ins.inserted_id})
            assert doc["closed_at"] and doc["dismissed"] is True

            # A muted check that keeps failing raises nothing and pushes nothing.
            sent = []

            async def fake_alert(*a, **k):
                sent.append(a)

            monkeypatch.setattr(watchdog, "_alert", fake_alert)
            await watchdog._open("pytest_mute", "still broken")
            assert await db.incidents.count_documents(
                {"check": "pytest_mute", "closed_at": None}) == 0
            assert sent == []

            # And the mute lifts itself the moment it passes.
            async def ok_probe():
                return "fine now"

            watchdog.PROBES["pytest_mute"] = ok_probe
            assert await watchdog.probe_one("pytest_mute") == "ok"
            assert not await watchdog.is_muted("pytest_mute")
        finally:
            watchdog.PROBES.pop("pytest_mute", None)
            watchdog.CHECKS.pop("pytest_mute", None)
            await watchdog.unmute("pytest_mute")
            await db.incidents.delete_many({"check": "pytest_mute"})
            client.close()

    asyncio.run(go())


def test_a_closed_alert_cannot_be_dismissed_twice():
    async def go():
        client, db = _db()
        try:
            ins = await db.incidents.insert_one(
                {"check": "pytest_mute2", "opened_at": _now(), "closed_at": _now(),
                 "reason": "already over"})
            out = await watchdog.dismiss_incident(ins.inserted_id)
            assert out["dismissed"] is False and out["reason"]
            assert (await watchdog.dismiss_incident("nonsense"))["dismissed"] is False
        finally:
            await db.incidents.delete_many({"check": "pytest_mute2"})
            client.close()

    asyncio.run(go())


def test_a_mute_cannot_outlive_a_month():
    async def go():
        client, db = _db()
        try:
            watchdog.CHECKS["pytest_mute3"] = ("warning", 60, "Тестова проверка", "")
            got = await watchdog.mute("pytest_mute3", days=9999)
            assert got["until"] <= _now() + timedelta(days=watchdog.MUTE_MAX_DAYS + 1)
        finally:
            await watchdog.unmute("pytest_mute3")
            watchdog.CHECKS.pop("pytest_mute3", None)
            client.close()

    asyncio.run(go())


def test_an_expired_mute_is_no_longer_a_mute():
    async def go():
        client, db = _db()
        try:
            await db.settings.update_one(
                {"_id": watchdog.MUTES_ID},
                {"$set": {"checks.pytest_mute4": {"until": _now() - timedelta(minutes=1),
                                                  "since": _now(), "reason": "old"}}},
                upsert=True)
            assert not await watchdog.is_muted("pytest_mute4")
        finally:
            await watchdog.unmute("pytest_mute4")
            client.close()

    asyncio.run(go())
