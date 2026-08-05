"""The owner's curation of Encar's taxonomy: rename a value, or fold one value into another.

Encar's own trim list is full of near-duplicates — "M2 쿠페", "M2 쿠페 M 퍼포먼스 스티어링 휠
에디션" and "M2 블랙 쉐도우" are the same car with a different steering wheel — and a buyer
should see ONE entry with all nine cars behind it. Overrides are kept per (level, value) in
`taxonomy_overrides`, applied when a dropdown is built, and a filter on the surviving value
expands to everything folded into it, so the merged entry really does return every car.

Nothing here touches the crawled data: `listings` keeps Encar's own values, so an override can
be undone at any time and a re-crawl can never overwrite it.
"""
import re
import time

_TTL = 20.0
_YEARS_TTL = 7 * 24 * 3600
_cache = {"at": 0.0, "target": {}, "members": {}, "label": {}, "years": {}}

# Encar names generations the way a Korean dealer speaks: "The New Sportage", "All New
# Tucson", "Sportage 5th Generation". A buyer in Europe reads YEARS, so the marketing words
# come off and the production span our own catalogue can see goes on instead.
_NEW = re.compile(r"^\s*(the\s+)?(all[\s\-]*new|brand[\s\-]*new|new)\s+", re.I)
_GEN = re.compile(r"[\s(]*\b\d{1,2}(?:st|nd|rd|th)\s+gen(?:eration)?\b\)?", re.I)


async def refresh(db, force=False):
    """Reload the overrides at most every 20s. Called before anything that reads them."""
    if not force and _cache["at"] and time.monotonic() - _cache["at"] < _TTL:
        return
    target, members, label = {}, {}, {}
    async for d in db.taxonomy_overrides.find({}):
        level, value = int(d.get("level") or 0), d.get("value") or ""
        if not value:
            continue
        if d.get("target"):
            target[(level, value)] = d["target"]
            members.setdefault((level, d["target"]), []).append(value)
        if d.get("label"):
            label[(level, value)] = d["label"]
    doc = await db.model_years.find_one({"_id": "spans"}) or {}
    years = {r["v"]: (r["lo"], r["hi"]) for r in (doc.get("items") or [])}
    _cache.update({"at": time.monotonic(), "target": target,
                   "members": members, "label": label, "years": years})


async def ensure_years(db):
    """The production span of every model, straight out of our own catalogue.

    One grouped pass over the listings, kept for a week. Encar's model year (`form_year`) is
    closer to the generation than the registration date, so that is what is measured.
    """
    doc = await db.model_years.find_one({"_id": "spans"}, {"at": 1})
    if doc and time.time() - (doc.get("at") or 0) < _YEARS_TTL:
        return
    rows = await db.listings.aggregate([
        {"$match": {"active": True, "form_year": {"$gte": 1980}}},
        {"$group": {"_id": "$model",
                    "lo": {"$min": "$form_year"}, "hi": {"$max": "$form_year"}}},
    ]).to_list(length=20000)
    items = [{"v": r["_id"], "lo": int(r["lo"]), "hi": int(r["hi"])}
             for r in rows if r.get("_id")]
    await db.model_years.update_one(
        {"_id": "spans"}, {"$set": {"items": items, "at": time.time()}}, upsert=True)
    _cache["years"] = {r["v"]: (r["lo"], r["hi"]) for r in items}


def display(level, value, label=""):
    """The label a buyer sees: the owner's own rename wins, then our model-name cleanup."""
    manual = label_for(level, value)
    if manual:
        return manual
    label = label or value
    return model_label(value, label) if int(level) == 2 else label


def model_label(value, label, this_year=None):
    """A model name as a European buyer should read it: no "The New", years instead."""
    out = _GEN.sub("", _NEW.sub("", str(label or ""))).strip(" -\u2013\u00b7,")
    span = _cache["years"].get(value)
    if span:
        lo, hi = span
        now = this_year or time.gmtime().tm_year
        # Still on sale? Leave the span open rather than pretending it ended last year.
        out = f"{out} ({lo}-)" if hi >= now - 1 else f"{out} ({lo}-{hi})"
    return out or label



def merged_into(level, value):
    return _cache["target"].get((int(level), value)) or ""


def label_for(level, value, fallback=""):
    return _cache["label"].get((int(level), value)) or fallback


def root(level, value, depth=4):
    """Follow a chain of merges to the value that actually survives."""
    seen = value
    for _ in range(depth):
        nxt = merged_into(level, seen)
        if not nxt or nxt == seen:
            break
        seen = nxt
    return seen


def expand(level, values):
    """Every value folded into the selected ones, so the filter returns all their cars."""
    out = list(values or [])
    queue = list(out)
    while queue:
        v = queue.pop()
        for m in _cache["members"].get((int(level), v), []):
            if m not in out:
                out.append(m)
                queue.append(m)
    return out


def collapse(rows, level):
    """Fold merged rows into their target, summing the counts. The target keeps its slug."""
    by_value = {r["value"]: r for r in rows}
    out = []
    for r in rows:
        t = root(level, r["value"])
        if t != r["value"] and t in by_value:
            by_value[t]["count"] = (by_value[t].get("count") or 0) + (r.get("count") or 0)
            continue
        out.append(r)
    return out
