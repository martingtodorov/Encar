#!/usr/bin/env python3
"""Load a folder made by `export_data.py` into another database.

Every document is written by `_id`, so running it twice is safe and re-running after a partial
copy simply finishes the job.

    python3 import_data.py --dir /tmp/encar-dump --uri mongodb://localhost:27017 --db encar
"""
import argparse
import glob
import gzip
import os
import sys

from bson import json_util
from pymongo import MongoClient, ReplaceOne


def load(db, path, batch=1000):
    name = os.path.basename(path).replace(".jsonl.gz", "")
    ops, n = [], 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            doc = json_util.loads(line)
            ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
            if len(ops) >= batch:
                db[name].bulk_write(ops, ordered=False)
                n += len(ops)
                ops = []
    if ops:
        db[name].bulk_write(ops, ordered=False)
        n += len(ops)
    print(f"  {name}: {n}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--uri", default=os.environ.get("MONGO_URL"))
    ap.add_argument("--db", default=os.environ.get("DB_NAME"))
    a = ap.parse_args()
    if not a.uri or not a.db:
        sys.exit("MONGO_URL and DB_NAME must be set, or pass --uri and --db")

    files = sorted(glob.glob(os.path.join(a.dir, "*.jsonl.gz")))
    if not files:
        sys.exit(f"nothing to import in {a.dir}")
    db = MongoClient(a.uri)[a.db]
    print(f"importing {len(files)} collections into {a.db}")
    total = sum(load(db, f) for f in files)
    print(f"done: {total} documents")


if __name__ == "__main__":
    main()
