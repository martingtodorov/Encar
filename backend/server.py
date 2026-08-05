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
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (APIRouter, Depends, FastAPI, Header, HTTPException, Query,
                     Request)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import auth                  # noqa: E402
import archive                # noqa: E402
import deposits              # noqa: E402
import notify                # noqa: E402
import fx as fx_mod          # noqa: E402
import mailer                # noqa: E402
import pricing               # noqa: E402
import slugs as slugs_mod    # noqa: E402
import syncjob as syncjob_mod  # noqa: E402
import pricewatch as pricewatch_mod  # noqa: E402
import edi                  # noqa: E402
import jsoncargo            # noqa: E402
import maersk_public        # noqa: E402
import tracking             # noqa: E402
import curate               # noqa: E402
import sync as sync_mod      # noqa: E402
from encar import encar, image_url, detail_photo_paths  # noqa: E402
from translate import (LANGS, breaker_status, schedule_translation,  # noqa: E402
                       stream_description, translate_cached_only,
                       translate_listings, translate_many, translate_one)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "encar_skin")
# No default: an unset ADMIN_TOKEN disables header-token admin access entirely rather
# than leaving a guessable master key in the tree.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

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
        "model_t": curate.display(2, doc.get("model"), doc.get("model_t")),
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
        # every photo we hold, so the card can be swiped without opening the car
        "images": [image_url(p, 640, 360) for p in photos],
        "has_inspection": bool(doc.get("has_inspection")),
        "has_record": bool(doc.get("has_record")),
        "diagnosed": bool(doc.get("diagnosed")),
        "active": bool(doc.get("active", True)),
        "first_seen": jsonable(doc.get("first_seen")),
    }


async def publish_prices(items):
    """Make the list price and the car-page price agree, keeping the HIGHER one.

    Rows carry a `sale_eur` precomputed at the last reprice, while the car page quotes
    live FX. Between the two the rate drifts, and after charm rounding that shows up as a
    price that changes by ~EUR 100 when the buyer clicks the ad. Owner's rule: publish the
    higher figure, so an advertised price is never undercut by the page behind it.
    """
    rates = await fx_mod.get_rates(db)
    sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
    S = pricing.merge_settings(sdoc.get("constants"))
    for it in items:
        krw = it.get("price_krw")
        if not krw:
            continue
        landed, live = pricing.quick_sale_eur(krw, rates["fx_krw_eur"], rates["usd_eur"], S)
        if live > (it.get("sale_eur") or 0):
            it["sale_eur"] = live
            if it.get("landed_eur") is not None:
                it["landed_eur"] = round(landed, 2)
    return rates, sdoc


def build_query(p):
    """Translate request filters into a Mongo query."""
    # duplicate ads for the same physical car are hidden (see sync.dedupe_pass)
    # under contract on Encar means effectively sold: never shown, never crawled again
    q = {"active": True, "duplicate": {"$ne": True}, "under_contract": {"$ne": True}}

    if p.get("makes"):
        q["manufacturer"] = {"$in": p["makes"]}
    # A model or trim the owner merged others into must return their cars too (curate.py).
    if p.get("models"):
        q["model"] = {"$in": curate.expand(2, p["models"])}
    if p.get("badges"):
        q["badge"] = {"$in": curate.expand(3, p["badges"])}
    if p.get("badge_details"):
        q["badge_detail"] = {"$in": curate.expand(4, p["badge_details"])}
    if p.get("fuels"):
        q["fuel_type"] = {"$in": p["fuels"]}
    if p.get("regions"):
        q["region"] = {"$in": p["regions"]}
    if p.get("transmissions"):
        q["transmission"] = {"$in": p["transmissions"]}

    # Filter on the REGISTRATION date (year_month), not Encar's model year: a car sold as a
    # 2015 model can be registered 12/2014, and the cards show the registration date. With
    # form_year here, "from 2015" was listing cars that display 12/2014.
    year = {}
    if p.get("year_min"):
        year["$gte"] = int(p["year_min"]) * 100 + 1
    if p.get("year_max"):
        year["$lte"] = int(p["year_max"]) * 100 + 12
    if year:
        q["year_month"] = year

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


RELEVANT_POOL = 600

SORTS = {
    "newest": [("recency", 1)],
    "price_asc": [("sale_eur", 1)],
    "price_desc": [("sale_eur", -1)],
    "mileage_asc": [("mileage", 1)],
    "year_desc": [("year_month", -1)],
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


class ListingIdsBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


@api.post("/listings/by-ids")
async def listings_by_ids(body: ListingIdsBody, lang: str = "bg"):
    """Grid rows for a known set of ids, straight from our own index.

    The saved-cars page used to call /car/{id} per favourite, which fetches the detail,
    insurance, inspection and diagnosis documents from Encar upstream - seconds of
    waiting for data the grid never shows. Everything the grid needs already lives in
    our listings collection.
    """
    ids = [str(i) for i in body.ids[:200] if i]
    if not ids:
        return {"items": []}
    lang = norm_lang(lang)
    docs = {d["_id"]: d async for d in db.listings.find({"_id": {"$in": ids}})}
    rows = [docs[i] for i in ids if i in docs]          # keep the caller's order
    await translate_listings(db, rows, lang)
    items = [listing_out(r) for r in rows]
    await publish_prices(items)
    return {"items": items}


@api.post("/car/{listing_id}/translate-description")
async def translate_description(listing_id: str, lang: str = "bg"):
    """Translate ONE dealer description, on demand.

    These are long, unique per car and most visitors never read them, so translating
    them on page load would burn an LLM call per car view for nothing. The visitor asks
    for it with a button; the result is cached permanently like every other string, so
    the second person to ask pays nothing.
    """
    lang = norm_lang(lang)
    cached = await db.car_details.find_one({"_id": listing_id})
    text = (((cached or {}).get("detail") or {}).get("contents") or {}).get("text") or ""
    text = text.strip()
    if not text:
        raise HTTPException(404, "this car has no dealer description")
    out = await translate_many(db, [text], lang)
    translated = out.get(text)
    if not translated or translated == text:
        raise HTTPException(503, "translation is unavailable right now, please try again")
    return {"text": translated, "lang": lang}


def _sse(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@api.get("/car/{listing_id}/translate-description/stream")
async def translate_description_stream(listing_id: str, lang: str = "bg"):
    """Same translation as the POST route, streamed.

    Descriptions take 10-20s to generate because output length is the bottleneck, so the
    text is pushed out as it arrives instead of after it is finished. A cached
    translation is sent as a single event immediately.
    """
    lang = norm_lang(lang)
    cached = await db.car_details.find_one({"_id": listing_id})
    text = (((cached or {}).get("detail") or {}).get("contents") or {}).get("text") or ""
    text = text.strip()
    if not text:
        raise HTTPException(404, "this car has no dealer description")

    async def events():
        hit = await translate_cached_only(db, [text], lang)
        if hit.get(text):
            yield _sse({"chunk": hit[text]})
            yield _sse({"done": True, "cached": True})
            return
        try:
            async for piece in stream_description(db, text, lang):
                yield _sse({"chunk": piece})
            yield _sse({"done": True, "cached": False})
        except Exception as e:
            log.warning("description stream failed for %s: %s", listing_id, str(e)[:200])
            yield _sse({"error": "translation is unavailable right now"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",   # stop nginx-style proxies holding the stream back
    })


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


class TasteBody(BaseModel):
    """What a visitor's browser learned about them. Sent per request, never stored."""
    makes: dict[str, float] = Field(default_factory=dict)
    models: dict[str, float] = Field(default_factory=dict)
    fuels: dict[str, float] = Field(default_factory=dict)
    samples: list[list[float]] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    limit: int = 12
    lang: str = "bg"


def _weights(raw, keep=6):
    """Trust nothing from the client: cap the size and clamp every weight."""
    clean = {}
    for key, value in list(raw.items())[:24]:
        name = str(key).strip()[:60]
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if name and 0 < weight:
            clean[name] = min(weight, 50.0)
    return dict(sorted(clean.items(), key=lambda kv: -kv[1])[:keep])


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
    taste: TasteBody | None = None


VIEW_WINDOW_DAYS = int(os.environ.get("VIEW_WINDOW_DAYS", "14"))
_popular = {"at": 0.0, "ids": []}


@api.post("/car/{listing_id}/view")
async def car_view(listing_id: str):
    """Count a real open of an ad.

    Counted from the detail page rather than from the GET, because hovering a card
    pre-fetches the same endpoint and a hover is not interest. One document per ad per day,
    so the popularity window can be trimmed by simply dropping old days.
    """
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await db.car_views.update_one(
        {"_id": f"{listing_id}:{day}"},
        {"$inc": {"n": 1}, "$set": {"car_id": listing_id, "day": day}}, upsert=True)
    return {"ok": True}


async def popular_ids(limit=RELEVANT_POOL):
    """The most opened ads of the last two weeks, most popular first.

    This is what "relevant" means for someone we know nothing about yet: not the newest car
    in the country, but the one everyone else is looking at. Recomputed at most every five
    minutes — it does not need to be to the second.
    """
    if _popular["ids"] and time.time() - _popular["at"] < 300:
        return _popular["ids"][:limit]
    since = (datetime.now(timezone.utc) - timedelta(days=VIEW_WINDOW_DAYS)).strftime("%Y-%m-%d")
    rows = await db.car_views.aggregate([
        {"$match": {"day": {"$gte": since}}},
        {"$group": {"_id": "$car_id", "n": {"$sum": "$n"}}},
        {"$sort": {"n": -1}},
        {"$limit": RELEVANT_POOL},
    ]).to_list(RELEVANT_POOL)
    _popular["ids"] = [r["_id"] for r in rows]
    _popular["at"] = time.time()
    return _popular["ids"][:limit]


async def _profile(request: Request, sent):
    """The profile to rank by: what the browser sent, else what the account remembers."""
    if sent and (sent.makes or sent.models):
        return sent.makes, sent.models, sent.fuels, sent.samples
    try:
        user = await auth.optional_user(request)
    except Exception:
        user = None
    stored = (user or {}).get("taste") or {}
    return (stored.get("makes") or {}, stored.get("models") or {},
            stored.get("fuels") or {}, stored.get("samples") or [])


SEARCH_KEYS = ("q", "makes", "models", "badges", "badge_details", "fuels",
               "price_min", "price_max", "year_min", "year_max",
               "mileage_min", "mileage_max")


async def _remember_search(request, p):
    """Keep the last REAL search of a signed-in buyer.

    An operator ringing a customer wants to open with what that customer was just looking
    for, not with a guess. An empty query (the plain home page) is not worth remembering.
    """
    kept = {k: p.get(k) for k in SEARCH_KEYS if p.get(k)}
    if not kept:
        return
    try:
        user = await auth.optional_user(request)
    except Exception:
        user = None
    if not user:
        return
    kept["at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_search": kept}})


