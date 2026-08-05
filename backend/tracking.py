"""Shipment tracking: Maersk Track & Trace Plus + AIS vessel position.

Everything upstream is cached in Mongo. Maersk quotas are per consumer key (roughly
120/min, 5,000/hour) and a buyer refreshing a page must never spend one call per render,
so a reference is fetched at most once every CACHE_TTL and every response is stored raw
alongside the normalised view.

Credentials live in backend/.env and are read lazily, so the app boots and the page
renders a clear "not connected" state instead of crashing when they are absent.
"""
import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

import edi
import jsoncargo
import maersk_public
import ports

log = logging.getLogger("tracking")

CACHE_TTL = int(os.environ.get("TRACKING_CACHE_TTL", "900"))
VESSEL_TTL = int(os.environ.get("VESSEL_CACHE_TTL", "1800"))
PUBLIC_TTL = int(os.environ.get("PUBLIC_TRACK_TTL", "1800"))

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
        "ais_base": os.environ.get("MARINETRAFFIC_BASE_URL",
                                   "https://services.marinetraffic.com/api"),
        "ais_version": os.environ.get("MARINETRAFFIC_EXPORTVESSEL_VERSION", "5"),
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


def _num(v, divisor=1):
    try:
        return float(v) / divisor if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _rows(payload):
    """MarineTraffic's `jsono` answers with an array of rows; some services wrap it."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        data = payload.get("DATA")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return [payload]
    return []


async def vessel_position(db, imo, mmsi=""):
    """Live AIS position from MarineTraffic (Kpler), only when a key is configured.

    Single Vessel Positions: the key is a PATH segment, the response is metered per call,
    and SPEED comes back in tenths of a knot. Redirects must be followed. Never fatal — the
    vessel card simply says the position is not available.
    """
    c = config()
    ident = ("imo", str(imo)) if imo else ("mmsi", str(mmsi)) if mmsi else None
    if not ident or not c["ais_key"]:
        return None

    async def load():
        params = {"v": c["ais_version"], ident[0]: ident[1], "timespan": 1440,
                  "msgtype": "extended", "protocol": "jsono"}
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as x:
            r = await x.get(f"{c['ais_base']}/exportvessel/{c['ais_key']}", params=params)
        if r.is_error:
            log.warning("ais lookup %s -> %s %s", ident[1], r.status_code, r.text[:200])
            return None
        rows = _rows(r.json())
        if not rows:
            return None                       # no AIS report inside the timespan
        row = rows[0]
        lat, lon = _num(row.get("LAT")), _num(row.get("LON"))
        if lat is None or lon is None:
            return None
        return {
            "lat": lat, "lon": lon,
            "speed": _num(row.get("SPEED"), 10),
            "course": _num(row.get("COURSE")),
            "name": row.get("SHIPNAME") or "",
            "destination": row.get("DESTINATION") or "",
            "eta": row.get("ETA") or "",
            "last_port": row.get("LAST_PORT") or "",
            "at": row.get("TIMESTAMP") or "",
        }

    try:
        payload, _ = await _cached(db, f"ais:{ident[0]}:{ident[1]}", VESSEL_TTL, load)
        return payload
    except Exception as e:
        log.warning("ais failed for %s: %s", ident[1], str(e)[:160])
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


_inflight = set()


async def _public_read(db, ref):
    """Read Maersk's public page and cache the result. Runs detached for buyer lookups."""
    key = f"pub:{ref}"
    try:
        raw = await maersk_public.read(ref)
    except Exception as e:
        log.warning("public track %s failed: %s", ref, str(e)[:200])
        return None
    finally:
        _inflight.discard(ref)
    if raw is None:
        return None
    payload = {"empty": raw["empty"],
               "events": [] if raw["empty"] else maersk_public.to_events(raw["json"])}
    await db.tracking_cache.replace_one(
        {"_id": key}, {"_id": key, "stored_at": _now(), "payload": payload,
                       "raw": raw["json"]}, upsert=True)
    return payload


