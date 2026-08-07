"""The mobile.bg posting queue: we queue a car, an outside bot does the posting.

The bot is not part of this app. It polls `GET /api/post-queue` with a bearer token, posts
each car to mobile.bg at OUR final price (which it reads from `/api/car/{id}` -
`quote.suggested_sale`, unchanged), and reports back with `POST /api/post-queue/{encar_id}`.

So this module owns exactly three things: the queue row, the operator's button, and the two
token-protected endpoints the bot speaks to. One row per car, keyed by the Encar id, because
"post this car" is a fact about the car and not an event worth keeping twice.
"""
import logging
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("postqueue")
router = APIRouter()
_db = None

STATES = ("pending", "posted", "failed")


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


def _token():
    return (os.environ.get("ENCAREUROPE_API_TOKEN") or "").strip()


def _require_bot(authorization):
    """The bot's only credential. Nothing about it is ever sent to a browser."""
    secret = _token()
    if not secret:
        raise HTTPException(503, "ENCAREUROPE_API_TOKEN is not configured")
    prefix = "bearer "
    got = (authorization or "").strip()
    if not got.lower().startswith(prefix) or not secrets.compare_digest(
            got[len(prefix):].strip(), secret):
        raise HTTPException(401, "bad or missing bearer token")


def _out(row):
    if not row:
        return None
    return {"encar_id": row["_id"], "status": row.get("status") or "pending",
            "mobilebg_url": row.get("mobilebg_url") or "",
            "note": row.get("note") or "",
            "requested_at": (row.get("requested_at") or _now()).isoformat(),
            "updated_at": (row.get("updated_at") or _now()).isoformat()}


# ── the bot's two endpoints ──────────────────────────────────────────────────
@router.get("/post-queue")
async def pending(authorization: str = Header(default="")):
    """Everything waiting to be posted, in the shape the bot already expects."""
    _require_bot(authorization)
    rows = await _db.post_queue.find({"status": "pending"}, {"_id": 1}).sort(
        "requested_at", 1).to_list(500)
    return {"pending": [r["_id"] for r in rows]}


class Report(BaseModel):
    status: str
    mobilebg_url: str = ""
    note: str = ""


@router.post("/post-queue/{encar_id}")
async def report(encar_id: str, body: Report, authorization: str = Header(default="")):
    """How the bot tells us what happened."""
    _require_bot(authorization)
    if body.status not in STATES:
        raise HTTPException(400, f"status must be one of {', '.join(STATES)}")
    result = await _db.post_queue.update_one(
        {"_id": encar_id},
        {"$set": {"status": body.status, "mobilebg_url": body.mobilebg_url[:500],
                  "note": body.note[:500], "updated_at": _now()}})
    if not result.matched_count:
        raise HTTPException(404, "that car is not in the queue")
    log.info("bot reported %s for %s%s", body.status, encar_id,
             f" ({body.mobilebg_url})" if body.mobilebg_url else "")
    return {"ok": True}


# ── the operator's side ─────────────────────────────────────────────────────
async def queue(encar_id, actor=""):
    """One row per car: asking again simply puts it back in the queue."""
    await _db.post_queue.update_one(
        {"_id": encar_id},
        {"$set": {"status": "pending", "requested_at": _now(), "updated_at": _now(),
                  "requested_by": actor, "mobilebg_url": "", "note": ""}},
        upsert=True)
    return _out(await _db.post_queue.find_one({"_id": encar_id}))


async def status_for(encar_id):
    return _out(await _db.post_queue.find_one({"_id": encar_id}))


async def status_map(ids):
    rows = await _db.post_queue.find({"_id": {"$in": list(ids)}}).to_list(500)
    return {r["_id"]: _out(r) for r in rows}


async def recent(limit=200):
    rows = await _db.post_queue.find().sort("updated_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def ensure_indexes(db):
    await db.post_queue.create_index([("status", 1), ("requested_at", 1)])
