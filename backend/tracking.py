"""Shipment tracking: Maersk Track & Trace Plus + AIS vessel position.

Everything upstream is cached in Mongo. Maersk quotas are per consumer key (roughly
120/min, 5,000/hour) and a buyer refreshing a page must never spend one call per render,
so a reference is fetched at most once every CACHE_TTL and every response is stored raw
alongside the normalised view.

Credentials live in backend/.env and are read lazily, so the app boots and the page
renders a clear "not connected" state instead of crashing when they are absent.
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timezone

import httpx

import edi
import ports

log = logging.getLogger("tracking")

CACHE_TTL = int(os.environ.get("TRACKING_CACHE_TTL", "900"))
VESSEL_TTL = int(os.environ.get("VESSEL_CACHE_TTL", "1800"))

# DCSA event codes Maersk returns, in the order a container actually moves.
# Codes that mean the container has reached the customer, in both vocabularies:
# EDI (D delivered, AE gate-out for delivery, RD empty returned) and DCSA/REST.
DELIVERED = {"D", "AE", "RD", "GTOT", "PICK", "SURR"}

_token = {"value": None, "expires": 0.0}


def _now():
    return datetime.now(timezone.utc)


def config():
    return {
        "base": os.environ.get("MAERSK_BASE_URL", "https://api.maersk.com"),
        "token_url": os.environ.get(
            "MAERSK_TOKEN_URL",
            "https://api.maersk.com/customer-identity/oauth/v2/access_token"),
        "key": os.environ.get("MAERSK_CONSUMER_KEY", ""),
        "secret": os.environ.get("MAERSK_CONSUMER_SECRET", ""),
        "ais_key": os.environ.get("MARINETRAFFIC_API_KEY", ""),
        "ais_url": os.environ.get(
            "MARINETRAFFIC_URL",
            "https://services.marinetraffic.com/api/exportvessel/v:5/{key}"
            "/timespan:60/imo:{imo}/protocol:jsono"),
    }


def is_configured():
    c = config()
    return bool(c["key"])


async def _access_token(c):
    """Client-credentials token, reused until a minute before it expires."""
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    if not c["secret"]:
        return None          # key-only subscriptions authenticate with Consumer-Key alone
    async with httpx.AsyncClient(timeout=20) as x:
        r = await x.post(c["token_url"], headers={"Consumer-Key": c["key"]},
                         data={"grant_type": "client_credentials",
                               "client_id": c["key"],
                               "client_secret": c["secret"],
                               "scope": "read"})
    if r.is_error:
        log.warning("maersk auth failed: %s %s", r.status_code, r.text[:200])
        raise RuntimeError("maersk authentication failed")
    body = r.json()
    _token["value"] = body["access_token"]
    _token["expires"] = time.time() + int(body.get("expires_in", 3600))
    return _token["value"]


async def _get(path, params):
    c = config()
    headers = {"Consumer-Key": c["key"], "Accept": "application/json"}
    tok = await _access_token(c)
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    async with httpx.AsyncClient(timeout=30) as x:
        r = await x.get(f"{c['base']}{path}", headers=headers, params=params)
    if r.status_code == 404:
        return None
    if r.status_code == 429:
        raise RuntimeError("maersk rate limit reached, try again shortly")
    if r.is_error:
        log.warning("maersk %s -> %s %s", path, r.status_code, r.text[:200])
        raise RuntimeError("the carrier did not answer")
    return r.json()


async def _cached(db, key, ttl, loader):
    doc = await db.tracking_cache.find_one({"_id": key})
    if doc and (_now() - doc["stored_at"].replace(tzinfo=timezone.utc)).total_seconds() < ttl:
        return doc["payload"], True
    payload = await loader()
    await db.tracking_cache.replace_one(
        {"_id": key}, {"_id": key, "stored_at": _now(), "payload": payload}, upsert=True)
    return payload, False


def _events(raw):
    """Maersk answers either a bare list or an object holding one."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ("events", "shipmentEvents", "transportEvents"):
            if isinstance(raw.get(k), list):
                return raw[k]
    return []


def _code(e):
    return (e.get("transportEventTypeCode") or e.get("equipmentEventTypeCode")
            or e.get("shipmentEventTypeCode") or e.get("eventType") or "")


def _milestone(e):
    loc = e.get("eventLocation") or e.get("location") or {}
    call = e.get("transportCall") or {}
    vessel = call.get("vessel") or {}
    return {
        "code": _code(e),
        "when": e.get("eventDateTime") or e.get("eventCreatedDateTime"),
        # ACT happened, EST/PLN are still forecasts
        "estimated": (e.get("eventClassifierCode") or "ACT").upper() != "ACT",
        "location": loc.get("locationName") or loc.get("UNLocationCode") or "",
        "country": (loc.get("address") or {}).get("country") or loc.get("countryCode") or "",
        "unloc": (loc.get("UNLocationCode") or "").upper(),
        "mode": call.get("modeOfTransport") or "",
        "vessel_name": vessel.get("vesselName") or call.get("vesselName") or "",
        "vessel_imo": str(vessel.get("vesselIMONumber") or call.get("vesselIMONumber") or ""),
        "voyage": call.get("carrierVoyageNumber") or call.get("exportVoyageNumber") or "",
    }


