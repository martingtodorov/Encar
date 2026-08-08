"""The hand-picked shelf a brand-new visitor sees, and the share preview for a pasted link.

A visitor with no taste profile at all must be met by the owner's own picks (source
"curated"), not by the crowd's most opened ads, and every pick must be measurable:
impressions when the shelf is built, clicks when a car from it is opened, deposits earned.
"""
import os

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "")}
RECO = f"{BASE_URL}/api/recommendations"
DEFAULTS = f"{BASE_URL}/api/admin/reco-defaults"


def test_anonymous_shelf_is_curated():
    r = requests.post(RECO, json={"limit": 12, "lang": "bg"}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("source") == "curated", data.get("source")
    assert data["items"], "the curated shelf came back empty"
    for it in data["items"]:
        assert "landed_eur" not in it
        assert it.get("sale_eur")


def test_curated_shelf_holds_the_owners_makes():
    """Every car on the shelf belongs to one of the configured picks."""
    conf = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60)
    assert conf.status_code == 200, conf.text
    picks = conf.json()["picks"]
    assert picks, "no picks configured"
    wanted = {(p["make"], p["model"]) for p in picks if p["available"]}
    items = requests.post(RECO, json={"limit": 12, "lang": "bg"}, timeout=60).json()["items"]
    for it in items:
        assert (it.get("manufacturer"), it.get("model")) in wanted, it.get("model")


def test_a_taste_profile_still_wins():
    """The picks are a FIRST impression only: the moment we know something, taste rules."""
    r = requests.post(RECO, json={"makes": {"BMW": 4.0}, "models": {"5시리즈": 5.0},
                                  "limit": 8, "lang": "bg"}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json().get("source") != "curated"


def test_admin_sees_stock_and_measurements_per_pick():
    r = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["enabled"], bool)
    for p in body["picks"]:
        for key in ("make", "model", "badge", "make_label", "model_label",
                    "available", "impressions", "clicks", "ctr", "deposits"):
            assert key in p, key
        assert p["make_label"] == p["make_label"].strip()
    # The seven the app ships with are all in stock; a pick with nothing behind it is a
    # configuration mistake the admin screen must show.
    assert sum(p["available"] for p in body["picks"]) > 0


def test_admin_endpoints_need_an_admin():
    assert requests.get(DEFAULTS, timeout=30).status_code == 401
    assert requests.put(DEFAULTS, json={"enabled": True, "picks": []}, timeout=30).status_code == 401


def test_click_is_counted_against_its_pick():
    items = requests.post(RECO, json={"limit": 12, "lang": "bg"}, timeout=60).json()["items"]
    car = items[0]
    before = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()["picks"]
    clicks = sum(p["clicks"] for p in before)
    r = requests.post(f"{BASE_URL}/api/reco/click", json={"id": car["id"]}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    after = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()["picks"]
    assert sum(p["clicks"] for p in after) == clicks + 1


def test_unknown_car_click_is_ignored():
    r = requests.post(f"{BASE_URL}/api/reco/click", json={"id": "does-not-exist"}, timeout=30)
    assert r.status_code == 200 and r.json()["ok"] is False


def test_switching_the_shelf_off_falls_back_to_popular():
    conf = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()
    keep = [{"make": p["make"], "model": p["model"], "badge": p["badge"]} for p in conf["picks"]]
    try:
        off = requests.put(DEFAULTS, headers=ADMIN_HEADERS,
                           json={"enabled": False, "picks": keep}, timeout=60)
        assert off.status_code == 200, off.text
        data = requests.post(RECO, json={"limit": 12, "lang": "bg"}, timeout=60).json()
        assert data.get("source") == "popular"
    finally:
        requests.post(f"{BASE_URL}/api/admin/reco-defaults/reset",
                      headers=ADMIN_HEADERS, timeout=60)
    back = requests.post(RECO, json={"limit": 12, "lang": "bg"}, timeout=60).json()
    assert back.get("source") == "curated"


# --- what a pasted car link previews as -------------------------------------------------
def test_share_preview_is_the_cars_first_photo():
    items = requests.post(RECO, json={"limit": 4, "lang": "bg"}, timeout=60).json()["items"]
    car = items[0]
    r = requests.get(f"{BASE_URL}/api/share/car/{car['id']}", params={"lang": "bg"}, timeout=60)
    assert r.status_code == 200, r.text
    html = r.text
    assert 'property="og:image"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert "1200" in html and "630" in html
    assert f"/bg/car/{car['id']}" in html
