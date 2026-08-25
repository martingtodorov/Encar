"""FX rates.

fx_krw_eur = KRW per 1 EUR (divides the Encar price)
usd_eur    = EUR per 1 USD (multiplies the USD fees)
eur_bgn    = fixed by the Bulgarian currency board peg
eur_ron    = live
eur_pln    = live (Polish złoty per 1 EUR)

A 1% haircut is held back on EUR/KRW as an exchange buffer (see HAIRCUT).

On the source: Google Finance was tried and rejected. It has no API, and its quote page
carries no stable hook for the rate - no data-last-price, no data-source/data-target, no
aria-label. The only marker available (jsname="Pdsbrc") repeats for ~40 unrelated
currency pairs on the same page, so picking a match by position returned 1,070.98 for
EUR/KRW instead of ~1,650: a 54% mis-price across the whole catalogue, from a page that
can be reordered by Google at any time without notice. Rates are taken from a feed with
an actual contract instead, and the market-vs-published rate is kept side by side on
every quote so the buffer is always auditable.

Cached in Mongo with a TTL and overridable by hand from the admin panel.
"""

import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("fx")

TTL_SECONDS = 6 * 3600
EUR_BGN_PEG = 1.95583  # Bulgarian lev is pegged to the euro

# We buy KRW at a worse rate than the mid-market quote, so part of the rate is held back
# as a buffer. A LOWER KRW-per-EUR means each car costs slightly more euros, which is
# what protects the margin when the rate moves between quoting and paying.
HAIRCUT = 0.99

# Listings carry a precomputed sale price, so when the rate moves the whole catalogue has
# to be repriced or search rows drift away from detail pages. Anything larger than this
# relative move raises a flag for sync.reprice_if_fx_drifted() to act on.
REPRICE_EPS = 0.002

FALLBACK = {"fx_krw_eur": 1664.0, "usd_eur": 0.867, "eur_ron": 4.977,
            "eur_pln": 4.35, "eur_bgn": EUR_BGN_PEG}


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
            if rates.get("PLN"):
                out["eur_pln"] = float(rates["PLN"])
        r = await c.get("https://open.er-api.com/v6/latest/USD")
        if r.status_code == 200:
            rates = (r.json() or {}).get("rates") or {}
            if rates.get("EUR"):
                out["usd_eur"] = float(rates["EUR"])
    return out


def _apply_overrides(rates, overrides):
    manual = []
    for k in ("fx_krw_eur", "usd_eur", "eur_ron", "eur_pln"):
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


def _apply_haircut(rates):
    """Publish the buffered rate, keeping the market rate alongside for auditing.

    Skipped when the rate was set by hand: a manual override is already the rate the
    operator wants used, and quietly shaving another 1% off it would be surprising.
    """
    market = rates.get("fx_krw_eur")
    rates["fx_krw_eur_market"] = market
    if market and "fx_krw_eur" not in (rates.get("manual_overrides") or []):
        rates["fx_krw_eur"] = market * HAIRCUT
        rates["fx_haircut"] = HAIRCUT
    else:
        rates["fx_haircut"] = 1.0
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
        rates = {k: doc[k] for k in ("fx_krw_eur", "usd_eur", "eur_ron", "eur_pln") if k in doc}
        rates.setdefault("eur_ron", FALLBACK["eur_ron"])
        rates.setdefault("eur_pln", FALLBACK["eur_pln"])
        out = _apply_haircut(_apply_overrides(rates, overrides))
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
        for k in ("fx_krw_eur", "usd_eur", "eur_ron", "eur_pln"):
            if doc.get(k):
                base[k] = doc[k]
    base.update(live)

    source = "open.er-api.com" if live else ("stale-cache" if doc else "fallback")
    # Raw-to-raw comparison: both sides are pre-haircut, so the check is independent of
    # whatever HAIRCUT happens to be set to.
    previous = (doc or {}).get("fx_krw_eur")
    drifted = bool(
        live.get("fx_krw_eur") and previous
        and abs(live["fx_krw_eur"] - previous) / previous > REPRICE_EPS
    )
    if drifted:
        log.info("EUR/KRW moved %.4f -> %.4f, catalogue reprice flagged",
                 previous, live["fx_krw_eur"])

    update = {
        "fx_krw_eur": base["fx_krw_eur"],
        "usd_eur": base["usd_eur"],
        "eur_ron": base["eur_ron"],
        "eur_pln": base["eur_pln"],
        "fetched_at": now,
        "source": source,
    }
    if drifted:
        update["reprice_needed"] = True
    await db.fx.update_one({"_id": "rates"}, {"$set": update}, upsert=True)

    out = _apply_haircut(_apply_overrides(base, overrides))
    out["fetched_at"] = now
    out["source"] = source
    return out
