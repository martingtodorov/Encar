"""Full-catalogue sync as an operator action, plus a daily timer.

A whole-catalogue crawl takes far longer than any request may live, so the endpoint only
starts the job and everything else is read back from `sync_state`. The post-crawl steps
mirror `crawl.py`: without the taxonomy rebuild the dropdowns and the English URL slugs
would still describe yesterday's catalogue.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import slugs as slugs_mod
import sync as sync_mod

log = logging.getLogger("syncjob")

JOB_ID = "catalogue_job"
SCHEDULE_ID = "sync_schedule"
DEFAULT_SCHEDULE = {"enabled": False, "time": "03:30", "tz": "Europe/Sofia"}

_task = None


def _now():
    return datetime.now(timezone.utc)


async def get_job(db):
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    return {k: v for k, v in doc.items() if k != "_id"} or {"status": "idle"}


async def get_schedule(db):
    doc = await db.settings.find_one({"_id": SCHEDULE_ID}) or {}
    sched = {**DEFAULT_SCHEDULE, **{k: v for k, v in doc.items() if k != "_id"}}
    sched["next_run_at"] = next_run_at(sched)
    return sched


async def set_schedule(db, enabled, time_hhmm, tz):
    hh, mm = _parse_time(time_hhmm)
    ZoneInfo(tz)                                  # raises on a bogus zone
    await db.settings.update_one(
        {"_id": SCHEDULE_ID},
        {"$set": {"enabled": bool(enabled), "time": f"{hh:02d}:{mm:02d}", "tz": tz,
                  "updated_at": _now()}},
        upsert=True)
    return await get_schedule(db)


def _parse_time(value):
    hh, _, mm = str(value or "").partition(":")
    hh, mm = int(hh), int(mm or 0)
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError("time must be HH:MM in 24-hour form")
    return hh, mm


def next_run_at(sched):
    if not sched.get("enabled"):
        return None
    try:
        hh, mm = _parse_time(sched.get("time"))
        zone = ZoneInfo(sched.get("tz") or DEFAULT_SCHEDULE["tz"])
    except Exception:
        return None
    local = datetime.now(zone)
    target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).isoformat()


def is_running(db=None):
    return _task is not None and not _task.done()


async def start(db, trigger="manual"):
    """Kick off the crawl detached. Returns immediately."""
    global _task
    if is_running():
        return {"started": False, "reason": "a catalogue sync is already running"}
    _task = asyncio.get_running_loop().create_task(_run(db, trigger))
    return {"started": True, "trigger": trigger}


async def _run(db, trigger):
    started = _now()
    await db.sync_state.update_one(
        {"_id": JOB_ID},
        {"$set": {"status": "running", "trigger": trigger, "started_at": started,
                  "finished_at": None, "error": None, "result": None}},
        upsert=True)
    result = {}
    try:
        await sync_mod.ensure_indexes(db)
        result = await sync_mod.crawl_partitioned(db, manufacturers=None, retire=True)
        result["manual_tagged"] = await sync_mod.tag_transmission(db)
        result["dedupe"] = await sync_mod.dedupe_pass(db)
        result["taxonomy"] = await sync_mod.build_taxonomy(db)
        result["slugs"] = await slugs_mod.ensure_taxonomy_slugs(db, force=True)
        try:
            await sync_mod.refresh_brand_coverage(db)
        except Exception as e:
            log.warning("coverage refresh failed: %s", str(e)[:200])
        result["active"] = await db.listings.count_documents({"active": True})
        await db.sync_state.update_one(
            {"_id": JOB_ID},
            {"$set": {"status": "done", "finished_at": _now(), "result": result}})
    except asyncio.CancelledError:
        await db.sync_state.update_one(
            {"_id": JOB_ID}, {"$set": {"status": "cancelled", "finished_at": _now()}})
        raise
    except Exception as e:
        log.exception("catalogue sync failed")
        await db.sync_state.update_one(
            {"_id": JOB_ID},
            {"$set": {"status": "error", "finished_at": _now(), "error": str(e)[:500],
                      "result": result}})


async def scheduler(db, period=30):
    """Fire the crawl once on the chosen local minute of each day."""
    while True:
        await asyncio.sleep(period)
        try:
            sched = await get_schedule(db)
            if not sched.get("enabled") or is_running():
                continue
            zone = ZoneInfo(sched.get("tz") or DEFAULT_SCHEDULE["tz"])
            local = datetime.now(zone)
            hh, mm = _parse_time(sched.get("time"))
            today = local.date().isoformat()
            if local.hour != hh or local.minute != mm:
                continue
            doc = await db.settings.find_one({"_id": SCHEDULE_ID}) or {}
            if doc.get("last_run_date") == today:
                continue
            await db.settings.update_one({"_id": SCHEDULE_ID},
                                         {"$set": {"last_run_date": today}}, upsert=True)
            log.info("scheduled catalogue sync firing for %s %s", today, sched["time"])
            await start(db, trigger="schedule")
        except Exception as e:
            log.warning("sync scheduler: %s", str(e)[:200])
