#!/usr/bin/env python3
"""What is actually IN the production database, and what is missing.

Run this on the Hetzner box. It reads the backend's own .env, counts every collection the
site depends on, and then says in plain words which of the three things that go wrong after a
fresh deploy have gone wrong here:

* no make/model/submodel dropdowns  -> the `taxonomy` tree was never built
* no merged or renamed models       -> `taxonomy_overrides` was never carried over
* no year span after a model name   -> `model_years` has not been computed

    cd /opt/encar/app/deploy && python3 doctor.py
    python3 doctor.py --env /opt/encar/app/backend/.env
"""
import argparse
import os
import sys

from pymongo import MongoClient

# Everything the site needs, grouped the way it has to be thought about. The second element
# says what happens when it is empty.
GROUPS = [
    ("Catalogue (re-crawlable, but nothing works without it)", [
        ("listings", "no cars anywhere on the site"),
        ("car_details", "detail pages fetch from Encar on first open (slow, not fatal)"),
    ]),
    ("Derived from the catalogue (rebuildable in one click)", [
        ("taxonomy", "NO make / model / submodel dropdowns at all"),
        ("model_years", "no (2018-2024) span after a model name"),
        ("facets", "the fuel / gearbox / colour filters come up empty"),
        ("option_dicts", "equipment lists on the detail page stay in Korean"),
        ("sync_state", "the site does not know when it last crawled"),
    ]),
    ("The owner's own work (CANNOT be rebuilt - must be carried over)", [
        ("taxonomy_overrides", "merged and renamed models fall back to Encar's raw names"),
        ("site_pages", "the edited pages and SEO titles fall back to the built-in copy"),
        ("site_settings", "the company details fall back to the ones in the code"),
        ("settings", "pricing constants and FX overrides are lost - PRICES WILL BE WRONG"),
        ("translations", "every sentence has to be paid for and translated again"),
    ]),
    ("Accounts and money (CANNOT be rebuilt)", [
        ("users", "nobody can sign in - not even the owner"),
        ("deposits", "paid reservation deposits are not on record"),
        ("purchased_listings", "the buyer's own purchases disappear from their account"),
        ("shipments", "assigned vessels and customers are lost"),
        ("shipment_events", "the tracking timeline loses its history"),
        ("enquiries", "leads nobody has answered yet"),
        ("price_watch", "saved-search price alerts stop"),
        ("search_watch", "saved-search email alerts stop"),
        ("push_subscriptions", "push notifications stop"),
        ("webauthn_credentials", "passkeys stop working"),
        ("totp_setup", "half-finished 2FA enrolments"),
        ("audit_log", "the admin history is lost"),
    ]),
]


