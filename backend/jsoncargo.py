"""JSONCargo container + vessel tracking (api.jsoncargo.com).

The owner's plan is metered: EVERY request counts against the monthly quota, including a
repeat lookup of the same container, so nothing here is fetched twice inside its TTL and
even 404s and quota errors are cached — a buyer refreshing a page must never cost a call.

Two shapes, both different from the EDI feed:
- `/containers/{n}/` is a SNAPSHOT, not an event history: where the box left, where it was
  last seen, where it goes next, and the ETAs. `to_events` turns that into the same
  canonical milestone shape the rest of the app speaks, marking only the ETAs as estimated.
  Nothing is invented: a field that is absent produces no milestone.
- `/vessel/finder/` resolves a vessel NAME (all the container endpoint gives us) to an
  IMO/MMSI/uuid, and `/vessel/pro/` returns the live AIS position for the map.

Paths: the container endpoints REQUIRE a trailing slash (without it nginx answers 301 and
the call is wasted), while `/vessel/*` and `/api_key/stats` must NOT have one — with a
slash they answer "endpoint does not exist". Both quirks are measured, not guessed.
"""
import logging
import os
import re
from datetime import datetime, timezone

import httpx

log = logging.getLogger("jsoncargo")

TTL_BOL = int(os.environ.get("CARGO_TTL_BOL", "2592000"))        # a B/L never changes
TTL_CONTAINER = int(os.environ.get("CARGO_TTL_CONTAINER", "86400"))   # once a day, shared
TTL_VESSEL = int(os.environ.get("CARGO_TTL_VESSEL", "21600"))         # 6h
TTL_NAME = int(os.environ.get("CARGO_TTL_NAME", "31536000"))          # identity is forever
TTL_STATS = int(os.environ.get("CARGO_TTL_STATS", "21600"))
ERROR_TTL = {404: 86400, 429: 900, 400: 3600}

# The carrier writes the status as prose ("Vessel arrival (GENOVA EXPRESS / 625W)").
# Mapped onto the SAME codes the EDI feed uses so the UI keeps one label map.
PHRASES = [
    ("empty to shipper", "EE"), ("empty return", "RD"), ("empty received", "RD"),
    ("gate in", "AG"), ("gate-in", "AG"), ("received", "AG"),
    ("stuff", "STUF"), ("load", "AR"), ("discharg", "UV"), ("unload", "UV"),
    ("depart", "VD"), ("sail", "VD"), ("arrival", "VA"), ("arriv", "VA"),
    ("gate out", "AE"), ("gate-out", "AE"), ("delivery", "AE"), ("deliver", "D"),
    ("customs", "CU"), ("available", "AV"), ("rail", "VD"),
]


def config():
    return {
        "key": os.environ.get("JSONCARGO_API_KEY", ""),
        "base": os.environ.get("JSONCARGO_BASE_URL", "https://api.jsoncargo.com/api/v1"),
        "line": os.environ.get("JSONCARGO_SHIPPING_LINE", "MAERSK"),
    }


def configured():
    return bool(config()["key"])


def _now():
    return datetime.now(timezone.utc)


