"""Answer one question honestly: what happens to the call button INSIDE working hours?

Forces the office open for today, checks the public endpoint, then puts the schedule back
exactly as it was. Nothing is left changed.
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = os.environ["PUBLIC_SITE_URL"].rstrip("/")
ADMIN = {"x-admin-token": os.environ["ADMIN_TOKEN"]}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def session():
    s = requests.Session()
    s.headers["X-CSRF-Token"] = s.get(f"{API}/api/csrf", timeout=30).json()["token"]
    s.headers.update(ADMIN)
    return s


def main():
    s = session()
    conf = s.get(f"{API}/api/admin/call-button", timeout=30).json()
    keep = {d: conf["hours"][d] for d in DAYS}
    base = {"enabled": True, "phone": conf["phone"], "phone_label": conf["phone_label"]}
    print("before      : open_now =", conf["open_now"], "at", conf["local_time"])

    try:
        wide = {**keep, conf["day"]: {"open": "00:00", "close": "23:59", "closed": False}}
        r = s.put(f"{API}/api/admin/call-button", json={**base, "hours": wide}, timeout=30)
        r.raise_for_status()
        now = requests.get(f"{API}/api/call-button", timeout=30).json()
        print("forced open : open_now =", now["open_now"], "at", now["local_time"])
        assert now["open_now"] is True, "the office would not open"

        # Inside hours the button dials straight away, so the call-back form is unreachable.
        # A call-back BOOKED for a working-hour slot is still accepted by the API (that is what
        # every request is), which is what the next line proves.
        book = s.post(f"{API}/api/callback", timeout=30, json={
            "phone": "+359880009911", "email": "inhours.check@example.com",
            "day": now["local_date"], "time": "23:30", "lang": "bg"})
        print("api accepts a slot inside today's window:", book.status_code,
              book.json() if book.status_code != 200 else book.json()["when"])
        if book.status_code == 200:
            requests.delete(f"{API}/api/admin/callbacks/{book.json()['id']}",
                            headers=ADMIN, timeout=30)
            print("             (test request deleted again)")
    finally:
        s.put(f"{API}/api/admin/call-button", json={**base, "hours": keep}, timeout=30)
        back = requests.get(f"{API}/api/call-button", timeout=30).json()
        print("restored    : open_now =", back["open_now"], "| hours match:",
              back["hours"] == keep)


if __name__ == "__main__":
    sys.exit(main())
