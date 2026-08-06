"""Second factor, device list and reservation deposit, end to end against the live app."""
import os
import re
import time
from datetime import datetime, timezone

import pyotp
import requests

def _base():
    """The public HTTPS origin: session cookies are Secure and never ride over plain http."""
    if os.environ.get("E2E_BASE"):
        return os.environ["E2E_BASE"].rstrip("/") + "/api"
    env = open("/app/frontend/.env").read()
    return re.search(r"REACT_APP_BACKEND_URL=(\S+)", env).group(1).rstrip("/") + "/api"


BASE = _base()
EMAIL = f"sec-{int(time.time())}@example.com"
PASSWORD = "SecurityTest2026!"


def session():
    s = requests.Session()
    s.headers["user-agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                              "Version/17.0 Safari/605.1.15")
    return s


def next_window_code(secret):
    """A code from the FOLLOWING window: the one that enabled 2FA is legitimately spent."""
    totp = pyotp.TOTP(secret)
    start = totp.timecode(datetime.now(timezone.utc))
    while totp.timecode(datetime.now(timezone.utc)) == start:
        time.sleep(1)
    return totp.now()


def test_two_factor_and_sessions():
    s = session()
    r = s.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD,
                                              "name": "Security Test"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["twofa"] is False

    setup = s.post(f"{BASE}/auth/2fa/setup").json()
    assert setup["qr_data_url"].startswith("data:image/png;base64,")
    secret = setup["manual_key"]
    assert f"otpauth://totp/Encar:{EMAIL}" in setup["otpauth_uri"].replace("%40", "@")

    # A wrong code must not turn it on.
    assert s.post(f"{BASE}/auth/2fa/enable", json={"code": "000000"}).status_code == 400

    totp = pyotp.TOTP(secret)
    enabled = s.post(f"{BASE}/auth/2fa/enable", json={"code": totp.now()})
    assert enabled.status_code == 200, enabled.text
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10
    assert s.get(f"{BASE}/auth/me").json()["user"]["twofa"] is True

    # Password alone must no longer produce a session.
    fresh = session()
    step1 = fresh.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()
    assert step1["mfa_required"] is True and step1["pending_id"]
    assert fresh.get(f"{BASE}/auth/me").json().get("user") is None

    assert fresh.post(f"{BASE}/auth/2fa/login", json={
        "pending_id": step1["pending_id"], "code": "111111"}).status_code == 401
    done = fresh.post(f"{BASE}/auth/2fa/login", json={
        "pending_id": step1["pending_id"], "code": next_window_code(secret)})
    assert done.status_code == 200, done.text
    assert done.json()["user"]["email"] == EMAIL

    # A recovery code works once and only once.
    third = session()
    pending = third.post(f"{BASE}/auth/login",
                        json={"email": EMAIL, "password": PASSWORD}).json()["pending_id"]
    body = {"pending_id": pending, "code": codes[0], "recovery": True}
    assert third.post(f"{BASE}/auth/2fa/login", json=body).status_code == 200
    again = session()
    pending2 = again.post(f"{BASE}/auth/login",
                         json={"email": EMAIL, "password": PASSWORD}).json()["pending_id"]
    spent = again.post(f"{BASE}/auth/2fa/login",
                      json={"pending_id": pending2, "code": codes[0], "recovery": True})
    assert spent.status_code == 401, "a spent recovery code was accepted twice"

    # Three devices are signed in; the list knows which one is asking.
    rows = s.get(f"{BASE}/auth/sessions").json()["items"]
    assert len(rows) >= 3
    mine = [r for r in rows if r["current"]]
    assert len(mine) == 1
    assert mine[0]["label"] == "Safari on macOS"

    other = next(r for r in rows if not r["current"])
    assert s.delete(f"{BASE}/auth/sessions/{other['id']}").status_code == 200
    assert s.delete(f"{BASE}/auth/sessions/{mine[0]['id']}").status_code == 400

    cleared = s.post(f"{BASE}/auth/sessions/revoke-others").json()
    assert cleared["signed_out"] >= 1
    assert len(s.get(f"{BASE}/auth/sessions").json()["items"]) == 1
    assert s.get(f"{BASE}/auth/me").json()["user"]["email"] == EMAIL
    # The devices that were cut off really are out.
    assert fresh.get(f"{BASE}/auth/me").json().get("user") is None

    # Turning it off needs the password.
    assert s.post(f"{BASE}/auth/2fa/disable", json={"password": "wrong"}).status_code == 401
    assert s.post(f"{BASE}/auth/2fa/disable", json={"password": PASSWORD}).status_code == 200
    assert s.get(f"{BASE}/auth/me").json()["user"]["twofa"] is False


def test_deposit_is_ten_percent_with_no_floor():
    s = session()
    assert s.post(f"{BASE}/auth/register", json={"email": f"dep-{EMAIL}",
                                                 "password": PASSWORD}).status_code == 200
    rows = s.post(f"{BASE}/search", json={"page": 1, "page_size": 40,
                                          "lang": "en"}).json()["items"]
    cheap = min(rows, key=lambda r: r["sale_eur"])
    dear = max(rows, key=lambda r: r["sale_eur"])

    for car in (cheap, dear):
        expected = round(car["sale_eur"] * 0.10, 2)
        quote = s.get(f"{BASE}/deposit/car/{car['id']}").json()
        assert quote["amount_eur"] == expected, (car["id"], quote)
        assert quote["minimum_eur"] == 0.0 and quote["rate"] == 0.10

    started = s.post(f"{BASE}/deposit/checkout",
                    json={"car_id": dear["id"], "origin_url": "https://example.com/en"})
    assert started.status_code == 200, started.text
    out = started.json()
    assert out["amount_eur"] == round(dear["sale_eur"] * 0.10, 2)
    assert re.match(r"^https://checkout\.stripe\.com/", out["checkout_url"]), out

    status = s.get(f"{BASE}/deposit/status/{out['session_id']}").json()
    assert status["payment_status"] == "pending"
    assert s.get(f"{BASE}/deposit/mine").json()["items"] == []

    # Signing out must close the till.
    s.post(f"{BASE}/auth/logout")
    assert s.post(f"{BASE}/deposit/checkout",
                 json={"car_id": dear["id"],
                       "origin_url": "https://example.com/en"}).status_code == 401


def test_admin_customer_search():
    token = {"x-admin-token": os.environ.get("ADMIN_TOKEN", "")}
    rows = requests.get(f"{BASE}/admin/customers", params={"q": "admin"},
                        headers=token).json()["items"]
    assert any(r["email"] == "admin@encarskin.com" for r in rows), rows
    assert requests.get(f"{BASE}/admin/customers").status_code in (401, 403)
