"""Undo listings that were marked sold by an upstream failure, not by Encar.

Why this script exists
----------------------
`encar.get_json()` used to return None for every unexpected HTTP status. `car_detail()` read
a falsy detail as "Encar retired this ad" and called `_gone()`, which sets
`active: false, sold: true, sold_at: now`. So during the CloudFront 407 window on
2026-09-04, every uncached car a visitor happened to click was retired — while being
perfectly live. The client now raises `EncarUnavailable` and only a real 404 can retire a
car, but the rows written during the incident need putting back.

What it will NOT touch
----------------------
  * cars under contract (`sales_status: CONTRACT` / `under_contract: true`) — a real pending
    sale, and Encar told us so;
  * cars whose `last_seen` predates `sold_at` by more than `--stale-hours` — the crawler had
    already stopped seeing them, so "sold" is plausibly true;
  * anything outside the given window.

With `--verify` each candidate is confirmed against Encar before it is restored: a 404 means
the ad really is gone and the row is left alone. That is the safest mode and the one to use
on production, where the upstream is reachable.

Usage
-----
    # look, change nothing (default)
    python restore_false_sold.py --from "2026-09-04T20:00:00Z" --to "2026-09-04T21:00:00Z"

    # confirm each one with Encar, then restore
    python restore_false_sold.py --from ... --to ... --verify --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv                                          # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient                      # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _iso(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from", dest="start", required=True,
                   help="window start, ISO 8601 UTC, e.g. 2026-09-04T20:00:00Z")
    p.add_argument("--to", dest="end", required=True, help="window end, ISO 8601 UTC")
    p.add_argument("--stale-hours", type=float, default=6.0,
                   help="skip a car whose last_seen is older than this many hours before "
                        "sold_at (default 6): the crawler had already lost sight of it")
    p.add_argument("--verify", action="store_true",
                   help="ask Encar about each candidate; skip the ones that really are gone")
    p.add_argument("--apply", action="store_true",
                   help="actually restore. Without it this is a dry run")
    p.add_argument("--limit", type=int, default=0, help="stop after N candidates")
    args = p.parse_args()

    start, end = _iso(args.start), _iso(args.end)
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    query = {"sold": True, "sold_at": {"$gte": start, "$lte": end}}
    total = await db.listings.count_documents(query)
    print(f"{total} listings marked sold between {start.isoformat()} and {end.isoformat()}\n")

    restored = skipped_contract = skipped_stale = skipped_gone = 0
    cursor = db.listings.find(query)
    if args.limit:
        cursor = cursor.limit(args.limit)

    async for car in cursor:
        cid = car["_id"]
        sold_at = _aware(car.get("sold_at"))
        last_seen = _aware(car.get("last_seen"))
        label = " ".join(filter(None, [car.get("manufacturer"), car.get("model")]))[:40]

        if car.get("under_contract") or (car.get("sales_status") or "").upper() == "CONTRACT":
            skipped_contract += 1
            print(f"  skip  {cid}  {label:<40} under contract")
            continue

        if last_seen and sold_at and last_seen < sold_at - timedelta(hours=args.stale_hours):
            skipped_stale += 1
            print(f"  skip  {cid}  {label:<40} last_seen {last_seen.isoformat()} is stale")
            continue

        if args.verify:
            from encar import EncarUnavailable, encar
            try:
                detail = await encar.detail(cid)
            except EncarUnavailable as e:
                print(f"  wait  {cid}  {label:<40} upstream unavailable ({e}); left as is")
                continue
            if detail is None:
                skipped_gone += 1
                print(f"  skip  {cid}  {label:<40} Encar returns 404 — genuinely gone")
                continue

        restored += 1
        print(f"  FIX   {cid}  {label:<40} sold_at {sold_at.isoformat() if sold_at else '?'}")
        if args.apply:
            await db.listings.update_one(
                {"_id": cid},
                {"$set": {"active": True, "sold": False},
                 "$unset": {"sold_at": "", "under_contract": ""}})

    print(f"\n{'restored' if args.apply else 'would restore'}: {restored}")
    print(f"skipped — under contract: {skipped_contract}, stale last_seen: {skipped_stale}, "
          f"confirmed gone: {skipped_gone}")
    if not args.apply and restored:
        print("\nThis was a dry run. Re-run with --apply (and --verify on production).")


if __name__ == "__main__":
    asyncio.run(main())
