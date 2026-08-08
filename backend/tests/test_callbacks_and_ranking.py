"""Call-back requests, and the shelf ordering itself by results.

A call-back booked for a time nobody works never happens, so the slot is re-checked on the
server. And a pick must not win the front row on luck: below the impressions threshold it is
not judged at all.
"""
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "")}
CALLBACK = f"{BASE_URL}/api/callback"
ADMIN_LIST = f"{BASE_URL}/api/admin/callbacks"
CALL_INFO = f"{BASE_URL}/api/call-button"
DEFAULTS = f"{BASE_URL}/api/admin/reco-defaults"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _session():
    """POST needs the CSRF pair the browser would carry."""
    s = requests.Session()
    token = s.get(f"{BASE_URL}/api/csrf", timeout=30).json()["token"]
    s.headers["X-CSRF-Token"] = token
    return s


def _next_open_slot(info):
    """The first slot the office is actually open for, from its own clock."""
    today = datetime.strptime(info["local_date"], "%Y-%m-%d")
    for step in range(1, 9):
        day = today + timedelta(days=step)
        row = info["hours"][DAYS[day.weekday()]]
        if not row["closed"] and row["open"] and row["close"]:
            return day.strftime("%Y-%m-%d"), row["open"], row
    raise AssertionError("the office is never open")


def _closed_day(info):
    today = datetime.strptime(info["local_date"], "%Y-%m-%d")
    for step in range(1, 9):
        day = today + timedelta(days=step)
        row = info["hours"][DAYS[day.weekday()]]
        if row["closed"] or not row["open"]:
            return day.strftime("%Y-%m-%d")
    return ""


def test_a_callback_is_booked_and_reaches_the_admin_list():
    s = _session()
    info = s.get(CALL_INFO, timeout=30).json()
    day, at, _ = _next_open_slot(info)
    r = s.post(CALLBACK, timeout=30, json={
        "phone": "+359 88 000 1122", "email": "callback.test@example.com", "name": "Test Buyer",
        "day": day, "time": at, "listing_id": "42341529", "car_title": "Test car", "lang": "bg"})
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["ok"] is True and made["when"] == f"{day} {at}"

    rows = requests.get(ADMIN_LIST, headers=ADMIN_HEADERS, timeout=30).json()
    mine = next((c for c in rows["items"] if c["id"] == made["id"]), None)
    assert mine, "the request is not in the admin list"
    assert mine["status"] == "new"
    assert mine["when_label"] == f"{day} {at}"
    assert mine["email"] == "callback.test@example.com"
    assert re.sub(r"\D", "", mine["phone"]).endswith("880001122")

    # new -> called -> closed, and gone when deleted
    for status in ("called", "closed"):
        p = requests.patch(f"{ADMIN_LIST}/{made['id']}", headers=ADMIN_HEADERS,
                           json={"status": status}, timeout=30)
        assert p.status_code == 200, p.text
        assert p.json()["status"] == status
    bad = requests.patch(f"{ADMIN_LIST}/{made['id']}", headers=ADMIN_HEADERS,
                         json={"status": "whenever"}, timeout=30)
    assert bad.status_code == 400
    d = requests.delete(f"{ADMIN_LIST}/{made['id']}", headers=ADMIN_HEADERS, timeout=30)
    assert d.status_code == 200
    assert requests.delete(f"{ADMIN_LIST}/{made['id']}", headers=ADMIN_HEADERS,
                           timeout=30).status_code == 404