@api.post("/search")
async def search(body: SearchBody, request: Request):
    lang = norm_lang(body.lang)
    p = body.model_dump()
    await curate.refresh(db)
    query = build_query(p)
    sort = SORTS.get(body.sort, SORTS["newest"])

    page = max(1, int(body.page))
    size = min(max(1, int(body.page_size)), 96)
    skip = (page - 1) * size

    if page == 1:
        await _remember_search(request, p)

    total = await db.listings.count_documents(query)

    rows = None
    if body.sort == "relevant":
        # Ranking by taste cannot be expressed as a Mongo sort, so a bounded pool of the
        # freshest matches is scored in memory. Deeper pages fall back to newest.
        makes, models, fuels, samples = await _profile(request, body.taste)
        makes, models, fuels = _weights(makes, 4), _weights(models, 6), _weights(fuels, 4)
        if (makes or models) and skip < RELEVANT_POOL:
            pool = [d async for d in
                    db.listings.find(query).sort(SORTS["newest"]).limit(RELEVANT_POOL)]
            price, _, _ = _centre(samples, 0)
            mileage, _, _ = _centre(samples, 1)
            scored = _rank_by_taste(pool, makes, models, fuels, price, mileage)
            # Diversity decides the ORDER, never the contents. The per-model and per-make
            # caps used to DROP the cars they rejected, so a search showed only a slice of
            # its own results; those cars now simply queue up behind the picked ones.
            picked = _space(_spread(scored, len(scored), per_model=2,
                                    per_make=max(2, size // 4)))
            taken = {d["_id"] for _, _, d in picked}
            head = ([d for _, _, d in picked]
                    + [d for _, _, d in scored if d["_id"] not in taken])
            rows = head[skip:skip + size]
            if len(rows) < size and len(head) >= RELEVANT_POOL:
                # The pool is exactly the newest RELEVANT_POOL matches, so the rest of the
                # result set continues right after it — no risk of repeating a car.
                fill = db.listings.find(query).sort(SORTS["newest"]) \
                    .skip(len(head)).limit(size - len(rows))
                rows += [d async for d in fill]
        elif skip >= RELEVANT_POOL:
            cursor = db.listings.find(query).sort(SORTS["newest"]).skip(skip).limit(size)
            rows = [d async for d in cursor]
        else:
            # Nothing known about this visitor yet: show what everyone else has been
            # opening for the last two weeks instead of a bare "newest" list.
            ids = await popular_ids()
            if ids:
                hot = {d["_id"]: d async for d in
                       db.listings.find({**query, "_id": {"$in": ids}})}
                ordered = [hot[i] for i in ids if i in hot]
                rows = ordered[skip:skip + size]
                if len(rows) < size:
                    # Top up with the newest ads the popular list did not cover.
                    seen = {d["_id"] for d in ordered}
                    fill = db.listings.find({**query, "_id": {"$nin": list(seen)[:500]}}) \
                        .sort(SORTS["newest"]).limit(size - len(rows))
                    rows += [d async for d in fill]

    if rows is None:
        cursor = db.listings.find(query).sort(sort).skip(skip).limit(size)
        rows = [d async for d in cursor]

    await translate_listings(db, rows, lang)
    items = [listing_out(d) for d in rows]
    await publish_prices(items)

    # Landed cost is business data: stripped for everyone, then handed back to signed-in
    # admins as the two-scenario range they want to see on every ad.
    if await _is_admin_request(request):
        rates = await fx_mod.get_rates(db)
        sdoc = await db.settings.find_one({"_id": "pricing"}) or {}
        for it in items:
            krw = it.get("price_krw")
            if not krw:
                continue
            q = pricing.price_car(krw, rates["fx_krw_eur"], rates["usd_eur"],
                                  sdoc.get("constants"))
            q["suggested_sale"] = max(q["suggested_sale"], it.get("sale_eur") or 0)
            it["admin"] = pricing.admin_range(q)
    else:
        for it in items:
            it.pop("landed_eur", None)

    return {
        "total": total,
        "page": page,
        "page_size": size,
        "pages": (total + size - 1) // size,
        "items": items,
        "lang": lang,
    }


def _centre(samples, slot):
    """The middle of what the buyer keeps looking at, weighted by how long they looked.

    A plain mean would let one curious click at €90,000 drag the whole profile upwards, so
    the samples are weighted and the top and bottom thirds are allowed to define a RANGE
    rather than being averaged away.
    """
    rows = [(float(s[slot]), float(s[2]) if len(s) > 2 else 1.0)
            for s in samples if isinstance(s, (list, tuple)) and len(s) > slot
            and _positive(s[slot])]
    if not rows:
        return None, None, None
    rows.sort(key=lambda r: r[0])
    total = sum(w for _, w in rows) or 1.0
    running, centre = 0.0, rows[-1][0]
    for value, weight in rows:
        running += weight
        if running >= total / 2:
            centre = value
            break
    return centre, rows[0][0], rows[-1][0]


def _positive(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _rank_by_taste(rows, makes, models, fuels, price, mileage):
    """Score candidates against a profile. Returns [(score, why, doc)] highest first.

    A model match counts for far more than its make, fuel is a mild preference, and distance
    from the buyer's price and mileage is a PENALTY rather than a filter — so a slightly
    dearer or higher-mileage car can still win on the rest of its merits.
    """
    scale_make = max(makes.values()) if makes else 1
    scale_model = max(models.values()) if models else 1
    scale_fuel = max(fuels.values()) if fuels else 1

    scored = []
    for doc in rows:
        model_w = models.get(doc.get("model") or "", 0) / scale_model
        make_w = makes.get(doc.get("manufacturer") or "", 0) / scale_make
        fuel_w = fuels.get(doc.get("fuel_type") or "", 0) / scale_fuel
        score = 6 * model_w + 3 * make_w + 1.5 * fuel_w

        if price and doc.get("sale_eur"):
            score -= 2.5 * min(1.0, abs(doc["sale_eur"] - price) / price)
        if mileage and doc.get("mileage"):
            score -= 1.5 * min(1.0, abs(doc["mileage"] - mileage) / max(mileage, 1))
        # A nudge for the freshest ads, never enough to outrank a real preference.
        score += 0.4 if (doc.get("recency") or 999) < 50 else 0

        scored.append((score, "model" if model_w else "make" if make_w else "", doc))

    scored.sort(key=lambda s: -s[0])
    return scored


def _spread(scored, limit, per_model=3, per_make=6):
    """A shelf of near-identical cars is not a choice: cap how many share a model, and cap
    the make too — a buyer who looked at three Mercedes should not be handed a page of
    nothing but Mercedes."""
    out, models, makes = [], {}, {}
    for row in scored:
        model = row[2].get("model") or ""
        make = row[2].get("manufacturer") or ""
        if models.get(model, 0) >= per_model or makes.get(make, 0) >= per_make:
            continue
        models[model] = models.get(model, 0) + 1
        makes[make] = makes.get(make, 0) + 1
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _why_label(out, why):
    if why == "model":
        return out.get("model_t") or out.get("model") or ""
    if why == "make":
        return out.get("manufacturer_t") or out.get("manufacturer") or ""
    return ""


def _space(scored, gap=2):
    """Keep the ranking, but never let one brand sit within `gap` places of itself.

    A strict round-robin across makes is the opposite mistake: it hands out exactly one car
    per brand and buries the preference the ranking just found. This only breaks up RUNS, so
    a favourite make still comes back every few rows.
    """
    pool, out = list(scored), []
    while pool:
        recent = {(r[2].get("manufacturer") or "") for r in out[-gap:]}
        pick = next((i for i, row in enumerate(pool)
                     if (row[2].get("manufacturer") or "") not in recent), 0)
        out.append(pool.pop(pick))
    return out


async def _popular_shelf(lang, exclude, limit):
    """What to show someone we know nothing about yet: the most opened ads of the fortnight.

    The profile lives in a cookie, so a buyer who browsed on a laptop arrives on their phone
    with an empty one. An empty shelf there reads as a broken page, and the popular list is
    an honest answer to "what should I look at".
    """
    ids = [i for i in await popular_ids() if i not in set(exclude or [])]
    if not ids:
        return []
    query = build_query({})
    query["_id"] = {"$in": ids[:limit * 3]}
    rows = [d async for d in db.listings.find(query).limit(limit * 3)]
    order = {car_id: n for n, car_id in enumerate(ids)}
    rows.sort(key=lambda d: order.get(d["_id"], 10**6))
    rows = rows[:limit]
    await translate_listings(db, rows, lang)
    items = [listing_out(d) for d in rows]
    await publish_prices(items)
    for it in items:
        it.pop("landed_eur", None)
    return items


@api.post("/recommendations")
async def recommendations(body: TasteBody, request: Request):
    """Cars this visitor is most likely to want next."""
    lang = norm_lang(body.lang)
    makes = _weights(body.makes, 4)
    models = _weights(body.models, 6)
    fuels = _weights(body.fuels, 4)
    limit = max(1, min(body.limit, 24))
    if not makes and not models:
        return {"items": await _popular_shelf(lang, body.exclude, limit),
                "lang": lang, "source": "popular"}

    price, price_low, price_high = _centre(body.samples, 0)
    mileage, _, _ = _centre(body.samples, 1)

    query = build_query({})
    ors = []
    if makes:
        ors.append({"manufacturer": {"$in": list(makes)}})
    if models:
        ors.append({"model": {"$in": list(models)}})
    query["$or"] = ors
    if body.exclude:
        query["_id"] = {"$nin": [str(x)[:64] for x in body.exclude[:60]]}
    # A generous window around the range they browse, so scoring has room to prefer the
    # closest ones without hiding a good car just outside it.
    if price_low and price_high:
        query["sale_eur"] = {"$gte": price_low * 0.7, "$lte": price_high * 1.4}

    rows = [d async for d in db.listings.find(query).sort(SORTS["newest"]).limit(300)]
    if not rows:
        return {"items": await _popular_shelf(lang, body.exclude, limit),
                "lang": lang, "source": "popular"}

    best = _space(_spread(_rank_by_taste(rows, makes, models, fuels, price, mileage),
                          max(1, min(body.limit, 24)), per_model=2, per_make=4))

    docs = [d for _, _, d in best]
    await translate_listings(db, docs, lang)
    items = []
    for (_, why, _), doc in zip(best, docs):
        out = listing_out(doc)
        out.pop("landed_eur", None)
        # Built AFTER translation, or the reason would name the car in Korean.
        out["why_label"] = _why_label(out, why)
        items.append(out)
    await publish_prices(items)
    return {"items": items, "lang": lang}


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
                "year_min": {"$min": "$year_month"},
                "year_max": {"$max": "$year_month"},
                "mileage_max": {"$max": "$mileage"},
                "price_min": {"$min": "$sale_eur"},
                "price_max": {"$max": "$sale_eur"},
            }},
        ]
        bounds = {}
        async for d in db.listings.aggregate(bounds_pipe):
            bounds = {k: v for k, v in d.items() if k != "_id"}
        # The year bounds come out as YYYYMM; the slider wants plain years.
        for key in ("year_min", "year_max"):
            if bounds.get(key):
                bounds[key] = int(bounds[key]) // 100

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
    # Marque names are proper nouns: English in every language.
    make_labels = await translate_many(db, [x["value"] for x in cached.get("makes", [])], "en")
    tmap = {**tmap, **make_labels}

    # Slugs let the query string read `?fuels=petrol` instead of percent-encoded Hangul.
    try:
        make_slugs = await slugs_mod.taxonomy_slug_map(db, 1)
        _, fuel_slugs = await slugs_mod.facet_slugs(db, "fuel")
        _, region_slugs = await slugs_mod.facet_slugs(db, "region")
    except Exception as e:
        log.warning("facet slugs unavailable: %s", str(e)[:160])
        make_slugs, fuel_slugs, region_slugs = {}, {}, {}

    def decorate(items, smap=None):
        return [{"value": i["value"], "count": i["count"],
                 "slug": (smap or {}).get(i["value"], ""),
                 "label": tmap.get(i["value"], i["value"])} for i in items]

    return {
        "makes": decorate(cached.get("makes", []), make_slugs),
        "fuels": decorate(cached.get("fuels", []), fuel_slugs),
        "regions": decorate(cached.get("regions", []), region_slugs),
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
    raw: bool = False,
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
    try:
        # URLs carry English slugs, so the tree must always have them; a rebuild swaps
        # the collection and wipes them, hence the check on every read.
        await slugs_mod.ensure_taxonomy_slugs(db)
    except Exception as e:
        log.warning("taxonomy slug fill failed: %s", str(e)[:160])

    q = {"level": level}
    if level >= 2:
        q["make"] = make
    if level >= 3:
        q["model"] = model
    if level >= 4:
        q["badge"] = badge

    rows = [
        {"value": d["value"], "count": d["count"], "slug": d.get("slug") or ""}
        async for d in db.taxonomy.find(q, {"value": 1, "count": 1, "slug": 1})
        .sort([("value", 1)])          # alphabetical, not by popularity
        .limit(limit)
    ]
    # The owner folds Encar's near-duplicate trims together and renames what reads badly
    # (curate.py). `raw=1` skips it, which is how the admin screen sees what to merge.
    await curate.refresh(db)
    try:
        await curate.ensure_years(db)
    except Exception as e:
        log.warning("model year spans failed: %s", str(e)[:160])
    if not raw:
        rows = curate.collapse(rows, level)
    values = [r["value"] for r in rows]
    # Levels 1 and 2 are marques and model names: proper nouns, always English.
    label_lang = "en" if level <= 2 else lang
    try:
        tmap = await translate_many(db, values, label_lang)
    except Exception as e:
        log.warning("taxonomy translation failed: %s", str(e)[:160])
        tmap = await translate_cached_only(db, values, label_lang)
        missing = [v for v in values if v not in tmap]
        if missing:
            schedule_translation(db, missing, label_lang)

    built = await db.sync_state.find_one({"_id": "taxonomy"})
    return {
        "level": level,
        "items": [{**r,
                   "label": curate.display(level, r["value"],
                                           tmap.get(r["value"], r["value"])),
                   "merged_into": curate.merged_into(level, r["value"]),
                   "renamed": bool(curate.label_for(level, r["value"]))}
                  for r in rows],
        "built_at": jsonable((built or {}).get("built_at")),
    }


@api.get("/meta/resolve")
async def meta_resolve(
    make: str = "",
    model: str = "",
    badge: str = "",
    badge_detail: str = "",
    fuels: str = "",
    regions: str = "",
):
    """English slugs from the URL -> the upstream Korean values the search speaks.

    Unknown tokens are echoed back untouched so links made before slugs existed, and any
    value we could not translate, still work.
    """
    try:
        await slugs_mod.ensure_taxonomy_slugs(db)
    except Exception as e:
        log.warning("taxonomy slug fill failed: %s", str(e)[:160])

    tax = await slugs_mod.resolve_taxonomy(db, make, model, badge, badge_detail)

    async def flat(dim, raw):
        tokens = [t for t in (raw or "").split("~") if t]
        if not tokens:
            return []
        by_slug, _ = await slugs_mod.facet_slugs(db, dim)
        return [by_slug.get(t, t) for t in tokens]

    return {
        "make": tax.get("make", ""),
        "model": tax.get("model", ""),
        "badge": tax.get("badge", ""),
        "badge_detail": tax.get("badge_detail", ""),
        "fuels": await flat("fuel", fuels),
        "regions": await flat("region", regions),
    }


@api.post("/admin/taxonomy/rebuild")
async def admin_taxonomy(x_admin_token: str = Header(default="")):
    _check_admin(x_admin_token)
    return await sync_mod.build_taxonomy(db)


async def _gone(listing, listing_id, lang):
    """Encar has nothing for this ad any more — it sold, or the dealer pulled it.

    A bare "not found" is a dead end for a buyer who followed a link, so the ad is retired
    from our index and the same make and model are offered in its place. 410 Gone rather
    than 404: the car existed, it simply is not coming back.
    """
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found upstream")
    await db.listings.update_one(
        {"_id": listing_id},
        {"$set": {"active": False, "sold": True,
                  "sold_at": datetime.now(timezone.utc)}})

    query = build_query({})
    query["_id"] = {"$ne": listing_id}
    if listing.get("manufacturer"):
        query["manufacturer"] = listing["manufacturer"]
    if listing.get("model"):
        query["model"] = listing["model"]
    rows = [d async for d in db.listings.find(query).sort(SORTS["newest"]).limit(12)]
    if len(rows) < 4 and query.pop("model", None):
        # Nothing left of that exact model: the make is still the closest thing we have.
        rows = [d async for d in db.listings.find(query).sort(SORTS["newest"]).limit(12)]

    await translate_listings(db, rows + [listing], lang)
    items = [listing_out(d) for d in rows]
    await publish_prices(items)
    for it in items:
        it.pop("landed_eur", None)
    return JSONResponse(status_code=410, content=jsonable({
        "sold": True,
        "id": listing_id,
        "lang": lang,
        "make": listing.get("manufacturer_t") or listing.get("manufacturer") or "",
        "model": listing.get("model_t") or listing.get("model") or "",
        "similar": items,
    }))


_DEALER_NOISE = re.compile(
    r"계좌|예금주|접수처|납부|보험료|입금|송금|문의|상담|전화|\d{2,4}-\d{2,4}-\d{3,4}"
    r"|1533|1588|☎")


def _diag_comment_parts(text):
    """The diagnosis comment, split into sentences and stripped of the dealer's own notes.

    Encar's comment is a few boilerplate sentences that repeat on thousands of cars, and
    then whatever the dealer pasted after them: a credit-union account for the warranty
    premium, an insurer's hotline, a ♣ or two. That tail is what made the WHOLE paragraph a
    unique string, so it could never be a cache hit and the buyer was left reading Korean.
    Sentence by sentence the boilerplate comes straight from the cache, and the payment
    details are dropped — nobody in Europe is wiring money to a Korean credit union.
    """
    cleaned = re.sub(r"[♣♠◆■※★]+", "\n", str(text or ""))
    cleaned = re.sub(r"《[^》]*》|\([^)]*접수[^)]*\)", "\n", cleaned)
    parts, seen = [], set()
    for line in cleaned.split("\n"):
        for seg in re.split(r"(?<=다\.)\s*|(?<=[.!?])\s+", line):
            seg = (seg or "").strip().strip("·-–,").strip()
            if len(seg) < 4 or _DEALER_NOISE.search(seg) or seg in seen:
                continue
            seen.add(seg)
            parts.append(seg)
    return parts


def _attr(s):
    return (str(s or "").replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


@api.get("/share/car/{listing_id}", response_class=HTMLResponse)
async def share_car(listing_id: str, request: Request, lang: str = "bg"):
    """A shareable link whose preview picture is the ad's own lead photo.

    Viber, Messenger, WhatsApp and Facebook never run our JavaScript, so the og:* tags the
    car page writes at runtime are invisible to them. This page carries them in the HTML
    and forwards a human straight to the car.
    """
    lang = norm_lang(lang)
    doc = await db.listings.find_one(
        {"_id": listing_id},
        {"photos": 1, "manufacturer": 1, "model": 1, "manufacturer_t": 1, "model_t": 1,
         "badge_detail": 1, "year_month": 1, "mileage": 1, "sale_eur": 1})
    photos = (doc or {}).get("photos") or []
    # Makes and models are proper nouns: translate_listings resolves them from the ENGLISH
    # cache, so a shared link never shows the Korean model name.
    if doc:
        await translate_listings(db, [doc], lang, fields=("manufacturer", "model"))
    title = " ".join(filter(None, [
        (doc or {}).get("manufacturer_t") or (doc or {}).get("manufacturer"),
        (doc or {}).get("model_t") or (doc or {}).get("model"),
    ])) or "Europe Encar"
    ym = str((doc or {}).get("year_month") or "")
    facts = [f"{ym[4:6]}/{ym[:4]}" if len(ym) >= 6 else "",
             f"{(doc or {}).get('mileage'):,} km".replace(",", " ")
             if (doc or {}).get("mileage") else "",
             f"€{(doc or {}).get('sale_eur'):,.0f}".replace(",", " ")
             if (doc or {}).get("sale_eur") else ""]
    description = " · ".join([f for f in facts if f])
    # 1200x630 is what every chat app and social network crops to.
    image = image_url(photos[0], 1200, 630) if photos else ""
    base = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/") \
        or str(request.base_url).rstrip("/")
    target = f"{base}/{lang}/car/{listing_id}"

    tags = [f'<meta property="og:title" content="{_attr(title)}">',
            f'<meta property="og:description" content="{_attr(description)}">',
            f'<meta property="og:url" content="{_attr(target)}">',
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="Europe Encar">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{_attr(title)}">',
            f'<meta name="twitter:description" content="{_attr(description)}">']
    if image:
        tags += [f'<meta property="og:image" content="{_attr(image)}">',
                 f'<meta property="og:image:secure_url" content="{_attr(image)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 f'<meta property="og:image:alt" content="{_attr(title)}">',
                 f'<meta name="twitter:image" content="{_attr(image)}">']

    html = ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{_attr(title)}</title>" + "".join(tags)
            + f'<link rel="canonical" href="{_attr(target)}">'
            + f'<meta http-equiv="refresh" content="0;url={_attr(target)}">'
            + "</head><body>"
            + f'<a href="{_attr(target)}">{_attr(title)}</a>'
            + f'<script>location.replace("{target}")</script>'
            + "</body></html>")
    # Chat apps cache previews hard; a day is long enough to be cheap and short enough
    # that a price change is picked up.
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=86400"})


@api.get("/car/{listing_id}")
async def car_detail(listing_id: str, request: Request, lang: str = "bg",
                     refresh: bool = False):
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
            return await _gone(listing, listing_id, lang)
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
    for path in detail_photo_paths(detail):
        photos.append({
            "full": image_url(path, 1280, 720),
            # 640x360, not 256x144: the thumbnail rail is 276px wide on desktop, so the
            # smaller file was being upscaled and looked soft.
            "thumb": image_url(path, 640, 360),
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
    # They are also always resolved in ENGLISH: a marque and a model name are proper
    # nouns, so they must not be Cyrillicised or localised (see translate.LATIN_FIELDS).
    always = [v for v in (cat.get("manufacturerName"), cat.get("modelName")) if v]
    if always:
        try:
            tr.update(await translate_many(db, always, "en"))
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
        # The comment is boilerplate plus whatever the dealer pasted after it, so it is
        # split into sentences and cleaned before translating (see _diag_comment_parts).
        parted = [(c, _diag_comment_parts(c.get("result"))) for c in comments]
        flat = [s for _, parts in parted for s in parts]
        if flat:
            ko_names.extend(flat)
            tr.update(await translate_cached_only(db, flat, lang))
            miss2 = [s for s in flat if s not in tr]
            if miss2:
                schedule_translation(db, list(dict.fromkeys(miss2)), lang)
        diagnosis = {
            "available": True,
            "date": diag.get("diagnosisDate"),
            "center": diag.get("reservationCenterName"),
            "total": len(panels),
            "abnormal": len([i for i in panels if i.get("resultCode") != "NORMAL"]),
            "items": [{"panel": _panel_label(i.get("name")),
                       "result_code": i.get("resultCode"),
                       "result": T(i.get("result"))} for i in panels],
            "comments": [" ".join(T(s) for s in parts) for _, parts in parted if parts],
        }

    body_panels = _body_panels(insp, diag)
    mech_checks = _mech_checks(insp)

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
    # The row the buyer clicked carries a stored price; keep whichever is higher so the
    # price never changes between the ad and the car page (see publish_prices).
    if quote:
        stored = (listing or {}).get("sale_eur") or 0
        if stored > quote["suggested_sale"]:
            quote["suggested_sale"] = stored
            quote["profit_min"] = stored - quote["landed"]
            quote["profit_max"] = stored - quote["landed_secondary"]
            quote["realized_margin"] = stored - quote["landed"]

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
                                        curate.display(2, (listing or {}).get("model") or "",
                                                       T(cat.get("modelName")))])),
        "manufacturer": T(cat.get("manufacturerName")),
        "model": curate.display(2, (listing or {}).get("model") or "",
                                T(cat.get("modelName"))),
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
        "body_panels": body_panels,
        "mech_checks": mech_checks,
        # Public quote carries the customer-facing price only. Landed cost, margins and
        # the two customs scenarios are business data and are added below for admins.
        "quote": {"suggested_sale": (quote or {}).get("suggested_sale")},
        "fetched_at": cached.get("fetched_at"),
        "lang": lang,
    }

    # Catch every remaining Korean string anywhere in the payload (insurance,
    # inspection, diagnosis, equipment/options, spec, category ...).
    #
    # Cache-only, deliberately. These bounded enumerations are shared catalogue-wide and
    # are already cached, so the page still renders fully translated. What is left over is
    # per-car freeform text (dealer branch, address, plate number) which can NEVER be a
    # cache hit — translating it inline made the first view of every car wait ~6s on the
    # LLM. It is filled in the background instead and the client refetches once it lands.
    leftovers = set()
    collect_korean(payload, leftovers)
    translation_pending = False
    if leftovers:
        tmap = dict(tr)
        missing = [x for x in leftovers if x not in tmap]
        if missing:
            tmap.update(await translate_cached_only(db, missing, lang))
            still = [x for x in missing if x not in tmap]
            if still:
                schedule_translation(db, list(dict.fromkeys(still)), lang)
                translation_pending = True
        payload = apply_translations(payload, tmap)
    payload["translation_pending"] = translation_pending

    if await _is_admin_request(request):
        payload["admin"] = pricing.admin_range(quote)

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


