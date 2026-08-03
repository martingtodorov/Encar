"""English slugs for the Korean taxonomy values that appear in URLs.

Encar's makes, models, trims, fuels and regions are Hangul, and putting them in the
query string gives percent-encoded gibberish that is unreadable, unshareable and worth
nothing to a search engine. The slug is built from the ENGLISH translation we already
cache, so `?make=hyundai&model=grandeur` resolves back to the exact upstream values.

Slugs live on the taxonomy documents themselves (one indexed lookup to resolve) and are
rebuilt whenever the taxonomy is, since the collection is swapped wholesale.
"""

import logging
import re
import unicodedata

from translate import translate_cached_only

log = logging.getLogger("slugs")

DIMS = ("make", "model", "badge", "badge_detail")
LEVEL_OF = {"make": 1, "model": 2, "badge": 3, "badge_detail": 4}


def slugify(text):
    """Lowercase ASCII slug. Returns "" when nothing usable survives (e.g. pure Hangul)."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80]


async def _en_labels(db, values):
    try:
        return await translate_cached_only(db, values, "en")
    except Exception as e:
        log.warning("english labels unavailable: %s", str(e)[:160])
        return {}


async def ensure_taxonomy_slugs(db, force=False):
    """Fill in missing slugs. Cheap no-op once the tree has them."""
    if not force and not await db.taxonomy.find_one({"slug": {"$exists": False}}, {"_id": 1}):
        return 0

    docs = [d async for d in db.taxonomy.find(
        {}, {"level": 1, "value": 1, "make": 1, "model": 1, "badge": 1})]
    labels = await _en_labels(db, [d["value"] for d in docs])

    # Uniqueness only has to hold inside the scope a slug is resolved in: level 1 is
    # global, deeper levels are scoped by their parents.
    taken = {}
    ops = []
    from pymongo import UpdateOne
    for d in docs:
        scope = (d["level"], d.get("make", ""), d.get("model", ""), d.get("badge", ""))
        base = slugify(labels.get(d["value"]) or d["value"])
        if not base:
            continue                       # untranslated: keep the raw value in the URL
        slug, n = base, 1
        while (scope, slug) in taken and taken[(scope, slug)] != d["value"]:
            n += 1
            slug = f"{base}-{n}"
        taken[(scope, slug)] = d["value"]
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {"slug": slug}}))

    for i in range(0, len(ops), 2000):
        await db.taxonomy.bulk_write(ops[i:i + 2000], ordered=False)
    await db.taxonomy.create_index([("level", 1), ("make", 1), ("model", 1),
                                   ("badge", 1), ("slug", 1)])
    log.info("taxonomy slugs written: %s", len(ops))
    return len(ops)


async def facet_slugs(db, dim):
    """value <-> slug for the flat facets (fuel, region). Small sets, no storage needed."""
    field = {"fuel": "fuels", "region": "regions"}[dim]
    cached = await db.facets.find_one({"_id": "filters"}, {field: 1}) or {}
    values = [x["value"] for x in cached.get(field, [])]
    labels = await _en_labels(db, values)
    by_slug, by_value, taken = {}, {}, set()
    for v in values:
        base = slugify(labels.get(v) or v)
        if not base:
            continue
        slug, n = base, 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        by_slug[slug] = v
        by_value[v] = slug
    return by_slug, by_value


async def taxonomy_slug_map(db, level, make="", model="", badge=""):
    """value -> slug for one dropdown level, so the UI can write slugs into the URL."""
    q = {"level": level}
    if level >= 2:
        q["make"] = make
    if level >= 3:
        q["model"] = model
    if level >= 4:
        q["badge"] = badge
    return {d["value"]: d.get("slug") or ""
            async for d in db.taxonomy.find(q, {"value": 1, "slug": 1})}


async def resolve_taxonomy(db, make="", model="", badge="", badge_detail=""):
    """Slugs (or raw values) -> the upstream Korean values, top down.

    Anything that does not match a slug is passed through unchanged, so links created
    before slugs existed keep working.
    """
    out = {}
    ctx = {"make": "", "model": "", "badge": ""}
    for dim, token in (("make", make), ("model", model), ("badge", badge),
                       ("badge_detail", badge_detail)):
        if not token:
            break
        q = {"level": LEVEL_OF[dim], "slug": token}
        if dim != "make":
            q["make"] = ctx["make"]
        if dim in ("badge", "badge_detail"):
            q["model"] = ctx["model"]
        if dim == "badge_detail":
            q["badge"] = ctx["badge"]
        doc = await db.taxonomy.find_one(q, {"value": 1})
        value = doc["value"] if doc else token
        out[dim] = value
        if dim in ctx:
            ctx[dim] = value
    return out
