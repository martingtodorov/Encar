#!/usr/bin/env python3
"""Export the collections worth carrying to another server, as gzipped JSON.

The catalogue can always be re-crawled, but some collections must NOT be thrown away:

* `translations` — every sentence in here has already been paid for once.
* `taxonomy_overrides` — the renames and merges made by hand in the admin panel.
* `users`, `purchases`, `shipments`, `enquiries` — the actual business.

Run it against the OLD database, copy the folder over, then run `import_data.py` against the
new one. BSON types survive the trip (json_util), so dates come back as dates.

    python3 export_data.py --out /tmp/encar-dump
    python3 export_data.py --out /tmp/encar-dump --with-listings   # + the whole catalogue
"""
import argparse
import gzip
import os
import sys

from bson import json_util
from pymongo import MongoClient

SETTINGS = ["translations", "taxonomy", "taxonomy_overrides", "model_years",
            "settings", "sync_state", "facets", "option_dicts",
            # The pages, SEO titles and company details written in Admin -> Pages & SEO.
            "site_pages", "site_settings"]
# NOTE: these are the REAL collection names. An earlier version of this list asked for
# "purchases", which does not exist, so every paid deposit was silently left behind.
ACCOUNTS = ["users", "deposits", "purchased_listings", "shipments", "shipment_events",
            "enquiries", "price_watch", "search_watch", "push_subscriptions",
            "webauthn_credentials", "totp_setup", "audit_log"]
CATALOGUE = ["listings", "car_details"]


def dump(db, name, out_dir, batch=2000):
    path = os.path.join(out_dir, f"{name}.jsonl.gz")
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for doc in db[name].find({}, batch_size=batch):
            fh.write(json_util.dumps(doc) + "\n")
            n += 1
            if n % 20000 == 0:
                print(f"  {name}: {n}…", flush=True)
    if not n:
        os.remove(path)
    print(f"  {name}: {n}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder to write the dump into")
    ap.add_argument("--uri", default=os.environ.get("MONGO_URL"))
    ap.add_argument("--db", default=os.environ.get("DB_NAME"))
    ap.add_argument("--with-listings", action="store_true",
                    help="also dump the crawled catalogue (big; it can be re-crawled)")
    ap.add_argument("--no-accounts", action="store_true",
                    help="skip users, purchases, shipments and enquiries")
    a = ap.parse_args()
    if not a.uri or not a.db:
        sys.exit("MONGO_URL and DB_NAME must be set, or pass --uri and --db")

    os.makedirs(a.out, exist_ok=True)
    db = MongoClient(a.uri)[a.db]
    names = set(db.list_collection_names())

    wanted = list(SETTINGS)
    if not a.no_accounts:
        wanted += ACCOUNTS
    if a.with_listings:
        wanted += CATALOGUE

    total = 0
    print(f"exporting from {a.db} -> {a.out}")
    for name in wanted:
        if name in names:
            total += dump(db, name, a.out)
        else:
            print(f"  {name}: not present, skipped")
    print(f"done: {total} documents in {a.out}")


if __name__ == "__main__":
    main()
