"""Asking everybody again, and carrying a guest's decision onto a new account.

Two facts from the live database drove this: 500 accounts, ZERO with a consent record — the
guest decision never left the visitor's own machine, and nobody had been asked since the
categories were introduced.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"x-admin-token": os.environ["ADMIN_TOKEN"]}
PASSWORD = "ConsentTest2026!"

# The re-ask stamp is ONE row for the whole site, so these tests cannot share a run with each
# other across xdist workers. `--dist loadscope` already pins a module to one worker; the
# group marker keeps that true if anybody runs the file with a different distribution.
pytestmark = pytest.mark.xdist_group("consent_reask")


@pytest.fixture(autouse=True)
def no_reask():
    """Never leave the whole site asking every visitor again because a test ran."""
    yield
    requests.post(f"{BASE}/api/admin/consent/reask", headers=ADMIN, timeout=30,
                  json={"on": False})


def _account():
    s = requests.Session()
    email = f"consent-{uuid.uuid4().hex[:10]}@example.com"
    r = s.post(f"{BASE}/api/auth/register", timeout=30,
               json={"email": email, "password": PASSWORD, "name": "Consent Test",
                     "lang": "bg"})
    assert r.status_code == 200, r.text[:300]
    return s, email, r.json()["user"]


def _iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def test_reask_is_public_and_switchable():
    requests.post(f"{BASE}/api/admin/consent/reask", headers=ADMIN, timeout=30,
                  json={"on": False})
    before = requests.get(f"{BASE}/api/consent/policy", timeout=30).json()
    assert before["reask_at"] == ""

    on = requests.post(f"{BASE}/api/admin/consent/reask", headers=ADMIN, timeout=30,
                       json={"on": True, "note": "нови категории"})
    assert on.status_code == 200
    stamp = on.json()["reask_at"]
    assert stamp

    # Every visitor's browser can read it without signing in — that is how the dialog knows.
    public = requests.get(f"{BASE}/api/consent/policy", timeout=30).json()
    assert public["reask_at"] == stamp and public["note"] == "нови категории"

    off = requests.post(f"{BASE}/api/admin/consent/reask", headers=ADMIN, timeout=30,
                        json={"on": False})
    assert off.status_code == 200 and off.json()["reask_at"] == ""
    assert requests.get(f"{BASE}/api/consent/policy", timeout=30).json()["reask_at"] == ""


def test_reask_needs_an_admin():
    r = requests.post(f"{BASE}/api/admin/consent/reask", timeout=30, json={"on": True})
    assert r.status_code == 401


def test_a_decision_older_than_the_reask_is_waiting():
    s, email, _ = _account()
    assert s.post(f"{BASE}/api/auth/consent", timeout=30, json={
        "v": "2026-06-08", "ts": _iso(days=-2), "cats": {"statistics": True},
        "source": "pre_account_cookie"}).json()["stored"] is True

    requests.post(f"{BASE}/api/admin/consent/reask", headers=ADMIN, timeout=30,
                  json={"on": True})
    row = _row(email)
    assert row["stale"] is True                 # asked again, has not answered yet

    # Answering now clears it: the new decision is stamped after the request.
    assert s.post(f"{BASE}/api/auth/consent", timeout=30, json={
        "v": "2026-06-08", "ts": _iso(), "cats": {"statistics": True}}).json()["stored"] is True
    assert _row(email)["stale"] is False


def _row(email):
    log = requests.get(f"{BASE}/api/admin/consent", headers=ADMIN, timeout=30).json()
    hit = [r for r in log["items"] if r["email"] == email]
    assert hit, f"{email} not in the consent log"
    return hit[0]


def test_guest_decision_is_carried_onto_a_fresh_account():
    s, email, user = _account()
    assert not user.get("consent_record")       # a new account starts with nothing

    ts = _iso(days=-3)                          # decided as a guest, three days ago
    r = s.post(f"{BASE}/api/auth/consent", timeout=30, json={
        "v": "2026-06-08", "ts": ts,
        "cats": {"personalisation": True, "statistics": True},
        "source": "pre_account_cookie"})
    assert r.status_code == 200 and r.json()["stored"] is True

    me = s.get(f"{BASE}/api/auth/me", timeout=30).json()["user"]
    rec = me["consent_record"]
    assert rec["ts"] == ts                      # the buyer's own moment, not ours
    assert rec["cats"] == {"personalisation": True, "statistics": True}
    assert rec["source"] == "pre_account_cookie"
    assert rec["recorded_at"]                   # ... plus when WE saw it
    assert me["consent"] == "all"

    row = _row(email)
    assert row["carried"] is True and sorted(row["categories"]) == [
        "personalisation", "statistics"]


def test_an_older_carried_decision_never_overwrites_a_newer_one():
    s, _, _ = _account()
    fresh = _iso()
    s.post(f"{BASE}/api/auth/consent", timeout=30,
           json={"v": "2026-06-08", "ts": fresh, "cats": {"statistics": True}})

    stale = s.post(f"{BASE}/api/auth/consent", timeout=30, json={
        "v": "2026-06-08", "ts": _iso(days=-40),
        "cats": {"personalisation": True, "statistics": True},
        "source": "pre_account_cookie"})
    assert stale.status_code == 200 and stale.json()["stored"] is False

    rec = s.get(f"{BASE}/api/auth/me", timeout=30).json()["user"]["consent_record"]
    assert rec["ts"] == fresh and rec["cats"] == {"statistics": True}


def test_an_empty_decision_is_refused_and_needs_a_session():
    s, _, _ = _account()
    assert s.post(f"{BASE}/api/auth/consent", timeout=30,
                  json={"v": "2026-06-08", "ts": _iso(), "cats": {}}).status_code == 400
    assert requests.post(f"{BASE}/api/auth/consent", timeout=30,
                         json={"v": "x", "ts": _iso(),
                               "cats": {"statistics": True}}).status_code == 401


def test_a_refusal_is_carried_too():
    """Refusing everything optional is a decision, and it must travel with the buyer."""
    s, email, _ = _account()
    r = s.post(f"{BASE}/api/auth/consent", timeout=30, json={
        "v": "2026-06-08", "ts": _iso(days=-1),
        "cats": {"personalisation": False, "statistics": False},
        "source": "pre_account_cookie"})
    assert r.json()["stored"] is True
    me = s.get(f"{BASE}/api/auth/me", timeout=30).json()["user"]
    assert me["consent"] == "necessary"
    row = _row(email)
    assert row["has_record"] is True and row["categories"] == []
