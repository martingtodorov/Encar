"""Encar localized skin - FastAPI backend.

Architecture notes:
  * User searches are served ENTIRELY from our own MongoDB index -> zero upstream
    calls per search, unlimited pagination depth, and filtering/sorting by the
    computed landed EUR price (which encar.com itself cannot do).
  * The catalogue is synced politely (~436 requests for ~218k cars, limit=500).
  * Car images are NEVER proxied - the browser loads them straight from Encar's CDN,
    which is ~98% of bandwidth and genuinely uses the visitor's own IP.
  * Korean text is AI-translated once and cached in MongoDB forever.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import auth                  # noqa: E402
import fx as fx_mod          # noqa: E402
import mailer                # noqa: E402
import pricing               # noqa: E402
import sync as sync_mod      # noqa: E402
from encar import encar, image_url  # noqa: E402
from translate import (LANGS, breaker_status, schedule_translation,  # noqa: E402
                       translate_cached_only, translate_listings,
                       translate_many, translate_one)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "encar_skin")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "encar-admin")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Encar Import - localized skin")
api = APIRouter(prefix="/api")

FACET_TTL = 600  # seconds


# ───────────────────────────────── helpers ────────────────────────────────────
def jsonable(doc):
    """Mongo docs contain datetimes, which are not JSON serialisable."""
    if isinstance(doc, list):
        return [jsonable(d) for d in doc]
    if isinstance(doc, dict):
        return {k: jsonable(v) for k, v in doc.items()}
    if isinstance(doc, datetime):
        return doc.replace(tzinfo=doc.tzinfo or timezone.utc).isoformat()
    return doc


def norm_lang(lang):
    lang = (lang or "bg").lower()
    return lang if lang in LANGS else "bg"


def listing_out(doc):
    """Shape a listing for the grid, including ready-to-use CDN image URLs."""
    photos = doc.get("photos") or []
    return {
        "id": doc["_id"],
        "manufacturer": doc.get("manufacturer"),
        "model": doc.get("model"),
        "badge": doc.get("badge"),
        "manufacturer_t": doc.get("manufacturer_t"),
        "model_t": doc.get("model_t"),
        "badge_t": doc.get("badge_t"),
        "badge_detail": doc.get("badge_detail"),
        "badge_detail_t": doc.get("badge_detail_t"),
        "under_contract": bool(doc.get("under_contract")),
        "sales_status": doc.get("sales_status") or "",
        "fuel_type": doc.get("fuel_type"),
        "fuel_type_t": doc.get("fuel_type_t"),
        "region": doc.get("region"),
        "region_t": doc.get("region_t"),
        "transmission": doc.get("transmission"),
        "year_month": doc.get("year_month"),
        "form_year": doc.get("form_year"),
        "mileage": doc.get("mileage"),
        "price_krw": doc.get("price_krw"),
        "price_manwon": doc.get("price_manwon"),
        "landed_eur": doc.get("landed_eur"),
        "sale_eur": doc.get("sale_eur"),
        "photo_count": doc.get("photo_count") or len(photos),
        "image": image_url(photos[0] if photos else None, 640, 360),
        "image_sm": image_url(photos[0] if photos else None, 320, 180),
        "has_inspection": bool(doc.get("has_inspection")),
        "has_record": bool(doc.get("has_record")),
        "diagnosed": bool(doc.get("diagnosed")),
        "active": bool(doc.get("active", True)),
        "first_seen": jsonable(doc.get("first_seen")),
    }


def build_query(p):
    """Translate request filters into a Mongo query."""
    # duplicate ads for the same physical car are hidden (see sync.dedupe_pass)
    q = {"active": True, "duplicate": {"$ne": True}}

    if p.get("makes"):
        q["manufacturer"] = {"$in": p["makes"]}
    if p.get("models"):
        q["model"] = {"$in": p["models"]}
    if p.get("badges"):
        q["badge"] = {"$in": p["badges"]}
    if p.get("badge_details"):
        q["badge_detail"] = {"$in": p["badge_details"]}
    if p.get("fuels"):
        q["fuel_type"] = {"$in": p["fuels"]}
    if p.get("regions"):
        q["region"] = {"$in": p["regions"]}
    if p.get("transmissions"):
        q["transmission"] = {"$in": p["transmissions"]}

    year = {}
    if p.get("year_min"):
        year["$gte"] = int(p["year_min"])
    if p.get("year_max"):
        year["$lte"] = int(p["year_max"])
    if year:
        q["form_year"] = year

    mil = {}
    if p.get("mileage_min") is not None:
        mil["$gte"] = int(p["mileage_min"])
    if p.get("mileage_max"):
        mil["$lte"] = int(p["mileage_max"])
    if mil:
        q["mileage"] = mil

    price = {}
    if p.get("price_min") is not None:
        price["$gte"] = float(p["price_min"])
    if p.get("price_max"):
        price["$lte"] = float(p["price_max"])
    if price:
        q["sale_eur"] = price

    if p.get("only_inspection"):
        q["has_inspection"] = True
    if p.get("only_record"):
        q["has_record"] = True
    if p.get("only_diagnosed"):
        q["diagnosed"] = True

    kw = (p.get("q") or "").strip()
    if kw:
        # regex on the denormalised search_text: works for Korean AND Latin queries
        q["$or"] = [
            {"search_text": {"$regex": kw, "$options": "i"}},
            {"_id": kw},
        ]
    return q


SORTS = {
    "newest": [("recency", 1)],
    "price_asc": [("sale_eur", 1)],
    "price_desc": [("sale_eur", -1)],
    "mileage_asc": [("mileage", 1)],
    "year_desc": [("form_year", -1)],
}


# ───────────────────────────────── routes ─────────────────────────────────────


HANGUL = re.compile(r"[\uac00-\ud7a3]")
# per user instruction the per-vehicle dealer description stays in the original
NO_TRANSLATE_KEYS = {"description", "description_original", "vin", "vehicle_no", "id"}

# How many never-before-seen Korean phrases one detail page will translate inline
# before deferring the rest to the background. Generous, because these phrase sets are
# shared catalogue-wide and cached permanently, so in practice the cap is rarely hit.
SYNC_TRANSLATE_CAP = 240


def collect_korean(obj, out, skip=NO_TRANSLATE_KEYS):
    """Gather every Hangul-containing string in a payload, so each can be cached."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip:
                continue
            collect_korean(v, out, skip)
    elif isinstance(obj, list):
        for v in obj:
            collect_korean(v, out, skip)
    elif isinstance(obj, str) and HANGUL.search(obj):
        out.add(obj.strip())


