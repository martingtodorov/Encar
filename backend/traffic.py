"""How many people are on the site, counted first-party and without a cookie.

Nothing is written to the visitor's device, so ePrivacy's consent rule for storage does not
apply and the count is honest rather than "only those who accepted a banner". What tells two
visits apart is an HMAC of the IP address and the user agent, computed under TWO salts:

  * a short salt that is generated fresh every day and thrown away after two, so live and
    today's counts cannot be linked from one day to the next;
  * a long salt that rotates every ~45 days (kept just inside the hit retention window),
    used exclusively so that the week and month unique-visitor counts do not over-count a
    returning visitor once per day. Without the long salt the daily salt would fingerprint
    the same person differently each day and a lawyer who visits every day would appear as
    seven unique people in the week window and thirty in the month.

Both salts are deleted well before their fingerprints outlive their usefulness, so once the
salt is gone nobody - us included - can recompute yesterday's fingerprints or link them to
today's. The lawful basis is legitimate interest under Art. 6(1)(f): knowing the traffic on
your own shop.

The raw IP is never stored. Only the digests are, and only for as long as the retention
window.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import auth

log = logging.getLogger("traffic")
router = APIRouter()
_db = None

LIVE_MINUTES = 5
KEEP_DAYS = 40                     # a month of history plus room for the month-to-date window
SALT_KEEP_DAYS = 2
LONG_SALT_KEEP_DAYS = 45           # just outside the 30-day month window, well inside retention
SNAPSHOT_CACHE_SECONDS = 10

# A visit from any of these is a machine, not a buyer, and must not be counted as a page
# view. This list is kept in lock-step with the nginx crawler map (see
# deploy/hetzner/ansible/templates/nginx-encar.conf.j2); if nginx routes a UA to the SSR
# share endpoint, the same UA must also be skipped here - otherwise every Facebook, iMessage
# or Viber link preview poll adds a "user" to the dashboard.
#
# The `AppleWebKit/… (KHTML, like Gecko)$` clause catches Apple's headless iMessage fetcher
# (iOS 16+) whose UA ends at the Gecko marker with no `Version/` or `Safari/` suffix. A real
# Safari or a WebKit-based iOS Chrome/Firefox ALWAYS carries at least one of those trailing
# tokens, so the anchor pins the match to the crawler only.
BOTS = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python-requests|httpx|headless|lighthouse|"
    r"pingdom|uptime|monitor|preview|facebookexternalhit|facebookcatalog|Facebot|"
    r"whatsapp|viber|telegram|slack|discord|linkedin|pinterest|redditbot|"
    r"skypeuripreview|iframely|embedly|snapchat|instagram|mastodon|bluesky|vkshare|"
    r"com\.apple\.webkit\.networking|applebot|applebot-extended|"
    r"AppleWebKit/[0-9.]+ \(KHTML, like Gecko\)\s*$",
    re.I)

TZ = ZoneInfo(os.environ.get("ADMIN_TZ", "Europe/Sofia"))

_cache = {"at": None, "data": None}


def set_db(db):
    global _db
    _db = db


async def ensure_indexes(db):
    # Both collections expire themselves. Traffic history that outlives its purpose is a
    # liability, and a salt that outlives its day would undo the whole point of rotating it.
    await db.traffic_hits.create_index("at", expireAfterSeconds=KEEP_DAYS * 86400)
    await db.traffic_hits.create_index([("at", -1), ("v", 1)])
    await db.traffic_hits.create_index([("at", -1), ("vl", 1)])
    await db.traffic_salt.create_index("created_at",
                                       expireAfterSeconds=SALT_KEEP_DAYS * 86400)
    # A separate collection so the daily and the long salt cannot share a TTL by accident.
    await db.traffic_salt_long.create_index("created_at",
                                            expireAfterSeconds=LONG_SALT_KEEP_DAYS * 86400)


def _now():
    return datetime.now(timezone.utc)


def _client_ip(request: Request):
    """The real client, from the proxy chain. We hash this and never store it."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


