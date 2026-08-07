"""Backend tests for POST /api/recommendations (interest-based landing shelf).

The API accepts a client-side taste profile (makes/models/fuels weights + optional
price/year) and returns up to `limit` cars, capped at 3 per model, with `why_label`
built after translation.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
URL = f"{BASE_URL}/api/recommendations"


def _post(payload):
    return requests.post(URL, json=payload, timeout=30)


# --- profile with makes/models returns items -------------------------------------------
def test_profile_returns_items_and_shape():
    r = _post({
        "makes": {"BMW": 4.0, "Audi": 1.0},
        "models": {"5시리즈": 5.0, "3시리즈": 2.0},
        "fuels": {"diesel": 1.5},
        "price": 30000,
        "year": 2020,
        "limit": 12,
        "lang": "bg",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "items" in data and isinstance(data["items"], list)
    assert data["lang"] == "bg"
    if data["items"]:
        assert len(data["items"]) <= 12
        # never more than 3 of the same model
        from collections import Counter
        c = Counter(it.get("model") or "" for it in data["items"])
        assert all(v <= 3 for v in c.values()), c
        for it in data["items"]:
            # non-admin: landed_eur must not leak
            assert "landed_eur" not in it
            assert "why_label" in it


def test_limit_respected():
    r = _post({"makes": {"BMW": 3.0}, "models": {}, "limit": 4, "lang": "bg"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) <= 4


# --- empty profile ---------------------------------------------------------------------
def test_empty_profile_returns_no_items():
    """No taste yet is not an empty shelf: the visitor gets the popular cars instead."""
    r = _post({"makes": {}, "models": {}, "fuels": {}, "limit": 12, "lang": "bg"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("source") == "popular", data.get("source")
    assert len(data["items"]) <= 12


# --- price clustering ------------------------------------------------------------------
def test_price_window_clusters_results():
    price = 20000
    r = _post({
        "makes": {"BMW": 3.0},
        "models": {},
        # A bare `price` field was sent here for years and quietly ignored - TasteBody has no
        # such field. The browser sends SAMPLES: [price, mileage, weight] per car looked at,
        # and that is what defines the window, so the test now speaks the same language.
        "samples": [[price, 60000, 3.0]],
        "limit": 12,
        "lang": "bg",
    })
    assert r.status_code == 200
    for it in r.json()["items"]:
        p = it.get("sale_eur")
        if p:
            assert price * 0.5 <= p <= price * 1.8, f"{p} outside window around {price}"


# --- rubbish input never 500s ----------------------------------------------------------
def test_rubbish_input_does_not_500():
    payloads = [
        # huge dict of makes
        {"makes": {f"junk{i}": 1.0 for i in range(500)}, "models": {}, "limit": 12},
        # negative weights (filtered out) + non-numeric
        {"makes": {"BMW": -5.0, "Audi": "bad", "Kia": 2.0}, "models": {}, "limit": 12},
        # absurd limit
        {"makes": {"BMW": 2.0}, "models": {}, "limit": 999999},
        # negative limit
        {"makes": {"BMW": 2.0}, "models": {}, "limit": -3},
        # non-numeric weights everywhere
        {"makes": {"BMW": "abc"}, "models": {"5시리즈": None}, "limit": 12},
        # huge exclude list
        {"makes": {"BMW": 2.0}, "exclude": [str(i) for i in range(500)], "limit": 12},
        # weirdly long keys
        {"makes": {"X" * 500: 3.0}, "limit": 5},
    ]
    for p in payloads:
        r = _post(p)
        assert r.status_code in (200, 422), f"Server error on {p}: {r.status_code} {r.text[:200]}"
        if r.status_code == 200:
            assert isinstance(r.json().get("items"), list)


def test_why_label_is_translated_not_korean():
    """When `why=model`, why_label must come from model_t (translated), never raw Korean."""
    r = _post({
        "makes": {"BMW": 4.0},
        "models": {"5시리즈": 5.0},
        "limit": 12,
        "lang": "bg",
    })
    assert r.status_code == 200
    for it in r.json()["items"]:
        wl = it.get("why_label") or ""
        # Not asserting non-empty (could be a make-only match), but if present it
        # must not be raw Korean hangul when lang=bg.
        if wl:
            # Any Hangul characters would fail the "translated" contract for non-KO.
            assert not any("\uac00" <= ch <= "\ud7a3" for ch in wl), f"Korean leaked: {wl}"
