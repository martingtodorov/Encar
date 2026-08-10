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
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate, parsedate_to_datetime
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import (APIRouter, Depends, FastAPI, Header, HTTPException, Query,
                     Request, Response)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# These three are read at IMPORT time by the modules below, so a missing one kills the process
# before uvicorn ever binds a port — the deploy then fails with nothing but "connection
# refused". Checked here, together, so one restart names EVERYTHING that is missing instead of
# dying on the first key and hiding the next two.
_REQUIRED_ENV = ("MONGO_URL", "DB_NAME", "MEDIA_ROOT")
_missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    raise RuntimeError(
        "Missing required environment variables: " + ", ".join(_missing)
        + ". Add them to the environment file the service reads "
        "(EnvironmentFile= in the systemd unit) and restart. MEDIA_ROOT is the directory "
        "where photos of purchased cars are archived and must be writable by the service user."
    )

import auth                  # noqa: E402
import archive                # noqa: E402
import cms                    # noqa: E402
import seed_curation          # noqa: E402
import deposits              # noqa: E402
import notify                # noqa: E402
import fx as fx_mod          # noqa: E402
import mailer                # noqa: E402
import pricing               # noqa: E402
import slugs as slugs_mod    # noqa: E402
import syncjob as syncjob_mod  # noqa: E402
import contracts as contracts_mod  # noqa: E402
import postqueue  # noqa: E402
import traffic  # noqa: E402
import pricewatch as pricewatch_mod  # noqa: E402
import searchwatch as searchwatch_mod  # noqa: E402
import digest as digest_mod  # noqa: E402
import csrf as csrf_mod  # noqa: E402
import edi                  # noqa: E402
import jsoncargo            # noqa: E402
import maersk_public        # noqa: E402
import tracking             # noqa: E402
import mapshot              # noqa: E402
import dialcodes            # noqa: E402
import geoip                # noqa: E402
import phones               # noqa: E402
import ports as ports_mod   # noqa: E402
import curate               # noqa: E402
import sync as sync_mod      # noqa: E402
from encar import encar, image_url, detail_photo_paths, under_contract, sales_status  # noqa: E402
from translate import (LANGS, breaker_status, cached_label_set,  # noqa: E402
                       schedule_translation,
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
        # 500x280 is what a card in the grid actually paints (487 CSS px wide at the
        # widest desktop breakpoint, so 500 covers a 1x screen exactly and a 2x screen
        # sees a marginal downscale). Lighthouse flagged 640x360 as ~9 KB waste per
        # thumbnail across a 12-card grid.
        "image": image_url(photos[0] if photos else None, 500, 280),
        "image_sm": image_url(photos[0] if photos else None, 320, 180),
        # every photo we hold, so the card can be swiped without opening the car
        "images": [image_url(p, 500, 280) for p in photos],
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

    # A make, model or trim the owner merged others into must return their cars too
    # (curate.py).
    if p.get("makes"):
        q["manufacturer"] = {"$in": curate.expand(1, p["makes"])}
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


# The shop window has a floor: the landing view never shows a car under this price. Applied
# only while NOTHING narrows the search — the moment a visitor searches or filters, they see
# the whole catalogue, and the floor is never shown as a filter chip because it is our
# curation choice, not theirs.
HOME_MIN_EUR = float(os.environ.get("HOME_MIN_EUR") or 18000)

_NARROWING = (
    "q", "makes", "models", "badges", "badge_details", "fuels", "regions", "transmissions",
    "year_min", "year_max", "mileage_min", "mileage_max", "price_min", "price_max",
    "only_inspection", "only_record", "only_diagnosed",
)


def unfiltered(p):
    """Is this the bare landing view, with nothing at all narrowing it?"""
    return not any(p.get(k) for k in _NARROWING)


def apply_home_floor(query):
    """Raise the query's price floor to HOME_MIN_EUR without lowering an existing one."""
    price = dict(query.get("sale_eur") or {})
    price["$gte"] = max(float(price.get("$gte") or 0), HOME_MIN_EUR)
    query["sale_eur"] = price
    return query


_catalogue_count = {"at": 0.0, "n": 0}


async def _catalogue_total():
    """How many cars the catalogue really holds, cached: it is the same number for everyone."""
    now = time.time()
    if now - _catalogue_count["at"] > 300:
        _catalogue_count["n"] = await db.listings.count_documents(build_query({}))
        _catalogue_count["at"] = now
    return _catalogue_count["n"]


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
# per user instruction the per-vehicle dealer description stays in the original.
# TRIM FIELDS ARE LATIN EVERYWHERE (owner's rule), so they must be invisible to the
# leftover-Korean pass: it walks the whole payload and replaces Hangul with the PAGE
# language, which is how the car page came to print "Дизел 2.0 2WD Noblesse" while the
# rows and the filters said "Diesel 2.0 2WD Noblesse". They are resolved from the ENGLISH
# cache before the pass instead.
NO_TRANSLATE_KEYS = {"description", "description_original", "vin", "vehicle_no", "id",
                     "badge", "badge_detail", "grade"}

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


_view_salt = {"day": "", "salt": ""}


async def _daily_salt(day):
    """One secret per day, so a fingerprint cannot be recomputed or linked across days.

    Kept in the settings collection rather than in code: a restart must not reset it, or every
    visitor would be counted twice on the day of a deploy.
    """
    if _view_salt["day"] == day:
        return _view_salt["salt"]
    doc = await db.settings.find_one({"_id": "view_salt"}) or {}
    if doc.get("day") != day:
        doc = {"day": day, "salt": secrets.token_hex(16)}
        await db.settings.update_one({"_id": "view_salt"}, {"$set": doc}, upsert=True)
    _view_salt.update({"day": day, "salt": doc["salt"]})
    return doc["salt"]


async def _first_view_today(request: Request, listing_id, day):
    """Is this the first time this person has opened this ad today?

    No identifier is written to the visitor's device for this: the fingerprint is a salted
    hash of the address and browser string, and the salt changes daily, so yesterday's rows
    cannot be tied to today's and nothing here can be reversed into a person. What it buys us
    is that one buyer refreshing an ad two hundred times counts once - which is the only
    version of "most viewed" worth putting in an email.
    """
    salt = await _daily_salt(day)
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "")
    agent = request.headers.get("user-agent") or ""
    print_ = hashlib.sha256(f"{salt}|{ip}|{agent}|{listing_id}|{day}".encode()).hexdigest()[:32]
    try:
        await db.car_view_seen.insert_one({
            "_id": print_, "car_id": listing_id, "day": day,
            "at": datetime.now(timezone.utc)})
        return True
    except DuplicateKeyError:
        return False


