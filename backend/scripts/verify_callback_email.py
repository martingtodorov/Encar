"""Prove a call-back really leaves the building: run it and read the Resend ids.

`_send` returning None means the letter was DROPPED (no API key, no recipient, or the shared
sender refused it) — which is exactly the silent failure the owner asked us to rule out. A real
id means Resend accepted it.

    cd /app/backend && python3 scripts/verify_callback_email.py
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import mailer  # noqa: E402  (needs the env loaded first)

DOC = {
    "_id": "verify-callback",
    "when_label": "2026-08-10 09:00",
    "timezone": "Europe/Sofia",
    "phone": "+359 88 6717074",
    "name": "Проверка на писмото",
    "email": os.environ.get("ADMIN_NOTIFY_EMAIL", ""),
    "car_title": "Hyundai Santa Fe DM",
    "listing_id": "42341529",
    "lang": "bg",
    "message": "",
}


async def main():
    print("mailer status:", mailer.status())
    admin = await mailer.notify_new_callback(DOC)
    buyer = await mailer.acknowledge_callback(DOC)
    print("admin notification ->", admin)
    print("buyer confirmation ->", buyer)
    if not admin:
        raise SystemExit("FAIL: the admin notification was dropped, not sent")
    print("PASS: Resend accepted both letters")


if __name__ == "__main__":
    asyncio.run(main())
