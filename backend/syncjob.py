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


LIVE_ID = "catalogue_partition_live"

# Rough share of the whole job each phase represents, so the bar keeps moving during the
# post-crawl passes instead of sitting at 100% for a few minutes.
PHASE_WEIGHT = {"crawl": 0.86, "retire": 0.88, "manual": 0.90, "dedupe": 0.93,
                "taxonomy": 0.97, "slugs": 0.99, "coverage": 1.0}
PHASE_LABEL = {"crawl": "Crawling Encar", "retire": "Retiring sold cars",
               "manual": "Tagging gearboxes", "dedupe": "Removing duplicates",
               "taxonomy": "Rebuilding dropdowns", "slugs": "Rebuilding URL slugs",
               "coverage": "Refreshing coverage"}


async def get_job(db):
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    job = {k: v for k, v in doc.items() if k != "_id"} or {"status": "idle"}
    job["progress"] = await get_progress(db, job)
    return job


async def get_progress(db, job):
    """Percent complete, honestly derived: crawled-so-far against the upstream count."""
    live = await db.sync_state.find_one({"_id": LIVE_ID}) or {}
    if not live:
        return None
    phase = live.get("phase") or "crawl"
    upstream = live.get("upstream") or 0
    seen = live.get("seen") or 0
    if job.get("status") == "done":
        pct = 100
    elif phase == "crawl":
        pct = min(85, round(seen / upstream * 85)) if upstream else 0
    else:
        pct = round(PHASE_WEIGHT.get(phase, 0.9) * 100)
    return {
        "phase": phase,
        "phase_label": PHASE_LABEL.get(phase, phase),
        "percent": pct,
        "seen": seen,
        "written": live.get("written") or 0,
        "upstream": upstream,
        "leaves": live.get("leaves") or 0,
        "updated_at": live.get("updated_at"),
        "run_id": live.get("run_id"),
    }


async def _phase(db, phase):
    await db.sync_state.update_one(
        {"_id": LIVE_ID}, {"$set": {"phase": phase, "updated_at": _now()}}, upsert=True)


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


# A sync interrupted longer ago than this is not worth resuming automatically: the
# catalogue has moved on and the operator can start a fresh one.
RESUME_WINDOW_S = 6 * 3600


async def stop(db, timeout=20):
    """Cancel a running sync and record it, while the database client is still open.

    Without this the process shutdown closes Mongo underneath the detached task, which
    then dies mid-write ("Cannot use MongoClient after close") and leaves the job doc
    stuck on "running" — which in turn jams the Sync button until the next startup.
    """
    global _task
    if not is_running():
        return False
    _task.cancel()
    await asyncio.wait([_task], timeout=timeout)
    await db.sync_state.update_one(
        {"_id": JOB_ID},
        {"$set": {"status": "interrupted", "finished_at": _now(),
                  "error": "the server restarted while this sync was running"}})
    log.info("catalogue sync stopped for shutdown")
    return True


async def resume_if_interrupted(db):
    """Pick a restart-interrupted sync back up, once.

    The crawl upserts, so starting it again converges on the same index; what matters is
    that a restart in the middle of a sync does not silently leave the catalogue
    half-refreshed. `resumed` bounds this to a single automatic attempt, so a crash loop
    cannot turn into an endless crawl.
    """
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    if doc.get("status") != "interrupted" or doc.get("resumed") or is_running():
        return False
    started = doc.get("started_at")
    if started:
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if (_now() - started).total_seconds() > RESUME_WINDOW_S:
            return False
    live = await db.sync_state.find_one({"_id": LIVE_ID}) or {}
    run_id = live.get("run_id")
    log.info("resuming the catalogue sync the restart interrupted (run %s)", run_id)
    await start(db, trigger="resume", resume_run_id=run_id)
    return True


async def clear_stale(db):
    """A restart kills the task but not the status doc, which would jam the button."""
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    if doc.get("status") == "running" and not is_running():
        await db.sync_state.update_one(
            {"_id": JOB_ID},
            {"$set": {"status": "interrupted", "finished_at": _now(),
                      "error": "the server restarted while this sync was running"}})


async def start(db, trigger="manual", resume_run_id=None):
    """Kick off the crawl detached. Returns immediately."""
    global _task
    if is_running():
        return {"started": False, "reason": "a catalogue sync is already running"}
    _task = asyncio.get_running_loop().create_task(_run(db, trigger, resume_run_id))
    return {"started": True, "trigger": trigger, "resumed_run": resume_run_id}


async def _run(db, trigger, resume_run_id=None):
    started = _now()
    await db.sync_state.update_one(
        {"_id": JOB_ID},
        {"$set": {"status": "running", "trigger": trigger, "started_at": started,
                  "finished_at": None, "error": None, "result": None}},
        upsert=True)
    result = {}
    try:
        await db.sync_state.update_one(
            {"_id": JOB_ID}, {"$set": {"resumed": trigger == "resume"}})
        await sync_mod.ensure_indexes(db)
        # A resumed run keeps the ORIGINAL run_id. The retire pass deactivates anything
        # whose last_crawl is not this run, so a fresh id would retire everything the
        # interrupted crawl had already indexed.
        live = await db.sync_state.find_one({"_id": LIVE_ID}) or {}
        crawl_done = (resume_run_id and live.get("run_id") == resume_run_id
                      and live.get("phase") not in (None, "crawl"))
        if crawl_done:
            log.info("resume: the crawl had already finished, picking up at the post-crawl "
                     "passes")
            result["crawl"] = "already complete"
        else:
            result = await sync_mod.crawl_partitioned(
                db, manufacturers=None, retire=True, run_id=resume_run_id,
                resume=bool(resume_run_id))
        await _phase(db, "manual")
        result["manual_tagged"] = await sync_mod.tag_transmission(db)
        await _phase(db, "dedupe")
        result["dedupe"] = await sync_mod.dedupe_pass(db)
        await _phase(db, "taxonomy")
        result["taxonomy"] = await sync_mod.build_taxonomy(db)
        await _phase(db, "slugs")
        result["slugs"] = await slugs_mod.ensure_taxonomy_slugs(db, force=True)
        await _phase(db, "coverage")
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
