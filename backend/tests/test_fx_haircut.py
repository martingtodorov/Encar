"""FX haircut buffer + price consistency tests (iteration 12)."""
import os
import httpx
import pytest
from pathlib import Path

def _read_backend_url():
    env_path = Path("/app/frontend/.env")
    for line in env_path.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

BASE = _read_backend_url().rstrip("/")
ADMIN_HDR = {"x-admin-token": "encar-admin"}
HAIRCUT = 0.995319


# ---------- /api/fx ----------
def test_fx_haircut_arithmetic():
    r = httpx.get(f"{BASE}/api/fx", timeout=30)
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
    r = httpx.get(f"{BASE}/api/settings", timeout=30)
    assert r.status_code == 200
    s = r.json()
    consts = s.get("constants") or s
    # Some backends return dict-in-dict; flatten
    for k, v in [
        ("IMPORT_DUTY_RATE", 0.10),
        ("VAT_RATE", 0.20),
        ("CUSTOMS_BASE_FRACTION", 0.18),
        ("AUTOWINI_FEE_USD", 2900.0),
        ("DOMESTIC_TOTAL", 1600.0),
        ("MARGIN_PCT", 0.014),
        ("MARGIN_MIN_EUR", 500.0),
    ]:
        assert float(consts.get(k)) == v, (k, consts.get(k))


# ---------- /api/car/{id} quote uses buffered rate ----------
def test_car_quote_uses_buffered_rate():
    fx = httpx.get(f"{BASE}/api/fx", timeout=30).json()
    published = fx["fx_krw_eur"]
    r = httpx.get(f"{BASE}/api/car/41995353?lang=en", timeout=45)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    q = j.get("quote") or {}
    assert q, "quote missing"
    assert abs(q["fx_krw_eur"] - published) < 0.5, (q["fx_krw_eur"], published)
    # encar_eur is price_krw / fx_krw_eur
    expected_encar = round(q["price_krw"] / q["fx_krw_eur"], 2)
    assert abs(q["encar_eur"] - expected_encar) < 0.02
    # internal consistency: customs_base = car_eur * 0.18
    assert abs(q["customs_base"] - q["car_eur"] * 0.18) < 0.5
    # duty = base * 0.10
    assert abs(q["duty"] - q["customs_base"] * 0.10) < 0.5
    # vat = (base + duty) * 0.20
    assert abs(q["vat"] - (q["customs_base"] + q["duty"]) * 0.20) < 0.5
    # landed = car_eur + duty + vat + 1600
    expected_landed = q["car_eur"] + q["duty"] + q["vat"] + q["domestic_total"]
    assert abs(q["landed"] - expected_landed) < 1.0
    # suggested_sale ends in 99
    assert int(q["suggested_sale"]) % 100 == 99
    assert q["suggested_sale"] >= q["landed"]


# ---------- price consistency: list vs detail ----------
def test_list_vs_detail_price_match():
    r = httpx.post(f"{BASE}/api/search", json={"page": 1}, timeout=30)
    assert r.status_code == 200
    items = (r.json().get("items") or [])[:3]
    assert len(items) >= 3, "search returned <3 items"
    mismatches = []
    for row in items:
        cid = row.get("car_id") or row.get("id")
        list_sale = row.get("sale_eur")
        dr = httpx.get(f"{BASE}/api/car/{cid}?lang=en", timeout=45)
        if dr.status_code != 200:
            mismatches.append((cid, "detail http", dr.status_code))
            continue
        detail_sale = ((dr.json().get("quote") or {}).get("suggested_sale"))
        if list_sale != detail_sale:
            mismatches.append((cid, list_sale, detail_sale))
    assert not mismatches, mismatches


# ---------- manual override skips haircut ----------
def _get_settings_doc():
    r = httpx.get(f"{BASE}/api/admin/settings", headers=ADMIN_HDR, timeout=30)
    return r


def test_manual_override_skips_haircut():
    # GET current settings
    get_r = httpx.get(f"{BASE}/api/settings", timeout=30)
    assert get_r.status_code == 200
    current = get_r.json()
    current_fxo = current.get("fx_overrides") or {}
    payload = {"constants": current.get("constants") or {},
               "fx_overrides": {**current_fxo, "fx_krw_eur": 1700},
               "reprice": False}
    r = httpx.put(f"{BASE}/api/settings", headers=ADMIN_HDR, json=payload, timeout=60)
    assert r.status_code == 200, r.text[:300]
    try:
        fx = httpx.get(f"{BASE}/api/fx?refresh=1", timeout=30).json()
        assert abs(fx["fx_krw_eur"] - 1700) < 0.01, fx
        assert fx["fx_haircut"] == 1.0, fx
    finally:
        # remove override
        clear = {"constants": current.get("constants") or {},
                 "fx_overrides": {k: v for k, v in current_fxo.items() if k != "fx_krw_eur"},
                 "reprice": False}
        httpx.put(f"{BASE}/api/settings", headers=ADMIN_HDR, json=clear, timeout=60)
    fx2 = httpx.get(f"{BASE}/api/fx?refresh=1", timeout=30).json()
    assert fx2["fx_haircut"] == HAIRCUT, fx2
    assert abs(fx2["fx_krw_eur"] - fx2["fx_krw_eur_market"] * HAIRCUT) < 0.01