async def _public(db, ref, refresh=False):
    """Milestones read off Maersk's public track page.

    A read costs a browser page and ~30 seconds, so a buyer never waits for one: a cached
    payload is served when it is fresh, and otherwise the read is scheduled in the
    background and the answer says so. Only the operator's refresh runs it inline.
    """
    if not maersk_public.enabled():
        return None
    key = f"pub:{ref}"
    if not refresh:
        doc = await db.tracking_cache.find_one({"_id": key})
        if doc and (_now() - doc["stored_at"].replace(tzinfo=timezone.utc)
                    ).total_seconds() < PUBLIC_TTL:
            return doc["payload"]
        if ref not in _inflight:
            _inflight.add(ref)
            asyncio.create_task(_public_read(db, ref))
        return {"pending": True, "empty": False, "events": []}
    _inflight.discard(ref)
    return await _public_read(db, ref)


async def _cargo(db, ref, by, refresh=False):
    """Milestones + route from JSONCargo. A B/L is resolved to its container first."""
    if not jsoncargo.configured():
        return None
    number = ref
    try:
        if by == "bol":
            numbers = await jsoncargo.containers_for_bol(db, ref, refresh)
            if not numbers:
                return None
            number = numbers[0]
        snap = await jsoncargo.container(db, number, refresh)
    except RuntimeError as e:
        log.warning("jsoncargo lookup for %s failed: %s", ref, str(e)[:160])
        return None
    if not snap:
        return None
    return {"container": number, "events": jsoncargo.to_events(snap),
            "route": jsoncargo.route(snap), "snapshot": snap}


DELIVERY_DAYS = int(os.environ.get("DELIVERY_LEAD_DAYS", "7"))
CUSTOMS_DAYS = int(os.environ.get("CUSTOMS_LEAD_DAYS", "4"))


def _stone(code, text, when, place="", country=""):
    return {"code": code, "text": text, "when": when, "estimated": True,
            "location": place, "country": country, "unloc": "", "mode": "road",
            "vessel_name": "", "vessel_imo": "", "voyage": ""}


async def _last_leg(db, stones, owner_id):
    """The two steps the carrier never reports: clearing customs, then the buyer's door.

    Ocean tracking ends at the destination terminal, but nobody is waiting at a terminal.
    Customs clearance runs about four days after the box comes OFF THE SHIP and the lorry
    arrives about a week after that, so both are appended as CLEARLY ESTIMATED steps — the
    delivery one named with the country from the buyer's billing address when we have it.
    """
    if not stones:
        return []
    # Both dates hang off the box being DISCHARGED, not off whatever event happens to be
    # last: a barge leg onward to Bergen op Zoom pushed customs a week past the day the
    # container was already standing on the quay in Rotterdam.
    arrival = next((s for s in reversed(stones) if s.get("code") == "UV"), None)
    if not arrival:
        arrival = next((s for s in reversed(stones)
                        if s.get("code") in ("AV", "VA", "ARRI")), stones[-1])
    port = arrival.get("location") or ""
    try:
        base = datetime.fromisoformat(arrival["when"])
    except (ValueError, KeyError, TypeError):
        return []
    country = ""
    if owner_id:
        owner = await db.users.find_one({"_id": owner_id}, {"billing": 1})
        country = ((owner or {}).get("billing") or {}).get("country") or ""
    fmt = "%Y-%m-%dT%H:%M:00"
    return [
        _stone("CU", "Customs cleared",
               (base + timedelta(days=CUSTOMS_DAYS)).strftime(fmt), port),
        # Country only — the buyer's street address is not something to print on a page
        # that a shared link can open.
        _stone("DLV", "Delivery",
               (base + timedelta(days=CUSTOMS_DAYS + DELIVERY_DAYS)).strftime(fmt),
               country, country),
    ]