async def _salt():
    """Today's secret. Created once, on first use, and never regenerated for the same day."""
    day = _now().strftime("%Y-%m-%d")
    row = await _db.traffic_salt.find_one({"_id": day})
    if row:
        return day, row["salt"]
    salt = secrets.token_hex(32)
    # Racing workers are fine: whoever loses the upsert reads the winner's salt back.
    await _db.traffic_salt.update_one({"_id": day},
                                     {"$setOnInsert": {"salt": salt, "created_at": _now()}},
                                     upsert=True)
    row = await _db.traffic_salt.find_one({"_id": day})
    return day, (row or {}).get("salt", salt)


async def _long_salt():
    """The salt behind the week/month unique-visitor counter.

    Rotates lazily: whichever hit arrives when there is no live long salt in Mongo creates
    a fresh one, and TTL takes the previous one out at ~45 days. Keeping it just outside the
    30-day month window means a well-formed month query sees one salt for its entire span;
    keeping it inside the 40-day hit retention window means the fingerprints in Mongo never
    outlive the salt that made them - once the salt is gone, they are permanently opaque.
    """
    row = await _db.traffic_salt_long.find_one({"_id": "current"})
    if row:
        return row["salt"]
    salt = secrets.token_hex(32)
    await _db.traffic_salt_long.update_one(
        {"_id": "current"},
        {"$setOnInsert": {"salt": salt, "created_at": _now()}},
        upsert=True)
    row = await _db.traffic_salt_long.find_one({"_id": "current"})
    return (row or {}).get("salt", salt)


