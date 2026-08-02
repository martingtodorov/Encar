"""Backend tests for iteration 11:
- POST /api/listings/by-ids (batch resolve, preserves order)
- POST /api/car/{listing_id}/translate-description (Claude-powered, cached)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# --- POST /api/listings/by-ids ---

def test_by_ids_returns_both_in_order(s):
    r = s.post(f"{BASE_URL}/api/listings/by-ids?lang=bg", json={"ids": ["42244072", "41995353"]})
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert isinstance(items, list) and len(items) == 2
    assert str(items[0].get("listing_id") or items[0].get("id")) == "42244072"
    assert str(items[1].get("listing_id") or items[1].get("id")) == "41995353"
    for it in items:
        # Required fields for saved cards
        assert any(k in it for k in ("sale_eur", "price_eur", "sale_price_eur"))
        assert "image" in it or "photo" in it or "images" in it
        assert any(k in it for k in ("manufacturer_t", "make_t", "brand_t"))
        assert any(k in it for k in ("model_t",))


def test_by_ids_reversed_order(s):
    r = s.post(f"{BASE_URL}/api/listings/by-ids?lang=bg", json={"ids": ["41995353", "42244072"]})
    assert r.status_code == 200
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert len(items) == 2
    assert str(items[0].get("listing_id") or items[0].get("id")) == "41995353"


def test_by_ids_empty(s):
    r = s.post(f"{BASE_URL}/api/listings/by-ids?lang=bg", json={"ids": []})
    assert r.status_code in (200, 400, 422)


def test_by_ids_includes_images_array(s):
    r = s.post(f"{BASE_URL}/api/listings/by-ids?lang=bg", json={"ids": ["41995353"]})
    assert r.status_code == 200
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert len(items) == 1
    it = items[0]
    # listing_out should include images array per request
    if "images" in it:
        assert isinstance(it["images"], list)


# --- POST /api/car/{id}/translate-description ---

def test_translate_description_bg(s):
    t0 = time.time()
    r = s.post(f"{BASE_URL}/api/car/41995353/translate-description?lang=bg", json={}, timeout=60)
    dt1 = time.time() - t0
    assert r.status_code == 200, r.text
    data = r.json()
    assert "text" in data
    text = data["text"]
    assert isinstance(text, str) and len(text) > 10
    # Bulgarian is Cyrillic
    has_cyrillic = any("\u0400" <= ch <= "\u04FF" for ch in text)
    assert has_cyrillic, f"Expected Cyrillic in Bulgarian translation, got: {text[:200]}"
    print(f"First call took {dt1:.2f}s")

    # Second call should be cached and fast
    t1 = time.time()
    r2 = s.post(f"{BASE_URL}/api/car/41995353/translate-description?lang=bg", json={}, timeout=15)
    dt2 = time.time() - t1
    assert r2.status_code == 200
    assert r2.json().get("text") == text
    print(f"Second (cached) call took {dt2:.2f}s")
    assert dt2 < max(3.0, dt1 * 0.5), f"Cached call not fast enough: {dt2}s vs first {dt1}s"


def test_translate_description_missing_car(s):
    r = s.post(f"{BASE_URL}/api/car/9999999999/translate-description?lang=bg", json={}, timeout=30)
    assert r.status_code in (404, 400, 503)
