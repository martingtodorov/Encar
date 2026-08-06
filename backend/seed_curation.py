"""The owner's curation, carried in the repository so every deploy has it.

The merges and renames (`taxonomy_overrides`) and the model year spans (`model_years`) are
the owner's own work, not something a fresh install can compute. Keeping them in
`seed/curation.json` means a brand new server has the same dropdowns as the one the owner
curated, without anybody remembering to copy a database.

Applied at startup, INSERT-IF-MISSING by `_id`. It never overwrites a document that is
already there, so an override edited on the live server is not thrown away by the next
restart or deploy.

Regenerate the file from whichever database currently has the truth:

    cd /app/backend && python3 seed_curation.py --dump
"""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("seed_curation")

SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed", "curation.json")
COLLECTIONS = ("taxonomy_overrides", "model_years")


def _load():
    try:
        with open(SEED_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("curation seed unreadable, skipping: %s", str(e)[:200])
        return {}


async def ensure_curation(db):
    """Put anything from the seed file that this database has not got yet."""
    data = _load()
    added = {}
    for name in COLLECTIONS:
        docs = data.get(name) or []
        if not docs:
            continue
        have = set(await db[name].distinct("_id"))
        fresh = [d for d in docs if d.get("_id") not in have]
        if fresh:
            await db[name].insert_many(fresh, ordered=False)
            added[name] = len(fresh)
    if added:
        log.info("curation seeded: %s",
                 ", ".join(f"{n} x {c}" for c, n in added.items()))
    return added


async def dump(db):
    """Write the current database's curation into the repository file."""
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Seeded at startup, insert-if-missing. Regenerate with "
                "`python3 seed_curation.py --dump`.",
    }
    for name in COLLECTIONS:
        out[name] = [d async for d in db[name].find({})]
    os.makedirs(os.path.dirname(SEED_PATH), exist_ok=True)
    with open(SEED_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    counts = {n: len(out[n]) for n in COLLECTIONS}
    spans = next((len(d.get("items") or []) for d in out["model_years"]
                  if d.get("_id") == "spans"), 0)
    print(f"wrote {SEED_PATH}: {counts}, {spans} year spans, "
          f"{os.path.getsize(SEED_PATH):,} bytes")


def main():
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient

    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="write the seed file from the database")
    a = ap.parse_args()
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    asyncio.run(dump(db) if a.dump else ensure_curation(db))


if __name__ == "__main__":
    main()