def env_from(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as e:
        sys.exit(f"cannot read {path}: {e}")
    return out


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.path.join(os.path.dirname(here), "backend", ".env"))
    ap.add_argument("--uri")
    ap.add_argument("--db")
    a = ap.parse_args()

    uri, name = a.uri, a.db
    if not (uri and name):
        env = env_from(a.env)
        uri = uri or env.get("MONGO_URL")
        name = name or env.get("DB_NAME")
        print(f"env: {a.env}")
    if not uri or not name:
        sys.exit("MONGO_URL / DB_NAME not found — pass --uri and --db")

    db = MongoClient(uri, serverSelectionTimeoutMS=8000)[name]
    present = set(db.list_collection_names())
    print(f"database: {name}\n")

    counts = {}
    for title, items in GROUPS:
        print(title)
        for coll, hurt in items:
            n = db[coll].count_documents({}) if coll in present else 0
            counts[coll] = n
            flag = "  ok " if n else "EMPTY"
            print(f"  [{flag}] {coll:<22} {n:>9,}" + ("" if n else f"   -> {hurt}"))
        print()

    # ── the three symptoms, checked properly ────────────────────────────────
    print("Diagnosis")
    active = db.listings.count_documents({"active": True}) if counts["listings"] else 0
    print(f"  active listings: {active:,}")

    if counts["taxonomy"]:
        for lvl, what in ((1, "makes"), (2, "models"), (3, "submodels"), (4, "trims")):
            n = db.taxonomy.count_documents({"level": lvl})
            slugged = db.taxonomy.count_documents({"level": lvl, "slug": {"$nin": [None, ""]}})
            print(f"  level {lvl} {what:<10} {n:>7,}   with URL slug: {slugged:,}")
        if db.taxonomy.count_documents({"slug": {"$in": [None, ""]}}):
            print("  ! some nodes have no slug: model URLs and the Back button will misbehave")
    else:
        print("  ! the taxonomy tree is EMPTY -> this is why there are no dropdowns")

    built = (db.sync_state.find_one({"_id": "taxonomy"}) or {}).get("built_at")
    print(f"  taxonomy built at: {built or 'never'}")

    spans = (db.model_years.find_one({"_id": 'spans'}) or {}).get("items") or []
    print(f"  model year spans: {len(spans):,}" + ("" if spans else "  ! no (2018-2024) labels"))

    if counts["taxonomy_overrides"]:
        print(f"  owner's merges and renames: {counts['taxonomy_overrides']}")
        for d in db.taxonomy_overrides.find({}):
            arrow = f"-> {d['target']}" if d.get("target") else f'labelled "{d.get("label")}"'
            print(f"    level {d.get('level')}  {d.get('value')}  {arrow}")
    else:
        print("  ! no merges or renames -> Encar's raw duplicate names are showing")

    admins = db.users.count_documents({"is_admin": True}) if counts["users"] else 0
    print(f"  administrators: {admins}")
    pricing = db.settings.find_one({"_id": "pricing"}) if counts["settings"] else None
    print(f"  pricing settings: {'present' if pricing else 'MISSING - prices will be wrong'}")

    # ── keys that are silently blank ────────────────────────────────────────
    # A blank key does not crash anything, it just makes a whole feature answer "not
    # connected". That is how shipment tracking goes dark after a deploy.
    env = env_from(a.env)
    print("\nIntegrations (a blank key = that feature is switched off)")
    dark = []
    for key, feature in (
        ("JSONCARGO_API_KEY", "shipment tracking (\"Проследяването още не е свързано\")"),
        ("STRIPE_SECRET_KEY", "reservation deposits"),
        ("RESEND_API_KEY", "every email"),
        ("ANTHROPIC_API_KEY", "translation"),
        ("GEMINI_API_KEY", "translation (standby)"),
        ("VAPID_PRIVATE_KEY", "push notifications"),
        ("TOTP_ENCRYPTION_KEY", "two-factor authentication"),
        ("MEDIA_ROOT", "the backend will not even start"),
        ("PUBLIC_SITE_URL", "links inside emails"),
    ):
        ok = bool((env.get(key) or "").strip())
        print(f"  [{'  ok ' if ok else 'BLANK'}] {key:<22}" + ("" if ok else f"  -> {feature}"))
        if not ok:
            dark.append(key)

    # ── what to do about it ─────────────────────────────────────────────────
    print("\nWhat to do")
    steps = []
    if not active:
        steps.append("Nothing has been crawled yet. Admin -> Catalogue sync -> Run a full "
                     "sync (hours), or carry the catalogue over with "
                     "`export_data.py --with-listings`.")
    missing_own = [c for c in ("taxonomy_overrides", "site_pages", "site_settings",
                               "settings", "translations") if not counts[c]]
    if missing_own:
        steps.append("Carry the owner's own work over from the old database — it cannot be "
                     f"rebuilt here: {', '.join(missing_own)}.\n"
                     "      on the OLD box:  python3 deploy/export_data.py --out /tmp/dump\n"
                     "      copy it over:    scp -r /tmp/dump root@THIS_BOX:/tmp/dump\n"
                     "      on THIS box:     python3 deploy/import_data.py --dir /tmp/dump")
    if active and (not counts["taxonomy"] or not spans):
        steps.append("Rebuild what is derived from the catalogue: Admin -> Catalogue sync -> "
                     "\"Rebuild dropdowns\" (or POST /api/admin/rebuild-derived with the "
                     "admin token). Takes a minute or two.")
    if not admins:
        steps.append("No administrator exists. Set OWNER_EMAIL and OWNER_PASSWORD in "
                     "backend/.env and restart the backend — it seeds the owner on startup.")
    if dark:
        steps.append("Fill these in group_vars/all.yml on your Mac and deploy again — they "
                     f"are blank here, so those features are off: {', '.join(dark)}.")
    if not steps:
        steps.append("Nothing missing. If a dropdown still looks wrong, rebuild the "
                     "dropdowns from Admin -> Catalogue sync.")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")


if __name__ == "__main__":
    main()
