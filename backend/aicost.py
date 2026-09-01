"""What the language models actually cost, and a letter about it every evening.

Three jobs, deliberately in one small module:

  * `billed()` — the REAL invoiced figure, read from Anthropic's Admin API
    (`/v1/organizations/cost_report`). Our own per-call arithmetic in `translate.meter`
    is an estimate from list prices; this is what Anthropic will charge. It needs an
    ADMIN key (`ANTHROPIC_ADMIN_KEY`, prefix `sk-ant-admin…`) — the ordinary
    ANTHROPIC_API_KEY cannot read an organisation's spend. Missing key = the panel
    simply shows our estimate and says so, nothing breaks.
  * `daily_report()` — the day rolled up: cost, tokens, which part of the site spent
    them, failures. Stored in `db.ai_reports` so the archive survives the TTL on the
    individual call rows, and emailed to the owner at 21:00 Sofia.
  * budget watch — if a day passes the owner's ceiling (default $5) an alert goes out
    once, immediately, and the admin screen carries a banner.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import mailer

log = logging.getLogger("aicost")

TZ = "Europe/Sofia"
REPORT_HOUR = 21          # 9pm Sofia, as the owner asked
REPORT_MINUTE = 0
DEFAULT_BUDGET_USD = 5.0
BUDGET_ID = "ai_budget"
COST_URL = "https://api.anthropic.com/v1/organizations/cost_report"


def admin_key():
    return (os.environ.get("ANTHROPIC_ADMIN_KEY") or "").strip()


def today_sofia():
    return datetime.now(ZoneInfo(TZ)).date()


async def budget(db):
    doc = await db.settings.find_one({"_id": BUDGET_ID}) or {}
    return float(doc.get("daily_usd") or DEFAULT_BUDGET_USD)


async def set_budget(db, daily_usd):
    await db.settings.update_one(
        {"_id": BUDGET_ID},
        {"$set": {"daily_usd": float(daily_usd),
                  "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return float(daily_usd)


async def billed(db, days=30, *, refresh=True):
    """Anthropic's own cost figures per Sofia day: {"2026-06-01": 1.23, ...}.

    Cached in `db.ai_billing` because the Admin API is rate-limited and the numbers for
    a closed day never change. Only today's row is re-fetched. Returns {} when no admin
    key is configured — the caller then shows the estimate alone.
    """
    days = max(1, min(days, 90))
    first = today_sofia() - timedelta(days=days - 1)
    rows = {d["_id"]: d.get("cost_usd", 0.0)
            async for d in db.ai_billing.find({"_id": {"$gte": first.isoformat()}})}
    if not admin_key() or not refresh:
        return rows

    # Only ask for what we do not have (plus today, which is still moving).
    want_from = first
    known = [k for k in rows if k < today_sofia().isoformat()]
    if len(known) >= days - 1:
        want_from = today_sofia()

    try:
        fetched = await _fetch_cost(want_from, today_sofia() + timedelta(days=1))
    except Exception as e:
        log.warning("anthropic cost report failed: %s", str(e)[:200])
        return rows

    if fetched:
        from pymongo import UpdateOne
        await db.ai_billing.bulk_write(
            [UpdateOne({"_id": day},
                       {"$set": {"cost_usd": round(cost, 6),
                                 "at": datetime.now(timezone.utc)}}, upsert=True)
             for day, cost in fetched.items()], ordered=False)
        rows.update({k: round(v, 6) for k, v in fetched.items()})
    return rows


async def _fetch_cost(start, end):
    """One Admin API sweep, day buckets. Returns {"YYYY-MM-DD": usd}."""
    import httpx

    out = {}
    params = {"starting_at": f"{start.isoformat()}T00:00:00Z",
              "ending_at": f"{end.isoformat()}T00:00:00Z",
              "bucket_width": "1d", "limit": 31}
    headers = {"x-api-key": admin_key(), "anthropic-version": "2023-06-01"}
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            r = await c.get(COST_URL, params=params, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
            body = r.json()
            for bucket in body.get("data") or []:
                stamp = (bucket.get("starting_at") or "")[:10]
                if not stamp:
                    continue
                total = 0.0
                for res in bucket.get("results") or []:
                    try:
                        total += float(res.get("amount") or 0)
                    except (TypeError, ValueError):
                        continue
                out[stamp] = out.get(stamp, 0.0) + total
            if not body.get("has_more") or not body.get("next_page"):
                break
            params = {"page": body["next_page"]}
    return out


async def rollup(db, day):
    """Everything `db.ai_calls` knows about ONE Sofia day."""
    pipe = [{"$match": {"day": day}},
            {"$group": {"_id": None, "calls": {"$sum": 1},
                        "cost": {"$sum": "$cost_usd"},
                        "in_tokens": {"$sum": "$in_tokens"},
                        "out_tokens": {"$sum": "$out_tokens"},
                        "failed": {"$sum": {"$cond": ["$ok", 0, 1]}}}}]
    got = [d async for d in db.ai_calls.aggregate(pipe)]
    base = got[0] if got else {}

    async def by(field):
        p = [{"$match": {"day": day}},
             {"$group": {"_id": f"${field}", "calls": {"$sum": 1},
                         "cost": {"$sum": "$cost_usd"},
                         "in_tokens": {"$sum": "$in_tokens"},
                         "out_tokens": {"$sum": "$out_tokens"}}},
             {"$sort": {"cost": -1}}]
        return [{field: d["_id"] or "other", "calls": d["calls"],
                 "cost": round(d["cost"], 6), "in_tokens": d["in_tokens"],
                 "out_tokens": d["out_tokens"]}
                async for d in db.ai_calls.aggregate(p)]

    return {
        "day": day,
        "calls": base.get("calls", 0),
        "cost_est": round(base.get("cost", 0.0), 6),
        "in_tokens": base.get("in_tokens", 0),
        "out_tokens": base.get("out_tokens", 0),
        "failed": base.get("failed", 0),
        "by_kind": await by("kind"),
        "by_model": await by("model"),
    }


async def daily_report(db, day=None, *, send=True):
    """Roll up a day, store it, and post it to the owner."""
    day = day or today_sofia().isoformat()
    report = await rollup(db, day)
    bills = await billed(db, days=2)
    report["cost_billed"] = bills.get(day)
    prev = (datetime.fromisoformat(day).date() - timedelta(days=1)).isoformat()
    prev_doc = await db.ai_reports.find_one({"_id": prev}) or {}
    report["prev_cost"] = prev_doc.get("cost_est")
    report["budget_usd"] = await budget(db)
    report["at"] = datetime.now(timezone.utc)

    await db.ai_reports.update_one({"_id": day}, {"$set": report}, upsert=True)

    to = (os.environ.get("ADMIN_NOTIFY_EMAIL") or os.environ.get("OWNER_EMAIL") or "").strip()
    if send and to:
        sent = await mailer.send_ai_cost_report(to, report)
        await db.ai_reports.update_one({"_id": day}, {"$set": {"emailed": bool(sent)}})
    return report


async def check_budget(db):
    """One alert per day, the moment the ceiling is crossed."""
    day = today_sofia().isoformat()
    limit = await budget(db)
    got = await rollup(db, day)
    if got["cost_est"] < limit:
        return None
    doc = await db.ai_reports.find_one({"_id": day}) or {}
    if doc.get("alerted"):
        return None
    got["budget_usd"] = limit
    got["cost_billed"] = (await billed(db, days=2)).get(day)
    await db.ai_reports.update_one(
        {"_id": day}, {"$set": {**got, "alerted": True,
                                "at": datetime.now(timezone.utc)}}, upsert=True)
    to = (os.environ.get("ADMIN_NOTIFY_EMAIL") or os.environ.get("OWNER_EMAIL") or "").strip()
    if to:
        await mailer.send_ai_cost_report(to, got, alert=True)
    log.warning("AI budget crossed: $%.2f of $%.2f on %s", got["cost_est"], limit, day)
    return got


def _seconds_until_report():
    now = datetime.now(ZoneInfo(TZ))
    target = now.replace(hour=REPORT_HOUR, minute=REPORT_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def scheduler(db, budget_every=1800):
    """The evening report on its own clock, plus a budget probe every half hour."""
    next_report = _seconds_until_report()
    while True:
        wait = min(budget_every, max(5, next_report))
        await asyncio.sleep(wait)
        next_report -= wait
        try:
            await check_budget(db)
        except Exception as e:
            log.warning("ai budget check failed: %s", str(e)[:200])
        if next_report <= 0:
            try:
                await daily_report(db)
            except Exception as e:
                log.warning("ai daily report failed: %s", str(e)[:200])
            next_report = _seconds_until_report()