def apply_translations(obj, tmap, skip=NO_TRANSLATE_KEYS):
    """Replace Hangul strings with cached translations, in place."""
    if isinstance(obj, dict):
        return {k: (v if k in skip else apply_translations(v, tmap, skip))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [apply_translations(v, tmap, skip) for v in obj]
    if isinstance(obj, str) and HANGUL.search(obj):
        return tmap.get(obj.strip(), obj)
    return obj


_OPT_MEM = {"at": 0, "data": None}


async def option_dicts_cached(ttl=86400):
    """Option dictionaries are global and change rarely. Cache in memory AND Mongo so
    a car page costs zero extra upstream calls (previously 2 after every restart)."""
    now = datetime.now(timezone.utc).timestamp()
    if _OPT_MEM["data"] and now - _OPT_MEM["at"] < ttl:
        return _OPT_MEM["data"]

    doc = await db.option_dicts.find_one({"_id": "car"})
    if doc and (now - doc["at"]) < ttl:
        data = {"standard": doc["standard"], "tuning": doc["tuning"], "metas": doc["metas"]}
        _OPT_MEM.update(at=now, data=data)
        return data

    fresh = await encar.option_dicts()
    data = {"standard": fresh["standard"], "tuning": fresh["tuning"], "metas": fresh["metas"]}
    if data["standard"]:
        await db.option_dicts.update_one(
            {"_id": "car"}, {"$set": {**data, "at": now}}, upsert=True)
        _OPT_MEM.update(at=now, data=data)
    elif doc:  # upstream hiccup: prefer stale data over nothing
        data = {"standard": doc["standard"], "tuning": doc["tuning"], "metas": doc["metas"]}
    return data


_SIZE_MEM = {"at": 0.0, "count": 0}


async def upstream_size_cached(ttl=900):
    """Live number of ads currently listed on Encar.

    One cheap upstream request (count-only search, limit=1), cached in memory and in
    Mongo, so the hero figure tracks Encar in near-real-time instead of freezing at
    whatever the last full catalogue crawl happened to see.
    """
    now = datetime.now(timezone.utc).timestamp()
    if _SIZE_MEM["count"] and now - _SIZE_MEM["at"] < ttl:
        return _SIZE_MEM["count"]

    doc = await db.settings.find_one({"_id": "upstream_size"})
    if doc and (now - doc.get("at", 0)) < ttl:
        _SIZE_MEM.update(at=doc["at"], count=doc["count"])
        return doc["count"]

    try:
        n = int(await encar.count() or 0)
    except Exception as e:
        log.warning("live upstream count failed: %s", str(e)[:160])
        n = 0
    if n:
        await db.settings.update_one({"_id": "upstream_size"},
                                     {"$set": {"count": n, "at": now}}, upsert=True)
        _SIZE_MEM.update(at=now, count=n)
        return n
    # upstream hiccup: prefer the last known figure over showing nothing
    return (doc or {}).get("count") or _SIZE_MEM["count"] or 0


@api.get("/catalogue/size")
async def catalogue_size():
    """Powers the hero counter. `upstream` = ads live on Encar right now,
    `unique_cars` = distinct physical cars we show after hiding re-registered ads."""
    return {
        "upstream": await upstream_size_cached(),
        "unique_cars": await db.listings.count_documents(
            {"active": True, "duplicate": {"$ne": True}}),
    }


@api.get("/health")
async def health():
    state = await sync_mod.get_state(db)
    return {
        "ok": True,
        "listings_total": await db.listings.count_documents({}),
        "listings_active": await db.listings.count_documents({"active": True}),
        "unique_cars": await db.listings.count_documents(
            {"active": True, "duplicate": {"$ne": True}}),
        "duplicate_ads_hidden": await db.listings.count_documents(
            {"active": True, "duplicate": True}),
        "translations_cached": await db.translations.count_documents({}),
        "translation_breaker": breaker_status(),
        "sync": jsonable({k: v for k, v in state.items() if k != "_id"}),
        "encar_stats": dict(encar.stats),
    }


@api.get("/fx")
async def get_fx(refresh: bool = False):
    return jsonable(await fx_mod.get_rates(db, force=refresh))


class SearchBody(BaseModel):
    q: str | None = None
    makes: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    badge_details: list[str] = Field(default_factory=list)
    fuels: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    transmissions: list[str] = Field(default_factory=list)
    year_min: int | None = None
    year_max: int | None = None
    mileage_min: int | None = None
    mileage_max: int | None = None
    price_min: float | None = None
    price_max: float | None = None
    only_inspection: bool = False
    only_record: bool = False
    only_diagnosed: bool = False
    sort: str = "newest"
    page: int = 1
    page_size: int = 24
    lang: str = "bg"


@api.post("/search")
async def search(body: SearchBody):
    lang = norm_lang(body.lang)
    p = body.model_dump()
    query = build_query(p)
    sort = SORTS.get(body.sort, SORTS["newest"])

    page = max(1, int(body.page))
    size = min(max(1, int(body.page_size)), 96)
    skip = (page - 1) * size

    total = await db.listings.count_documents(query)
    cursor = db.listings.find(query).sort(sort).skip(skip).limit(size)
    rows = [d async for d in cursor]

    await translate_listings(db, rows, lang)
    items = [listing_out(d) for d in rows]

    return {
        "total": total,
        "page": page,
        "page_size": size,
        "pages": (total + size - 1) // size,
        "items": items,
        "lang": lang,
    }


@api.get("/meta/filters")
async def meta_filters(lang: str = "bg", refresh: bool = False):
    """Facet values + counts, computed by aggregation and cached (TTL 10 min)."""
    lang = norm_lang(lang)
    now = datetime.now(timezone.utc)
    cached = await db.facets.find_one({"_id": "filters"})
    stale = True
    if cached and not refresh:
        stale = (now - cached["computed_at"].replace(tzinfo=timezone.utc)).total_seconds() > FACET_TTL

    if stale:
        async def top(field, limit=400):
            pipe = [
                {"$match": {"active": True, "duplicate": {"$ne": True},
                            field: {"$nin": [None, ""]}}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": limit},
            ]
            return [{"value": d["_id"], "count": d["count"]}
                    async for d in db.listings.aggregate(pipe)]

        makes = await top("manufacturer", 200)
        fuels = await top("fuel_type", 40)
        regions = await top("region", 40)
        transmissions = await top("transmission", 5)

        bounds_pipe = [
            {"$match": {"active": True, "duplicate": {"$ne": True}}},
            {"$group": {
                "_id": None,
                "year_min": {"$min": "$form_year"},
                "year_max": {"$max": "$form_year"},
                "mileage_max": {"$max": "$mileage"},
                "price_min": {"$min": "$sale_eur"},
                "price_max": {"$max": "$sale_eur"},
            }},
        ]
        bounds = {}
        async for d in db.listings.aggregate(bounds_pipe):
            bounds = {k: v for k, v in d.items() if k != "_id"}

        cached = {
            "_id": "filters", "computed_at": now, "makes": makes, "fuels": fuels,
            "regions": regions, "transmissions": transmissions, "bounds": bounds,
        }
        await db.facets.update_one({"_id": "filters"}, {"$set": cached}, upsert=True)

    # translate facet labels (bounded set, cached forever after first pass).
    # No slice on makes: every make must render in the user's language, not just the
    # 80 most common ones.
    labels = [x["value"] for x in cached.get("makes", [])]
    labels += [x["value"] for x in cached.get("fuels", [])]
    labels += [x["value"] for x in cached.get("regions", [])]
    tmap = await translate_many(db, labels, lang)

    def decorate(items):
        return [{"value": i["value"], "count": i["count"],
                 "label": tmap.get(i["value"], i["value"])} for i in items]

    return {
        "makes": decorate(cached.get("makes", [])),
        "fuels": decorate(cached.get("fuels", [])),
        "regions": decorate(cached.get("regions", [])),
        "transmissions": cached.get("transmissions", []),
        "bounds": cached.get("bounds", {}),
        "computed_at": jsonable(cached.get("computed_at")),
        "lang": lang,
    }


@api.get("/meta/models")
async def meta_models(make: str = Query(...), lang: str = "bg", limit: int = 300):
    """Models for a make - loaded on demand so the sidebar stays fast."""
    lang = norm_lang(lang)
    pipe = [
        {"$match": {"active": True, "duplicate": {"$ne": True},
                    "manufacturer": make, "model": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$model", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    rows = [{"value": d["_id"], "count": d["count"]} async for d in db.listings.aggregate(pipe)]
    tmap = await translate_many(db, [r["value"] for r in rows], lang)
    return {"make": make,
            "models": [{**r, "label": tmap.get(r["value"], r["value"])} for r in rows]}


@api.get("/meta/taxonomy")
async def meta_taxonomy(
    level: int = Query(1, ge=1, le=4),
    make: str = "",
    model: str = "",
    badge: str = "",
    lang: str = "bg",
    limit: int = 600,
):
    """Cascading Make -> Model -> Trim -> Sub-trim dropdown data.

    Served from the precomputed `taxonomy` collection (rebuilt on each sync, and at
    most weekly on demand), so each level is one indexed lookup instead of a full
    aggregation.

    Labels translate SYNCHRONOUSLY: a make/model/submodel dropdown must never show
    Hangul. The value set per level is bounded and cached permanently (and warmed by
    the sync), so this is a cache hit in practice. If the LLM is unreachable we fall
    back to cache-only rather than failing the dropdown.
    """
    lang = norm_lang(lang)
    try:
        await sync_mod.refresh_taxonomy_if_stale(db)
    except Exception as e:
        log.warning("taxonomy refresh failed: %s", e)

    q = {"level": level}
    if level >= 2:
        q["make"] = make
    if level >= 3:
        q["model"] = model
    if level >= 4:
        q["badge"] = badge

    rows = [
        {"value": d["value"], "count": d["count"]}
        async for d in db.taxonomy.find(q, {"value": 1, "count": 1})
        .sort([("value", 1)])          # alphabetical, not by popularity
        .limit(limit)
    ]
    values = [r["value"] for r in rows]
    try:
        tmap = await translate_many(db, values, lang)
    except Exception as e:
        log.warning("taxonomy translation failed: %s", str(e)[:160])
        tmap = await translate_cached_only(db, values, lang)
        missing = [v for v in values if v not in tmap]
        if missing:
            schedule_translation(db, missing, lang)

    built = await db.sync_state.find_one({"_id": "taxonomy"})
    return {
        "level": level,
        "items": [{**r, "label": tmap.get(r["value"], r["value"])} for r in rows],
        "built_at": jsonable((built or {}).get("built_at")),
    }


@api.post("/admin/taxonomy/rebuild")
async def admin_taxonomy(x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    return await sync_mod.build_taxonomy(db)


@api.get("/car/{listing_id}")
async def car_detail(listing_id: str, lang: str = "bg", refresh: bool = False):
    """Everything for one car: all photos, spec, options, insurance history,
    inspection sheet, diagnosis and the landed-price breakdown.

    Upstream is hit at most ONCE per car ever (these documents are immutable), then
    served from cache. Photos are returned as CDN URLs the browser loads directly.
    """
    lang = norm_lang(lang)
    listing = await db.listings.find_one({"_id": listing_id})
    cached = None if refresh else await db.car_details.find_one({"_id": listing_id})

    if not cached:
        detail = await encar.detail(listing_id)
        if not detail:
            raise HTTPException(status_code=404, detail="listing not found upstream")
        vid = detail.get("vehicleId") or listing_id
        vno = detail.get("vehicleNo") or ""
        # all four documents in parallel - previously sequential, which cost
        # ~1.2s of forced pacing each
        record, inspection_raw, diagnosis_raw, choice = await asyncio.gather(
            encar.record(vid, vno),
            encar.inspection(vid),
            encar.diagnosis(vid),
            encar.choice_options(vid),
            return_exceptions=True,
        )
        clean = lambda v: None if isinstance(v, Exception) else v  # noqa: E731
        cached = {
            "_id": listing_id,
            "vehicle_id": vid,
            "vehicle_no": vno,
            "detail": detail,
            "record": clean(record),
            "inspection": clean(inspection_raw),
            "diagnosis": clean(diagnosis_raw),
            "choice_options": clean(choice) or [],
            "fetched_at": datetime.now(timezone.utc),
        }
        await db.car_details.update_one({"_id": listing_id}, {"$set": cached}, upsert=True)

    detail = cached.get("detail") or {}
    cat = detail.get("category") or {}
    spec = detail.get("spec") or {}
    adv = detail.get("advertisement") or {}
    opts = detail.get("options") or {}

    # ── photos: every one, at gallery and thumbnail size ─────────────────────────
    photos = []
    raw_photos = sorted(
        (detail.get("photos") or []),
        key=lambda x: int(str(x.get("code") or "999").strip() or 999),
    )  # Encar returns these shuffled; ascending code matches the real ad order
    for p in raw_photos:
        path = p.get("path")
        if not path:
            continue
        photos.append({
            "full": image_url(path, 1280, 720),
            "thumb": image_url(path, 256, 144),
            "type": p.get("type"),
        })

    # ── options resolved from the dictionaries and grouped by category ───────────
    dicts = await option_dicts_cached()
    smap, tmap_opt, metas = dicts["standard"], dicts["tuning"], dicts["metas"]
    cmap = {o["optionCd"]: o for o in (cached.get("choice_options") or [])}

    ko_names = []
    groups = {}
    for code in opts.get("standard") or []:
        o = smap.get(code)
        if o:
            g = metas.get(o.get("optionTypeCd")) or "\uae30\ud0c0"
            groups.setdefault(g, []).append(o["optionName"])
            ko_names.append(o["optionName"])
    factory = []
    for code in opts.get("choice") or []:
        o = cmap.get(code)
        if o:
            factory.append({"name": o["optionName"], "price_manwon": o.get("price"),
                            "description": o.get("description")})
            ko_names.append(o["optionName"])
    tuning = []
    for code in opts.get("tuning") or []:
        o = tmap_opt.get(code)
        if o:
            tuning.append(o["optionName"])
            ko_names.append(o["optionName"])

    # option names are a bounded set -> translate once, then always cached
    ko_names += [g for g in groups]
    ko_names += [v for v in [spec.get("fuelName"), spec.get("colorName"),
                             spec.get("bodyName"), spec.get("transmissionName"),
                             cat.get("manufacturerName"), cat.get("modelName"),
                             cat.get("gradeName")] if v]
    tr = await translate_cached_only(db, ko_names, lang)
    miss = [x for x in ko_names if x and x.strip() not in tr]
    if miss:
        schedule_translation(db, list(dict.fromkeys(miss)), lang)

    # Make and model must NEVER render as Korean, so unlike the rest of the page they
    # are translated synchronously on a cache miss. It is a tiny, bounded set (two
    # strings) and it is cached forever after the first car of that model.
    always = [v for v in (cat.get("manufacturerName"), cat.get("modelName")) if v]
    if always:
        try:
            tr.update(await translate_many(db, always, lang))
        except Exception as e:
            log.warning("make/model translation failed: %s", str(e)[:160])

    def T(v):
        return tr.get((v or "").strip(), v) if v else v

    # ── insurance history ("\ubcf4\ud5d8\uc774\ub825") ─────────────────────────────────────────────
    rec = cached.get("record") or {}
    insurance = None
    if rec:
        insurance = {
            "available": True,
            "own_accidents": rec.get("myAccidentCnt"),
            "other_accidents": rec.get("otherAccidentCnt"),
            "total_accidents": rec.get("accidentCnt"),
            "own_accident_cost": rec.get("myAccidentCost"),
            "other_accident_cost": rec.get("otherAccidentCost"),
            "owner_changes": rec.get("ownerChangeCnt"),
            "plate_changes": rec.get("carNoChangeCnt"),
            "total_loss": rec.get("totalLossCnt"),
            "flood_total_loss": rec.get("floodTotalLossCnt"),
            "flood_part_loss": rec.get("floodPartLossCnt"),
            "theft": rec.get("robberCnt"),
            "commercial_use": rec.get("business"),
            "government_use": rec.get("government"),
            "rental_use": rec.get("loan"),
            "first_registration": rec.get("firstDate"),
            "body_shape": T(rec.get("carShape")),
            "accident_free": (rec.get("accidentCnt") or 0) == 0,
        }

    # ── inspection sheet ────────────────────────────────────────────────────────
    insp = cached.get("inspection") or {}
    master = insp.get("master") or {}
    idet = master.get("detail") or {}
    inspection = None
    if insp:
        inspection = {
            "available": True,
            "accident": master.get("accdient"),
            "simple_repair": master.get("simpleRepair"),
            "mileage": idet.get("mileage"),
            "vin": idet.get("vin"),
            "motor_type": idet.get("motorType"),
            "first_registration": idet.get("firstRegistrationDate"),
            "validity_start": idet.get("validityStartDate"),
            "validity_end": idet.get("validityEndDate"),
            "guaranty": T((idet.get("guarantyType") or {}).get("title")),
            "board_state": T((idet.get("boardStateType") or {}).get("title")),
            "record_no": idet.get("recordNo"),
        }

    # ── Encar diagnosis (per-panel) ─────────────────────────────────────────────
    # Encar names panels with raw enum codes (FRONT_DOOR_LEFT); show them as words.
    diag = cached.get("diagnosis") or {}
    diagnosis = None
    if diag and (diag.get("items") or []):
        items = diag["items"]
        panels = [i for i in items if not str(i.get("name") or "").endswith("_COMMENT")]
        comments = [i for i in items if str(i.get("name") or "").endswith("_COMMENT")]
        for c in comments:                      # queue comment text for translation
            if c.get("result"):
                ko_names.append(c["result"].strip())
        if comments:
            tr.update(await translate_cached_only(
                db, [c["result"].strip() for c in comments if c.get("result")], lang))
            miss2 = [c["result"].strip() for c in comments
                     if c.get("result") and c["result"].strip() not in tr]
            if miss2:
                schedule_translation(db, miss2, lang)
        diagnosis = {
            "available": True,
            "date": diag.get("diagnosisDate"),
            "center": diag.get("reservationCenterName"),
            "total": len(panels),
            "abnormal": len([i for i in panels if i.get("resultCode") != "NORMAL"]),
            "items": [{"panel": _panel_label(i.get("name")),
                       "result_code": i.get("resultCode"),
                       "result": T(i.get("result"))} for i in panels],
            "comments": [T(c["result"].strip()) for c in comments if c.get("result")],
        }

    # ── dealer description (unique per car -> one LLM call, cached forever) ──────
    desc_ko = ((detail.get("contents") or {}).get("text") or "").strip()
    # The per-vehicle dealer description is deliberately NOT translated.
    desc_t, desc_pending = desc_ko, False

    # ── pricing ─────────────────────────────────────────────────────────────────
    price_krw = (listing or {}).get("price_krw") or (adv.get("price") or 0) * 10_000
    rates = await fx_mod.get_rates(db)
    sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
    quote = pricing.price_car(price_krw, rates["fx_krw_eur"], rates["usd_eur"],
                              sdoc.get("constants")) if price_krw else None

    # Encar reports insurance claim amounts in raw KRW, which is meaningless next to
    # the EUR prices on the rest of the page. Convert with a straight FX rate (these
    # are historical repair payouts, NOT something to run through the landed-cost
    # formula). fx_krw_eur is KRW per 1 EUR, so we divide.
    if insurance:
        krw_per_eur = rates.get("fx_krw_eur") or 0
        for src, dst in (("own_accident_cost", "own_accident_cost_eur"),
                         ("other_accident_cost", "other_accident_cost_eur")):
            v = insurance.get(src) or 0
            insurance[dst] = round(v / krw_per_eur, 2) if (v and krw_per_eur) else None
        insurance["fx_krw_eur"] = krw_per_eur

    payload = {
        "id": listing_id,
        "vehicle_id": cached.get("vehicle_id"),
        "under_contract": bool((listing or {}).get("under_contract")),
        "sales_status": (listing or {}).get("sales_status") or adv.get("status"),
        "active": bool((listing or {}).get("active", True)),
        "title": " ".join(filter(None, [T(cat.get("manufacturerName")),
                                        T(cat.get("modelName"))])),
        "manufacturer": T(cat.get("manufacturerName")),
        "model": T(cat.get("modelName")),
        "grade": T(cat.get("gradeName")) or cat.get("gradeEnglishName"),
        "badge_detail": (listing or {}).get("badge_detail"),
        "year_month": cat.get("yearMonth"),
        "form_year": cat.get("formYear"),
        "origin_price_manwon": cat.get("originPrice"),
        "spec": {
            "mileage": spec.get("mileage"),
            "displacement": spec.get("displacement"),
            "transmission": T(spec.get("transmissionName")),
            "fuel": T(spec.get("fuelName")),
            "colour": T(spec.get("colorName")),
            "seats": spec.get("seatCount"),
            "body": T(spec.get("bodyName")),
            "vin": detail.get("vin"),
        },
        "photos": photos,
        "photo_count": len(photos),
        "options": {
            "groups": [{"category": T(g), "items": [T(x) for x in items]}
                       for g, items in groups.items()],
            "factory": [{**f, "name": T(f["name"])} for f in factory],
            "tuning": [T(x) for x in tuning],
            "total": len(ko_names),
        },
        "description": desc_t or desc_ko,
        "description_original": desc_ko,
        "description_pending": desc_pending,
        "insurance": insurance,
        "inspection": inspection,
        "diagnosis": diagnosis,
        "quote": quote,
        "fetched_at": cached.get("fetched_at"),
        "lang": lang,
    }

    # Catch every remaining Korean string anywhere in the payload (insurance,
    # inspection, diagnosis, equipment/options, spec, category ...).
    #
    # This resolves SYNCHRONOUSLY: a detail page must never show Hangul in the spec
    # sheet, inspection report, insurance history or equipment list. These are bounded
    # enumerations shared across the whole catalogue, so a car is only slow the first
    # time an unseen phrase appears; afterwards it is a pure cache hit. Anything beyond
    # the cap is still filled in the background so the next view is complete.
    leftovers = set()
    collect_korean(payload, leftovers)
    if leftovers:
        tmap = dict(tr)
        pending = [x for x in leftovers if x not in tmap]
        if pending:
            head, tail = pending[:SYNC_TRANSLATE_CAP], pending[SYNC_TRANSLATE_CAP:]
            try:
                tmap.update(await translate_many(db, head, lang))
            except Exception as e:
                log.warning("detail translation failed: %s", str(e)[:160])
                tail = pending
            if tail:
                schedule_translation(db, tail, lang)
        payload = apply_translations(payload, tmap)

    return jsonable(payload)


@api.get("/pricing/quote")
async def pricing_quote(price_krw: float = Query(..., gt=0)):
    """Full landed-cost breakdown for a KRW price - drives the detail-page panel."""
    rates = await fx_mod.get_rates(db)
    sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
    return jsonable(pricing.price_car(price_krw, rates["fx_krw_eur"], rates["usd_eur"],
                                      sdoc.get("constants")))


@api.get("/settings")
async def get_settings():
    doc = await db.settings.find_one({"_id": "pricing"}) or {}
    return jsonable({
        "constants": pricing.merge_settings(doc.get("constants")),
        "defaults": pricing.DEFAULT_SETTINGS,
        "fx_overrides": doc.get("fx_overrides") or {},
        "last_repriced_at": doc.get("last_repriced_at"),
        "last_repriced_count": doc.get("last_repriced_count"),
    })


class SettingsBody(BaseModel):
    constants: dict = Field(default_factory=dict)
    fx_overrides: dict = Field(default_factory=dict)
    reprice: bool = True


def _panel_label(name):
    """FRONT_DOOR_LEFT -> 'Front door left'. Encar's raw enum codes are not something
    to show a buyer."""
    s = (name or "").replace("_", " ").strip().lower()
    return s[:1].upper() + s[1:]


def _check_admin(token):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="bad admin token")


async def _require_admin(request: Request, token: str = ""):
    """Admin access via a signed-in admin account (the normal path, per the login
    requirement) or the pre-existing header token (for scripts/curl)."""
    if token and token == ADMIN_TOKEN:
        return None
    user = await auth.optional_user(request)
    if not (user and user.get("is_admin")):
        raise HTTPException(status_code=401, detail="administrator sign-in required")
    return user


@api.put("/settings")
async def put_settings(body: SettingsBody, request: Request,
                       x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    clean = {}
    for k, v in (body.constants or {}).items():
        if k not in pricing.DEFAULT_SETTINGS:
            continue
        clean[k] = bool(v) if k == "VAT_RECLAIMABLE" else float(v)

    fxo = {}
    for k, v in (body.fx_overrides or {}).items():
        if k in ("fx_krw_eur", "usd_eur", "eur_ron") and v not in (None, "", 0):
            fxo[k] = float(v)

    await db.settings.update_one(
        {"_id": "pricing"},
        {"$set": {"constants": clean, "fx_overrides": fxo,
                  "updated_at": datetime.now(timezone.utc)}},
        upsert=True)

    repriced = await sync_mod.reprice_all(db) if body.reprice else 0
    return {"ok": True, "constants": pricing.merge_settings(clean),
            "fx_overrides": fxo, "repriced": repriced}


@api.get("/admin/overview")
async def admin_overview(request: Request, x_admin_token: str = Header(default="")):
    """Everything the operator needs on one screen: index size, crawl progress,
    translation cache health and the enquiry backlog."""
    await _require_admin(request, x_admin_token)
    state = await sync_mod.get_state(db)
    partition = await db.sync_state.find_one({"_id": "catalogue_partition"}) or {}
    tax = await db.sync_state.find_one({"_id": "taxonomy"}) or {}
    return jsonable({
        "listings_total": await db.listings.count_documents({}),
        "listings_active": await db.listings.count_documents({"active": True}),
        "unique_cars": await db.listings.count_documents(
            {"active": True, "duplicate": {"$ne": True}}),
        "duplicate_ads_hidden": await db.listings.count_documents(
            {"active": True, "duplicate": True}),
        "upstream": await upstream_size_cached(),
        "translations_cached": await db.translations.count_documents({}),
        "translation_breaker": breaker_status(),
        "taxonomy": {"nodes": tax.get("nodes", 0), "built_at": tax.get("built_at")},
        "sync": {k: v for k, v in state.items() if k != "_id"},
        "partition": {k: v for k, v in partition.items() if k != "_id"},
        "encar_stats": dict(encar.stats),
        "enquiries": {
            "total": await db.enquiries.count_documents({}),
            "new": await db.enquiries.count_documents({"status": "new"}),
        },
        "email": mailer.status(),
    })


@api.get("/admin/coverage")
async def admin_coverage(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    data = await sync_mod.get_brand_coverage(db)
    # brand keys are Korean in the index; the operator should not have to read Hangul
    brands = data.get("brands") or []
    labels = await translate_cached_only(db, [b["make"] for b in brands], "en")
    for b in brands:
        b["label"] = labels.get(b["make"], b["make"])
    return jsonable(data)


@api.post("/admin/coverage/refresh")
async def admin_coverage_refresh(request: Request, x_admin_token: str = Header(default="")):
    """One upstream count per brand takes a couple of minutes, so it runs detached and
    the dashboard polls /admin/coverage for progress."""
    await _require_admin(request, x_admin_token)
    asyncio.get_running_loop().create_task(sync_mod.refresh_brand_coverage(db))
    return {"started": True}


ENQUIRY_STATUSES = ("new", "contacted", "closed")


@api.get("/admin/enquiries")
async def admin_enquiries(request: Request, status: str = "", q: str = "",
                          page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                          x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    query = {}
    if status in ENQUIRY_STATUSES:
        query["status"] = status
    if q.strip():
        rx = re.escape(q.strip())
        query["$or"] = [{f: {"$regex": rx, "$options": "i"}}
                        for f in ("car_title", "name", "email", "phone", "message",
                                  "listing_id")]
    total = await db.enquiries.count_documents(query)
    rows = [d async for d in db.enquiries.find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)]
    for r in rows:
        r["id"] = r.pop("_id")
    counts = {s: await db.enquiries.count_documents({"status": s})
              for s in ENQUIRY_STATUSES}
    return jsonable({"total": total, "page": page, "page_size": page_size,
                     "pages": max(1, -(-total // page_size)),
                     "counts": counts, "items": rows})


class EnquiryStatusBody(BaseModel):
    status: str


@api.patch("/admin/enquiries/{enquiry_id}")
async def admin_enquiry_status(enquiry_id: str, body: EnquiryStatusBody, request: Request,
                               x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    if body.status not in ENQUIRY_STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(ENQUIRY_STATUSES)}")
    res = await db.enquiries.update_one(
        {"_id": enquiry_id},
        {"$set": {"status": body.status, "updated_at": datetime.now(timezone.utc)}})
    if not res.matched_count:
        raise HTTPException(404, "no such enquiry")
    return {"ok": True, "status": body.status}


@api.post("/admin/sync")
async def admin_sync(max_pages: int | None = None, x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    return await sync_mod.run_full_sync(db, max_pages=max_pages)


@api.get("/admin/sync/status")
async def admin_sync_status():
    state = await sync_mod.get_state(db)
    return jsonable({**{k: v for k, v in state.items() if k != "_id"},
                     "encar_stats": dict(encar.stats)})


@api.post("/admin/reprice")
async def admin_reprice(x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    return {"repriced": await sync_mod.reprice_all(db)}


@api.post("/admin/dedupe")
async def admin_dedupe(x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    return await sync_mod.dedupe_pass(db)


@api.post("/admin/warm-translations")
async def admin_warm(x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    from translate import warm_translations
    return await warm_translations(db)


class TranslateBody(BaseModel):
    texts: list[str]
    lang: str = "bg"


@api.post("/translate")
async def translate_endpoint(body: TranslateBody):
    return await translate_many(db, body.texts[:400], norm_lang(body.lang))


class EnquiryBody(BaseModel):
    listing_id: str = ""
    car_title: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""
    lang: str = "bg"


@api.post("/enquiry")
async def create_enquiry(body: EnquiryBody, request: Request):
    """Buyer enquiry about one car. Works for GUESTS as well as signed-in users - the
    account only pre-fills the contact details, it is never required to make contact."""
    user = await auth.optional_user(request)
    email = (body.email or (user or {}).get("email") or "").strip().lower()
    phone = body.phone.strip()
    if not email and not phone:
        raise HTTPException(400, "please leave an email address or a phone number")

    doc = {
        "_id": str(uuid.uuid4()),
        "listing_id": body.listing_id,
        "car_title": body.car_title[:200],
        "name": (body.name or (user or {}).get("name") or "").strip()[:120],
        "email": email[:200],
        "phone": phone[:60],
        "message": body.message.strip()[:4000],
        "lang": norm_lang(body.lang),
        "user_id": (user or {}).get("_id"),
        "is_guest": user is None,
        "status": "new",
        "created_at": datetime.now(timezone.utc),
    }
    await db.enquiries.insert_one(doc)
    log.info("enquiry %s for listing %s (guest=%s)", doc["_id"], doc["listing_id"],
             doc["is_guest"])
    mailer.send_enquiry_emails(doc)
    return {"ok": True, "id": doc["_id"]}


auth.set_db(db)
api.include_router(auth.router)
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.environ.get("CORS_ORIGINS", "*").split(",")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    await sync_mod.ensure_indexes(db)
    await auth.ensure_indexes(db)
    if not await db.settings.find_one({"_id": "pricing"}):
        await db.settings.update_one(
            {"_id": "pricing"},
            {"$set": {"constants": {}, "fx_overrides": {},
                      "created_at": datetime.now(timezone.utc)}},
            upsert=True)
    log.info("startup complete: %s listings in index",
             await db.listings.count_documents({}))


@app.on_event("shutdown")
async def on_shutdown():
    await encar.close()
    client.close()