def test_a_slot_nobody_works_is_refused():
    s = _session()
    info = s.get(CALL_INFO, timeout=30).json()
    day, at, row = _next_open_slot(info)
    base = {"phone": "+359880001122", "email": "callback.test@example.com"}

    late = s.post(CALLBACK, json={**base, "day": day, "time": "23:30"}, timeout=30)
    assert late.status_code == 400 and row["close"] in late.json()["detail"]

    shut = _closed_day(info)
    if shut:
        r = s.post(CALLBACK, json={**base, "day": shut, "time": at}, timeout=30)
        assert r.status_code == 400 and "closed" in r.json()["detail"]

    gone = datetime.now(ZoneInfo(info["timezone"])) - timedelta(days=3)
    past = s.post(CALLBACK, json={**base, "day": gone.strftime("%Y-%m-%d"), "time": at},
                  timeout=30)
    assert past.status_code == 400, past.text

    assert s.post(CALLBACK, json={"day": day, "time": at, "email": "a@b.com",
                                  "phone": "12"}, timeout=30).status_code == 400
    assert s.post(CALLBACK, json={"day": day, "time": at, "phone": "+359880001122",
                                  "email": "not-an-email"}, timeout=30).status_code == 400
    assert s.post(CALLBACK, json={**base, "day": "tomorrow", "time": at},
                  timeout=30).status_code == 400


def test_admin_callback_list_needs_an_admin():
    assert requests.get(ADMIN_LIST, timeout=30).status_code == 401
    assert requests.delete(f"{ADMIN_LIST}/anything", timeout=30).status_code == 401


# --- the shelf ordering itself --------------------------------------------------------
# One test, deliberately: these assertions all mutate or read the SAME global setting, and as
# separate tests xdist ran them in parallel and they read each other's half-applied state.
def test_the_order_follows_the_score_and_luck_cannot_win_the_front_row():
    body = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()
    assert body["auto_rank"] is True
    assert body["min_impressions"] >= 1
    judged = [p for p in body["picks"] if p["judged"]]
    for p in judged:
        assert p["impressions"] >= body["min_impressions"]
        assert abs(p["score"] - (p["deposits"] * 10 + p["ctr"])) < 0.6, p
    # Ranks are a permutation, judged picks all outrank unjudged ones, and among the judged
    # the order is the score.
    ranks = sorted(p["rank"] for p in body["picks"])
    assert ranks == list(range(1, len(body["picks"]) + 1))
    if judged and len(judged) < len(body["picks"]):
        assert max(p["rank"] for p in judged) < min(
            p["rank"] for p in body["picks"] if not p["judged"])
    ordered = sorted(judged, key=lambda p: p["rank"])
    for a, b in zip(ordered, ordered[1:]):
        assert a["score"] >= b["score"], (a, b)

    # With the threshold above every pick's impressions nothing is judged at all, and the
    # owner's own order stands — which is exactly what protects a brand-new pick.
    keep = [{"make": p["make"], "model": p["model"], "badge": p["badge"]} for p in body["picks"]]
    try:
        r = requests.put(DEFAULTS, headers=ADMIN_HEADERS, timeout=60,
                         json={"enabled": True, "auto_rank": True,
                               "min_impressions": 10_000_000, "picks": keep})
        assert r.status_code == 200, r.text
        after = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()
        assert all(p["judged"] is False and p["score"] is None for p in after["picks"])
        assert [p["key"] for p in sorted(after["picks"], key=lambda p: p["rank"])] == \
               [p["key"] for p in after["picks"]]

        off = requests.put(DEFAULTS, headers=ADMIN_HEADERS, timeout=60,
                           json={"enabled": True, "auto_rank": False,
                                 "min_impressions": 1, "picks": keep})
        assert off.status_code == 200, off.text
        plain = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()
        assert plain["auto_rank"] is False
        assert [p["key"] for p in sorted(plain["picks"], key=lambda p: p["rank"])] == \
               [p["key"] for p in plain["picks"]]
    finally:
        requests.post(f"{BASE_URL}/api/admin/reco-defaults/reset",
                      headers=ADMIN_HEADERS, timeout=60)
    back = requests.get(DEFAULTS, headers=ADMIN_HEADERS, timeout=60).json()
    assert back["auto_rank"] is True and back["min_impressions"] == 50


def test_the_shelf_still_fills_up_under_auto_rank():
    s = _session()
    data = s.post(f"{BASE_URL}/api/recommendations", json={"limit": 12, "lang": "bg"},
                  timeout=60).json()
    assert data["source"] == "curated"
    assert len(data["items"]) == 12
    assert len({i["id"] for i in data["items"]}) == 12
