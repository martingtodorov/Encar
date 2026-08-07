"""The mobile.bg posting queue: the contract an OUTSIDE bot depends on.

This one matters more than most. The bot is a separate program with its own deploy: if the
shape of `{"pending": [...]}` or the meaning of a status ever drifts, nothing here breaks and
nobody notices - cars simply stop being posted. So the shapes are asserted literally.
"""
import os
import uuid

import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOKEN = (os.environ.get("ENCAREUROPE_API_TOKEN") or "").strip()
ADMIN = {"x-admin-token": (os.environ.get("ADMIN_TOKEN") or "").strip()}
BOT = {"Authorization": f"Bearer {TOKEN}"}


def _a_real_car():
    r = requests.post(f"{BASE}/api/search", json={"page": 1}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    items = r.json().get("items") or []
    assert items, "catalogue is empty"
    return items[0].get("car_id") or items[0].get("id")


@pytest.fixture(scope="module")
def car():
    if not TOKEN:
        pytest.skip("ENCAREUROPE_API_TOKEN is not set")
    cid = _a_real_car()
    yield cid
    requests.post(f"{BASE}/api/post-queue/{cid}", headers=BOT, timeout=20,
                  json={"status": "posted", "mobilebg_url": "", "note": ""})


# ── the token is the whole door ──────────────────────────────────────────────
def test_queue_requires_a_bearer_token():
    assert requests.get(f"{BASE}/api/post-queue", timeout=20).status_code == 401
    assert requests.get(f"{BASE}/api/post-queue",
                        headers={"Authorization": "Bearer wrong"},
                        timeout=20).status_code == 401
    # A wrong token on the report endpoint must not write anything either.
    r = requests.post(f"{BASE}/api/post-queue/42174890",
                      headers={"Authorization": "Bearer wrong"},
                      json={"status": "posted"}, timeout=20)
    assert r.status_code == 401


def test_admin_endpoints_are_not_public(car):
    assert requests.post(f"{BASE}/api/admin/post-queue/{car}", timeout=20).status_code == 401
    assert requests.get(f"{BASE}/api/admin/post-queue/{car}", timeout=20).status_code == 401


# ── the flow the bot actually runs ───────────────────────────────────────────
def test_queue_then_report_round_trip(car):
    if not TOKEN:
        pytest.skip("ENCAREUROPE_API_TOKEN is not set")

    # 1. the operator queues the car
    r = requests.post(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN, timeout=30)
    assert r.status_code == 200, r.text[:300]
    item = r.json()["item"]
    assert item["encar_id"] == car
    assert item["status"] == "pending"

    # 2. the bot polls, and the shape is EXACTLY {"pending": [ids]}
    r = requests.get(f"{BASE}/api/post-queue", headers=BOT, timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert list(body.keys()) == ["pending"], body
    assert car in body["pending"], body
    assert all(isinstance(x, str) for x in body["pending"])

    # 3. the bot reports success
    url = f"https://www.mobile.bg/obiava-test-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE}/api/post-queue/{car}", headers=BOT, timeout=30,
                      json={"status": "posted", "mobilebg_url": url, "note": ""})
    assert r.status_code == 200, r.text[:300]
    assert r.json() == {"ok": True}

    # 4. it leaves the queue, and the operator sees the link
    body = requests.get(f"{BASE}/api/post-queue", headers=BOT, timeout=30).json()
    assert car not in body["pending"]
    row = requests.get(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN,
                       timeout=20).json()["item"]
    assert row["status"] == "posted"
    assert row["mobilebg_url"] == url


def test_failure_is_reported_with_a_reason(car):
    if not TOKEN:
        pytest.skip("ENCAREUROPE_API_TOKEN is not set")
    requests.post(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN, timeout=30)
    r = requests.post(f"{BASE}/api/post-queue/{car}", headers=BOT, timeout=30,
                      json={"status": "failed", "note": "mobile.bg rejected the photos"})
    assert r.status_code == 200
    row = requests.get(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN,
                       timeout=20).json()["item"]
    assert row["status"] == "failed"
    assert row["note"] == "mobile.bg rejected the photos"
    # A failed car is NOT retried in a loop: the operator decides to send it again.
    body = requests.get(f"{BASE}/api/post-queue", headers=BOT, timeout=30).json()
    assert car not in body["pending"]


def test_queueing_twice_keeps_one_row(car):
    if not TOKEN:
        pytest.skip("ENCAREUROPE_API_TOKEN is not set")
    for _ in range(3):
        requests.post(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN, timeout=30)
    body = requests.get(f"{BASE}/api/post-queue", headers=BOT, timeout=30).json()
    assert body["pending"].count(car) == 1, body
    # Re-queuing clears the previous result, so a stale mobile.bg link cannot linger.
    row = requests.get(f"{BASE}/api/admin/post-queue/{car}", headers=ADMIN,
                       timeout=20).json()["item"]
    assert row["status"] == "pending"
    assert row["mobilebg_url"] == ""
    assert row["note"] == ""


def test_unknown_car_and_bad_status_are_refused(car):
    if not TOKEN:
        pytest.skip("ENCAREUROPE_API_TOKEN is not set")
    r = requests.post(f"{BASE}/api/post-queue/no-such-car-{uuid.uuid4().hex[:6]}",
                      headers=BOT, json={"status": "posted"}, timeout=20)
    assert r.status_code == 404, r.text[:200]
    r = requests.post(f"{BASE}/api/post-queue/{car}", headers=BOT,
                      json={"status": "sort-of-posted"}, timeout=20)
    assert r.status_code == 400, r.text[:200]
    r = requests.post(f"{BASE}/api/admin/post-queue/definitely-not-a-car",
                      headers=ADMIN, timeout=20)
    assert r.status_code == 404, r.text[:200]
