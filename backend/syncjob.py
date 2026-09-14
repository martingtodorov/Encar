"""Full-catalogue sync as an operator action, plus a daily timer.

A whole-catalogue crawl takes far longer than any request may live, so the endpoint only
starts the job and everything else is read back from `sync_state`. The post-crawl steps
mirror `crawl.py`: without the taxonomy rebuild the dropdowns and the English URL slugs
would still describe yesterday's catalogue.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import slugs as slugs_mod
import pricewatch as pricewatch_mod
import searchwatch as searchwatch_mod
import sync as sync_mod

log = logging.getLogger("syncjob")

JOB_ID = "catalogue_job"
SCHEDULE_ID = "sync_schedule"
DEFAULT_SCHEDULE = {"enabled": False, "times": ["03:30"], "tz": "Europe/Sofia"}
MAX_DAILY_TIMES = 6

_task = None


def _now():
    return datetime.now(timezone.utc)


LIVE_ID = "catalogue_partition_live"

# Rough share of the whole job each phase represents, so the bar keeps moving during the
# post-crawl passes instead of sitting at 100% for a few minutes.
PHASE_WEIGHT = {"crawl": 0.86, "retire": 0.88, "manual": 0.895, "colour": 0.915,
                "dedupe": 0.94, "taxonomy": 0.97, "slugs": 0.99, "coverage": 1.0}
PHASE_LABEL = {"crawl": "Crawling Encar", "retire": "Retiring sold cars",
               "manual": "Tagging gearboxes", "colour": "Tagging colours",
               "dedupe": "Removing duplicates",
               "taxonomy": "Rebuilding dropdowns", "slugs": "Rebuilding URL slugs",
               "coverage": "Refreshing coverage"}


async def get_job(db):
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    job = {k: v for k, v in doc.items() if k != "_id"} or {"status": "idle"}
    job["progress"] = await get_progress(db, job)
    job["checkpoint"] = None if is_running() else await find_resumable(db)
    job["stalled_for_s"] = await stalled_for(db)
    job["stall_after_s"] = STALL_AFTER_S
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
    raw = {k: v for k, v in doc.items() if k != "_id"}
    # Migration: an older schedule stored one `time` string; treat it as a single-entry list.
    times = raw.get("times")
    if not times and raw.get("time"):
        times = [raw["time"]]
    times = _clean_times(times or DEFAULT_SCHEDULE["times"])
    sched = {
        "enabled": bool(raw.get("enabled", DEFAULT_SCHEDULE["enabled"])),
        "times": times,
        "tz": raw.get("tz") or DEFAULT_SCHEDULE["tz"],
    }
    sched["next_run_at"] = next_run_at(sched)
    return sched


async def set_schedule(db, enabled, times, tz):
    times = _clean_times(times)
    if not times:
        raise ValueError("at least one time is required")
    ZoneInfo(tz)                                  # raises on a bogus zone
    await db.settings.update_one(
        {"_id": SCHEDULE_ID},
        {"$set": {"enabled": bool(enabled), "times": times, "tz": tz,
                  "updated_at": _now()},
         "$unset": {"time": ""}},
        upsert=True)
    return await get_schedule(db)


def _parse_time(value):
    hh, _, mm = str(value or "").partition(":")
    hh, mm = int(hh), int(mm or 0)
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError("time must be HH:MM in 24-hour form")
    return hh, mm


def _clean_times(values):
    """De-duplicate, validate and sort a list of HH:MM strings."""
    if isinstance(values, str):
        values = [values]
    seen = set()
    out = []
    for v in values or []:
        hh, mm = _parse_time(v)
        s = f"{hh:02d}:{mm:02d}"
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    if len(out) > MAX_DAILY_TIMES:
        raise ValueError(f"at most {MAX_DAILY_TIMES} daily runs are allowed")
    out.sort()
    return out


def next_run_at(sched):
    if not sched.get("enabled"):
        return None
    try:
        zone = ZoneInfo(sched.get("tz") or DEFAULT_SCHEDULE["tz"])
    except Exception:
        return None
    times = sched.get("times") or []
    local = datetime.now(zone)
    candidates = []
    for t in times:
        try:
            hh, mm = _parse_time(t)
        except Exception:
            continue
        target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        candidates.append(target)
    if not candidates:
        return None
    return min(candidates).astimezone(timezone.utc).isoformat()


def is_running(db=None):
    return _task is not None and not _task.done()


RESUME_ID = "catalogue_partition_resume"
# A checkpoint older than this is not worth continuing from: the catalogue has moved on,
# so the next run starts clean. Measured from the LAST checkpoint write, not from the
# start of the run - a long crawl is still resumable seconds after it was interrupted.
RESUME_WINDOW_S = 12 * 3600
# A crash loop must not turn into an endless crawl, so automatic resumes are capped.
# The counter resets whenever a run is started by hand or by the schedule.
MAX_AUTO_RESUMES = 40


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def find_resumable(db):
    """The checkpoint a new run should continue from, or None to start clean.

    Two kinds exist. `crawl_partitioned` keeps a per-slice checkpoint while it walks
    Encar (deleted the moment the walk completes), and the live doc tells us when only
    the post-crawl passes are left. Either way the run_id is what matters: it is what
    marks indexed cars, and the retire pass keys off it.
    """
    ck = await db.sync_state.find_one({"_id": RESUME_ID}) or {}
    updated = _aware(ck.get("updated_at"))
    if ck.get("run_id") and updated and (_now() - updated).total_seconds() <= RESUME_WINDOW_S:
        return {"run_id": ck["run_id"], "slices": len(ck.get("done") or []),
                "counts_cached": len(ck.get("plan") or []),
                "updated_at": updated, "crawl_done": False}

    live = await db.sync_state.find_one({"_id": LIVE_ID}) or {}
    lupdated = _aware(live.get("updated_at"))
    phase = live.get("phase")
    job = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    if (live.get("run_id") and phase not in (None, "crawl")
            and job.get("status") in ("interrupted", "cancelled", "error")
            and lupdated and (_now() - lupdated).total_seconds() <= RESUME_WINDOW_S):
        return {"run_id": live["run_id"], "slices": live.get("leaves") or 0,
                "counts_cached": 0, "updated_at": lupdated, "crawl_done": True}
    return None


async def stop(db, timeout=20, reason="the server restarted while this sync was running"):
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
        {"$set": {"status": "interrupted", "finished_at": _now(), "error": reason}})
    log.info("catalogue sync stopped: %s", reason)
    return True


# The crawl publishes progress every ~3 seconds and every post-crawl pass stamps the live
# document as it begins, so silence for this long means the task is wedged — a socket that
# never timed out, an upstream that accepted the connection and then said nothing — rather
# than merely paced slowly.
STALL_AFTER_S = int(os.environ.get("SYNC_STALL_AFTER_S", "1800"))
AUTO_RESTART = os.environ.get("SYNC_AUTO_RESTART", "1").lower() not in ("0", "false", "no")
# A wedge that comes straight back must not turn into a restart loop.
AUTO_RESTART_COOLDOWN_S = 1800
_last_auto_restart = {"at": 0.0}


async def stalled_for(db):
    """Seconds since the running sync last moved, or None when nothing is running."""
    if not is_running():
        return None
    live = await db.sync_state.find_one({"_id": LIVE_ID}) or {}
    job = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    last = _aware(live.get("updated_at")) or _aware(job.get("started_at"))
    if not last:
        return None
    return max((_now() - last).total_seconds(), 0.0)


async def restart(db, fresh=False, trigger="restart"):
    """Kill a wedged sync and start it again — from its checkpoint, or clean if `fresh`.

    The whole point is the case the owner hits in practice: the crawl stops moving halfway
    through and there is no way to make it let go. Cancelling settles the job document, so
    the checkpoint is intact and the new run carries on from the last indexed slice.
    """
    stalled = await stalled_for(db)
    stopped = await stop(db, reason=(
        f"restarted by hand after {int(stalled or 0)}s without progress"
        if trigger == "restart" else
        f"restarted automatically after {int(stalled or 0)}s without progress"))
    if fresh:
        # A clean start must not continue the old checkpoint.
        await db.sync_state.delete_one({"_id": RESUME_ID})
    out = await start(db, trigger=trigger, fresh=fresh)
    return {**out, "stopped": stopped, "was_stalled_for_s": stalled}


async def restart_if_stalled(db):
    """Self-heal a wedged sync, so a crawl that dies at 3am is running again by 3:30."""
    if not AUTO_RESTART:
        return False
    stalled = await stalled_for(db)
    if stalled is None or stalled < STALL_AFTER_S:
        return False
    import time as _time
    if _time.monotonic() - _last_auto_restart["at"] < AUTO_RESTART_COOLDOWN_S:
        return False
    _last_auto_restart["at"] = _time.monotonic()
    log.error("catalogue sync has not moved for %ss — restarting it", int(stalled))
    await restart(db, trigger="auto-restart")
    return True


async def resume_if_interrupted(db):
    """Pick a restart-interrupted sync back up from its last checkpoint.

    The crawl checkpoints every slice it indexes, so a restart costs at most the slice in
    flight instead of the whole run. Repeated restarts each get their own resume - only a
    crash loop (MAX_AUTO_RESUMES) or a stale checkpoint stops it.
    """
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    if doc.get("status") not in ("interrupted", "cancelled") or is_running():
        return False
    if (doc.get("resume_attempts") or 0) >= MAX_AUTO_RESUMES:
        log.warning("not resuming the catalogue sync: %s automatic resumes already",
                    doc.get("resume_attempts"))
        return False
    ck = await find_resumable(db)
    if not ck:
        return False
    log.info("resuming the catalogue sync the restart interrupted (run %s, %s slices "
             "already indexed)", ck["run_id"], ck["slices"])
    await start(db, trigger="resume", resume_run_id=ck["run_id"])
    return True


async def clear_stale(db):
    """A restart kills the task but not the status doc, which would jam the button."""
    doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
    if doc.get("status") == "running" and not is_running():
        await db.sync_state.update_one(
            {"_id": JOB_ID},
            {"$set": {"status": "interrupted", "finished_at": _now(),
                      "error": "the server restarted while this sync was running"}})
    # The retired page-based sync left its own doc behind, and nothing ever cleared it: a
    # crawl interrupted months ago kept the admin Overview reading "running, page 142 of
    # 420" for ever. Settle it too, so the panel cannot lie.
    legacy = await db.sync_state.find_one({"_id": "catalogue"}) or {}
    if legacy.get("status") == "running":
        await db.sync_state.update_one(
            {"_id": "catalogue"},
            {"$set": {"status": "interrupted", "finished_at": _now()}})


async def start(db, trigger="manual", resume_run_id=None, fresh=False):
    """Kick off the crawl detached. Returns immediately.

    Unless `fresh`, a start continues the last checkpoint instead of re-crawling the
    ~210k cars an interrupted run had already indexed.
    """
    global _task
    if is_running():
        return {"started": False, "reason": "a catalogue sync is already running"}
    if not fresh and not resume_run_id:
        ck = await find_resumable(db)
        if ck:
            resume_run_id = ck["run_id"]
            log.info("%s start continues run %s (%s slices already indexed)",
                     trigger, ck["run_id"], ck["slices"])
    _task = asyncio.get_running_loop().create_task(_run(db, trigger, resume_run_id))
    return {"started": True, "trigger": trigger, "resumed_run": resume_run_id}


async def _run(db, trigger, resume_run_id=None):
    started = _now()
    attempts = 0
    if trigger == "resume":
        doc = await db.sync_state.find_one({"_id": JOB_ID}) or {}
        attempts = (doc.get("resume_attempts") or 0) + 1
    await db.sync_state.update_one(
        {"_id": JOB_ID},
        {"$set": {"status": "running", "trigger": trigger, "started_at": started,
                  "finished_at": None, "error": None, "result": None,
                  "resumed": bool(resume_run_id), "resumed_run": resume_run_id,
                  "resume_attempts": attempts}},
        upsert=True)
    result = {}
    try:
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
        # Colour is the same kind of pass as the gearbox one: not in the list payload, but an
        # upstream facet. It belongs HERE, in the catalogue sync that actually runs, and not
        # only in the legacy full sweep.
        await _phase(db, "colour")
        result["colours"] = await sync_mod.tag_colors(db)
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
        # Prices have just been refreshed, so this is the one moment when checking saved
        # cars for a drop is worth anything. Detached: the job is already finished.
        pricewatch_mod.run_later(db)
        # The catalogue has just grown: this is also the moment a standing saved search can
        # have picked something up.
        searchwatch_mod.run_later(db)
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
    """Fire the crawl once for every chosen local minute of each day."""
    while True:
        await asyncio.sleep(period)
        try:
            if await restart_if_stalled(db):
                continue
            sched = await get_schedule(db)
            if not sched.get("enabled") or is_running():
                continue
            zone = ZoneInfo(sched.get("tz") or DEFAULT_SCHEDULE["tz"])
            local = datetime.now(zone)
            now_hhmm = f"{local.hour:02d}:{local.minute:02d}"
            if now_hhmm not in sched.get("times", []):
                continue
            today = local.date().isoformat()
            doc = await db.settings.find_one({"_id": SCHEDULE_ID}) or {}
            last_runs = dict(doc.get("last_runs") or {})
            # Migration: honour the previous single-slot `last_run_date` so we don't
            # double-fire the same time on the day the schedule is upgraded.
            legacy = doc.get("last_run_date")
            times = sched.get("times") or []
            if legacy and times and not last_runs:
                last_runs[times[0]] = legacy
            if last_runs.get(now_hhmm) == today:
                continue
            last_runs[now_hhmm] = today
            await db.settings.update_one(
                {"_id": SCHEDULE_ID},
                {"$set": {"last_runs": last_runs, "last_run_date": today}},
                upsert=True)
            log.info("scheduled catalogue sync firing for %s %s", today, now_hhmm)
            await start(db, trigger="schedule")
        except Exception as e:
            log.warning("sync scheduler: %s", str(e)[:200])
