"""Notification preferences, contact phone, push subscriptions and GDPR erasure."""
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


def _base():
    env = open("/app/frontend/.env").read()
    return re.search(r"REACT_APP_BACKEND_URL=(\S+)", env).group(1).rstrip("/") + "/api"


BASE = _base()
PASSWORD = "SecurityTest2026!"


def account():
    s = requests.Session()
    email = f"notif-{int(time.time() * 1000)}@example.com"
    r = s.post(f"{BASE}/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return s, email


def test_defaults_and_toggles():
    s, _ = account()
    data = s.get(f"{BASE}/notifications").json()
    # Email on by default (they asked for it by registering), push off until a device opts in.
    assert data["prefs"]["email"]["enabled"] is True
    assert data["prefs"]["push"]["enabled"] is False
    assert data["devices"] == 0
    # "enquiry" and "deposit" are the OPERATOR's alerts: a buyer carries the switches but
    # never a subscription for them, because they are only ever sent to is_admin accounts.
    assert set(data["events"]) == {"saved_search", "price_drop", "shipment", "enquiry",
                                   "deposit"}

    prefs = data["prefs"]
    prefs["email"]["price_drop"] = False
    prefs["push"]["shipment"] = False
    saved = s.put(f"{BASE}/notifications", json=prefs).json()["prefs"]
    assert saved["email"]["price_drop"] is False
    assert saved["push"]["shipment"] is False
    assert s.get(f"{BASE}/notifications").json()["prefs"]["email"]["price_drop"] is False


def test_phone_is_stored_and_trimmed():
    s, _ = account()
    out = s.put(f"{BASE}/phone", json={"phone": "  +359 88   123 4567 "}).json()
    assert out["phone"] == "+359 88 123 4567"
    assert s.get(f"{BASE}/notifications").json()["phone"] == "+359 88 123 4567"


def test_push_key_is_public_and_subscriptions_are_per_endpoint():
    key = requests.get(f"{BASE}/push/key").json()["key"]
    assert key and len(key) > 80
    assert key == os.environ["VAPID_PUBLIC_KEY"]
    # The private half must never be reachable.
    assert os.environ["VAPID_PRIVATE_KEY"] not in requests.get(f"{BASE}/push/key").text

    s, _ = account()
    endpoint = "https://fcm.googleapis.com/fcm/send/fake-endpoint-for-tests"
    sub = {"endpoint": endpoint, "keys": {"p256dh": "BFakeKeyForTests", "auth": "fakeAuth"}}

    assert s.post(f"{BASE}/push/subscribe", json=sub).status_code == 200
    # Subscribing turns the channel on, and re-subscribing must not multiply the device.
    assert s.post(f"{BASE}/push/subscribe", json=sub).status_code == 200
    data = s.get(f"{BASE}/notifications").json()
    assert data["devices"] == 1
    assert data["prefs"]["push"]["enabled"] is True

    # An incomplete subscription is refused rather than stored half-formed.
    assert s.post(f"{BASE}/push/subscribe",
                  json={"endpoint": endpoint, "keys": {}}).status_code == 400

    assert s.post(f"{BASE}/push/unsubscribe", json=sub).json()["devices"] == 0
    assert s.get(f"{BASE}/notifications").json()["prefs"]["push"]["enabled"] is False

    assert requests.get(f"{BASE}/notifications").status_code == 401


def test_gdpr_delete_needs_password_and_the_word():
    s, email = account()
    s.put(f"{BASE}/phone", json={"phone": "+359881234567"})

    # Wrong confirmation word, then wrong password: both must refuse.
    assert s.delete(f"{BASE}/account",
                    json={"password": PASSWORD, "confirm": "yes"}).status_code == 400
    assert s.delete(f"{BASE}/account",
                    json={"password": "nope", "confirm": "DELETE"}).status_code == 401

    gone = s.delete(f"{BASE}/account", json={"password": PASSWORD, "confirm": "изтрий"})
    assert gone.status_code == 200, gone.text

    # The account is really gone: the old session is dead and the password no longer works.
    assert s.get(f"{BASE}/auth/me").json().get("user") is None
    fresh = requests.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})
    assert fresh.status_code == 401