# Encar's inspection sheet names panels with P-codes and Korean titles. Mapping them onto
# our own slugs keeps the diagram and its labels ours: the drawing is drawn here and the
# words come from our own translations, not from Korean text pasted onto a page.
PANEL_SLUGS = {
    "P011": "hood", "P021": "front_fender_left", "P022": "front_fender_right",
    "P031": "front_door_left", "P032": "front_door_right",
    "P033": "rear_door_left", "P034": "rear_door_right",
    "P041": "trunk_lid", "P051": "radiator_support",
    "P061": "quarter_panel_left", "P062": "quarter_panel_right",
    "P071": "roof", "P081": "side_sill_left", "P082": "side_sill_right",
    "P091": "front_panel", "P101": "cross_member",
    "P111": "inside_panel_left", "P112": "inside_panel_right",
    "P121": "front_side_member_left", "P122": "front_side_member_right",
    "P131": "front_wheelhouse_left", "P132": "front_wheelhouse_right",
    "P141": "pillar_front_left", "P142": "pillar_centre_left", "P143": "pillar_rear_left",
    "P144": "pillar_front_right", "P145": "pillar_centre_right",
    "P146": "pillar_rear_right",
    "P151": "rear_side_member_left", "P152": "rear_side_member_right",
    "P161": "rear_wheelhouse_left", "P162": "rear_wheelhouse_right",
    "P171": "trunk_floor", "P181": "rear_panel",
}

