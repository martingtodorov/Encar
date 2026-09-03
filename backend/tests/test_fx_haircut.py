"""FX haircut buffer + price consistency.

Two rules kept this file honest after it went stale twice:
  * never copy a number the owner can change (the haircut, the margin, the lead times) -
    read it from the module the app itself reads;
  * use `requests`, not httpx, for anything unsafe - the CSRF token is added by conftest for
    `requests` only, and an httpx POST gets a truthful 403.
"""
import asyncio
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fx import HAIRCUT                                        # noqa: E402
import pricing                                                # noqa: E402

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_HDR = {"x-admin-token": (os.environ.get("ADMIN_TOKEN") or "").strip().strip('"')}
CAR = "41995353"


def _listing(car_id):
    """The row the site sells, straight from Mongo: the price the quote is built on."""
    from motor.motor_asyncio import AsyncIOMotorClient

    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            db = client[os.environ["DB_NAME"]]
            return await db.listings.find_one({"_id": car_id},
                                              {"price_krw": 1, "sale_eur": 1})
        finally:
            client.close()

    return asyncio.run(go())


# ---------- /api/fx ----------
def test_fx_haircut_arithmetic():
    r = requests.get(f"{BASE}/api/fx", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert "fx_krw_eur_market" in d and "fx_krw_eur" in d and "fx_haircut" in d
    assert d["fx_haircut"] == HAIRCUT
    market = d["fx_krw_eur_market"]
    published = d["fx_krw_eur"]
    assert abs(published - market * HAIRCUT) < 0.01, (market, published)
    # sanity ranges (KRW/EUR ~1600-1700 today)
    assert 1400 < market < 1900
    assert published < market


# ---------- /api/settings ----------
def test_settings_constants():
    """What the API publishes must be what the pricing module actually charges."""
    r = requests.get(f"{BASE}/api/settings", timeout=30)
    assert r.status_code == 200
    body = r.json()
    consts, defaults = body.get("constants") or {}, body.get("defaults") or {}
    assert consts, "no constants published"
    # The published defaults ARE the module's defaults - no second copy of the spec.
    for key, value in pricing.DEFAULT_SETTINGS.items():
        assert key in defaults, f"{key} missing from the published defaults"
        if isinstance(value, bool):
            assert defaults[key] == value, (key, defaults[key])
        else:
            assert float(defaults[key]) == float(value), (key, defaults[key], value)
    # Every knob the pricing module needs must be live, and the effective value is whatever
    # the owner set - the point is that nothing is missing or a string.
    for key, value in pricing.DEFAULT_SETTINGS.items():
        assert key in consts, f"{key} missing from /api/settings"
        assert isinstance(consts[key], bool if isinstance(value, bool) else (int, float)), \
            (key, consts[key])


# ---------- /api/car/{id} quote uses the buffered rate ----------
def test_car_quote_uses_buffered_rate():
    """The price on the car page is the pricing formula run on the BUFFERED rate.

    The endpoint exposes only `suggested_sale` (the breakdown is admin-only), so the check is
    end to end: recompute the quote here from the listing's own KRW price and the published
    rate, and the two must agree to the euro.
    """
    fx = requests.get(f"{BASE}/api/fx", timeout=30).json()
    listing = _listing(CAR)
    if not listing or not listing.get("price_krw"):
        pytest.skip(f"{CAR} is not in the catalogue right now")
    # Only an ACTIVE car quotes from `listing.price_krw`. Once the ad leaves Encar's search
    # results that value freezes at the last sync, and the car page deliberately falls back
    # to the cached advertisement price - which the dealer can still have edited. Comparing
    # the two on an inactive car tests nothing but how long ago it dropped out.
    if not listing.get("active"):
        pytest.skip(f"{CAR} is no longer active; its stored KRW price is frozen")
    r = requests.get(f"{BASE}/api/car/{CAR}?lang=en", timeout=45)
    assert r.status_code == 200, r.text[:300]
    sale = ((r.json().get("quote") or {}).get("suggested_sale"))
    assert sale, "quote missing"

    expected = pricing.price_car(listing["price_krw"], fx["fx_krw_eur"], fx["usd_eur"])
    assert abs(sale - expected["suggested_sale"]) < 1.0, (sale, expected["suggested_sale"])
    # Charm pricing and the floor, both from the spec.
    assert int(sale) % 100 == 99
    assert sale >= expected["landed"]
    # The market rate would make the car cheaper; a buffered quote is never below the market
    # one, which is the whole point of the haircut.
    market = pricing.price_car(listing["price_krw"], fx["fx_krw_eur_market"], fx["usd_eur"])
    assert sale >= market["suggested_sale"]


# ---------- price consistency: list vs detail ----------
def test_list_vs_detail_price_match():
    r = requests.post(f"{BASE}/api/search", json={"page": 1}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    items = (r.json().get("items") or [])[:3]
    assert len(items) >= 3, "search returned <3 items"
    mismatches = []
    for row in items:
        cid = row.get("car_id") or row.get("id")
        list_sale = row.get("sale_eur")
        dr = requests.get(f"{BASE}/api/car/{cid}?lang=en", timeout=45)
        if dr.status_code != 200:
            mismatches.append((cid, "detail http", dr.status_code))
            continue
        detail_sale = ((dr.json().get("quote") or {}).get("suggested_sale"))
        if list_sale != detail_sale:
            mismatches.append((cid, list_sale, detail_sale))
    assert not mismatches, mismatches


# ---------- manual override skips haircut ----------
def test_manual_override_skips_haircut():
    get_r = requests.get(f"{BASE}/api/settings", timeout=30)
    assert get_r.status_code == 200
    current = get_r.json()
    current_fxo = current.get("fx_overrides") or {}
    payload = {"constants": current.get("constants") or {},
               "fx_overrides": {**current_fxo, "fx_krw_eur": 1700},
               "reprice": False}
    r = requests.put(f"{BASE}/api/settings", headers=ADMIN_HDR, json=payload, timeout=60)
    assert r.status_code == 200, r.text[:300]
    try:
        fx = requests.get(f"{BASE}/api/fx?refresh=1", timeout=30).json()
        assert abs(fx["fx_krw_eur"] - 1700) < 0.01, fx
        assert fx["fx_haircut"] == 1.0, fx
    finally:
        clear = {"constants": current.get("constants") or {},
                 "fx_overrides": {k: v for k, v in current_fxo.items() if k != "fx_krw_eur"},
                 "reprice": False}
        requests.put(f"{BASE}/api/settings", headers=ADMIN_HDR, json=clear, timeout=60)
    fx2 = requests.get(f"{BASE}/api/fx?refresh=1", timeout=30).json()
    assert fx2["fx_haircut"] == HAIRCUT, fx2
    assert abs(fx2["fx_krw_eur"] - fx2["fx_krw_eur_market"] * HAIRCUT) < 0.01