async def track(db, ref, by="container", refresh=False):
    """Normalised tracking view for one container or bill of lading.

    Sources, in order of authority: the EDI feed Maersk pushes to us, then Maersk's own
    public track page read with a real browser, then the private REST API when a consumer
    key is configured. Whatever the admin assigned by hand (customer, car, ship) is merged
    on top so the buyer always sees the vessel we told them about.
    """
    ref = (ref or "").strip().upper()
    if not ref or len(ref) > 40:
        raise ValueError("that reference does not look right")

    # What the admin assigned: customer, car, ship. The EDI feed (when it arrives) is merged
    # on top of it rather than replacing it.
    manual = await db.shipments.find_one({"ref": ref}, {"_id": 0})
    owner_id = (manual or {}).pop("user_id", "") if manual else ""

    stones = await edi.events_for(db, ref, by)
    source = "edi"
    asked_carrier, checking, cargo = False, False, None
    if not stones:
        cargo = await _cargo(db, ref, by, refresh)
        if cargo and cargo["events"]:
            stones, source = cargo["events"], "jsoncargo"
    if not stones:
        pub = await _public(db, ref, refresh)
        checking = bool(pub and pub.get("pending"))
        asked_carrier = pub is not None and not checking
        if pub and pub["events"]:
            stones, source = pub["events"], "public"

    if not stones and manual:
        vessel = None
        if manual.get("vessel_name") or manual.get("vessel_imo") or manual.get("vessel_mmsi"):
            vessel = {"imo": manual.get("vessel_imo") or "", "name": manual.get("vessel_name") or "",
                      "mmsi": manual.get("vessel_mmsi") or "", "voyage": "",
                      "position": await vessel_position(db, manual.get("vessel_imo"),
                                                        manual.get("vessel_mmsi"))}
        return {"configured": True, "found": True, "source": "assigned", "cached": False,
                "reference": ref, "by": by, "status": "in_transit", "last": None,
                "eta": {"code": "VA", "when": manual.get("eta") or None, "estimated": True,
                        "location": "", "country": ""} if manual.get("eta") else None,
                "vessel": vessel, "note": manual.get("note") or "", "milestones": [],
                "checking": checking, "updated_at": _now().isoformat()}

    if stones:
        sailing = next((m for m in reversed(stones) if m.get("vessel_name")), None)
        vessel = None
        if sailing:
            vessel = {"imo": sailing.get("vessel_imo") or "", "name": sailing["vessel_name"],
                      "voyage": sailing.get("voyage") or "",
                      "position": await vessel_position(db, sailing.get("vessel_imo"))}
            # The snapshot gives a vessel NAME only, so the AIS position is resolved through
            # the same provider (name -> IMO once, then the live position).
            if not vessel["position"] and source == "jsoncargo":
                live = await jsoncargo.vessel(db, name=vessel["name"],
                                              imo=vessel["imo"], refresh=refresh)
                if live:
                    vessel["imo"] = vessel["imo"] or live["imo"]
                    vessel["mmsi"] = live["mmsi"]
                    vessel["position"] = live["position"]
        if manual:
            vessel = vessel or {"imo": "", "name": "", "voyage": "", "position": None}
            vessel["name"] = manual.get("vessel_name") or vessel["name"]
            vessel["imo"] = manual.get("vessel_imo") or vessel["imo"]
            vessel["mmsi"] = manual.get("vessel_mmsi") or vessel.get("mmsi", "")
            if not vessel["position"]:
                vessel["position"] = await vessel_position(db, vessel["imo"],
                                                           vessel.get("mmsi", ""))
        # Customs and the buyer's own doorstep, which no carrier reports, as estimates.
        tail = await _last_leg(db, stones, owner_id)
        if tail:
            stones = stones + tail
        view = _view(ref, by, stones, source, vessel=vessel)
        view["delivery"] = tail[-1] if tail else None
        view["customs"] = tail[0] if tail else None
        if cargo:
            view["route"] = cargo["route"]
            view["container"] = cargo["container"]
        if manual:
            view["note"] = manual.get("note") or ""
        return view

    if not is_configured():
        # The carrier answered "nothing public for this reference" — that is an answer, not
        # a missing integration, so the page says "not found" rather than "not connected".
        if asked_carrier or checking:
            return {"configured": True, "reference": ref, "by": by, "found": False,
                    "source": "public", "cached": False, "checking": checking,
                    "milestones": []}
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