# Encar's own diagnosis covers the outer skin only, with its own enum names.
DIAGNOSIS_SLUGS = {
    "HOOD": "hood", "ROOF_PANEL": "roof", "TRUNK_LID": "trunk_lid",
    "FRONT_FENDER_LEFT": "front_fender_left", "FRONT_FENDER_RIGHT": "front_fender_right",
    "FRONT_DOOR_LEFT": "front_door_left", "FRONT_DOOR_RIGHT": "front_door_right",
    "BACK_DOOR_LEFT": "rear_door_left", "BACK_DOOR_RIGHT": "rear_door_right",
    "QUARTER_PANEL_LEFT": "quarter_panel_left",
    "QUARTER_PANEL_RIGHT": "quarter_panel_right",
}


def _body_panels(insp, diag):
    """Panel-by-panel condition, normalised for the body diagram.

    Two upstream sources overlap. The inspection sheet is the richer one: it lists only the
    panels WITH a finding, each carrying a status code (X replaced, W sheet metal or weld,
    C corrosion, A scratch, U dent, T damage). Encar's own diagnosis covers the outer skin
    and reports replaced against normal. The sheet wins when present; the diagnosis is the
    fallback. A car with neither gets no diagram at all, because an empty one would read as
    "every panel is fine" — a claim we cannot make.
    """
    findings = {}
    if insp:
        for row in (insp.get("outers") or []):
            code = ((row.get("type") or {}).get("code") or "").upper()
            slug = PANEL_SLUGS.get(code)
            statuses = [(s.get("code") or "").upper()
                        for s in (row.get("statusTypes") or []) if s.get("code")]
            if not statuses:
                continue
            key = slug or code
            findings.setdefault(key, {"slug": slug, "code": code, "statuses": []})
            findings[key]["statuses"].extend(statuses)
        return {"available": True, "source": "inspection",
                "findings": list(findings.values())}

    items = (diag or {}).get("items") or []
    if not items:
        return None
    for it in items:
        slug = DIAGNOSIS_SLUGS.get(it.get("name") or "")
        if slug and it.get("resultCode") not in (None, "", "NORMAL"):
            findings[slug] = {"slug": slug, "code": "", "statuses": ["X"]}
    return {"available": True, "source": "diagnosis",
            "findings": list(findings.values())}


