"""Iteration 25 tests: photo de-dup, relevant sort spread + cold-start, tracking tail, cache."""
import os
import sys
import time
import requests
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracking import DELIVERY_DAYS  # noqa: E402

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE}/api"
ADMIN_TOKEN = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "")}


# --- photo de-duplication ---------------------------------------------------

def test_car_42259236_has_18_unique_photos():
    r = requests.get(f"{API}/car/42259236", params={"lang": "en"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    photos = d.get("photos") or []
    assert d.get("photo_count") == len(photos), f"photo_count={d.get('photo_count')} len={len(photos)}"
    assert len(photos) == 18, f"expected 18 photos, got {len(photos)}"
    fulls = [p.get("full") for p in photos]
    thumbs = [p.get("thumb") for p in photos]
    assert len(set(fulls)) == len(fulls), f"duplicate full urls: {[u for u in fulls if fulls.count(u)>1][:3]}"
    assert len(set(thumbs)) == len(thumbs)


def test_sample_cars_have_unique_photos():
    r = requests.post(f"{API}/search", json={"page": 1, "page_size": 12, "lang": "en"}, timeout=30)
    assert r.status_code == 200
    items = r.json().get("items") or []
    ids = [it["id"] for it in items[:8]]
    assert len(ids) >= 6
    checked = 0
    for cid in ids:
        cr = requests.get(f"{API}/car/{cid}", params={"lang": "en"}, timeout=30)
        if cr.status_code != 200:
            continue
        d = cr.json()
        photos = d.get("photos") or []
        if not photos:
            continue
        fulls = [p.get("full") for p in photos]
        thumbs = [p.get("thumb") for p in photos]
        assert d["photo_count"] == len(photos), f"{cid}: photo_count mismatch"
        assert len(set(fulls)) == len(fulls), f"{cid}: duplicate full urls"
        assert len(set(thumbs)) == len(thumbs), f"{cid}: duplicate thumb urls"
        checked += 1
    assert checked >= 6, f"only checked {checked} cars"


# --- relevant sort spread ---------------------------------------------------

def _relevant(taste):
    r = requests.post(f"{API}/search", json={
        "sort": "relevant", "page": 1, "page_size": 24, "lang": "en", "taste": taste
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _spread_asserts(items, label):
    assert len(items) == 24, f"{label}: got {len(items)} items"
    makes = [it.get("manufacturer_en") or it.get("manufacturer") for it in items]
    models = [it.get("model_en") or it.get("model") for it in items]
    from collections import Counter
    mk_ct = Counter(makes)
    md_ct = Counter(models)
    top_make, top_n = mk_ct.most_common(1)[0]
    assert top_n <= 6, f"{label}: {top_make} appears {top_n} times of 24 (limit 6). Counter={mk_ct}"
    top_model, top_mn = md_ct.most_common(1)[0]
    assert top_mn <= 2, f"{label}: model {top_model} appears {top_mn} times (limit 2)"
    # No two consecutive same manufacturer
    for a, b in zip(makes, makes[1:]):
        assert a != b, f"{label}: adjacent same make {a}. Sequence={makes}"


def test_relevant_sort_mercedes_heavy_taste_is_spread():
    taste = {"makes": {"벤츠": 9}, "models": {"E-Class W213": 5},
             "fuels": {"디젤": 3}, "samples": [[30000, 50000, 2]]}
    data = _relevant(taste)
    _spread_asserts(data.get("items") or [], "mercedes-heavy")


def test_relevant_sort_hyundai_kia_taste_is_spread():
    taste = {"makes": {"현대": 9, "기아": 6}, "models": {"쏘렌토": 4},
             "fuels": {"가솔린": 3}, "samples": [[20000, 40000, 2]]}
    data = _relevant(taste)
    _spread_asserts(data.get("items") or [], "hyundai-kia")


def test_relevant_sort_empty_taste_fallback_popular():
    r = requests.post(f"{API}/search", json={
        "sort": "relevant", "page": 1, "page_size": 24, "lang": "en", "taste": None
    }, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    items = d.get("items") or []
    assert len(items) == 24, f"empty taste returned {len(items)} items"
    assert d.get("total", 0) > 0


def test_relevant_sort_pagination_deep():
    for page in (2, 30):
        r = requests.post(f"{API}/search", json={
            "sort": "relevant", "page": page, "page_size": 24, "lang": "en"
        }, timeout=30)
        assert r.status_code == 200, f"page {page}: {r.text[:200]}"


# --- tracking tail ----------------------------------------------------------

def test_tracking_delivery_plus_7_country_only():
    # 271191199 is the previously cached BoL reference used in prior iterations
    r = requests.get(f"{API}/tracking", params={"ref": "271191199", "by": "bol"}, timeout=40)
    if r.status_code != 200:
        pytest.skip(f"tracking endpoint {r.status_code}: {r.text[:120]}")
    d = r.json()
    if not d.get("found"):
        pytest.skip(f"271191199 not found: {d}")
    stones = d.get("milestones") or []
    dlv = next((s for s in stones if s.get("code") == "DLV"), None)
    assert dlv is not None, "no DLV (Delivery) milestone appended"
    # The owner dropped our invented customs forecast: delivery is dated straight off the
    # official arrival, so nothing of ours may sit in between.
    assert not [s for s in stones if s.get("code") == "CU" and s.get("estimated")], \
        "a customs forecast is back in the timeline"
    # Delivery MUST NOT show a street/city — location should be only country (2 chars) or empty
    dlv_loc = (dlv.get("location") or "").strip()
    dlv_country = (dlv.get("country") or "").strip()
    # country is 2-letter ISO OR empty. location must equal country OR be empty (never a street)
    assert len(dlv_country) <= 3, f"country too long: {dlv_country}"
    assert dlv_loc == dlv_country or dlv_loc == "", f"delivery location leaked: {dlv_loc!r}"
    # Container ID should not be echoed as reference when queried by=bol
    assert d.get("by") == "bol"
    assert d.get("reference") == "271191199"
    # +7 offset from the arrival stone
    from datetime import datetime, timedelta
    # find arrival (UV, else AV/VA/ARRI); if none, use the last carrier stone
    carrier = [s for s in stones if s.get("code") != "DLV"]
    arrival = (next((s for s in reversed(carrier) if s.get("code") == "UV"), None)
               or next((s for s in reversed(carrier)
                        if s.get("code") in ("AV", "VA", "ARRI")),
                       carrier[-1] if carrier else None))
    if arrival:
        base = datetime.fromisoformat(arrival["when"])
        dlv_when = datetime.fromisoformat(dlv["when"])
        # The offset is configuration (tracking.DELIVERY_DAYS), never copied in here: the
        # owner has changed it once already.
        assert (dlv_when - base) == timedelta(days=DELIVERY_DAYS), \
            f"DLV offset {(dlv_when - base)}"


# --- jsoncargo cache: no upstream call within TTL --------------------------

def test_jsoncargo_container_cache_no_new_upstream():
    q1 = requests.get(f"{API}/admin/tracking-quota", headers=ADMIN_TOKEN, timeout=15)
    if q1.status_code != 200:
        pytest.skip(f"quota endpoint {q1.status_code}")
    used0 = q1.json().get("used", 0)
    # Two lookups back to back; should be served from cache
    for _ in range(2):
        r = requests.get(f"{API}/tracking",
                         params={"ref": "MRSU5757040", "by": "container"}, timeout=40)
        assert r.status_code == 200
        time.sleep(0.3)
    q2 = requests.get(f"{API}/admin/tracking-quota", headers=ADMIN_TOKEN, timeout=15)
    used1 = q2.json().get("used", 0)
    assert used1 == used0, f"upstream calls made: used {used0} -> {used1}"