async def vessel_position(db, imo):
    """Live AIS position, only if an AIS key is configured. Never fatal."""
    c = config()
    if not imo or not c["ais_key"]:
        return None

    async def load():
        url = c["ais_url"].format(key=c["ais_key"], imo=imo)
        async with httpx.AsyncClient(timeout=25) as x:
            r = await x.get(url)
        if r.is_error:
            log.warning("ais lookup %s -> %s %s", imo, r.status_code, r.text[:160])
            return None
        rows = r.json()
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not isinstance(row, dict):
            return None
        return {
            "lat": float(row.get("LAT") or row.get("lat") or 0) or None,
            "lon": float(row.get("LON") or row.get("lon") or 0) or None,
            "speed": row.get("SPEED") or row.get("speed"),
            "course": row.get("COURSE") or row.get("course"),
            "destination": row.get("DESTINATION") or row.get("destination") or "",
            "eta": row.get("ETA") or row.get("eta") or "",
            "at": row.get("TIMESTAMP") or row.get("timestamp") or "",
        }

    try:
        payload, _ = await _cached(db, f"ais:{imo}", VESSEL_TTL, load)
        return payload
    except Exception as e:
        log.warning("ais failed for %s: %s", imo, str(e)[:160])
        return None


def _view(ref, by, stones, source, cached=False, vessel=None):
    """Turn a sorted list of canonical events into what the Track page renders."""
    # Coordinates where the port is one we know, so the map can draw the route. Unknown
    # ports simply have no marker; the timeline still names them.
    for m in stones:
        where = ports.locate(m.get("unloc"), m.get("location"))
        if where:
            m["lat"], m["lon"] = where["lat"], where["lon"]
            m["location"] = m["location"] or where["port"]
    done = [m for m in stones if not m["estimated"]]
    ahead = [m for m in stones if m["estimated"]]
    # The port arrival is the date a buyer plans around; the trailing gate-out/delivery
    # forecasts only matter once the ship is in.
    eta = (next((m for m in ahead if m["code"] in ("VA", "ARRI")), None)
           or (ahead[-1] if ahead else None))
    last = done[-1] if done else None
    return {
        "configured": True,
        "found": True,
        "source": source,
        "cached": cached,
        "reference": ref,
        "by": by,
        "status": "delivered" if (last and last["code"] in DELIVERED)
                  else "in_transit" if done else "booked",
        "last": last,
        "eta": eta,
        "vessel": vessel,
        "milestones": stones,
        "updated_at": _now().isoformat(),
    }


async def track(db, ref, by="container"):
    """Normalised tracking view for one container or bill of lading.

    The EDI feed is authoritative: Maersk pushes status messages to us, so if anything has
    arrived for this reference it is used and nothing upstream is called. The REST client is
    the fallback for references the feed has not covered.
    """
    ref = (ref or "").strip().upper()
    if not ref or len(ref) > 40:
        raise ValueError("that reference does not look right")

    stones = await edi.events_for(db, ref, by)
    if stones:
        sailing = next((m for m in reversed(stones) if m.get("vessel_name")), None)
        vessel = None
        if sailing:
            vessel = {"imo": sailing.get("vessel_imo") or "", "name": sailing["vessel_name"],
                      "voyage": sailing.get("voyage") or "",
                      "position": await vessel_position(db, sailing.get("vessel_imo"))}
        return _view(ref, by, stones, "edi", vessel=vessel)

    if not is_configured():
        return {"configured": False, "reference": ref, "by": by}

    field = "equipmentReference" if by == "container" else "transportDocumentReference"
    key = "mae:" + hashlib.sha256(f"{field}:{ref}".encode()).hexdigest()
    raw, cached = await _cached(
        db, key, CACHE_TTL,
        lambda: _get("/track-and-trace-private/events", {field: ref, "limit": 100}))

    events = _events(raw)
    if not events:
        return {"configured": True, "reference": ref, "by": by, "found": False,
                "cached": cached, "milestones": []}

    stones = sorted([m for m in (_milestone(e) for e in events) if m["when"]],
                    key=lambda m: m["when"])
    sailing = next((m for m in reversed(stones) if m["vessel_imo"]), None)
    vessel = None
    if sailing:
        vessel = {"imo": sailing["vessel_imo"], "name": sailing["vessel_name"],
                  "voyage": sailing["voyage"],
                  "position": await vessel_position(db, sailing["vessel_imo"])}
    return _view(ref, by, stones, "rest", cached=cached, vessel=vessel)