# The inspection sheet's mechanical half, grouped the way the sheet groups it.
MECH_SECTIONS = {
    "S00": "self_diagnosis", "S01": "engine", "S02": "transmission",
    "S03": "drivetrain", "S04": "steering", "S05": "braking",
    "S06": "electrics", "S07": "fuel", "S08": "high_voltage",
}

# Engine and gearbox lead, because that is the order a buyer worries in. The electronic
# self-diagnosis goes last: it is a scan result, not a physical check.
MECH_ORDER = ["engine", "transmission", "drivetrain", "steering", "braking",
              "electrics", "fuel", "high_voltage", "self_diagnosis"]

MECH_ITEMS = {
    "s001": "engine_self_test", "s002": "transmission_self_test",
    "s003": "idle_running", "s004": "rocker_cover", "s005": "head_gasket",
    "s006": "cylinder_block", "s007": "oil_level", "s008": "head_gasket_coolant",
    "s009": "water_pump", "s010": "radiator", "s011": "coolant_level",
    "s012": "common_rail", "s013": "oil_leak", "s014": "fluid_level_condition",
    "s015": "operation_idle", "s016": "oil_leak", "s017": "gear_selector",
    "s019": "operation_idle", "s020": "clutch", "s021": "cv_joint",
    "s022": "driveshaft_bearings", "s023": "power_steering_leak",
    "s024": "steering_gear", "s025": "steering_pump", "s026": "tie_rod_ball_joint",
    "s027": "brake_master_cylinder", "s028": "brake_fluid_leak",
    "s029": "brake_booster", "s030": "alternator_output", "s031": "starter_motor",
    "s032": "wiper_motor", "s033": "cabin_blower", "s034": "radiator_fan",
    "s035": "window_motors", "s036": "fuel_leak", "s037": "differential",
    "s038": "steering_joints", "s039": "high_pressure_hose",
    "s040": "charge_port_insulation", "s041": "traction_battery_isolation",
    "s042": "hv_wiring",
}

