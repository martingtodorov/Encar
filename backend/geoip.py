"""Which country the visitor is calling from, so a phone field starts on the right prefix.

Behind Cloudflare the answer arrives as a header and costs nothing. Without one, the IP is
looked up once and the ANSWER is cached against a HASH of the address — the address itself is
never written down, exactly as with the traffic counters, and the row expires by itself.
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Request

log = logging.getLogger("geoip")

_db = None
KEEP_DAYS = 30
LOOKUP = os.environ.get("GEOIP_URL", "http://ip-api.com/json/{ip}?fields=status,countryCode")
PRIVATE = ("10.", "192.168.", "127.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2",
           "172.30.", "172.31.", "169.254.", "::1", "fc", "fd")


def set_db(db):
    global _db
    _db = db


async def ensure_indexes():
    await _db.geoip.create_index("expires_at", expireAfterSeconds=0)


def client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "") or ""


def _key(ip):
    return hashlib.sha256(f"geo:{ip}".encode()).hexdigest()[:40]


def _from_headers(request: Request):
    """A CDN in front of us has already done the lookup."""
    for header in ("cf-ipcountry", "x-vercel-ip-country", "x-appengine-country",
                   "x-geo-country"):
        value = (request.headers.get(header) or "").strip().upper()
        if len(value) == 2 and value.isalpha() and value not in ("XX", "T1"):
            return value
    return ""


async def country_of(request: Request):
    """ISO 3166-1 alpha-2, or "" when we genuinely cannot tell."""
    hinted = _from_headers(request)
    if hinted:
        return hinted
    ip = client_ip(request)
    if not ip or ip.startswith(PRIVATE):
        return ""
    key = _key(ip)
    row = await _db.geoip.find_one({"_id": key})
    if row:
        return row.get("country") or ""
    country = ""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(LOOKUP.format(ip=ip))
            if r.is_success:
                data = r.json()
                if data.get("status") in (None, "success"):
                    country = (data.get("countryCode") or "").upper()[:2]
    except (httpx.HTTPError, ValueError) as e:
        log.info("geoip lookup failed: %s", str(e)[:120])
    # A failure is cached too, briefly, so a provider being down cannot turn one form into a
    # queue of outbound requests.
    await _db.geoip.update_one(
        {"_id": key},
        {"$set": {"country": country,
                  "expires_at": datetime.now(timezone.utc)
                  + timedelta(days=KEEP_DAYS if country else 1)}},
        upsert=True)
    return country
