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

# Why the last call failed, kept in memory only and never shown to a buyer. Without it a
# missing carrier or a rejected key looks EXACTLY like "tracking not connected" on the page,
# and the only trace is a warning in a log on a box you have to SSH into. That is what made a
# one-line misconfiguration take an afternoon to find. Surfaced on the admin dashboard.
_last_error = {"when": None, "message": "", "path": ""}


def _note(path, message):
    _last_error.update({"when": datetime.now(timezone.utc), "message": message[:300],
                        "path": path})


def last_error():
    if not _last_error["message"]:
        return None
    return {"message": _last_error["message"], "path": _last_error["path"],
            "when": _last_error["when"].isoformat() if _last_error["when"] else ""}



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


def _env(name, fallback=""):
    """An env var set to an EMPTY string counts as absent.

    This is not pedantry: the Ansible deploy writes every variable from group_vars whether it
    was filled in or not, so `jsoncargo_shipping_line: ""` reaches the server as
    `JSONCARGO_SHIPPING_LINE=` - and a plain `os.environ.get(name, default)` then returns the
    empty string, silently beating the default. The carrier is a REQUIRED query parameter, so
    every container lookup on that host answered 400 while the preview box, which happened to
    have the value spelled out, worked. One empty line in a YAML file, tracking dead.
    """
    got = (os.environ.get(name) or "").strip()
    return got or fallback


def config():
    return {
        "key": _env("JSONCARGO_API_KEY"),
        "base": _env("JSONCARGO_BASE_URL", "https://api.jsoncargo.com/api/v1"),
        "line": _env("JSONCARGO_SHIPPING_LINE", "MAERSK"),
    }


def configured():
    return bool(config()["key"])


def _now():
    return datetime.now(timezone.utc)


class ConfigError(RuntimeError):
    """A failure caused by OUR configuration, not by the reference being looked up.

    Deliberately NEVER cached. A missing carrier or a rejected key answers the same way for
    every container, and the moment the setting is corrected the answer changes - so a stale
    fifteen-minute row would make a freshly fixed deployment look broken and send whoever
    fixed it looking for a second bug that is not there.
    """


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
        _note(path, "the tracking plan has no requests left this month")
        raise RuntimeError("the tracking plan has no requests left this month")
    if r.is_error:
        msg = (body.get("error") or {}).get("title") if isinstance(body, dict) else ""
        log.warning("jsoncargo %s -> %s %s", path, r.status_code, str(body)[:200])
        _note(path, f"{r.status_code}: {msg or 'the tracking provider did not answer'}")
        # A rejected key, or a 400 complaining about the carrier we were meant to send: that is
        # this deployment's env file, not the tracking number.
        if r.status_code in (401, 403) or (
                r.status_code == 400 and "shipping_line" in str(body)):
            raise ConfigError(msg or "the tracking provider rejected our configuration")
        raise RuntimeError(msg or "the tracking provider did not answer")
    _last_error.update({"when": None, "message": "", "path": ""})
    return body.get("data") if isinstance(body, dict) else None


# How long a snapshot may stand in for a missing answer. Past this we would rather admit we do
# not know than show a fortnight-old position as current.
STALE_MAX = 7 * 24 * 3600


def _hollow(snap):
    """A snapshot carrying an id and nothing else.

    JSONCargo intermittently answers 200 with every meaningful field blank — for BL 272520178
    it returned Inchon and Shanghai at 19:11 and a hollow shell ten minutes later. Caching that
    as success made the whole page flip to "not found", so it is treated as "no answer yet".
    """
    if not isinstance(snap, dict):
        return False
    return not any(snap.get(k) for k in
                   ("shipped_from", "shipped_to", "last_location", "next_location",
                    "atd_origin", "eta_final_destination", "container_status",
                    # The port pair alone is worth keeping: it is how we know the box is bound
                    # for Rotterdam even while every dated field is still null.
                    "loading_port", "discharging_port"))


async def _cached(db, key, ttl, loader, refresh=False, hollow=None):
    """One document per fact. Errors are cached too, or a bad reference costs a call a view."""
    doc = await db.cargo_cache.find_one({"_id": key})
    if doc and not refresh:
        age = (_now() - doc["stored_at"].replace(tzinfo=timezone.utc)).total_seconds()
        if age < (doc.get("error_ttl") or ttl):
            if doc.get("error"):
                raise RuntimeError(doc["error"])
            return doc["payload"]

    try:
        payload = await loader()
    except ConfigError:
        # Drop any row we cached for this fact before the misconfiguration was noticed, so the
        # first lookup after the fix goes out for real instead of replaying the old failure.
        await db.cargo_cache.delete_one({"_id": key})
        raise
    except RuntimeError as e:
        await db.cargo_cache.replace_one(
            {"_id": key}, {"_id": key, "stored_at": _now(), "payload": None,
                           "error": str(e), "error_ttl": ERROR_TTL[429]}, upsert=True)
        raise

    # "No answer" comes in three shapes from this provider: nothing at all, a hollow shell, or
    # an outright error. None of them may be allowed to replace ports and dates we already
    # hold — BL 272520178 answered with real INCHON->ROTTERDAM data one minute and None the
    # next, which is what made tracking flip to "not found".
    if payload is None or (hollow and hollow(payload)):
        kept = (doc or {}).get("payload") if not (doc or {}).get("error") else None
        fresh_enough = doc and (_now() - doc["stored_at"].replace(
            tzinfo=timezone.utc)).total_seconds() < STALE_MAX
        if kept and fresh_enough and not (hollow and hollow(kept)):
            _note(key, "provider had no answer; serving the last real snapshot")
            log.info("jsoncargo %s: empty answer ignored, keeping the cached snapshot", key)
            return kept
        await db.cargo_cache.replace_one(
            {"_id": key}, {"_id": key, "stored_at": _now(), "payload": payload,
                           "error_ttl": ERROR_TTL[404]}, upsert=True)
        return payload

    await db.cargo_cache.replace_one(
        {"_id": key}, {"_id": key, "stored_at": _now(), "payload": payload,
                       "error_ttl": None},
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
                         refresh, hollow=_hollow)


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
        "from": snap.get("shipped_from") or snap.get("loading_port") or "",
        "from_terminal": snap.get("shipped_from_terminal") or "",
        # `shipped_to` is null on plenty of live bookings while `discharging_port` holds the
        # answer: BL 272520178 read {"shipped_to": "", "discharging_port": "ROTTERDAM"}, so the
        # destination came back empty and the page fell back to the last place the box was
        # seen — Shanghai, a transshipment port. The port pair is the fallback, not a guess.
        "to": snap.get("shipped_to") or snap.get("discharging_port") or "",
        "to_terminal": snap.get("shipped_to_terminal") or "",
        "status": snap.get("container_status") or "",
        "updated": snap.get("last_updated") or "",
    }