@api.post("/car/{listing_id}/view")
async def car_view(listing_id: str, request: Request):
    """Count a real open of an ad — once per person per day, not once per refresh.

    Counted from the detail page rather than from the GET, because hovering a card
    pre-fetches the same endpoint and a hover is not interest. One document per ad per day,
    so the popularity window can be trimmed by simply dropping old days.

    `u` is the number the site ranks and reports on: distinct people. `n` stays as the raw
    count, which is only useful for spotting the difference.
    """
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    first_time = await _first_view_today(request, listing_id, day)
    await db.car_views.update_one(
        {"_id": f"{listing_id}:{day}"},
        {"$inc": {"n": 1, "u": 1 if first_time else 0},
         "$set": {"car_id": listing_id, "day": day}}, upsert=True)
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
        # Distinct people, not refreshes. Days recorded before uniques existed fall back
        # to their raw count so the ranking does not suddenly forget two weeks of history.
        {"$group": {"_id": "$car_id", "n": {"$sum": {"$ifNull": ["$u", "$n"]}}}},
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
    # A visitor who asks for the cheapest first is telling us they are hunting a bargain, so
    # the shop window's floor is dropped for them — pushing 18k cars at someone sorting by
    # price is the opposite of helpful.
    floored = unfiltered(p) and body.sort != "price_asc"
    if floored:
        apply_home_floor(query)
    sort = SORTS.get(body.sort, SORTS["newest"])

    page = max(1, int(body.page))
    size = min(max(1, int(body.page_size)), 96)
    skip = (page - 1) * size

    if page == 1:
        await _remember_search(request, p)

    total = await db.listings.count_documents(query)
    # The counter should advertise the whole library, not the slice the shop-window floor
    # leaves behind, so the floored count stays for PAGING and the real one is sent alongside.
    total_all = await _catalogue_total() if floored else total

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
                                    per_make=max(2, size // 4),
                                    per_band=max(3, size // 4) if floored else None))
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
                if floored:
                    # The popular list clusters hard around one price, so the shop window
                    # spreads it across brackets. Nothing is dropped: what the caps reject
                    # queues up behind, keeping the pages complete.
                    kept = [d for _, _, d in
                            _spread([(0, "", d) for d in ordered], len(ordered),
                                    per_model=2, per_make=max(2, size // 4),
                                    per_band=max(3, size // 4))]
                    taken = {d["_id"] for d in kept}
                    ordered = kept + [d for d in ordered if d["_id"] not in taken]
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
        "total_all": total_all,
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


_BANDS = (22_000, 28_000, 35_000, 45_000, 60_000, 90_000)


def _band(doc):
    """Which price bracket a car sits in, so one bracket cannot take over the shelf."""
    price = doc.get("sale_eur") or 0
    return next((i for i, edge in enumerate(_BANDS) if price < edge), len(_BANDS))


def _spread(scored, limit, per_model=3, per_make=6, per_band=None):
    """A shelf of near-identical cars is not a choice: cap how many share a model, and cap
    the make too — a buyer who looked at three Mercedes should not be handed a page of
    nothing but Mercedes.

    `per_band` caps the PRICE bracket the same way. Without it the landing view collapses onto
    whatever price everyone has been clicking — a page of nothing but €23,000 cars — because
    both the popular list and the taste ranking pull towards a single number.
    """
    out, models, makes, bands = [], {}, {}, {}
    for row in scored:
        model = row[2].get("model") or ""
        make = row[2].get("manufacturer") or ""
        band = _band(row[2])
        if models.get(model, 0) >= per_model or makes.get(make, 0) >= per_make:
            continue
        if per_band and bands.get(band, 0) >= per_band:
            continue
        models[model] = models.get(model, 0) + 1
        makes[make] = makes.get(make, 0) + 1
        bands[band] = bands.get(band, 0) + 1
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
    a favourite make still comes back every few rows. Price bracket is broken up the same way
    but only as a SECOND preference, so a row of near-identical prices reads as a range
    without the ranking being thrown away.
    """
    pool, out = list(scored), []
    while pool:
        makes = {(r[2].get("manufacturer") or "") for r in out[-gap:]}
        bands = {_band(r[2]) for r in out[-gap:]}
        pick = next((i for i, row in enumerate(pool)
                     if (row[2].get("manufacturer") or "") not in makes
                     and _band(row[2]) not in bands), None)
        if pick is None:
            pick = next((i for i, row in enumerate(pool)
                         if (row[2].get("manufacturer") or "") not in makes), 0)
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
    apply_home_floor(query)
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


# ── the shelf a brand-new visitor sees ────────────────────────────────────────────────
# Somebody arriving for the first time has no profile at all, and "the most opened ads of
# the fortnight" is an honest answer but a dull one — it is whatever the crowd clicked. The
# owner would rather the first impression be the cars the shop wants to be known for, so a
# hand-picked shelf comes first and the popular list stays as the fallback.
#
# The values are Encar's OWN (Korean makes, Encar model codes), never translations: a pick
# has to be an exact catalogue match or it would quietly stop matching the day a label
# changed. `badge` is an optional substring of the trim, which is how a pick can be one
# specific version of a model ("C63" inside "C63 S AMG 쿠페").
DEFAULT_PICKS = [
    {"make": "BMW", "model": "M2 (G87)", "badge": ""},
    {"make": "페라리", "model": "458", "badge": ""},
    {"make": "현대", "model": "싼타페 (MX5)", "badge": ""},
    {"make": "벤츠", "model": "C-클래스 W205", "badge": "C63"},
    {"make": "현대", "model": "팰리세이드", "badge": ""},
    {"make": "벤츠", "model": "GLE-클래스 W167", "badge": "GLE400d"},
    {"make": "BMW", "model": "X3 (G01)", "badge": "M40i"},
]
# Below this many impressions a pick is not judged at all: see `_pick_score`.
MIN_PICK_IMPRESSIONS = int(os.environ.get("MIN_PICK_IMPRESSIONS", "50"))


def _pick_key(p):
    return f"{p.get('make') or ''}|{p.get('model') or ''}|{p.get('badge') or ''}"


def _pick_matches(p, doc):
    if (doc.get("manufacturer") or "") != (p.get("make") or ""):
        return False
    if (doc.get("model") or "") != (p.get("model") or ""):
        return False
    return not p.get("badge") or p["badge"] in (doc.get("badge") or "")


def _pick_query(p):
    """Every car in the catalogue that is this pick, with the landing floor applied."""
    query = build_query({})
    apply_home_floor(query)
    query["manufacturer"] = p.get("make") or ""
    query["model"] = p.get("model") or ""
    if p.get("badge"):
        query["badge"] = {"$regex": re.escape(p["badge"])}
    return query


async def default_taste_conf():
    """The owner's list and how it is ordered, or what this file ships with."""
    doc = await db.site_settings.find_one({"_id": "default_taste"}) or {}
    picks = doc.get("picks")
    return {
        "enabled": bool(doc.get("enabled", True)),
        "picks": list(picks if picks is not None else DEFAULT_PICKS)[:24],
        "auto_rank": bool(doc.get("auto_rank", True)),
        "min_impressions": max(1, int(doc.get("min_impressions") or MIN_PICK_IMPRESSIONS)),
    }


async def default_picks():
    """The owner's list, or the one this file ships with."""
    conf = await default_taste_conf()
    return conf["enabled"], conf["picks"]


def _pick_score(row, min_impressions):
    """How well one pick is doing, or None when there is not enough evidence to say.

    A deposit is the only real proof a car earned anything; a click is interest. And a pick
    with three impressions and one click is NOT a 33% performer — it is unmeasured. Below the
    threshold it scores nothing at all, which keeps it in the shelf gathering data instead of
    winning or losing on luck.
    """
    shown = int((row or {}).get("impressions") or 0)
    if shown < min_impressions:
        return None
    clicks = int((row or {}).get("clicks") or 0)
    return round(int((row or {}).get("deposits") or 0) * 10.0 + clicks * 100.0 / shown, 2)


async def _pick_scores(picks, min_impressions):
    stats = {d["_id"]: d async for d in db.reco_stats.find({})}
    earned = await _reco_deposits(picks)
    out = {}
    for p in picks:
        key = _pick_key(p)
        row = dict(stats.get(key) or {})
        row["deposits"] = earned.get(key, 0)
        out[key] = _pick_score(row, min_impressions)
    return out


_rank_cache = {"at": 0.0, "order": None, "key": ""}


async def _ranked_picks(picks, min_impressions, fresh=False):
    """Best first. Picks with too little data keep their configured place at the back of the
    judged ones — they are never dropped, or they could never earn a number.

    `fresh` skips the cache. The shelf is happy with a minute-old order, but the admin screen
    shows the scores beside the order, and a cached order next to fresh scores contradicts
    itself on the page.
    """
    key = "|".join(_pick_key(p) for p in picks) + f"#{min_impressions}"
    if not fresh and _rank_cache["key"] == key and time.time() - _rank_cache["at"] < 60:
        return _rank_cache["order"]
    scores = await _pick_scores(picks, min_impressions)
    judged = sorted((p for p in picks if scores[_pick_key(p)] is not None),
                    key=lambda p: -scores[_pick_key(p)])
    order = judged + [p for p in picks if scores[_pick_key(p)] is None]
    _rank_cache.update({"at": time.time(), "order": order, "key": key})
    return order


async def _curated_shelf(lang, exclude, limit):
    """The hand-picked shelf. Empty if the owner has switched it off or nothing is in stock."""
    conf = await default_taste_conf()
    if not conf["enabled"] or not conf["picks"]:
        return []
    picks = await _ranked_picks(conf["picks"], conf["min_impressions"]) \
        if conf["auto_rank"] else conf["picks"]
    seen = {str(x) for x in (exclude or [])}
    # The leftover slots go to the front of the order: the strongest picks get two cars each,
    # everybody else one. A flat share handed the last pick nothing for no stated reason.
    extra = max(0, limit - len(picks))
    chosen = []
    for i, p in enumerate(picks):
        want = 2 if i < extra else 1
        taken = 0
        cursor = db.listings.find(_pick_query(p)).sort(SORTS["newest"]).limit(want * 4)
        async for doc in cursor:
            if doc["_id"] in seen:
                continue
            seen.add(doc["_id"])
            chosen.append((0.0, "model", doc, _pick_key(p)))
            taken += 1
            if taken >= want:
                break
    if not chosen:
        return []
    # Same rule as everywhere else: never two of one marque side by side.
    rows = _space(chosen)[:limit]
    docs = [r[2] for r in rows]
    await translate_listings(db, docs, lang)
    items = []
    for doc in docs:
        out = listing_out(doc)
        out.pop("landed_eur", None)
        out["why_label"] = out.get("model_t") or out.get("model") or ""
        items.append(out)
    await publish_prices(items)
    await _reco_seen([r[3] for r in rows])
    return items


async def _reco_seen(keys):
    """One impression per pick per shelf served, so the click-through rate means something."""
    if not keys:
        return
    ops = [UpdateOne({"_id": k}, {"$inc": {"impressions": 1}}, upsert=True) for k in keys]
    try:
        await db.reco_stats.bulk_write(ops, ordered=False)
    except Exception as e:
        log.warning("reco impressions failed: %s", str(e)[:120])


class RecoClickBody(BaseModel):
    id: str = ""


@api.post("/reco/click")
async def reco_click(body: RecoClickBody):
    """A car from the shelf was opened. Counted against the pick it came from, which is the
    only way to see which of the default cars actually earns attention."""
    doc = await db.listings.find_one({"_id": str(body.id)[:64]},
                                     {"manufacturer": 1, "model": 1, "badge": 1})
    if not doc:
        return {"ok": False}
    _, picks = await default_picks()
    key = next((_pick_key(p) for p in picks if _pick_matches(p, doc)), "")
    if key:
        await db.reco_stats.update_one({"_id": key}, {"$inc": {"clicks": 1}}, upsert=True)
    return {"ok": bool(key)}


async def _reco_deposits(picks):
    """How many deposits each pick has earned — the only number that is really retention.

    Only money that is actually HELD counts (authorised / captured / paid). A checkout the
    visitor opened and abandoned (`pending`), one that timed out (`expired`) and one we gave
    back (`released`) are not retention, and counting them made a pick with a single refunded
    deposit the winner of the whole shelf.
    """
    counts = {}
    async for d in db.deposits.find(
            {"payment_status": {"$in": list(deposits.HELD_STATES)}}, {"car_id": 1}):
        if d.get("car_id"):
            counts[d["car_id"]] = counts.get(d["car_id"], 0) + 1
    if not counts:
        return {}
    out = {}
    async for doc in db.listings.find({"_id": {"$in": list(counts)}},
                                      {"manufacturer": 1, "model": 1, "badge": 1}):
        for p in picks:
            if _pick_matches(p, doc):
                key = _pick_key(p)
                out[key] = out.get(key, 0) + counts[doc["_id"]]
                break
    return out


class RecoPickBody(BaseModel):
    make: str = ""
    model: str = ""
    badge: str = ""


class RecoDefaultsBody(BaseModel):
    enabled: bool = True
    auto_rank: bool = True
    min_impressions: int = MIN_PICK_IMPRESSIONS
    picks: list[RecoPickBody] = Field(default_factory=list)


@api.get("/admin/reco-defaults")
async def admin_reco_defaults(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    conf = await default_taste_conf()
    picks = conf["picks"]
    stats = {d["_id"]: d async for d in db.reco_stats.find({})}
    earned = await _reco_deposits(picks)
    scores = await _pick_scores(picks, conf["min_impressions"])
    # fresh=True on purpose: the admin screen prints the scores NEXT TO the order, and a
    # minute-old order beside freshly counted scores contradicts itself on the page.
    order = (await _ranked_picks(picks, conf["min_impressions"], fresh=True)
             if conf["auto_rank"] else picks)
    place = {_pick_key(p): n + 1 for n, p in enumerate(order)}
    names = await _labels([v for p in picks for v in (p.get("make"), p.get("model")) if v], "en")
    items = []
    for p in picks:
        key = _pick_key(p)
        row = stats.get(key) or {}
        shown, clicks = int(row.get("impressions") or 0), int(row.get("clicks") or 0)
        items.append({
            "key": key,
            "make": p.get("make") or "",
            "model": p.get("model") or "",
            "badge": p.get("badge") or "",
            "make_label": names.get(p.get("make") or "", p.get("make") or ""),
            "model_label": names.get(p.get("model") or "", p.get("model") or ""),
            "available": await db.listings.count_documents(_pick_query(p)),
            "impressions": shown,
            "clicks": clicks,
            "ctr": round(clicks * 100.0 / shown, 1) if shown else 0.0,
            "deposits": earned.get(key, 0),
            "score": scores[key],
            "rank": place.get(key, 0),
            "judged": scores[key] is not None,
        })
    return {"enabled": conf["enabled"], "auto_rank": conf["auto_rank"],
            "min_impressions": conf["min_impressions"], "picks": items,
            "custom": bool(await db.site_settings.count_documents({"_id": "default_taste"}))}


@api.put("/admin/reco-defaults")
async def admin_save_reco_defaults(body: RecoDefaultsBody, request: Request,
                                   x_admin_token: str = Header(default="")):
    admin = await _require_admin(request, x_admin_token)
    picks, seen = [], set()
    for raw in body.picks[:24]:
        p = {"make": raw.make.strip()[:60], "model": raw.model.strip()[:80],
             "badge": raw.badge.strip()[:80]}
        if not p["make"] or not p["model"] or _pick_key(p) in seen:
            continue
        seen.add(_pick_key(p))
        picks.append(p)
    await db.site_settings.update_one(
        {"_id": "default_taste"},
        {"$set": {"enabled": bool(body.enabled), "picks": picks,
                  "auto_rank": bool(body.auto_rank),
                  "min_impressions": max(1, min(int(body.min_impressions or 1), 100_000)),
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "updated_by": _actor(admin)}}, upsert=True)
    _rank_cache["key"] = ""          # the order must not survive a change to the list
    await _audit(request, _actor(admin), "reco.defaults", "default_taste",
                 f"{len(picks)} picks, {'on' if body.enabled else 'off'},"
                 f" auto-rank {'on' if body.auto_rank else 'off'}")
    return {"ok": True, "picks": picks}


# ── the call button ───────────────────────────────────────────────────────────────────
# A buyer who wants to talk should not have to hunt for a number, but a call at 23:40 rings
# in an empty office and reads as a company that does not answer. The button is always
# there; outside the hours the owner has set it says so first and asks whether to dial anyway.
CALL_TZ = os.environ.get("CALL_TZ", "Europe/Sofia")
CALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_CALL = {
    "enabled": True,
    "phone": "+359886717074",
    "phone_label": "+359 88 6717074",
    "hours": {
        "mon": {"open": "09:00", "close": "18:00", "closed": False},
        "tue": {"open": "09:00", "close": "18:00", "closed": False},
        "wed": {"open": "09:00", "close": "18:00", "closed": False},
        "thu": {"open": "09:00", "close": "18:00", "closed": False},
        "fri": {"open": "09:00", "close": "18:00", "closed": False},
        "sat": {"open": "10:00", "close": "15:00", "closed": False},
        "sun": {"open": "", "close": "", "closed": True},
    },
}


def _hhmm(value):
    """A 24-hour time, or "" — never a half-parsed one that would silently close the office."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not m:
        return ""
    hour, minute = int(m.group(1)), int(m.group(2))
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else ""


async def _call_conf():
    doc = await db.site_settings.find_one({"_id": "call_button"}) or {}
    conf = dict(DEFAULT_CALL)
    for key in ("phone", "phone_label"):
        if doc.get(key):
            conf[key] = str(doc[key])[:40]
    if "enabled" in doc:
        conf["enabled"] = bool(doc["enabled"])
    hours = {day: dict(row) for day, row in DEFAULT_CALL["hours"].items()}
    for day, row in (doc.get("hours") or {}).items():
        if day in CALL_DAYS and isinstance(row, dict):
            hours[day] = {"open": _hhmm(row.get("open")), "close": _hhmm(row.get("close")),
                          "closed": bool(row.get("closed"))}
    conf["hours"] = hours
    return conf


def _call_open(conf, now):
    """Open right now? A window with no times in it is closed, whatever the flag says."""
    today = conf["hours"][CALL_DAYS[now.weekday()]]
    if today.get("closed") or not today.get("open") or not today.get("close"):
        return False, today
    # Strings compare correctly in HH:MM, and a window that ends before it starts (an
    # overnight shift) is honoured by treating it as two halves of the clock.
    minute = now.strftime("%H:%M")
    if today["close"] > today["open"]:
        return today["open"] <= minute < today["close"], today
    return minute >= today["open"] or minute < today["close"], today


@api.get("/call-button")
async def call_button():
    """Whether to show the button, what to dial, and whether anybody is there to answer."""
    conf = await _call_conf()
    now = datetime.now(ZoneInfo(CALL_TZ))
    is_open, today = _call_open(conf, now)
    return {"enabled": conf["enabled"], "phone": conf["phone"],
            "phone_label": conf["phone_label"] or conf["phone"],
            "open_now": is_open, "timezone": CALL_TZ,
            "local_time": now.strftime("%H:%M"), "local_date": now.strftime("%Y-%m-%d"),
            "day": CALL_DAYS[now.weekday()],
            "today": today, "hours": conf["hours"]}


class CallWindow(BaseModel):
    open: str = ""
    close: str = ""
    closed: bool = False


class CallButtonBody(BaseModel):
    enabled: bool = True
    phone: str = ""
    phone_label: str = ""
    hours: dict[str, CallWindow] = Field(default_factory=dict)


@api.get("/admin/call-button")
async def admin_call_button(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    conf = await _call_conf()
    now = datetime.now(ZoneInfo(CALL_TZ))
    is_open, _ = _call_open(conf, now)
    return {**conf, "open_now": is_open, "timezone": CALL_TZ,
            "local_time": now.strftime("%H:%M"), "day": CALL_DAYS[now.weekday()]}


@api.put("/admin/call-button")
async def admin_save_call_button(body: CallButtonBody, request: Request,
                                 x_admin_token: str = Header(default="")):
    admin = await _require_admin(request, x_admin_token)
    phone = re.sub(r"[^\d+]", "", body.phone or "")[:24]
    if not phone:
        raise HTTPException(status_code=400, detail="a phone number is required")
    hours = {}
    for day in CALL_DAYS:
        row = body.hours.get(day)
        hours[day] = {"open": _hhmm(row.open) if row else "",
                      "close": _hhmm(row.close) if row else "",
                      "closed": bool(row.closed) if row else True}
    await db.site_settings.update_one(
        {"_id": "call_button"},
        {"$set": {"enabled": bool(body.enabled), "phone": phone,
                  "phone_label": (body.phone_label or phone).strip()[:40], "hours": hours,
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "updated_by": _actor(admin)}}, upsert=True)
    await _audit(request, _actor(admin), "call.button", "call_button",
                 f"{'on' if body.enabled else 'off'}, {phone}")
    return {"ok": True}


@api.post("/admin/reco-defaults/reset")
async def admin_reset_reco_defaults(request: Request, stats: bool = False,
                                    x_admin_token: str = Header(default="")):
    """`stats=1` clears the counters; otherwise the list goes back to the built-in seven."""
    admin = await _require_admin(request, x_admin_token)
    if stats:
        await db.reco_stats.delete_many({})
        _rank_cache["key"] = ""
        await _audit(request, _actor(admin), "reco.stats.reset", "reco_stats")
    else:
        await db.site_settings.delete_one({"_id": "default_taste"})
        _rank_cache["key"] = ""
        await _audit(request, _actor(admin), "reco.defaults.reset", "default_taste")
    return {"ok": True}



@api.post("/recommendations")
async def recommendations(body: TasteBody, request: Request):
    """Cars this visitor is most likely to want next."""
    lang = norm_lang(body.lang)
    makes = _weights(body.makes, 4)
    models = _weights(body.models, 6)
    fuels = _weights(body.fuels, 4)
    limit = max(1, min(body.limit, 24))
    if not makes and not models:
        # Nothing known about them yet: the owner's own shelf, then the crowd's.
        curated = await _curated_shelf(lang, body.exclude, limit)
        if curated:
            return {"items": curated, "lang": lang, "source": "curated"}
        return {"items": await _popular_shelf(lang, body.exclude, limit),
                "lang": lang, "source": "popular"}

    price, price_low, price_high = _centre(body.samples, 0)
    mileage, mileage_low, mileage_high = _centre(body.samples, 1)

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
    # closest ones without hiding a good car just outside it. Mileage is windowed too: a
    # buyer looking at 30,000 km cars is not shopping for a 200,000 km one, and without this
    # the shelf answered a €90,000 M2 with the cheapest, most worn BMWs in the catalogue.
    if price_low and price_high:
        query["sale_eur"] = {"$gte": price_low * 0.7, "$lte": price_high * 1.4}
    if mileage_low and mileage_high:
        query["mileage"] = {"$lte": max(mileage_high * 1.6, 30_000)}
    # The shelf only exists on the landing view, so the same floor applies. It can never
    # lower the taste window's own floor, only raise it.
    apply_home_floor(query)

    rows = [d async for d in db.listings.find(query).sort(SORTS["newest"]).limit(300)]
    if len(rows) < limit and "mileage" in query:
        # The mileage window can be genuinely empty (one look at a nearly-new car). Widening
        # THAT is fair; widening the price is not - a €20,000 buyer being shown a €54,000 car
        # is the very mismatch this window exists to prevent.
        query.pop("mileage", None)
        rows = [d async for d in db.listings.find(query).sort(SORTS["newest"]).limit(300)]
    if not rows:
        return {"items": await _popular_shelf(lang, body.exclude, limit),
                "lang": lang, "source": "popular"}

    # Variety must not starve the shelf: with a single-make profile every candidate is that
    # make, and a flat cap of four returned four cars for a request for twelve. Two of the
    # same model is still the limit - twelve near-identical cars are not a shelf.
    per_make = max(4, -(-limit // max(1, len(makes)))) if makes else limit
    best = _space(_spread(_rank_by_taste(rows, makes, models, fuels, price, mileage),
                          limit, per_model=2, per_make=per_make))

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


async def _labels(values, lang, budget=2.5):
    """Translated labels without ever making a visitor wait long.

    Warm cache: instant, no provider is touched. COLD cache: one attempt with a hard time
    budget, because a page full of Korean model names is worse than a short wait — that is
    what a freshly deployed server with an empty `translations` collection hits. Whatever is
    still missing after the budget is filled in the background and is instant from then on.
    """
    tmap = await translate_cached_only(db, values, lang)
    cold = [v for v in values if v not in tmap]
    if not cold:
        return tmap
    try:
        got = await asyncio.wait_for(translate_many(db, cold, lang), timeout=budget)
        tmap.update(got or {})
        cold = [v for v in cold if v not in tmap]
    except Exception as e:
        log.warning("labels: %s cold values (%s) not ready in %.1fs: %s",
                    len(cold), lang, budget, str(e)[:120])
    if cold:
        schedule_translation(db, cold, lang)
    return tmap


_filters_refreshing = False


async def _compute_filters():
    """The facet aggregation: values, counts and the slider bounds. Writes the cache.

    Pulled out of the endpoint so it can also run BEHIND a visitor (see below) instead of
    making whoever happens to arrive first after the TTL expires wait for it. Single-flight:
    a burst of visitors on a stale cache must start ONE aggregation, not twenty.
    """
    global _filters_refreshing
    if _filters_refreshing:
        return None
    _filters_refreshing = True
    try:
        return await _filters_aggregate()
    finally:
        _filters_refreshing = False


async def _filters_aggregate():
    now = datetime.now(timezone.utc)

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

    doc = {
        "_id": "filters", "computed_at": now, "makes": makes, "fuels": fuels,
        "regions": regions, "transmissions": transmissions, "bounds": bounds,
    }
    await db.facets.update_one({"_id": "filters"}, {"$set": doc}, upsert=True)
    return doc


@api.get("/meta/filters")
async def meta_filters(lang: str = "bg", refresh: bool = False):
    """Facet values + counts, computed by aggregation and cached (TTL 10 min)."""
    lang = norm_lang(lang)
    cached = None if refresh else await db.facets.find_one({"_id": "filters"})
    if cached:
        age = (datetime.now(timezone.utc)
               - cached["computed_at"].replace(tzinfo=timezone.utc)).total_seconds()
        if age > FACET_TTL:
            # Stale-while-revalidate. This aggregation takes over a second on 220k cars, and
            # it used to be paid by whichever visitor happened to arrive first after the
            # ten-minute window expired. Ten-minute-old counts are fine; a slow sidebar is
            # not, so they get the cached answer and the refresh runs behind them.
            asyncio.create_task(_compute_filters())
    else:
        # First ever call (or ?refresh=1). If another request is already aggregating, take
        # whatever it has written rather than starting a second one or failing.
        cached = (await _compute_filters()
                  or await db.facets.find_one({"_id": "filters"})
                  or {"makes": [], "fuels": [], "regions": [], "transmissions": [],
                      "bounds": {}})

    # translate facet labels (bounded set, cached forever after first pass).
    # No slice on makes: every make must render in the user's language, not just the
    # 80 most common ones.
    labels = [x["value"] for x in cached.get("makes", [])]
    labels += [x["value"] for x in cached.get("fuels", [])]
    labels += [x["value"] for x in cached.get("regions", [])]
    make_values = [x["value"] for x in cached.get("makes", [])]
    # Cache first, one short attempt for anything cold, background fill for the rest.
    tmap = await _labels(labels, lang)
    # Marque names are proper nouns: English in every language. The full make list is a closed
    # set, so it is cached permanently as one document rather than looked up value by value.
    make_labels = await cached_label_set(db, "tax:en:1:|||filters", make_values, "en")
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
    tmap = await _labels([r["value"] for r in rows], lang)
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

    # The owner's curation (curate.py) has to be loaded BEFORE the query is built: if a make
    # was merged into another, the surviving make's dropdown must list the models of both.
    await curate.refresh(db)
    try:
        await curate.ensure_years(db)
    except Exception as e:
        log.warning("model year spans failed: %s", str(e)[:160])

    q = {"level": level}
    if level >= 2:
        q["make"] = {"$in": curate.expand(1, [make])}
    if level >= 3:
        q["model"] = {"$in": curate.expand(2, [model])}
    if level >= 4:
        q["badge"] = {"$in": curate.expand(3, [badge])}

    found = [
        {"value": d["value"], "count": d["count"], "slug": d.get("slug") or ""}
        async for d in db.taxonomy.find(q, {"value": 1, "count": 1, "slug": 1})
        .sort([("value", 1)])          # alphabetical, not by popularity
        .limit(limit)
    ]
    # Two merged makes can list the same model name; it must appear once, with both counts.
    rows = []
    seen = {}
    for r in found:
        if r["value"] in seen:
            seen[r["value"]]["count"] += r["count"]
            continue
        seen[r["value"]] = r
        rows.append(r)
    # `raw=1` skips the collapse, which is how the admin screen sees what to merge.
    if not raw:
        rows = curate.collapse(rows, level)
    values = [r["value"] for r in rows]
    # Levels 1 and 2 are marques and model names: proper nouns, always English.
    # Marques, models AND trims are proper nouns — always Latin, never transliterated.
    label_lang = "en"
    # One permanently cached set per dropdown: "every model of Hyundai" is a closed list, so
    # once it has been translated it is one document read forever after. We WAIT for the
    # provider on a genuinely new value instead of serving Hangul and fixing it behind the
    # visitor - the wait happens once in the life of the site, the Korean would be seen by
    # everyone until the background job landed.
    set_id = f"tax:{label_lang}:{level}:{make}|{model}|{badge}"
    tmap = await cached_label_set(db, set_id, values, label_lang)

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
@api.post("/admin/rebuild-derived")
async def admin_taxonomy(x_admin_token: str = Header(default="")):
    """Rebuild everything that is DERIVED from the catalogue, in the right order.

    This used to build only the dropdown tree, which is why a freshly deployed server had
    menus but no year spans next to the model names and no URL slugs. It is the whole
    post-crawl pass now, so one call fixes all of it — `deploy/doctor.py` points here.
    """
    _check_admin(x_admin_token)
    return await sync_mod.post_crawl(db)


_CONTRACT_RECHECK_HOURS = float(os.environ.get("CONTRACT_RECHECK_HOURS") or 6)
_rechecking = set()


def _recheck_contract(listing_id, cached):
    """Ask Encar again, in the background, whether a car is still on sale.

    A car's detail documents are immutable, so they are fetched once and cached forever — but
    its SALES STATUS is not: an ad that was on sale when we cached it can go under contract
    an hour later. The check costs one upstream request per car per
    CONTRACT_RECHECK_HOURS and never delays the page: the visitor reading it now sees the ad,
    and by the time anyone else opens it, it is already out of the catalogue.
    """
    at = cached.get("status_at")
    if at is not None:
        # Mongo hands datetimes back NAIVE, and subtracting one of those from a tz-aware
        # `now()` raises — which would 500 every cached car page.
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - at).total_seconds() < _CONTRACT_RECHECK_HOURS * 3600:
            return
    if listing_id in _rechecking:
        return
    _rechecking.add(listing_id)

    async def run():
        try:
            fresh = await encar.detail(listing_id)
            if not fresh:
                return
            status = sales_status(fresh)
            await db.car_details.update_one(
                {"_id": listing_id},
                {"$set": {"sales_status": status,
                          "status_at": datetime.now(timezone.utc)}})
            if under_contract(fresh):
                await db.listings.update_one(
                    {"_id": listing_id},
                    {"$set": {"active": False, "sold": True, "under_contract": True,
                              "sales_status": "CONTRACT",
                              "sold_at": datetime.now(timezone.utc)}})
                log.info("car %s is under contract on Encar - retired", listing_id)
        except Exception as e:                      # noqa: BLE001 - never break a page view
            log.warning("contract re-check failed for %s: %s", listing_id, str(e)[:140])
        finally:
            _rechecking.discard(listing_id)

    asyncio.get_running_loop().create_task(run())


async def _gone(listing, listing_id, lang, contract=False):
    """Encar has nothing for this ad any more — it sold, was pulled, or is under contract.

    A bare "not found" is a dead end for a buyer who followed a link, so the ad is retired
    from our index and the same make and model are offered in its place. 410 Gone rather
    than 404: the car existed, it simply is not coming back.
    """
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found upstream")
    retire = {"active": False, "sold": True, "sold_at": datetime.now(timezone.utc)}
    if contract:
        # Also what search filters on, so it disappears from the grid immediately.
        retire["under_contract"] = True
        retire["sales_status"] = "CONTRACT"
    await db.listings.update_one({"_id": listing_id}, {"$set": retire})

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
        "contract": bool(contract),
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


_HANGUL = re.compile(r"[\uac00-\ud7a3]")
# Anything in brackets in a model name is either the production years or the factory's own
# generation code — "Cayenne (PO536)", "5 Series (F10)", "Morning (JA)". Neither means anything
# to a buyer reading a chat preview, and both push the trim out of a title that gets truncated.
_BRACKETS = re.compile(r"\s*[(（][^)）]*[)）]")
# Korean marketing calls a facelift "올 뉴": the English cache turns that into "All New Sorento"
# and "The All-New Niro EV". The model is the Sorento and the Niro.
_ALL_NEW = re.compile(r"^\s*(the\s+)?all[\s-]*new\s+", re.I)


def _title_part(value):
    """One piece of a preview title, with the noise the catalogue carries stripped out."""
    value = _BRACKETS.sub("", str(value or ""))
    value = _ALL_NEW.sub("", value)
    return " ".join(value.split())


def _share_title(doc):
    """Make, model, trim and sub-trim, as a link preview should read them.

    Rules learned from real ads:
      * brackets go — the production years and the factory generation code ("(2019-)",
        "(PO536)") are noise in a chat bubble and crowd out the trim;
      * "All New" / "The All-New" goes — that is Korean marketing for a facelift, not part of
        the model's name;
      * anything still in Hangul is dropped rather than shown: Encar's sub-trim is often
        untranslatable filler ("(세부등급 없음)" literally means "no sub-grade");
      * a sub-trim that merely repeats the trim is not printed twice.
    """
    if not doc:
        return ""
    parts = []
    for field in ("manufacturer", "model", "badge", "badge_detail"):
        raw = str(doc.get(f"{field}_t") or doc.get(field) or "").strip()
        # A part that is nothing BUT a parenthetical is Encar's own filler, translated or not:
        # "(세부등급 없음)" comes back as "(No detailed trim)" and belongs in no title.
        if raw.startswith("(") and raw.endswith(")"):
            continue
        value = _title_part(raw)
        if not value or _HANGUL.search(value):
            continue
        if any(value.casefold() in p.casefold() for p in parts):
            continue
        parts.append(value)
    # "BMW" + "M2" + "M2 Coupe" joins as "BMW M2 M2 Coupe" — a stutter. Consecutive
    # repeats of the same word collapse; non-adjacent repeats are legitimate names.
    words = " ".join(parts).split()
    return " ".join(w for i, w in enumerate(words)
                    if i == 0 or w.casefold() != words[i - 1].casefold())


def _share_base(request: Request):
    """The absolute site URL for og:* tags. Never relative: Facebook rejects those."""
    return os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/") \
        or str(request.base_url).rstrip("/")


def _hit(request: Request, endpoint: str, ref: str):
    """One line per preview-related request, readable at GET /api/share-debug.

    iMessage previews are fetched by the SENDER'S OWN phone, so no debugger tool can show
    what it asked for and what it got — the only witness is this server. IPs are truncated
    to two octets: enough to tell an Apple device (17.x) from Facebook (157.240.x / 69.171.x)
    from the owner's own connection, and nothing more.
    """
    ip = (request.headers.get("cf-connecting-ip")
          or request.headers.get("x-real-ip")
          or (request.client.host if request.client else ""))
    parts = ip.split(".")
    coarse = f"{parts[0]}.{parts[1]}.x.x" if len(parts) == 4 else ip[:16]
    row = {"_id": str(uuid.uuid4()),
           "ts": datetime.now(timezone.utc),
           "endpoint": endpoint, "ref": (ref or "")[:120],
           "method": request.method,
           "ua": (request.headers.get("user-agent") or "")[:300],
           "range": request.headers.get("range") or "",
           "inm": request.headers.get("if-none-match") or "",
           "accept": (request.headers.get("accept") or "")[:120],
           "ip": coarse}
    asyncio.get_running_loop().create_task(_hit_write(row))


async def _hit_write(row):
    try:
        await db.share_hits.insert_one(row)
    except Exception as e:
        log.info("share hit not recorded: %s", str(e)[:120])


@api.get("/share-debug")
async def share_debug(limit: int = 60):
    """The last preview-related requests, newest first. UA + truncated IP only."""
    rows = await db.share_hits.find({}, {"_id": 0}).sort("ts", -1) \
        .to_list(max(1, min(limit, 200)))
    for r in rows:
        r["ts"] = r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"])
    return {"hits": rows}


ENCAR_IMAGE_HOSTS = ("ci.encar.com", "img.encar.com", "image.encar.com", "static.encar.com")
# Facebook's debugger reports fb:app_id as missing on every URL. It is what ties a share back to
# the owner's own Facebook app (so the insights are theirs); sharing works without it, and an
# EMPTY one is worse than none, so the tag only appears once the id is configured.
FB_APP_ID = os.environ.get("FB_APP_ID", "").strip()


def _social_tags():
    return [f'<meta property="fb:app_id" content="{_attr(FB_APP_ID)}">'] if FB_APP_ID else []


_IMG_CLIENT = None
# One fetch per photo, however many callers want it at once. `share_car` warms the picture in
# the background while it answers the HTML and the crawler asks for that same picture a moment
# later, so without this the two race and BOTH pay a cold round trip to Korea — the preview
# then arrived without an image now and then, which is exactly the intermittent failure.
_IMG_INFLIGHT = {}


def _image_client():
    """A kept-alive client for Encar's CDN: a new one per photo paid a fresh TLS handshake
    across the world every time."""
    global _IMG_CLIENT
    if _IMG_CLIENT is None:
        _IMG_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=8, keepalive_expiry=120),
            headers={"Referer": "https://www.encar.com/", "User-Agent": "Mozilla/5.0"})
    return _IMG_CLIENT


def _img_file(url):
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    folder = Path(os.environ["MEDIA_ROOT"]) / "imgcache"
    for hit in folder.glob(f"{key}.*"):
        return hit
    return None


def _img_cached(url):
    hit = _img_file(url)
    if hit is None:
        return None
    return hit.read_bytes(), f"image/{hit.suffix.lstrip('.')}"


async def _fetch_encar_image(url):
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    folder = Path(os.environ["MEDIA_ROOT"]) / "imgcache"
    last = ""
    for attempt in (0, 1):
        try:
            r = await _image_client().get(url)
            if not r.is_error:
                kind = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
                subtype = kind.split("/")[-1] if kind.startswith("image/") else "jpeg"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{key}.{subtype}").write_bytes(r.content)
                return r.content, kind
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = str(e)[:120]
        if attempt == 0:
            await asyncio.sleep(0.4)
    # Logged, because "the preview sometimes has no picture" is otherwise invisible to us.
    log.warning("image-proxy could not fetch %s: %s", url[:110], last)
    raise HTTPException(502, "the image host refused that request")


async def _encar_image(url):
    """The bytes of an Encar photo, from disk if we have fetched it before.

    Facebook warns that "new images are processed asynchronously" when it cannot fetch the
    picture quickly, and a preview then arrives with no image on the first share. Encar's CDN
    is on the other side of the world, so every proxied photo is kept: the second fetch — the
    one the crawler makes — is local and instant.
    """
    hit = _img_cached(url)
    if hit:
        return hit
    task = _IMG_INFLIGHT.get(url)
    if task is None:
        task = asyncio.create_task(_fetch_encar_image(url))
        _IMG_INFLIGHT[url] = task
        task.add_done_callback(lambda t: _IMG_INFLIGHT.pop(url, None))
    return await asyncio.shield(task)


async def _preview_image_url(raw_image, base):
    """The preview picture URL, with the picture already on disk by the time we answer.

    A crawler asks for the HTML and then, within a moment, for the picture. Fetching it here
    (rather than only in a background task racing that request) means the crawler's fetch is
    local instead of a round trip to Encar's CDN in Korea, which is what made a preview arrive
    without a picture now and then.
    """
    if not raw_image:
        return ""
    proxy = f"{base}/api/image-proxy?url={quote(raw_image, safe='')}"
    hit = _img_file(raw_image)
    if hit is None:
        try:
            # A crawler waits a moment for the picture, and this is the ONLY chance to get it
            # on disk before it asks, so the fetch it makes is local instead of a trip to Korea.
            await asyncio.wait_for(asyncio.shield(_encar_image(raw_image)), 6)
        except (asyncio.TimeoutError, httpx.HTTPError, HTTPException, OSError) as e:
            log.info("preview picture not ready for %s: %s", raw_image[:80], str(e)[:120])
    return proxy


async def _warm_image(url):
    try:
        await _encar_image(url)
    except (httpx.HTTPError, HTTPException, OSError) as e:
        log.info("could not warm %s: %s", url[:80], str(e)[:120])


def _binary(request: Request, data: bytes, kind: str, max_age: int, mtime=None) -> Response:
    """A picture, answered the way every strict client expects a picture to be answered.

    Two things were missing and both are why an iMessage preview fell back to the site icon
    while Facebook, Viber and Instagram were happy — those three simply download the whole file.
    (1) HEAD: FastAPI does not add it to `@api.get`, so a client checking the picture first got
        405 and concluded there was none.
    (2) Range: a byte-range request was answered with 200 and the WHOLE file, with no
        `Accept-Ranges`, `ETag` or `Content-Range`. A client that asked for a range and is handed
        something else has every reason to give up.
    The header set mirrors AutoScout24's picture CDN (the delivery every chat app is happiest
    with): Last-Modified, Access-Control-Allow-Origin: *, Content-Disposition: inline.
    """
    etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
    headers = {"Cache-Control": f"public, max-age={max_age}",
               "Accept-Ranges": "bytes",
               "Access-Control-Allow-Origin": "*",
               "Content-Disposition": "inline",
               "ETag": etag}
    if mtime:
        headers["Last-Modified"] = formatdate(mtime, usegmt=True)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    ims = request.headers.get("if-modified-since")
    if ims and mtime and "if-none-match" not in request.headers:
        try:
            if parsedate_to_datetime(ims).timestamp() >= int(mtime):
                return Response(status_code=304, headers=headers)
        except (TypeError, ValueError):
            pass

    start, end = 0, len(data) - 1
    ranged = False
    asked = (request.headers.get("range") or "").strip().lower()
    if asked.startswith("bytes=") and "," not in asked:
        first, _, last = asked[6:].partition("-")
        try:
            if first:
                start = int(first)
                end = int(last) if last else end
            elif last:                                  # "bytes=-500": the last 500 bytes
                start = max(0, len(data) - int(last))
            else:                                       # "bytes=-": not a range at all
                raise ValueError
        except ValueError:
            start, end = 0, len(data) - 1
        else:
            end = min(end, len(data) - 1)
            if start > end:
                return Response(status_code=416, headers={
                    **headers, "Content-Range": f"bytes */{len(data)}"})
            # Apple's fetcher opens with "Range: bytes=0-" and reads a 200 answer as "this
            # server does not do ranges" — it then drops the image. So EVERY valid Range
            # request is answered 206 with a Content-Range, even one spanning the whole file.
            ranged = True

    body = data[start:end + 1]
    headers["Content-Length"] = str(len(body))
    if ranged:
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
    status = 206 if ranged else 200
    if request.method == "HEAD":
        return Response(status_code=status, media_type=kind, headers=headers)
    return Response(content=body, status_code=status, media_type=kind, headers=headers)


@api.api_route("/image-proxy", methods=["GET", "HEAD"])
async def image_proxy(url: str, request: Request):
    """Serve an Encar photo from OUR domain.

    A link preview is fetched by Facebook's own servers, and a CDN that answers a browser
    happily can still refuse an unknown crawler (hotlink protection, referer checks, plain
    geo-blocking) — the preview then arrives with no picture at all and the app gets blamed.
    Only Encar's own image hosts are allowed through, so this can never be turned into an open
    proxy for the whole internet.
    """
    host = urlparse(url).hostname or ""
    if not url.startswith("https://") or host not in ENCAR_IMAGE_HOSTS:
        raise HTTPException(400, "only Encar images can be served through here")
    _hit(request, "image-proxy", url)
    # A HEAD must carry the REAL Content-Length: answering one instantly with a length of zero
    # (which is what an empty body produces) reads to Apple as "a picture of nothing" and the
    # preview fell back to the site icon EVERY time. So a HEAD fetches like a GET — the
    # in-flight dedupe above means it shares the warm `share_car` already started, not a second
    # trip to Korea.
    try:
        data, kind = await _encar_image(url)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not fetch that image: {str(e)[:120]}")
    hit = _img_file(url)
    return _binary(request, data, kind, 604800, hit.stat().st_mtime if hit else None)


@api.api_route("/og/{listing_id}.jpg", methods=["GET", "HEAD"])
async def og_image(listing_id: str, request: Request):
    """The share preview photo under a clean .jpg URL.

    iMessage previews are built on the SENDER'S device, and Apple's fetcher has been seen
    dropping an og:image whose URL is one long percent-encoded query string with no file
    extension — exactly what /api/image-proxy?url=… is. A plain path ending in .jpg gives
    it nothing to mistrust; the bytes underneath are the same cached Encar photo.
    """
    _hit(request, "og-image", listing_id)
    doc = await db.listings.find_one({"_id": listing_id}, {"photos": 1})
    photos = (doc or {}).get("photos") or []
    if not photos:
        _hit(request, "og-image-resp", f"{listing_id} -> 404 no photo")
        raise HTTPException(404, "that car has no photo")
    url = image_url(photos[0], 1200, 630)
    data, kind = await _encar_image(url)
    hit = _img_file(url)
    resp = _binary(request, data, kind, 604800, hit.stat().st_mtime if hit else None)
    # What we ANSWERED, next to what was asked — reading /api/share-debug then shows the
    # whole exchange with Apple's fetcher, not just its arrival.
    _hit(request, "og-image-resp", f"{listing_id} -> {resp.status_code}, {len(data)}b {kind}")
    return resp


# Digit grouping exactly as Intl.NumberFormat does it for the three page locales
# (bg-BG NBSP and only from 10 000 up, ro-RO full stop, en-GB comma). Kept here because a
# preview and the rendered page must quote the same car identically.
_GROUPING = {"bg": ("\u00a0", 10000), "ro": (".", 1000), "en": (",", 1000)}


def _fmt_int(n, lang: str) -> str:
    sep, floor = _GROUPING.get(lang, _GROUPING["bg"])
    v = int(round(n))
    grouped = f"{v:,}"
    return grouped.replace(",", "") if abs(v) < floor else grouped.replace(",", sep)


def _fmt_price(amount, lang: str, currency: str = "EUR") -> str:
    v = _fmt_int(amount, lang)
    if currency == "RON":
        return f"{v}\u00a0RON"
    if lang == "en":
        return f"\u20ac{v}"
    if lang == "ro":
        return f"{v}\u00a0EUR"
    return f"{v}\u00a0\u20ac"


async def _share_price(sale_eur, lang: str) -> str:
    """The price the PAGE shows: Romanian visitors are quoted in RON (AppContext), everyone
    else in EUR. A preview quoting euros to a Romanian would not match the ad they open."""
    if not sale_eur:
        return ""
    if lang != "ro":
        return _fmt_price(sale_eur, lang)
    rates = await fx_mod.get_rates(db)
    return _fmt_price(sale_eur * float(rates.get("eur_ron") or 4.977), lang, "RON")



@api.get("/share/car/{listing_id}", response_class=HTMLResponse)
async def share_car(listing_id: str, request: Request, lang: str = "bg"):
    """A shareable link whose preview picture is the ad's own lead photo.

    Viber, Messenger, WhatsApp and Facebook never run our JavaScript, so the og:* tags the
    car page writes at runtime are invisible to them. This page carries them in the HTML
    and forwards a human straight to the car.
    """
    lang = norm_lang(lang)
    _hit(request, "share-car", listing_id)
    doc = await db.listings.find_one(
        {"_id": listing_id},
        {"photos": 1, "manufacturer": 1, "model": 1, "manufacturer_t": 1, "model_t": 1,
         "badge": 1, "badge_detail": 1, "year_month": 1, "mileage": 1, "sale_eur": 1})
    photos = (doc or {}).get("photos") or []
    # Makes, models and trims are all resolved from the ENGLISH cache (they are proper nouns),
    # so a shared link never shows a Korean name.
    if doc:
        await translate_listings(db, [doc], lang,
                                 fields=("manufacturer", "model", "badge", "badge_detail"))
    title = _share_title(doc) or "Europe Encar"
    ym = str((doc or {}).get("year_month") or "")
    facts = [f"{ym[4:6]}/{ym[:4]}" if len(ym) >= 6 else "",
             f"{_fmt_int((doc or {}).get('mileage'), lang)} km"
             if (doc or {}).get("mileage") else "",
             # Byte-identical to what the page prints (Intl.NumberFormat, see lib/format.js), so
             # a chat preview and the page itself never quote one car's price in two formats.
             await _share_price((doc or {}).get("sale_eur"), lang)]
    # The SAME description the page itself writes (see CarDetailPage `useSeo`): the facts, then
    # the one thing that makes this site worth using. A shared link and a search result should
    # not describe the same car differently.
    blurb = {
        "bg": "крайна цена до България с мито, ДДС и доставка.",
        "ro": "preț final livrat, cu taxe vamale, TVA și transport incluse.",
        "en": "final landed price with duty, VAT and delivery included.",
    }[lang]
    description = " · ".join([f for f in facts if f])
    description = f"{description} — {blurb}" if description else blurb
    # 1200x630 is what every chat app and social network crops to, and the picture is served
    # through OUR domain: Encar's CDN answers a browser but can refuse an unknown crawler, and
    # a refused image means a preview with no picture at all. Round 5 tried handing Apple the
    # bare ci.encar.com URL (AutoScout-style) — share-debug then proved the phone fetches
    # /api/og/{id}.jpg just fine (com.apple.WebKit.Networking hits at 20:23/20:40Z) while the
    # direct CDN fetch silently failed on the device (ci.encar.com has no AAAA record and the
    # owner's phone sits on Vivacom IPv6). So EVERY crawler gets the proxied URL again.
    raw_image = image_url(photos[0], 1200, 630) if photos else ""
    base = _share_base(request)
    image = ""
    if raw_image:
        # Still warmed onto disk BEFORE the HTML is answered (the crawler asks for the
        # picture a moment later), but the URL it is told to fetch is /api/og/{id}.jpg.
        await _preview_image_url(raw_image, base)
        image = f"{base}/api/og/{listing_id}.jpg"
    target = f"{base}/{lang}/car/{listing_id}"
    og_locale = {"bg": "bg_BG", "ro": "ro_RO", "en": "en_GB"}[lang]

    # Encar's own detail head is the reference (see fem.encar.com/cars/detail/*): one og:title,
    # one og:image, one og:description and og:url, plus site_name and locale. No twitter:*
    # duplicates, no og:image:secure_url or width/height/alt companions - those companion tags
    # were the last route the site logo took into a car preview when the SPA shell's defaults
    # leaked through. The picture is a car photo or it is absent; nothing falls back to a logo.
    tags = [f'<meta name="description" content="{_attr(description)}">',
            f'<meta property="og:title" content="{_attr(title)}">',
            f'<meta property="og:description" content="{_attr(description)}">',
            f'<meta property="og:url" content="{_attr(target)}">',
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="Europe Encar">',
            f'<meta property="og:locale" content="{og_locale}">']
    if image:
        tags.append(f'<meta property="og:image" content="{_attr(image)}">')
    tags += _social_tags()

    html = ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{_attr(title)}</title>" + "".join(tags)
            + f'<link rel="canonical" href="{_attr(target)}">'
            # No <meta http-equiv=refresh> here: an instant refresh pointing at the very URL
            # the crawler just fetched reads as a redirect loop to some fetchers (Apple's own
            # technote says metadata must stand WITHOUT redirects). Humans landing here are
            # forwarded by the script below; crawlers never follow either.
            + "</head><body>"
            + f'<a href="{_attr(target)}">{_attr(title)}</a>'
            + f'<script>location.replace("{target}")</script>'
            + "</body></html>")
    # Warmed in the background: the crawler asks for the HTML first and the picture a moment
    # later, so fetching from Encar NOW means the picture is already on disk when it does.
    # Facebook's "images are processed asynchronously" notice is exactly that race.
    if raw_image:
        asyncio.create_task(_warm_image(raw_image))
    # Chat apps cache previews hard; a day is long enough to be cheap and short enough
    # that a price change is picked up.
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=86400"})


def _map_stops(view):
    """Consecutive events in the same port collapse into one stop, like the Track page map."""
    stops = []
    for m in view.get("milestones") or []:
        if m.get("lat") is None or m.get("lon") is None:
            continue
        if stops and stops[-1]["lat"] == m["lat"] and stops[-1]["lon"] == m["lon"]:
            stops[-1]["estimated"] = stops[-1]["estimated"] and bool(m.get("estimated"))
            continue
        stops.append({"lat": m["lat"], "lon": m["lon"], "estimated": bool(m.get("estimated"))})
    return stops


def _default_stops():
    """Korea to Rotterdam: what the page is ABOUT, for a link with no reference on it."""
    out = []
    for name in ("INCHON", "SINGAPORE", "ROTTERDAM"):
        where = ports_mod.locate(name=name)
        if where:
            out.append({"lat": where["lat"], "lon": where["lon"], "estimated": False})
    return out


@api.api_route("/map/track.png", methods=["GET", "HEAD"])
async def map_track_png(request: Request, ref: str = "", by: str = "bol"):
    """The shipment's route drawn on OpenStreetMap tiles, for link previews.

    Messenger, Viber and WhatsApp never run our JavaScript, so the Leaflet map cannot be the
    preview picture — this is the same route, rendered server side.
    """
    ref = (ref or "").strip().upper()[:40]
    by = by if by in ("container", "bol") else "bol"
    key = hashlib.sha256(f"{ref}|{by}".encode()).hexdigest()[:32]
    data = mapshot.fresh(key)
    if data is None:
        stops = []
        if ref:
            try:
                view = await tracking.track(db, ref, by)
                if view.get("found"):
                    stops = _map_stops(view)
            except (ValueError, RuntimeError) as e:
                log.warning("map for %s failed: %s", ref, str(e)[:160])
        img = await mapshot.render(stops or _default_stops())
        if img is None:
            raise HTTPException(status_code=404, detail="no route to draw")
        data = mapshot.store(key, img)
    return _binary(request, data, "image/png", 21600)


@api.get("/share/track", response_class=HTMLResponse)
async def share_track(request: Request, ref: str = "", by: str = "bol", lang: str = "bg"):
    """The Track page as a shareable link: the preview picture is the route on a real map."""
    lang = norm_lang(lang)
    _hit(request, "share-track", ref)
    ref = (ref or "").strip().upper()[:40]
    by = by if by in ("container", "bol") else "bol"
    base = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/") \
        or str(request.base_url).rstrip("/")
    copy = {
        "bg": ("Проследи автомобила си · Encar Europe",
               "Виж къде е контейнерът с колата ти — от терминала в Корея до доставката."),
        "ro": ("Urmărește mașina ta · Encar Europe",
               "Vezi unde este containerul mașinii tale — din terminalul din Coreea până la livrare."),
        "en": ("Track my vehicle · Encar Europe",
               "See where your car's container is — from the terminal in Korea to delivery."),
    }[lang]
    title = f"{copy[0]} · {ref}" if ref else copy[0]
    query = f"?ref={ref}&by={by}" if ref else ""
    target = f"{base}/{lang}/track{query}"
    image = f"{base}/api/map/track.png{query}"
    tags = [f'<meta property="og:title" content="{_attr(title)}">',
            f'<meta property="og:description" content="{_attr(copy[1])}">',
            f'<meta property="og:url" content="{_attr(target)}">',
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="Europe Encar">',
            f'<meta property="og:image" content="{_attr(image)}">',
            f'<meta property="og:image:secure_url" content="{_attr(image)}">',
            '<meta property="og:image:type" content="image/png">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            f'<meta property="og:image:alt" content="{_attr(copy[0])}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{_attr(title)}">',
            f'<meta name="twitter:description" content="{_attr(copy[1])}">',
            f'<meta name="twitter:image" content="{_attr(image)}">']
    tags += _social_tags()
    html = ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{_attr(title)}</title>" + "".join(tags)
            + f'<link rel="canonical" href="{_attr(target)}">'
            + "</head><body>"
            + f'<a href="{_attr(target)}">{_attr(title)}</a>'
            + f'<script>location.replace("{target}")</script>'
            + "</body></html>")
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=21600"})


# --- Sitemaps -----------------------------------------------------------------
# Google reads a sitemap index and follows it to child sitemaps; a single flat
# sitemap tops out at 50 000 URLs and 50 MB, and this catalogue is well past that.
# The split by content type also means a fresh listing invalidates only the
# listings sitemap it lives in, not the makes/models one - crawl budget stays on
# the pages that actually changed.
#
# The three languages are declared as `xhtml:link rel="alternate" hreflang="…"`
# WITHIN one <url> entry (Google's recommendation) instead of three separate
# entries per listing; a file with 40 000 <url> elements each carrying three
# alternates counts as 40 000 URLs, not 120 000, so a chunk holds three times
# more real listings.

# 40 000 keeps a good headroom under Google's 50 000 hard limit and produces
# ~4 files for a 146k catalogue.
_SITEMAP_CHUNK = 40_000
_SITEMAP_TTL = 3600


def _sitemap_headers():
    return {"Content-Type": "application/xml; charset=utf-8",
            "Cache-Control": f"public, max-age={_SITEMAP_TTL}"}


def _sitemap_url(base: str, path_for: dict, lastmod: str,
                 changefreq: str = "weekly", priority: str = "0.5") -> str:
    """One <url> entry with an hreflang alternate for every language.

    `path_for` maps a language code to its URL path (starting with `/`). The primary
    <loc> is the English variant so a crawler that ignores alternates still walks the
    canonical version; x-default points there too.
    """
    parts = [f"<loc>{_attr(base + path_for['en'])}</loc>"]
    for code, path in path_for.items():
        parts.append(f'<xhtml:link rel="alternate" hreflang="{code}" '
                     f'href="{_attr(base + path)}"/>')
    parts.append(f'<xhtml:link rel="alternate" hreflang="x-default" '
                 f'href="{_attr(base + path_for["en"])}"/>')
    parts.append(f"<lastmod>{lastmod}</lastmod>")
    parts.append(f"<changefreq>{changefreq}</changefreq>")
    parts.append(f"<priority>{priority}</priority>")
    return "<url>" + "".join(parts) + "</url>"


def _sitemap_wrap(urls: list) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
            + "".join(urls) + "</urlset>")


async def _active_listings_count() -> int:
    return await db.listings.count_documents(
        {"active": True, "duplicate": {"$ne": True}, "under_contract": {"$ne": True}})


@api.get("/sitemap.xml")
async def sitemap_index(request: Request):
    """Points at every child sitemap. Google fetches this first."""
    base = _share_base(request)
    total = await _active_listings_count()
    chunks = max(1, -(-total // _SITEMAP_CHUNK))  # ceil
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = [
        f"<sitemap><loc>{_attr(base)}/sitemap-static.xml</loc>"
        f"<lastmod>{today}</lastmod></sitemap>",
        f"<sitemap><loc>{_attr(base)}/sitemap-models.xml</loc>"
        f"<lastmod>{today}</lastmod></sitemap>",
    ]
    for i in range(1, chunks + 1):
        entries.append(
            f"<sitemap><loc>{_attr(base)}/sitemap-listings-{i}.xml</loc>"
            f"<lastmod>{today}</lastmod></sitemap>")
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries) + "</sitemapindex>")
    return Response(body, headers=_sitemap_headers())


@api.get("/sitemap-static.xml")
async def sitemap_static(request: Request):
    """Landings and evergreen pages: /, /how-it-works, /faq, /terms, /track, ..."""
    base = _share_base(request)
    langs = list(LANGS)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # (path_suffix, changefreq, priority). "" means the landing itself.
    routes = [
        ("", "hourly", "1.0"),
        ("/how-it-works", "monthly", "0.8"),
        ("/faq", "monthly", "0.7"),
        ("/terms", "yearly", "0.3"),
        ("/privacy", "yearly", "0.3"),
        ("/cookies", "yearly", "0.3"),
        ("/contact", "monthly", "0.4"),
        ("/fees", "monthly", "0.5"),
        ("/track", "weekly", "0.5"),
    ]
    urls = []
    for suffix, freq, prio in routes:
        path_for = {code: f"/{code}{suffix}" for code in langs}
        urls.append(_sitemap_url(base, path_for, today, freq, prio))
    return Response(_sitemap_wrap(urls), headers=_sitemap_headers())


@api.get("/sitemap-models.xml")
async def sitemap_models(request: Request):
    """Every make landing (/bg/bmw) and every make/model landing (/bg/bmw/m2-g87)."""
    base = _share_base(request)
    langs = list(LANGS)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = []
    # Make landings (level 1)
    async for row in db.taxonomy.find(
            {"level": 1, "slug": {"$nin": [None, ""]}},
            {"slug": 1, "count": 1}):
        slug = row.get("slug")
        if not slug:
            continue
        path_for = {code: f"/{code}/{slug}" for code in langs}
        urls.append(_sitemap_url(base, path_for, today, "daily", "0.8"))
    # Make + model landings (level 2). The make slug must be resolved alongside the
    # model slug so the URL matches the router's /:lang/:makeSlug/:modelSlug shape.
    make_slugs = {}
    async for row in db.taxonomy.find(
            {"level": 1, "slug": {"$nin": [None, ""]}},
            {"value": 1, "slug": 1}):
        make_slugs[row["value"]] = row["slug"]
    async for row in db.taxonomy.find(
            {"level": 2, "slug": {"$nin": [None, ""]}},
            {"make": 1, "slug": 1, "count": 1}):
        mslug = make_slugs.get(row.get("make"))
        modelslug = row.get("slug")
        if not mslug or not modelslug:
            continue
        path_for = {code: f"/{code}/{mslug}/{modelslug}" for code in langs}
        urls.append(_sitemap_url(base, path_for, today, "daily", "0.7"))
    return Response(_sitemap_wrap(urls), headers=_sitemap_headers())


@api.get("/sitemap-listings-{n}.xml")
async def sitemap_listings(n: int, request: Request):
    """Chunk N of the active-listing sitemap.

    Sorted by `_id` so the URL that shows up in chunk 3 today is very likely still
    in chunk 3 tomorrow - a page's sitemap position rarely churns, which is what
    Google's freshness signal cares about.
    """
    if n < 1:
        raise HTTPException(404, "sitemap chunk numbers start at 1")
    base = _share_base(request)
    langs = list(LANGS)
    total = await _active_listings_count()
    chunks = max(1, -(-total // _SITEMAP_CHUNK))
    if n > chunks:
        raise HTTPException(404, "no such sitemap chunk")
    skip = (n - 1) * _SITEMAP_CHUNK

    urls = []
    cursor = db.listings.find(
        {"active": True, "duplicate": {"$ne": True}, "under_contract": {"$ne": True}},
        {"_id": 1, "last_seen": 1}
    ).sort([("_id", 1)]).skip(skip).limit(_SITEMAP_CHUNK)
    async for row in cursor:
        lid = row["_id"]
        # last_seen is when the sync last confirmed the ad is live; that is the
        # freshness signal Google wants, not the day the row was inserted.
        lm = row.get("last_seen")
        if isinstance(lm, datetime):
            lastmod = lm.astimezone(timezone.utc).strftime("%Y-%m-%d")
        else:
            lastmod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path_for = {code: f"/{code}/car/{lid}" for code in langs}
        urls.append(_sitemap_url(base, path_for, lastmod, "daily", "0.6"))
    return Response(_sitemap_wrap(urls), headers=_sitemap_headers())




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
        if under_contract(detail):
            # A pending sale on Encar. Nobody may reserve it and nobody should waste time
            # reading it, so it leaves the catalogue the moment we learn about it.
            return await _gone(listing, listing_id, lang, contract=True)
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
            "sales_status": sales_status(detail),
            "status_at": datetime.now(timezone.utc),
            "fetched_at": datetime.now(timezone.utc),
        }
        await db.car_details.update_one({"_id": listing_id}, {"$set": cached}, upsert=True)

    detail = cached.get("detail") or {}
    if cached.get("sales_status", "").upper() == "CONTRACT":
        return await _gone(listing, listing_id, lang, contract=True)
    _recheck_contract(listing_id, cached)
    cat = detail.get("category") or {}
    spec = detail.get("spec") or {}
    adv = detail.get("advertisement") or {}
    opts = detail.get("options") or {}

    # ── photos: every one, at gallery and thumbnail size ─────────────────────────
    photos = []
    for path in detail_photo_paths(detail):
        photos.append({
            # 1280x720: the main gallery on the detail page AND the fullscreen lightbox
            # both use this URL, so a single fetch covers both views. 1080p was tried and
            # rolled back - the extra bytes did not translate to any visible sharpness on
            # a laptop at ~662x372 CSS px, and doubled the bytes for every gallery photo.
            "full": image_url(path, 1280, 720),
            # 500x280 sharpens the 224x126 CSS thumbnails on retina (they render around
            # 448x252 device px) without shipping a full gallery-sized picture per
            # thumbnail. 260x147 was visibly soft on the pinned desktop rail.
            "thumb": image_url(path, 500, 280),
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

    # TRIMS ARE LATIN EVERYWHERE. `gradeName` is the trim ("4도어 43 4MATIC+") and running it
    # through T localised it, so the car page printed a Bulgarian sub-model while the rows and
    # the filters said English. Encar's own English name wins; otherwise the ENGLISH cache is
    # read (never the page language, never a blocking call), and the last resort is the
    # listing's own already-Latin `badge_t`.
    trims = [v for v in (cat.get("gradeName"), cat.get("gradeDetailName"),
                         (listing or {}).get("badge"), (listing or {}).get("badge_detail"))
             if v]
    latin = await translate_cached_only(db, trims, "en") if trims else {}
    cold = [v.strip() for v in trims if HANGUL.search(v) and v.strip() not in latin]
    if cold:
        # Cache-only above, so a trim nobody has looked up yet would stay Korean forever.
        schedule_translation(db, list(dict.fromkeys(cold)), "en")

    def L(v):
        return latin.get((v or "").strip()) or v

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
        # Our own cached English trim FIRST, so the car page, the result rows and the filter
        # dropdown all spell it the same way ("4-Door 43 4MATIC+", not Encar's "4Door 43").
        "grade": (listing or {}).get("badge_t") or L((listing or {}).get("badge"))
        or cat.get("gradeEnglishName") or L(cat.get("gradeName")),
        "badge": (listing or {}).get("badge_t") or L((listing or {}).get("badge")),
        "badge_detail": (listing or {}).get("badge_detail_t")
        or L((listing or {}).get("badge_detail")),
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
    if token and ADMIN_TOKEN and secrets.compare_digest(token, ADMIN_TOKEN):
        return None
    user = await auth.optional_user(request)
    if not (user and user.get("is_admin")):
        raise HTTPException(status_code=401, detail="administrator sign-in required")
    return user


def _actor(admin):
    """Who did it. `None` means the master token was used rather than an account."""
    return (admin or {}).get("email") or "master token"


async def _audit(request, actor, action, target, detail=""):
    """A trail of everything an operator changes or throws away.

    Deletions and merges are invisible after the fact — the row is simply not there any more —
    so each one is written down with who, what and when before it happens.
    """
    await db.audit_log.insert_one({
        "_id": str(uuid.uuid4()),
        "at": datetime.now(timezone.utc).isoformat(),
        "actor": actor, "action": action, "target": target, "detail": detail,
        "ip": request.client.host if request.client else "",
    })


@api.get("/admin/audit")
async def admin_audit(request: Request, limit: int = 200,
                      x_admin_token: str = Header(default="")):
    """The trail, newest first."""
    await _require_admin(request, x_admin_token)
    rows = await db.audit_log.find({}).sort("at", -1).limit(min(limit, 500)).to_list(500)
    return {"items": [{"id": r["_id"], "at": r.get("at"), "actor": r.get("actor"),
                       "action": r.get("action"), "target": r.get("target"),
                       "detail": r.get("detail") or ""} for r in rows]}


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
        "email": await mailer.health(),
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


async def _remember_phone(user, phone):
    """Keep a signed-in buyer's number, so the next form is already filled in.

    A number typed into an enquiry is the same number we would call back on; asking for it a
    second time is how enquiries get abandoned. An account that already has one is left alone.
    """
    if not user or not phone or user.get("phone"):
        return
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"phone": phone[:32]}})


@api.post("/enquiry")
async def create_enquiry(body: EnquiryBody, request: Request):
    """Buyer enquiry about one car. Works for GUESTS as well as signed-in users - the
    account only pre-fills the contact details, it is never required to make contact."""
    user = await auth.optional_user(request)
    email = (body.email or (user or {}).get("email") or "").strip().lower()
    phone = phones.clean(body.phone, body.lang)
    if body.phone.strip() and not phone:
        raise HTTPException(400, "that does not look like a phone number we can dial")
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
    await _remember_phone(user, phone)
    log.info("enquiry %s for listing %s (guest=%s)", doc["_id"], doc["listing_id"],
             doc["is_guest"])
    mailer.send_enquiry_emails(doc)
    # The operator hears about it on their phone, not only when they next open the panel.
    notify.push_to_admins_later(
        "New enquiry",
        f"{doc['name'] or doc['email']} asked about {doc['car_title'] or doc['listing_id']}",
        f"/{doc['lang']}/admin", "enquiry")
    return {"ok": True, "id": doc["_id"]}


# ── "call me back" ────────────────────────────────────────────────────────────────────
# Offered ONLY when the office is shut: inside working hours the buyer should just dial. The
# requested slot is re-checked against the owner's hours on the server — a form is a
# suggestion, not a fact, and a callback booked for a Sunday would simply never happen.
CALLBACK_STATUSES = ("new", "called", "closed")


class CallbackBody(BaseModel):
    name: str = ""
    phone: str = ""
    email: str = ""
    day: str = ""          # YYYY-MM-DD, read in the office's own timezone
    time: str = ""         # HH:MM
    listing_id: str = ""
    car_title: str = ""
    message: str = ""
    lang: str = "bg"


@api.post("/callback")
async def request_callback(body: CallbackBody, request: Request):
    """"Call me on this number at this time." Both a phone AND an email are required: the
    phone is how we ring, the email is how the buyer gets a written confirmation."""
    user = await auth.optional_user(request)
    phone = phones.clean(body.phone, body.lang)
    if not phone:
        raise HTTPException(400, "please leave a phone number we can dial")
    email = (body.email or (user or {}).get("email") or "").strip().lower()[:200]
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(400, "please leave an email address")

    conf = await _call_conf()
    at = _hhmm(body.time)
    try:
        wanted = datetime.strptime(str(body.day or "")[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "pick a day for the call")
    window = conf["hours"][CALL_DAYS[wanted.weekday()]]
    if window.get("closed") or not window.get("open") or not window.get("close"):
        raise HTTPException(400, "we are closed that day, please pick another")
    if not at or not window["open"] <= at <= window["close"]:
        raise HTTPException(400, f"pick a time between {window['open']} and {window['close']}")
    slot = wanted.replace(hour=int(at[:2]), minute=int(at[3:]), tzinfo=ZoneInfo(CALL_TZ))
    if slot < datetime.now(ZoneInfo(CALL_TZ)):
        raise HTTPException(400, "that time has already passed, please pick a later one")

    doc = {
        "_id": str(uuid.uuid4()),
        "listing_id": body.listing_id[:64],
        "car_title": body.car_title[:200],
        "name": (body.name or (user or {}).get("name") or "").strip()[:120],
        "phone": phone,
        "email": email,
        "when": slot.isoformat(),
        "when_label": f"{wanted.strftime('%Y-%m-%d')} {at}",
        "timezone": CALL_TZ,
        "message": body.message.strip()[:2000],
        "lang": norm_lang(body.lang),
        "user_id": (user or {}).get("_id"),
        "status": "new",
        "created_at": datetime.now(timezone.utc),
    }
    await db.callbacks.insert_one(doc)
    await _remember_phone(user, phone)
    log.info("callback %s for %s at %s", doc["_id"], doc["phone"], doc["when_label"])
    mailer.send_callback_emails(doc)
    notify.push_to_admins_later(
        "Call-back request",
        f"{doc['name'] or doc['phone']} wants a call on {doc['when_label']}",
        f"/{doc['lang']}/admin?tab=enquiries", "callback")
    return {"ok": True, "id": doc["_id"], "when": doc["when_label"]}


@api.get("/admin/callbacks")
async def admin_callbacks(request: Request, status: str = "",
                          page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                          x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    query = {"status": status} if status in CALLBACK_STATUSES else {}
    total = await db.callbacks.count_documents(query)
    rows = [d async for d in db.callbacks.find(query)
            .sort("when", 1)
            .skip((page - 1) * page_size)
            .limit(page_size)]
    for r in rows:
        r["id"] = r.pop("_id")
    counts = {s: await db.callbacks.count_documents({"status": s}) for s in CALLBACK_STATUSES}
    return jsonable({"total": total, "page": page, "page_size": page_size,
                     "counts": counts, "items": rows})


class CallbackStatusBody(BaseModel):
    status: str


@api.patch("/admin/callbacks/{callback_id}")
async def admin_callback_status(callback_id: str, body: CallbackStatusBody, request: Request,
                               x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    if body.status not in CALLBACK_STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(CALLBACK_STATUSES)}")
    res = await db.callbacks.update_one(
        {"_id": callback_id},
        {"$set": {"status": body.status, "updated_at": datetime.now(timezone.utc)}})
    if not res.matched_count:
        raise HTTPException(404, "no such call-back request")
    return {"ok": True, "status": body.status}


@api.delete("/admin/callbacks/{callback_id}")
async def admin_callback_delete(callback_id: str, request: Request,
                                x_admin_token: str = Header(default="")):
    admin = await _require_admin(request, x_admin_token)
    res = await db.callbacks.delete_one({"_id": callback_id})
    if not res.deleted_count:
        raise HTTPException(404, "no such call-back request")
    await _audit(request, _actor(admin), "callback.delete", callback_id)
    return {"ok": True}
auth.set_db(db)
deposits.set_db(db)
notify.set_db(db)
csrf_mod.set_db(db)
geoip.set_db(db)
# ── shipment tracking ---------------------------------------------------------
class TrackBody(BaseModel):
    ref: str
    by: str = "container"
    label: str = ""
    car_id: str = ""


@api.get("/geo")
async def geo_hint(request: Request):
    """The dial-code dropdown: every prefix, plus the one to start on.

    The country comes from the CDN header where there is one and from a cached IP lookup
    otherwise (geoip.py). It is only a STARTING POINT — the buyer can pick any prefix, and a
    wrong guess costs one click, never a rejected number.
    """
    country = await geoip.country_of(request)
    return {"country": country, "dial": dialcodes.dial_of(country),
            "guessed": bool(country), "codes": dialcodes.LIST}


@api.get("/tracking")
async def tracking_lookup(request: Request, ref: str, by: str = "container",
                         refresh: bool = False):
    if by not in ("container", "bol"):
        raise HTTPException(400, "by must be container or bol")
    # An admin looking at the buyer-facing page gets the provider's own reason for a failure;
    # a buyer never does. `refresh` bypasses the cache: an answer cached while the carrier was
    # misconfigured outlives the fix by up to a day, and without this there was no way to say
    # "ask again for real".
    viewer = await auth.optional_user(request)
    try:
        return await tracking.track(db, ref, by, refresh=refresh,
                                    admin=bool(viewer and viewer.get("is_admin")))
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
        {"user_id": user["_id"], "payment_status": {"$in": list(deposits.HELD_STATES)}}
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


@api.post("/admin/search-watch/run")
async def admin_search_watch_run(request: Request, first_seen: bool = False,
                                x_admin_token: str = Header(default="")):
    """Check saved searches for new matches now, instead of waiting for the next sync."""
    await _require_admin(request, x_admin_token)
    return jsonable(await searchwatch_mod.run(db, notify_first_seen=first_seen))



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
    who = _actor(admin)
    out = await deposits.refund(session_id, (admin or {}).get("email") or "")
    await _audit(request, who, "deposit refunded", session_id,
                 f"car {out.get('car_id') or '?'}")
    return jsonable(out)


class CaptureBody(BaseModel):
    amount_eur: float


@api.post("/admin/deposits/{session_id}/capture")
async def admin_deposit_capture(session_id: str, body: CaptureBody, request: Request,
                                x_admin_token: str = Header(default="")):
    """Take part (or all) of a held amount. The rest is released by Stripe for good."""
    admin = await _require_admin(request, x_admin_token)
    who = _actor(admin)
    out = await deposits.capture(session_id, body.amount_eur,
                                 (admin or {}).get("email") or "")
    await _audit(request, who, "deposit captured", session_id,
                 f"€{out.get('captured_eur')} of €{out.get('held_eur')} "
                 f"on car {out.get('car_id') or '?'}")
    return jsonable(out)


@api.post("/admin/deposits/{session_id}/release")
async def admin_deposit_release(session_id: str, request: Request,
                                x_admin_token: str = Header(default="")):
    """Let a hold go without taking a cent and put the car back on the market."""
    admin = await _require_admin(request, x_admin_token)
    who = _actor(admin)
    out = await deposits.release(session_id, (admin or {}).get("email") or "")
    await _audit(request, who, "deposit hold released", session_id,
                 f"car {out.get('car_id') or '?'}")
    return jsonable(out)


@api.get("/admin/post-queue")
async def admin_post_queue(request: Request, x_admin_token: str = Header(default="")):
    """Everything the operator has ever sent to the mobile.bg bot, newest change first."""
    await _require_admin(request, x_admin_token)
    return {"items": await postqueue.recent()}


@api.get("/admin/post-queue/{encar_id}")
async def admin_post_queue_one(encar_id: str, request: Request,
                               x_admin_token: str = Header(default="")):
    """The button's own state: queued, posted (with the link), or failed (with the reason)."""
    await _require_admin(request, x_admin_token)
    return {"item": await postqueue.status_for(encar_id)}


@api.post("/admin/post-queue/{encar_id}")
async def admin_post_queue_add(encar_id: str, request: Request,
                               x_admin_token: str = Header(default="")):
    """Queue one car for mobile.bg. The bot picks it up on its next poll."""
    admin = await _require_admin(request, x_admin_token)
    who = _actor(admin)
    car = await db.listings.find_one({"_id": encar_id}, {"_id": 1})
    if not car:
        raise HTTPException(404, "no such car")
    item = await postqueue.queue(encar_id, who)
    await _audit(request, who, "queued for mobile.bg", encar_id)
    return {"item": item}






@api.get("/admin/shipments")
async def admin_shipments(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    rows = await db.shipments.find({}, {"_id": 0}).sort("updated_at", -1).to_list(200)

    # The list used to print the bare car id, which tells an operator nothing about whether the
    # right car was tied to the reference. One lookup for the whole page, names in the rows.
    ids = [r["car_id"] for r in rows if r.get("car_id")]
    titles = {}
    if ids:
        async for d in db.deposits.find({"car_id": {"$in": ids}, "car_title": {"$ne": ""}},
                                        {"car_id": 1, "car_title": 1}):
            titles.setdefault(d["car_id"], d.get("car_title") or "")
        async for lst in db.listings.find({"_id": {"$in": [i for i in ids if i not in titles]}},
                                          {"manufacturer": 1, "model": 1}):
            titles[lst["_id"]] = " ".join(str(x) for x in [lst.get("manufacturer"),
                                                           lst.get("model")] if x)
    for r in rows:
        r["car_title"] = titles.get(r.get("car_id") or "", "")
    return {"items": rows}


@api.get("/admin/customer-cars")
async def admin_customer_cars(request: Request, email: str,
                              x_admin_token: str = Header(default="")):
    """The cars this customer has actually reserved, newest first.

    The bill of lading has to be tied to a car by its id, and an id typed from memory is an id
    typed wrong: a mismatch is invisible - the reference simply never appears on the buyer's
    purchases page and nothing anywhere says why. So the operator picks from this list instead.
    """
    await _require_admin(request, x_admin_token)
    user = await db.users.find_one({"email": email.strip().lower()}, {"_id": 1})
    if not user:
        raise HTTPException(404, f"no account for {email}")

    rows = await db.deposits.find(
        {"user_id": user["_id"], "payment_status": {"$in": list(deposits.HELD_STATES)}},
        {"car_id": 1, "car_title": 1, "updated_at": 1, "created_at": 1}
    ).sort("updated_at", -1).to_list(50)

    assigned = {s["car_id"]: s["ref"] async for s in db.shipments.find(
        {"user_id": user["_id"], "car_id": {"$nin": ["", None]}}, {"car_id": 1, "ref": 1})}

    items, seen = [], set()
    for row in rows:
        car_id = row.get("car_id") or ""
        if not car_id or car_id in seen:
            continue
        seen.add(car_id)
        title = row.get("car_title") or ""
        if not title:
            listing = await db.listings.find_one({"_id": car_id},
                                                {"manufacturer": 1, "model": 1}) or {}
            title = " ".join(str(x) for x in [listing.get("manufacturer"),
                                              listing.get("model")] if x)
        items.append({"car_id": car_id, "title": title or car_id,
                      "reserved_at": jsonable(row.get("updated_at") or row.get("created_at")),
                      "assigned_ref": assigned.get(car_id, "")})
    return {"items": items}


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
                                    refresh=True, admin=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@api.post("/admin/digest/run")
async def admin_digest_run(request: Request, x_admin_token: str = Header(default="")):
    """Send the weekly saved-search digest now, without waiting for Saturday.

    Kept for the operator (and for testing what a buyer actually receives): it uses exactly
    the scheduled path, so a manual run also moves each search's window forward.
    """
    admin = await _require_admin(request, x_admin_token)
    result = await digest_mod.run(db)
    await _audit(request, _actor(admin), "search digest sent", "digest",
                 f"{result['emails']} email(s)")
    return {**result, "next_run_at": digest_mod.next_run_at()}


@api.get("/admin/consent")
async def admin_consent(request: Request, x_admin_token: str = Header(default="")):
    """Who agreed to what, and when — the proof an inspector asks for.

    Only signed-in customers can be listed: a guest's decision lives in a cookie on their own
    machine and is never sent to us unless they have an account to attach it to. Accounts that
    have never decided are listed too, with no categories, because "not asked yet" is itself an
    answer an inspector will want to see.
    """
    await _require_admin(request, x_admin_token)
    rows = [u async for u in db.users.find(
        {}, {"email": 1, "consent": 1, "consent_record": 1, "created_at": 1}
    ).sort("created_at", -1).limit(500)]

    out = []
    for u in rows:
        rec = u.get("consent_record") or {}
        cats = rec.get("cats") or {}
        out.append({
            "email": u.get("email") or "",
            "summary": u.get("consent") or "",
            "version": rec.get("v") or "",
            "categories": [k for k, v in cats.items() if v],
            "decided_at": rec.get("ts") or "",
            "recorded_at": rec.get("recorded_at"),
            "joined_at": u.get("created_at"),
            "has_record": bool(rec),
        })
    # Whoever decided most recently first; accounts that never decided sink to the bottom.
    out.sort(key=lambda r: (r["has_record"], str(r["recorded_at"] or r["decided_at"] or "")),
             reverse=True)
    return {"items": out, "with_record": sum(1 for r in out if r["has_record"]),
            "total": len(out)}


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
             "last_search": 1, "created_at": 1, "is_admin": 1}).sort("created_at", -1).limit(300)]

    out = []
    for u in rows:
        taste = u.get("taste") or {}
        samples = taste.get("samples") or []
        price, price_low, price_high = _centre(samples, 0)
        mileage, mileage_low, mileage_high = _centre(samples, 1)
        top = lambda m, n: [k for k, _ in sorted((m or {}).items(), key=lambda kv: -kv[1])[:n]]
        out.append({
            "email": u.get("email") or "", "name": u.get("name") or "",
            "is_admin": bool(u.get("is_admin")),
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
    who = _actor(await _require_admin(request, x_admin_token))
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
    await _audit(request, who, "merged" if target else "renamed", value,
                 f"-> {target}" if target else f'"{label}"')
    return {"saved": True, "id": oid, **doc}


@api.delete("/admin/taxonomy/overrides/{oid}")
async def admin_taxonomy_override_remove(oid: str, request: Request,
                                        x_admin_token: str = Header(default="")):
    who = _actor(await _require_admin(request, x_admin_token))
    res = await db.taxonomy_overrides.delete_one({"_id": oid})
    await curate.refresh(db, force=True)
    if res.deleted_count:
        await _audit(request, who, "merge/rename undone", oid)
    return {"removed": bool(res.deleted_count)}


@api.delete("/admin/enquiries/{enquiry_id}")
async def admin_enquiry_delete(enquiry_id: str, request: Request,
                               x_admin_token: str = Header(default="")):
    """Throw away an enquiry that has been dealt with.

    A `new` one is never deletable: that is a lead nobody has spoken to yet, and losing it to
    a stray click would cost real money. Mark it contacted or closed first.
    """
    who = _actor(await _require_admin(request, x_admin_token))
    doc = await db.enquiries.find_one({"_id": enquiry_id}, {"status": 1, "name": 1, "email": 1})
    if not doc:
        raise HTTPException(404, "no such enquiry")
    if (doc.get("status") or "new") == "new":
        raise HTTPException(400, "mark it contacted or closed before deleting it")
    await _audit(request, who, "enquiry deleted",
                 doc.get("email") or enquiry_id, doc.get("name") or "")
    await db.enquiries.delete_one({"_id": enquiry_id})
    return {"removed": True}


@api.delete("/admin/users/{email}")
async def admin_user_delete(email: str, request: Request,
                            x_admin_token: str = Header(default="")):
    """Erase a customer account and everything that signs them in.

    Deposits are NOT deleted — they are money that moved, and a refund has to stay traceable —
    so an account with a live, unrefunded deposit is refused. Purchase records keep the email
    for the paperwork; everything that could sign the person in goes.
    """
    who = _actor(await _require_admin(request, x_admin_token))
    email = (email or "").strip().lower()
    user = await db.users.find_one({"email": email}, {"_id": 1})
    if not user:
        raise HTTPException(404, "no such customer")
    # Money is still on the buyer's card while the deposit is authorised, captured or (older
    # flow) paid; a release or refund is what settles it.
    live = await db.deposits.count_documents(
        {"user_id": user["_id"], "payment_status": {"$in": list(deposits.HELD_STATES)}})
    if live:
        raise HTTPException(
            400, f"this customer has {live} deposit(s) that are not settled — release or "
                 "refund them first")
    uid = user["_id"]
    for coll in ("sessions", "webauthn_credentials", "challenges"):
        await db[coll].delete_many({"user_id": uid})
    await db.totp_setup.delete_one({"_id": uid})
    await db.users.delete_one({"_id": uid})
    await _audit(request, who, "customer deleted", email)
    return {"removed": True, "email": email}


class AdminFlagBody(BaseModel):
    is_admin: bool


@api.put("/admin/users/{email}/admin")
async def admin_user_set_admin(email: str, body: AdminFlagBody, request: Request,
                               x_admin_token: str = Header(default="")):
    """Grant or take away administrator rights.

    Two rails. Nobody changes their OWN flag - that is how an install ends up with no
    administrator through one stray click - and the LAST administrator cannot be demoted,
    which would lock the admin pages away from everybody.
    """
    admin = await _require_admin(request, x_admin_token)
    who = _actor(admin)
    email = (email or "").strip().lower()
    user = await db.users.find_one({"email_norm": email}, {"_id": 1, "email": 1, "is_admin": 1})
    if not user:
        raise HTTPException(404, "no such customer")
    if admin and admin.get("_id") == user["_id"]:
        raise HTTPException(400, "you cannot change your own rights — ask another administrator")
    if not body.is_admin:
        others = await db.users.count_documents(
            {"is_admin": True, "_id": {"$ne": user["_id"]}})
        if not others:
            raise HTTPException(400, "that is the last administrator")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"is_admin": body.is_admin}})
    await _audit(request, who,
                 "made an administrator" if body.is_admin else "administrator rights removed",
                 user.get("email") or email)
    return {"email": user.get("email") or email, "is_admin": body.is_admin}


@api.get("/admin/tracking-quota")
async def admin_tracking_quota(request: Request, refresh: bool = False,
                              x_admin_token: str = Header(default="")):
    """Provider plan usage. Cached, because asking is itself a billable request."""
    await _require_admin(request, x_admin_token)
    if not jsoncargo.configured():
        return {"configured": False,
                "hint": "JSONCARGO_API_KEY is empty in this deployment's backend.env"}
    try:
        data = await jsoncargo.stats(db, refresh)
    except RuntimeError as e:
        return {"configured": True, "error": str(e), "last_error": jsoncargo.last_error(),
                "shipping_line": jsoncargo.config()["line"]}
    return {"configured": True, **(data or {}),
            # The plan can be healthy while every lookup fails on a bad carrier, so the last
            # provider failure is reported next to the quota rather than only in the log.
            "last_error": jsoncargo.last_error(),
            "shipping_line": jsoncargo.config()["line"]}


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


@api.get("/csrf")
async def csrf_token(request: Request, response: Response):
    """Hand the caller the token their next unsafe request has to carry.

    Safe by definition (it changes nothing but the secret we will accept next), and never
    cached: a shared cache serving one visitor's token to another would defeat the point.
    """
    token, kind = await csrf_mod.issue(request, response)
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "scope": kind}


api.include_router(auth.router)
api.include_router(deposits.router)
contracts_mod.set_db(db)
contracts_mod.set_admin_guard(_require_admin)
api.include_router(contracts_mod.router)
api.include_router(notify.router)
cms.set_db(db)
cms.set_admin_guard(_require_admin)
cms.set_audit(_audit)
api.include_router(cms.router)
postqueue.set_db(db)
api.include_router(postqueue.router)
traffic.set_db(db)
api.include_router(traffic.router)
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


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """One gate for every unsafe request, rather than a dependency on ~150 routes.

    A route added tomorrow is protected without anybody remembering to protect it, which is
    the only version of this that stays true. Exemptions live in csrf.exempt.
    """
    try:
        await csrf_mod.guard(request)
    except HTTPException as e:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)



@app.on_event("startup")
async def on_startup():
    await sync_mod.ensure_indexes(db)
    await auth.ensure_indexes(db)
    await csrf_mod.ensure_indexes(db)
    await postqueue.ensure_indexes(db)
    await traffic.ensure_indexes(db)
    await geoip.ensure_indexes()
    # The de-duplication fingerprints are useful for a day and kept a little longer only so a
    # late-running digest can still be computed; after that they are noise.
    await db.car_view_seen.create_index("at", expireAfterSeconds=40 * 86400)
    # Preview-debug lines are evidence for a live investigation, not history.
    await db.share_hits.create_index("ts", expireAfterSeconds=7 * 86400)
    await auth.ensure_owner(db)
    # The owner's merges, renames and year spans travel in the repo, so a fresh server has
    # the same dropdowns without anybody copying a database.
    try:
        await seed_curation.ensure_curation(db)
    except Exception as e:
        log.warning("curation seed failed: %s", str(e)[:200])
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
    # The weekly saved-search digest keeps its own clock (Saturday afternoon in Sofia).
    asyncio.get_running_loop().create_task(digest_mod.scheduler(db))
    # A card hold lasts seven days; this hands back the ones nobody captured and re-lists
    # the car, even if Stripe's webhook never reached us.
    asyncio.get_running_loop().create_task(deposits.scheduler())
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
