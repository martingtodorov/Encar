"""FX rates.

fx_krw_eur = KRW per 1 EUR (divides the Encar price)
usd_eur    = EUR per 1 USD (multiplies the USD fees)
eur_bgn    = fixed by the Bulgarian currency board peg
eur_ron    = live

Live from open.er-api.com (free, no key). Cached in Mongo with a TTL and
overridable by hand from the admin panel, because the user's spec pulls these
from a Google Sheet in production.
"""

import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("fx")

TTL_SECONDS = 6 * 3600
EUR_BGN_PEG = 1.95583  # Bulgarian lev is pegged to the euro

FALLBACK = {"fx_krw_eur": 1664.0, "usd_eur": 0.867, "eur_ron": 4.977, "eur_bgn": EUR_BGN_PEG}


async def _fetch_live():
    out = {}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://open.er-api.com/v6/latest/EUR")
        if r.status_code == 200:
            rates = (r.json() or {}).get("rates") or {}
            if rates.get("KRW"):
                out["fx_krw_eur"] = float(rates["KRW"])
            if rates.get("RON"):
                out["eur_ron"] = float(rates["RON"])
        r = await c.get("https://open.er-api.com/v6/latest/USD")
        if r.status_code == 200:
            rates = (r.json() or {}).get("rates") or {}
            if rates.get("EUR"):
                out["usd_eur"] = float(rates["EUR"])
    return out


def _apply_overrides(rates, overrides):
    manual = []
    for k in ("fx_krw_eur", "usd_eur", "eur_ron"):
        v = (overrides or {}).get(k)
        if v not in (None, "", 0):
            try:
                rates[k] = float(v)
                manual.append(k)
            except (TypeError, ValueError):
                pass
    rates["eur_bgn"] = EUR_BGN_PEG
    rates["manual_overrides"] = manual
    return rates


async def get_rates(db, force=False):
    """Returns the rate bundle, refreshing from the live feed when stale."""
    now = datetime.now(timezone.utc)
    doc = await db.fx.find_one({"_id": "rates"})
    settings_doc = await db.settings.find_one({"_id": "pricing"}) or {}
    overrides = settings_doc.get("fx_overrides") or {}

    fresh = False
    if doc and not force:
        age = (now - doc["fetched_at"].replace(tzinfo=timezone.utc)).total_seconds()
        fresh = age < TTL_SECONDS

    if fresh:
        rates = {k: doc[k] for k in ("fx_krw_eur", "usd_eur", "eur_ron") if k in doc}
        rates.setdefault("eur_ron", FALLBACK["eur_ron"])
        out = _apply_overrides(rates, overrides)
        out["fetched_at"] = doc["fetched_at"]
        out["source"] = doc.get("source", "cache")
        return out

    live = {}
    try:
        live = await _fetch_live()
    except Exception as e:  # network hiccup must never break browsing
        log.warning("FX fetch failed: %s", e)

    base = dict(FALLBACK)
    if doc:  # prefer last known good over hardcoded fallback
        for k in ("fx_krw_eur", "usd_eur", "eur_ron"):
            if doc.get(k):
                base[k] = doc[k]
    base.update(live)

    source = "open.er-api.com" if live else ("stale-cache" if doc else "fallback")
    await db.fx.update_one(
        {"_id": "rates"},
        {"$set": {
            "fx_krw_eur": base["fx_krw_eur"],
            "usd_eur": base["usd_eur"],
            "eur_ron": base["eur_ron"],
            "fetched_at": now,
            "source": source,
        }},
        upsert=True,
    )

    out = _apply_overrides(base, overrides)
    out["fetched_at"] = now
    out["source"] = source
    return out
