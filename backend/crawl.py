"""Manual partitioned-crawl runner.

Usage (from /app/backend):
    python crawl.py --make 벤츠                 # one manufacturer
    python crawl.py --make 벤츠 --make 현대      # several
    python crawl.py --all                        # whole catalogue
    python crawl.py --make 벤츠 --no-post        # skip transmission/dedupe/taxonomy

Deliberately a script, not an API endpoint: this is an operator task, and a long
crawl must not be attached to a request lifecycle.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

import sync                    # noqa: E402
from encar import encar        # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("crawl")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="append", default=[],
                    help="manufacturer as Encar spells it, e.g. 벤츠")
    ap.add_argument("--all", action="store_true", help="crawl the whole catalogue")
    ap.add_argument("--no-post", action="store_true",
                    help="skip transmission tagging, dedupe and taxonomy rebuild")
    ap.add_argument("--no-retire", action="store_true",
                    help="do not mark unseen listings inactive")
    args = ap.parse_args()

    if not args.make and not args.all:
        ap.error("pass --make <name> (repeatable) or --all")

    makes = None if args.all else args.make

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "encar_skin")]

    try:
        await sync.ensure_indexes(db)

        result = await sync.crawl_partitioned(
            db, manufacturers=makes, retire=not args.no_retire)

        if not args.no_post:
            result["manual_tagged"] = await sync.tag_transmission(db, manufacturers=makes)
            result["colours"] = await sync.tag_colors(db, manufacturers=makes)
            result["dedupe"] = await sync.dedupe_pass(db)
            try:
                result["taxonomy"] = await sync.build_taxonomy(db)
            except Exception as e:
                log.warning("taxonomy rebuild failed: %s", e)

        scope = {"manufacturer": {"$in": makes}} if makes else {}
        result["db_scope_total"] = await db.listings.count_documents(dict(scope))
        result["db_scope_active"] = await db.listings.count_documents(
            {**scope, "active": True})
        result["db_scope_unique"] = await db.listings.count_documents(
            {**scope, "active": True, "duplicate": {"$ne": True}})

        print("\n===== CRAWL RESULT =====")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

        # completeness assertion: distinct ids fetched vs upstream reported count
        for make, m in (result.get("per_make") or {}).items():
            cov = m["coverage"] * 100
            flag = "OK " if cov >= 95 else "LOW"
            print(f"[{flag}] {make}: upstream={m['upstream']} "
                  f"distinct={m['distinct_kept']} coverage={cov:.2f}%")
    finally:
        await encar.close()
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