# Upstream status codes. Good, adequate (fluid levels) and none-found all mean there is
# nothing to report; seepage is worth a warning; a leak or a faulty part is a finding.
MECH_STATUS = {"1": "ok", "2": "ok", "3": "ok", "6": "warn", "7": "bad", "10": "bad"}
_WORST = {"ok": 0, "warn": 1, "bad": 2}


def _mech_leaves(node):
    kids = node.get("children") or []
    if not kids:
        yield node
    for k in kids:
        yield from _mech_leaves(k)


def _mech_checks(insp):
    """The mechanical half of the inspection sheet: engine, gearbox, brakes and the rest.

    The sheet checks a few dozen items and almost all of them come back fine, so listing
    every one would bury the two that matter. Each section therefore reports a verdict —
    the worst of its items — and only the items that are NOT fine are named.
    """
    sections = {}
    for sec in (insp or {}).get("inners") or []:
        slug = MECH_SECTIONS.get(((sec.get("type") or {}).get("code") or "").upper())
        if not slug:
            continue
        row = sections.setdefault(slug, {"slug": slug, "verdict": "ok", "checks": 0,
                                         "findings": []})
        for leaf in _mech_leaves(sec):
            code = (leaf.get("statusType") or {}).get("code")
            status = MECH_STATUS.get(str(code)) if code is not None else None
            if not status:
                continue
            row["checks"] += 1
            if status == "ok":
                continue
            if _WORST[status] > _WORST[row["verdict"]]:
                row["verdict"] = status
            item = MECH_ITEMS.get((leaf.get("type") or {}).get("code") or "")
            # An unmapped item still counts towards the verdict, it just cannot be named -
            # better a section marked "needs attention" than Korean text on the page.
            if item:
                row["findings"].append({"slug": item, "status": status})

    rows = [s for s in sections.values() if s["checks"]]
    if not rows:
        return None
    rows.sort(key=lambda r: MECH_ORDER.index(r["slug"]) if r["slug"] in MECH_ORDER else 99)
    return {"available": True, "sections": rows,
            "checks": sum(r["checks"] for r in rows),
            "findings": sum(len(r["findings"]) for r in rows),
            "clean": all(r["verdict"] == "ok" for r in rows)}




def _check_admin(token):
    if not ADMIN_TOKEN or not secrets.compare_digest(token or "", ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="bad admin token")


async def _is_admin_request(request: Request):
    """Soft check for read paths: is this a signed-in admin? Never raises."""
    try:
        user = await auth.optional_user(request)
        return bool(user and user.get("is_admin"))
    except Exception:
        return False


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
        # The crawl the operator actually runs is the partitioned one, so its job doc is
        # the truth about status and progress. `sync` below is the retired page-based
        # sync's doc, kept only for the few counters that still read from it.
        "job": await syncjob_mod.get_job(db),
        "running": syncjob_mod.is_running(),
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


class SyncScheduleBody(BaseModel):
    enabled: bool = False
    time: str = "03:30"
    tz: str = "Europe/Sofia"