async def visitor_digest(request: Request):
    _, salt = await _salt()
    raw = f"{_client_ip(request)}|{request.headers.get('user-agent', '')}"
    return hmac.new(salt.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


async def visitor_digest_long(request: Request):
    salt = await _long_salt()
    raw = f"{_client_ip(request)}|{request.headers.get('user-agent', '')}"
    return hmac.new(salt.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


def _clean_path(value):
    value = (value or "/").split("?")[0].split("#")[0].strip()
    if not value.startswith("/"):
        value = "/" + value
    return value[:120]


def _clean_label(value):
    # Shown to administrators only, and React escapes it anyway; this is belt and braces.
    return re.sub(r"[<>]", "", (value or "").strip())[:70]


async def record(request: Request, path, label=""):
    if BOTS.search(request.headers.get("user-agent", "")):
        return False
    await _db.traffic_hits.insert_one({"v": await visitor_digest(request),
                                      "vl": await visitor_digest_long(request),
                                      "p": _clean_path(path), "l": _clean_label(label),
                                      "at": _now()})
    return True


def _day_start(days_back=0):
    """Midnight in Sofia, `days_back` calendar days ago, as UTC.

    The counters used to be rolling windows, so "24h" at 07:10 still carried half of
    yesterday evening and the number the owner read never matched "today". A period now starts
    at 00:00 Sofia time: today, the last 7 calendar days (today included) and the last 30.
    """
    local = datetime.now(TZ) - timedelta(days=days_back)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def _window(since, key="v"):
    """Unique people and total views in one window, without ever holding a set in memory.

    `key="v"` groups by the daily fingerprint (accurate inside one day, over-counts across
    days) and is used for live and today. `key="vl"` groups by the long fingerprint (accurate
    across the 30-day month window) and is used for week and month. Hits stored before the
    long salt existed have no `vl`; they fall back to `v` so old data still contributes rather
    than vanishing on rollout.
    """
    group_key = {"$ifNull": ["$vl", "$v"]} if key == "vl" else f"${key}"
    pipe = [{"$match": {"at": {"$gte": since}}},
            {"$group": {"_id": group_key, "n": {"$sum": 1}}},
            {"$group": {"_id": None, "visitors": {"$sum": 1}, "views": {"$sum": "$n"}}}]
    rows = await _db.traffic_hits.aggregate(pipe).to_list(1)
    if not rows:
        return {"visitors": 0, "views": 0}
    return {"visitors": rows[0]["visitors"], "views": rows[0]["views"]}


async def _live_pages(since):
    """What is being looked at right now, busiest first, counted in people not requests."""
    pipe = [{"$match": {"at": {"$gte": since}}},
            {"$group": {"_id": {"l": "$l", "p": "$p"}, "people": {"$addToSet": "$v"}}},
            {"$project": {"n": {"$size": "$people"}}},
            {"$sort": {"n": -1}},
            {"$limit": 6}]
    rows = await _db.traffic_hits.aggregate(pipe).to_list(6)
    return [{"label": r["_id"].get("l") or r["_id"].get("p") or "/", "count": r["n"]}
            for r in rows]


async def snapshot():
    """Cached for a few seconds: an open admin bar polls, and every poll is an aggregation."""
    now = _now()
    if _cache["at"] and (now - _cache["at"]).total_seconds() < SNAPSHOT_CACHE_SECONDS:
        return _cache["data"]

    live_since = now - timedelta(minutes=LIVE_MINUTES)
    live = await _window(live_since)
    data = {"live": live["visitors"],
            "live_minutes": LIVE_MINUTES,
            "pages": await _live_pages(live_since),
            "day": await _window(_day_start()),
            "week": await _window(_day_start(6), key="vl"),
            "month": await _window(_day_start(29), key="vl")}
    _cache.update({"at": now, "data": data})
    return data


async def history(days=30):
    """Visitors and views per day, oldest first, with empty days filled in.

    A day with no traffic must appear as a zero, not be missing: a chart that silently skips
    quiet days makes a flat week look like a busy one.
    """
    days = max(1, min(int(days), KEEP_DAYS))
    start = _day_start(days - 1)
    pipe = [{"$match": {"at": {"$gte": start}}},
            {"$group": {"_id": {"d": {"$dateToString": {"format": "%Y-%m-%d", "date": "$at",
                                                        "timezone": str(TZ)}},
                                "v": "$v"},
                        "n": {"$sum": 1}}},
            {"$group": {"_id": "$_id.d", "visitors": {"$sum": 1}, "views": {"$sum": "$n"}}}]
    rows = {r["_id"]: r async for r in _db.traffic_hits.aggregate(pipe)}

    out = []
    first = datetime.now(TZ).date() - timedelta(days=days - 1)
    for step in range(days):
        day = (first + timedelta(days=step)).strftime("%Y-%m-%d")
        row = rows.get(day)
        out.append({"day": day,
                    "visitors": row["visitors"] if row else 0,
                    "views": row["views"] if row else 0})
    return out


class PingBody(BaseModel):
    path: str = Field(default="/", max_length=300)
    label: str = Field(default="", max_length=200)


@router.post("/traffic/ping")
async def traffic_ping(body: PingBody, request: Request):
    """One page view. Public, because every visitor is what we are counting.

    An administrator's own browsing is NOT counted: an owner watching his own shop should not
    appear in his own "live now" figure.
    """
    viewer = await auth.optional_user(request)
    if viewer and viewer.get("is_admin"):
        return {"counted": False}
    try:
        counted = await record(request, body.path, body.label)
    except Exception as e:                                   # counting must never break a page
        log.warning("traffic ping dropped: %s", str(e)[:160])
        return {"counted": False}
    return {"counted": counted}


@router.get("/admin/traffic/history")
async def admin_traffic_history(request: Request, days: int = 30,
                                x_admin_token: str = Header(default="")):
    if not (x_admin_token and os.environ.get("ADMIN_TOKEN") == x_admin_token):
        viewer = await auth.optional_user(request)
        if not (viewer and viewer.get("is_admin")):
            raise HTTPException(401, "administrator sign-in required")
    return {"items": await history(days), "days": days}


@router.get("/admin/traffic")
async def admin_traffic(request: Request, x_admin_token: str = Header(default="")):
    if x_admin_token and os.environ.get("ADMIN_TOKEN") == x_admin_token:
        return await snapshot()
    viewer = await auth.optional_user(request)
    if not (viewer and viewer.get("is_admin")):
        raise HTTPException(401, "administrator sign-in required")
    return await snapshot()