async def _get(path, params=None):
    """Returns the `data` object, or None for a 404. Raises on quota / server errors."""
    c = config()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as x:
        r = await x.get(f"{c['base']}{path}", params=params or {},
                        headers={"x-api-key": c["key"], "Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 404:
        return None
    if r.status_code == 429:
        raise RuntimeError("the tracking plan has no requests left this month")
    if r.is_error:
        msg = (body.get("error") or {}).get("title") if isinstance(body, dict) else ""
        log.warning("jsoncargo %s -> %s %s", path, r.status_code, str(body)[:200])
        raise RuntimeError(msg or "the tracking provider did not answer")
    return body.get("data") if isinstance(body, dict) else None


async def _cached(db, key, ttl, loader, refresh=False):
    """One document per fact. Errors are cached too, or a bad reference costs a call a view."""
    doc = None if refresh else await db.cargo_cache.find_one({"_id": key})
    if doc:
        age = (_now() - doc["stored_at"].replace(tzinfo=timezone.utc)).total_seconds()
        if age < (doc.get("error_ttl") or ttl):
            if doc.get("error"):
                raise RuntimeError(doc["error"])
            return doc["payload"]

    try:
        payload = await loader()
    except RuntimeError as e:
        await db.cargo_cache.replace_one(
            {"_id": key}, {"_id": key, "stored_at": _now(), "payload": None,
                           "error": str(e), "error_ttl": ERROR_TTL[429]}, upsert=True)
        raise
    await db.cargo_cache.replace_one(
        {"_id": key}, {"_id": key, "stored_at": _now(), "payload": payload,
                       "error_ttl": ERROR_TTL[404] if payload is None else None},
        upsert=True)
    return payload


async def containers_for_bol(db, bol, refresh=False):
    line = config()["line"]
    data = await _cached(db, f"cargo:bol:{line}:{bol}", TTL_BOL,
                         lambda: _get(f"/containers/bol/{bol}/", {"shipping_line": line}),
                         refresh)
    return (data or {}).get("associated_container_numbers") or []


async def container(db, number, refresh=False):
    line = config()["line"]
    return await _cached(db, f"cargo:box:{line}:{number}", TTL_CONTAINER,
                         lambda: _get(f"/containers/{number}/", {"shipping_line": line}),
                         refresh)


async def stats(db, refresh=False):
    return await _cached(db, "cargo:stats", TTL_STATS, lambda: _get("/api_key/stats"),
                         refresh)


async def vessel(db, name="", imo="", mmsi="", refresh=False):
    """Live AIS for a vessel we only know by name. Identity is resolved once and kept."""
    if not configured():
        return None
    try:
        if not (imo or mmsi) and name:
            found = await _cached(
                db, f"cargo:vname:{name.lower()}", TTL_NAME,
                lambda: _get("/vessel/finder", {"name": name, "limit": "5"}), refresh)
            rows = found if isinstance(found, list) else (found or {}).get("vessels") or []
            # A name can match several hulls; the one with an IMO is the ocean-going ship.
            row = next((r for r in rows if r.get("imo")), rows[0] if rows else None)
            if not row:
                return None
            imo, mmsi = row.get("imo") or "", row.get("mmsi") or ""
        if not (imo or mmsi):
            return None
        params = {"imo": imo} if imo else {"mmsi": mmsi}
        data = await _cached(db, f"cargo:vpro:{imo or mmsi}", TTL_VESSEL,
                             lambda: _get("/vessel/pro", params), refresh)
        if not isinstance(data, dict) or data.get("lat") is None:
            return None
        return {
            "imo": str(data.get("imo") or imo or ""), "mmsi": str(data.get("mmsi") or ""),
            "name": data.get("name") or name,
            "position": {
                "lat": data["lat"], "lon": data["lon"],
                "speed": data.get("speed"), "course": data.get("course"),
                "destination": data.get("dest_port") or data.get("destination") or "",
                "dest_unloc": data.get("dest_port_unlocode") or "",
                "eta": data.get("eta_UTC") or "", "at": data.get("last_position_UTC") or "",
            },
        }
    except RuntimeError as e:
        log.warning("vessel lookup failed for %s: %s", name or imo or mmsi, str(e)[:160])
        return None


def _code(text):
    low = (text or "").lower()
    for phrase, code in PHRASES:
        if phrase in low:
            return code
    return ""


def _when(value):
    """'2026-08-01 19:04' -> ISO. Carrier local time, kept exactly as sent."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", str(value or ""))
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    return f"{y}-{mo}-{d}T{hh or '00'}:{mm or '00'}:00"


def _stone(code, text, when, place, estimated, vessel_name="", voyage=""):
    return {"code": code, "text": text, "when": when, "estimated": estimated,
            "location": (place or "").title() if (place or "").isupper() else (place or ""),
            "country": "", "unloc": "", "mode": "", "vessel_name": vessel_name,
            "vessel_imo": "", "voyage": voyage}


def to_events(snap):
    """Canonical milestones from a snapshot. A missing field produces NO milestone."""
    if not isinstance(snap, dict):
        return []
    status = snap.get("container_status") or ""
    ship = snap.get("current_vessel_name") or snap.get("last_vessel_name") or ""
    voyage = snap.get("current_voyage_number") or snap.get("last_voyage_number") or ""
    out = []

    when = _when(snap.get("atd_origin"))
    if when:
        out.append(_stone("VD", "Departed", when,
                          snap.get("loading_port") or snap.get("shipped_from"), False,
                          snap.get("last_vessel_name") or "",
                          snap.get("last_voyage_number") or ""))

    when = _when(snap.get("timestamp_of_last_location")
                 or snap.get("last_movement_timestamp"))
    if when:
        # The status text describes exactly this movement, so it names the milestone.
        out.append(_stone(_code(status) or "VA", re.sub(r"\s*\(.*\)$", "", status).strip()
                          or "Last movement", when, snap.get("last_location"), False,
                          ship, voyage))

    when = _when(snap.get("eta_next_destination"))
    if when and snap.get("next_location"):
        out.append(_stone("VA", "Expected arrival", when, snap.get("next_location"), True,
                          ship, voyage))

    when = _when(snap.get("eta_final_destination"))
    final = snap.get("shipped_to") or snap.get("discharging_port")
    if when and final and not any(
            s["location"].lower() == (final or "").lower() and s["when"] == when
            for s in out):
        out.append(_stone("AV", "Expected at destination", when, final, True, ship, voyage))

    return sorted(out, key=lambda s: s["when"])


def route(snap):
    """The leg description the buyer cares about, straight from the snapshot."""
    if not isinstance(snap, dict):
        return None
    return {
        "container": snap.get("container_id") or "",
        "type": snap.get("container_type") or "",
        "from": snap.get("shipped_from") or "", "from_terminal": snap.get("shipped_from_terminal") or "",
        "to": snap.get("shipped_to") or "", "to_terminal": snap.get("shipped_to_terminal") or "",
        "status": snap.get("container_status") or "",
        "updated": snap.get("last_updated") or "",
    }