@api.get("/admin/catalogue-sync")
async def catalogue_sync_state(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    return jsonable({"job": await syncjob_mod.get_job(db),
                     "running": syncjob_mod.is_running(),
                     "schedule": await syncjob_mod.get_schedule(db)})


@api.post("/admin/catalogue-sync/run")
async def catalogue_sync_run(request: Request, fresh: bool = False,
                             x_admin_token: str = Header(default="")):
    """Start a whole-catalogue crawl. Returns at once: the job outlives the request.

    Continues the last checkpoint by default; `fresh=true` re-crawls from scratch.
    """
    await _require_admin(request, x_admin_token)
    return jsonable(await syncjob_mod.start(db, trigger="manual", fresh=fresh))


@api.put("/admin/catalogue-sync/schedule")
async def catalogue_sync_schedule(body: SyncScheduleBody, request: Request,
                                  x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    try:
        return jsonable(await syncjob_mod.set_schedule(db, body.enabled, body.time, body.tz))
    except Exception as e:
        raise HTTPException(400, str(e)[:200])


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
deposits.set_db(db)
notify.set_db(db)
# ── shipment tracking ---------------------------------------------------------
class TrackBody(BaseModel):
    ref: str
    by: str = "container"
    label: str = ""
    car_id: str = ""


@api.get("/tracking")
async def tracking_lookup(ref: str, by: str = "container"):
    if by not in ("container", "bol"):
        raise HTTPException(400, "by must be container or bol")
    try:
        return await tracking.track(db, ref, by)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@api.get("/tracking/saved")
async def tracking_saved(user=Depends(auth.current_user)):
    return {"items": user.get("tracked_shipments") or []}


@api.post("/tracking/saved")
async def tracking_save(body: TrackBody, user=Depends(auth.current_user)):
    ref = body.ref.strip().upper()
    if not ref:
        raise HTTPException(400, "a reference is required")
    items = [x for x in (user.get("tracked_shipments") or []) if x.get("ref") != ref]
    items.insert(0, {"ref": ref, "by": body.by, "label": body.label.strip()[:80],
                     "car_id": body.car_id.strip()[:40],
                     "added_at": datetime.now(timezone.utc).isoformat()})
    await db.users.update_one({"_id": user["_id"]},
                             {"$set": {"tracked_shipments": items[:20]}})
    return {"items": items[:20]}


@api.delete("/tracking/saved/{ref}")
async def tracking_unsave(ref: str, user=Depends(auth.current_user)):
    items = [x for x in (user.get("tracked_shipments") or [])
             if x.get("ref") != ref.strip().upper()]
    await db.users.update_one({"_id": user["_id"]},
                             {"$set": {"tracked_shipments": items}})
    return {"items": items}


@api.post("/tracking/edi")
async def tracking_edi(request: Request, x_edi_token: str = Header(default="")):
    """Ingest a Maersk status message (X12 315 or EDIFACT IFTSTA).

    Maersk pushes these over AS2/SFTP/VAN, so whatever sits in front (the EDI provider or
    the VAN) forwards the raw message here. Authenticated by a shared secret, or by an
    admin session so the owner can paste a file in from the Track page.
    """
    token = os.environ.get("EDI_INGEST_TOKEN", "")
    if not (token and x_edi_token == token):
        await auth.current_admin(request)
    body = (await request.body()).decode("utf-8", "replace")
    if not body.strip():
        raise HTTPException(400, "empty message")
    try:
        return await edi.ingest(db, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


class ShipmentBody(BaseModel):
    email: str
    ref: str
    by: str = "container"
    car_id: str = ""
    vessel_name: str = ""
    vessel_imo: str = ""
    vessel_mmsi: str = ""
    eta: str = ""
    note: str = ""


@api.get("/purchases")
async def my_purchases(user=Depends(auth.current_user)):
    """The cars this buyer holds with a paid deposit, read from OUR archive.

    Encar is never touched here: the whole point of copying a listing at payment time is
    that a withdrawn ad still has a page and its pictures. The shipment is matched by car,
    so the Track button knows the bill of lading as soon as an operator assigns one.
    """
    paid = await db.deposits.find(
        {"user_id": user["_id"], "payment_status": "paid"}
    ).sort("updated_at", -1).to_list(100)

    car_ids = [d["car_id"] for d in paid]
    archives = {a["_id"]: a async for a in db.purchased_listings.find(
        {"_id": {"$in": car_ids}},
        {"photos": 1, "photo_count": 1, "listing": 1, "archived_at": 1})}
    shipments = {s.get("car_id"): s async for s in db.shipments.find(
        {"user_id": user["_id"]}, {"car_id": 1, "ref": 1, "by": 1})}

    items = []
    for row in paid:
        car_id = row["car_id"]
        archived = archives.get(car_id) or {}
        listing = archived.get("listing") or await db.listings.find_one({"_id": car_id}) or {}
        await translate_listings(db, [listing], norm_lang("en"))
        ship = shipments.get(car_id) or {}
        photos = archived.get("photos") or []
        items.append({
            "car_id": car_id,
            "title": row.get("car_title") or " ".join(
                str(x) for x in [listing.get("manufacturer_t") or listing.get("manufacturer"),
                                 listing.get("model_t") or listing.get("model")] if x),
            "subtitle": listing.get("badge_t") or listing.get("badge") or "",
            "photo": photos[0] if photos else None,
            "photo_count": archived.get("photo_count") or 0,
            "archived": bool(photos),
            "price_eur": listing.get("sale_eur") or row.get("car_price_eur") or 0,
            "deposit_eur": row.get("amount") or 0,
            "paid_at": jsonable(row.get("updated_at") or row.get("created_at")),
            "ref": ship.get("ref") or "",
            "by": ship.get("by") or "bol",
        })
    return {"items": items}


@api.get("/admin/customers")
async def admin_customers(request: Request, q: str = "", limit: int = 20,
                          x_admin_token: str = Header(default="")):
    """Customer accounts matching a name or email fragment, for the assignment picker.

    An operator knows the buyer by name, not by the exact address they registered with, so
    the search covers the account name, the billing name and the email.
    """
    await _require_admin(request, x_admin_token)
    term = (q or "").strip()[:60]
    query = {}
    if term:
        rx = {"$regex": re.escape(term), "$options": "i"}
        query = {"$or": [{"email": rx}, {"name": rx}, {"billing.full_name": rx}]}
    rows = await db.users.find(
        query, {"email": 1, "name": 1, "billing.full_name": 1, "created_at": 1}
    ).sort("email", 1).to_list(min(max(1, limit), 50))
    return {"items": [{"email": r.get("email") or "",
                       "name": r.get("name") or (r.get("billing") or {}).get("full_name") or "",
                       "created_at": jsonable(r.get("created_at"))} for r in rows]}


@api.post("/admin/price-watch/run")
async def admin_price_watch_run(request: Request, first_seen: bool = False,
                               x_admin_token: str = Header(default="")):
    """Check saved cars for price drops now, instead of waiting for the next sync."""
    await _require_admin(request, x_admin_token)
    return jsonable(await pricewatch_mod.run(db, notify_first_seen=first_seen))



@api.get("/admin/deposits")
async def admin_deposits(request: Request, x_admin_token: str = Header(default="")):
    """Every deposit that reached Stripe, so an operator can see what is held and refund."""
    await _require_admin(request, x_admin_token)
    return jsonable({"items": await deposits.list_for_admin()})


@api.post("/admin/deposits/{session_id}/refund")
async def admin_deposit_refund(session_id: str, request: Request,
                               x_admin_token: str = Header(default="")):
    """Refund a deposit in full and put the car back on the market."""
    admin = await _require_admin(request, x_admin_token)
    return jsonable(await deposits.refund(session_id, (admin or {}).get("email") or ""))



@api.get("/admin/shipments")
async def admin_shipments(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    rows = await db.shipments.find({}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return {"items": rows}


@api.post("/admin/shipments")
async def admin_shipment_assign(body: ShipmentBody, request: Request,
                                x_admin_token: str = Header(default="")):
    """Assign a carrier reference to a customer account.

    Public track cannot be read server-side for every reference, so the admin owns the
    facts: which customer, which car, which ship. Whatever the EDI feed later delivers for
    the same reference is merged on top of this automatically.
    """
    admin = await _require_admin(request, x_admin_token)
    ref = body.ref.strip().upper()
    email = body.email.strip().lower()
    if not ref or not email:
        raise HTTPException(400, "a customer email and a tracking reference are required")
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(404, f"no account for {email}")

    doc = {"ref": ref, "by": body.by, "email": email, "user_id": user["_id"],
           "car_id": body.car_id.strip(), "vessel_name": body.vessel_name.strip(),
           "vessel_imo": body.vessel_imo.strip(), "vessel_mmsi": body.vessel_mmsi.strip(),
           "eta": body.eta.strip(), "note": body.note.strip()[:400],
           "updated_at": datetime.now(timezone.utc),
           "updated_by": (admin or {}).get("email") or "admin token"}
    await db.shipments.update_one({"ref": ref}, {"$set": doc}, upsert=True)

    items = [x for x in (user.get("tracked_shipments") or []) if x.get("ref") != ref]
    items.insert(0, {"ref": ref, "by": body.by, "label": "", "car_id": body.car_id.strip(),
                     "assigned": True,
                     "added_at": datetime.now(timezone.utc).isoformat()})
    await db.users.update_one({"_id": user["_id"]},
                             {"$set": {"tracked_shipments": items[:20]}})
    return {"saved": True, "ref": ref, "email": email}


@api.post("/admin/shipments/{ref}/refresh")
async def admin_shipment_refresh(ref: str, request: Request, by: str = "container",
                                 x_admin_token: str = Header(default="")):
    """Force a fresh read of Maersk's public track page for one reference.

    The buyer-facing lookup is cached so a page refresh never spends a browser; this is the
    operator's way to pull the latest milestones on demand.
    """
    await _require_admin(request, x_admin_token)
    try:
        return await tracking.track(db, ref, by if by in ("container", "bol") else "container",
                                    refresh=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@api.get("/admin/buyers")
async def admin_buyers(request: Request, x_admin_token: str = Header(default="")):
    """What each customer is actually shopping for.

    Built from the same profile that drives their recommendations: the makes and models they
    keep coming back to, and the price and mileage range they browse in. Read-only, so the
    operator can pick up the phone knowing what to offer.
    """
    await _require_admin(request, x_admin_token)
    rows = [u async for u in db.users.find(
        {}, {"email": 1, "name": 1, "taste": 1, "billing": 1, "favourites": 1,
             "last_search": 1, "created_at": 1}).sort("created_at", -1).limit(300)]

    out = []
    for u in rows:
        taste = u.get("taste") or {}
        samples = taste.get("samples") or []
        price, price_low, price_high = _centre(samples, 0)
        mileage, mileage_low, mileage_high = _centre(samples, 1)
        top = lambda m, n: [k for k, _ in sorted((m or {}).items(), key=lambda kv: -kv[1])[:n]]
        out.append({
            "email": u.get("email") or "", "name": u.get("name") or "",
            "city": (u.get("billing") or {}).get("city") or "",
            "phone": (u.get("billing") or {}).get("phone") or "",
            "favourites": len(u.get("favourites") or []),
            "_makes": taste.get("makes") or {}, "_models": taste.get("models") or {},
            "_fuels": taste.get("fuels") or {},
            "_search": u.get("last_search") or {},
            "price": price, "price_low": price_low, "price_high": price_high,
            "mileage": mileage, "mileage_low": mileage_low, "mileage_high": mileage_high,
            "events": taste.get("events") or 0,
            "updated_at": taste.get("updated_at"),
            "joined_at": u.get("created_at"),
        })
    out.sort(key=lambda r: (-r["events"], r["email"]))

    # The taste profile stores whatever the listing carried, so the same make can sit in it
    # twice - once as "아우디" and once as "Audi". An operator picking up the phone needs one
    # English name, so every key is resolved through the ENGLISH cache (cache-only: this must
    # never call the LLM), the counts are merged under it, and only then is the top taken.
    words = {k for r in out for f in ("_makes", "_models", "_fuels") for k in r[f]}
    words |= {v for r in out for f in ("makes", "models", "badges", "badge_details", "fuels")
              for v in (r["_search"].get(f) or [])}
    en = await translate_cached_only(db, list(words), "en") if words else {}

    def merge(counts, n):
        totals = {}
        for k, v in (counts or {}).items():
            name = en.get(k, k)
            totals[name] = totals.get(name, 0) + v
        return [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:n]]

    def describe(s):
        """The last search as one line an operator can read out loud."""
        if not s:
            return ""
        bits = []
        names = [en.get(v, v) for v in
                 ((s.get("badge_details") or s.get("badges") or s.get("models")
                   or s.get("makes") or [])[:3])]
        if names:
            bits.append(", ".join(names))
        if s.get("q"):
            bits.append(f"\u201c{s['q']}\u201d")
        lo, hi = s.get("price_min"), s.get("price_max")
        if lo or hi:
            bits.append(f"€{int(lo or 0):,}–{int(hi):,}".replace(",", " ")
                        if hi else f"from €{int(lo):,}".replace(",", " "))
        y1, y2 = s.get("year_min"), s.get("year_max")
        if y1 and y2:
            bits.append(f"{y1}–{y2}")
        elif y1 or y2:
            bits.append(f"{y1}+" if y1 else f"up to {y2}")
        if s.get("mileage_max"):
            bits.append(f"up to {int(s['mileage_max']):,} km".replace(",", " "))
        if s.get("fuels"):
            bits.append(", ".join(en.get(v, v) for v in s["fuels"][:2]))
        return " · ".join(bits)

    for r in out:
        r["makes"] = merge(r.pop("_makes"), 3)
        r["models"] = merge(r.pop("_models"), 3)
        r["fuels"] = merge(r.pop("_fuels"), 2)
        s = r.pop("_search")
        r["last_search"] = describe(s)
        r["last_search_at"] = s.get("at")
    return {"items": out}


class TaxonomyOverrideBody(BaseModel):
    level: int = 2
    make: str = ""
    model: str = ""
    value: str
    target: str = ""
    label: str = ""


@api.get("/admin/taxonomy/overrides")
async def admin_taxonomy_overrides(request: Request, x_admin_token: str = Header(default="")):
    """Every rename and merge the owner has made, newest first."""
    await _require_admin(request, x_admin_token)
    rows = [d async for d in db.taxonomy_overrides.find({}).sort("at", -1).limit(500)]
    words = {v for d in rows for v in (d.get("value"), d.get("target")) if v}
    en = await translate_cached_only(db, list(words), "en") if words else {}
    return {"items": [{
        "id": d["_id"], "level": d.get("level"), "make": d.get("make") or "",
        "model": d.get("model") or "", "value": d.get("value") or "",
        "value_label": en.get(d.get("value") or "", d.get("value") or ""),
        "target": d.get("target") or "",
        "target_label": en.get(d.get("target") or "", d.get("target") or ""),
        "label": d.get("label") or "", "at": d.get("at"),
    } for d in rows]}


@api.post("/admin/taxonomy/overrides")
async def admin_taxonomy_override_save(body: TaxonomyOverrideBody, request: Request,
                                      x_admin_token: str = Header(default="")):
    """Rename a model or trim, or fold it into another one.

    One override per value, so saving again replaces the previous one. Merging into something
    that is itself merged follows the chain to whatever actually survives, which keeps the
    dropdown from ever pointing at an entry a buyer cannot see.
    """
    await _require_admin(request, x_admin_token)
    value = (body.value or "").strip()
    if not value:
        raise HTTPException(400, "which value?")
    await curate.refresh(db, force=True)
    target = curate.root(body.level, (body.target or "").strip()) if body.target else ""
    if target == value:
        raise HTTPException(400, "a value cannot be merged into itself")
    label = (body.label or "").strip()[:80]
    if not target and not label:
        raise HTTPException(400, "give a new name or something to merge into")
    doc = {"level": int(body.level), "make": body.make.strip(), "model": body.model.strip(),
           "value": value, "target": target, "label": label,
           "at": datetime.now(timezone.utc).isoformat()}
    # Deterministic id: one override per value, so saving again simply replaces it (and no
    # ObjectId ever reaches the admin screen).
    oid = f"{doc['level']}|{value}"
    await db.taxonomy_overrides.update_one({"_id": oid}, {"$set": doc}, upsert=True)
    await curate.refresh(db, force=True)
    return {"saved": True, "id": oid, **doc}


@api.delete("/admin/taxonomy/overrides/{oid}")
async def admin_taxonomy_override_remove(oid: str, request: Request,
                                        x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    res = await db.taxonomy_overrides.delete_one({"_id": oid})
    await curate.refresh(db, force=True)
    return {"removed": bool(res.deleted_count)}


@api.get("/admin/tracking-quota")
async def admin_tracking_quota(request: Request, refresh: bool = False,
                              x_admin_token: str = Header(default="")):
    """Provider plan usage. Cached, because asking is itself a billable request."""
    await _require_admin(request, x_admin_token)
    if not jsoncargo.configured():
        return {"configured": False}
    try:
        data = await jsoncargo.stats(db, refresh)
    except RuntimeError as e:
        return {"configured": True, "error": str(e)}
    return {"configured": True, **(data or {})}


@api.delete("/admin/shipments/{ref}")
async def admin_shipment_remove(ref: str, request: Request,
                                x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    ref = ref.strip().upper()
    doc = await db.shipments.find_one_and_delete({"ref": ref})
    if doc:
        await db.users.update_one(
            {"_id": doc["user_id"]},
            {"$pull": {"tracked_shipments": {"ref": ref}}})
    return {"removed": bool(doc)}


api.include_router(auth.router)
api.include_router(deposits.router)
api.include_router(notify.router)
app.include_router(api)

# The archived photos of purchased cars, served from our own disk so a withdrawn ad still
# has pictures. Mounted under /api so the ingress routes it to this service.
app.mount("/api/media", StaticFiles(directory=os.environ["MEDIA_ROOT"]), name="media")

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
    asyncio.get_running_loop().create_task(_fx_watchdog())
    await syncjob_mod.clear_stale(db)
    await syncjob_mod.resume_if_interrupted(db)
    asyncio.get_running_loop().create_task(syncjob_mod.scheduler(db))
    log.info("startup complete: %s listings in index",
             await db.listings.count_documents({}))


async def _fx_watchdog(period=1800):
    """Keep stored listing prices in step with the rate.

    Search rows serve a precomputed sale_eur while detail pages quote live, so an
    unnoticed rate move shows up as a price that jumps when the buyer clicks a car.
    Refreshing the bundle on a timer lets fx flag real drift, and the reprice then runs
    detached.
    """
    while True:
        await asyncio.sleep(period)
        try:
            await fx_mod.get_rates(db)
            await sync_mod.reprice_if_fx_drifted(db)
        except Exception as e:
            log.warning("fx watchdog: %s", str(e)[:200])


@app.on_event("shutdown")
async def on_shutdown():
    # Order matters: let a running sync be cancelled and record itself while Mongo is
    # still open, otherwise it dies mid-write and leaves the job stuck on "running".
    await syncjob_mod.stop(db)
    await maersk_public.close()
    await encar.close()
    client.close()
