"""The "Call us" button: the number, the owner's opening hours, and who may change them."""
import os

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_HEADERS = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "")}
PUBLIC = f"{BASE_URL}/api/call-button"
ADMIN = f"{BASE_URL}/api/admin/call-button"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def test_public_shape_and_defaults():
    r = requests.get(PUBLIC, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["phone"].startswith("+359")
    assert d["timezone"] == "Europe/Sofia"
    assert isinstance(d["open_now"], bool)
    assert d["day"] in DAYS
    assert set(d["hours"]) == set(DAYS)
    for day in DAYS:
        assert set(d["hours"][day]) == {"open", "close", "closed"}


def test_open_now_agrees_with_the_hours_it_publishes():
    d = requests.get(PUBLIC, timeout=30).json()
    today = d["hours"][d["day"]]
    if today["closed"] or not today["open"] or not today["close"]:
        assert d["open_now"] is False
    else:
        inside = today["open"] <= d["local_time"] < today["close"]
        assert d["open_now"] is inside, (d["local_time"], today)


def test_only_an_admin_can_change_it():
    assert requests.get(ADMIN, timeout=30).status_code == 401
    assert requests.put(ADMIN, json={"enabled": True, "phone": "+359886717074"},
                        timeout=30).status_code == 401


def test_a_saved_window_decides_open_and_closed():
    """Set today to a window that cannot be open, then one that cannot be shut."""
    before = requests.get(ADMIN, headers=ADMIN_HEADERS, timeout=30)
    assert before.status_code == 200, before.text
    conf = before.json()
    day = conf["day"]
    keep = {d: conf["hours"][d] for d in DAYS}
    try:
        shut = {**keep, day: {"open": "", "close": "", "closed": True}}
        r = requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                         json={"enabled": True, "phone": conf["phone"],
                               "phone_label": conf["phone_label"], "hours": shut})
        assert r.status_code == 200, r.text
        assert requests.get(PUBLIC, timeout=30).json()["open_now"] is False

        allday = {**keep, day: {"open": "00:00", "close": "23:59", "closed": False}}
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                     json={"enabled": True, "phone": conf["phone"],
                           "phone_label": conf["phone_label"], "hours": allday})
        assert requests.get(PUBLIC, timeout=30).json()["open_now"] is True

        # Switched off, the button is not rendered at all.
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                     json={"enabled": False, "phone": conf["phone"],
                           "phone_label": conf["phone_label"], "hours": allday})
        assert requests.get(PUBLIC, timeout=30).json()["enabled"] is False
    finally:
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                     json={"enabled": True, "phone": conf["phone"],
                           "phone_label": conf["phone_label"], "hours": keep})
    back = requests.get(PUBLIC, timeout=30).json()
    assert back["enabled"] is True and back["hours"] == keep


def test_a_phone_number_is_required_and_cleaned():
    conf = requests.get(ADMIN, headers=ADMIN_HEADERS, timeout=30).json()
    keep = {"enabled": True, "phone": conf["phone"], "phone_label": conf["phone_label"],
            "hours": {d: conf["hours"][d] for d in DAYS}}
    bad = requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                       json={**keep, "phone": "not a number"})
    assert bad.status_code == 400, bad.text
    try:
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                     json={**keep, "phone": "+359 88 671 7074", "phone_label": "+359 88 6717074"})
        d = requests.get(PUBLIC, timeout=30).json()
        assert d["phone"] == "+359886717074"          # dialled, so no spaces
        assert d["phone_label"] == "+359 88 6717074"  # read by a human
    finally:
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30, json=keep)


def test_a_broken_time_never_leaves_a_half_open_window():
    conf = requests.get(ADMIN, headers=ADMIN_HEADERS, timeout=30).json()
    keep = {"enabled": True, "phone": conf["phone"], "phone_label": conf["phone_label"],
            "hours": {d: conf["hours"][d] for d in DAYS}}
    try:
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30,
                     json={**keep, "hours": {**keep["hours"],
                                             "mon": {"open": "9", "close": "99:99",
                                                     "closed": False}}})
        mon = requests.get(PUBLIC, timeout=30).json()["hours"]["mon"]
        assert mon == {"open": "", "close": "", "closed": False}
    finally:
        requests.put(ADMIN, headers=ADMIN_HEADERS, timeout=30, json=keep)
