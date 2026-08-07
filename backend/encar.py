"""Encar API client.

Politeness policy (deliberate — see /app/memory/encar_api.md section 8):
  * ONE shared worker slot, minimum interval between upstream requests
  * exponential backoff on 429/5xx
  * NO IP rotation, NO residential proxy pool, NO rate-limit circumvention

Everything here is read-only public JSON. Images are never proxied through us;
the browser loads them straight from Encar's CDN.
"""

import asyncio
import logging
import re
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("encar")

API = "https://api.encar.com"
CDN = "https://ci.encar.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "http://www.encar.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# SellType.일반. = regular sale only. Lease (리스) and rental (렌트) cars belong to a
# finance company and cannot be exported, so they are filtered out UPSTREAM - we never
# fetch them, and every count we compare against is already the exportable subset.
BASE_Q = "(And.Hidden.N._.CarType.A._.SellType.\uc77c\ubc18.)"


def flatten_options(options):
    """Encar nests option variants under `subOptions` (code 075 'LED headlamp' lives
    inside group 001 'Headlamp'). Cars reference LEAF codes, so without a recursive
    flatten ~25% of a car's options never resolve."""
    flat = {}

    def walk(lst):
        for o in lst or []:
            walk(o.get("subOptions"))
            code = o.get("optionCd")
            if not code:
                continue
            if o.get("group"):
                flat.setdefault(code, o)
            else:
                flat[code] = o

    walk(options)
    return flat


class EncarClient:
    def __init__(self, min_interval=1.2, max_retries=5, interactive_concurrency=6):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._lock = asyncio.Lock()
        self._last = 0.0
        # Interactive (a human opened one car) must NOT wait behind the bulk-sync
        # pacing. A handful of parallel reads for a single page view is not abusive;
        # the rate-limit risk lives in the 436-request catalogue sweep, which keeps
        # its strict single-file pacing below.
        self._sem = asyncio.Semaphore(interactive_concurrency)
        self._client = None
        self.stats = {"requests": 0, "backoffs": 0, "errors": 0, "last_status": None}
        self._opt_cache = {"standard": None, "tuning": None, "metas": None, "at": 0}

    async def client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(headers=HEADERS, timeout=30,
                                             follow_redirects=True)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _throttle(self):
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self._last = time.monotonic()

    async def get_json(self, path, allow_404=False, interactive=False):
        """Single politely-paced GET with exponential backoff. Returns None on 404."""
        c = await self.client()
        delay = 1.0
        for attempt in range(self.max_retries):
            # interactive = one human opening one car: bounded concurrency, no forced
            # gap. Bulk sync keeps the strict single-file pacing.
            if interactive:
                await self._sem.acquire()
            else:
                await self._throttle()
            try:
                r = await c.get(f"{API}{path}")
            except Exception as e:
                self.stats["errors"] += 1
                log.warning("encar transport error %s: %s", path, e)
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
                continue
            finally:
                if interactive:
                    self._sem.release()

            self.stats["requests"] += 1
            self.stats["last_status"] = r.status_code

            if r.status_code == 200:
                if not r.text.strip():
                    return None
                try:
                    return r.json()
                except Exception:
                    return None
            if r.status_code == 404:
                if allow_404:
                    return None
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                self.stats["backoffs"] += 1
                log.warning("encar %s on %s — backing off %.0fs", r.status_code, path, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            log.warning("encar unexpected %s on %s", r.status_code, path)
            return None
        return None

    # ── catalogue ────────────────────────────────────────────────────────────
    async def search(self, offset=0, limit=500, q=BASE_Q, sort="ModifiedDate"):
        sr = quote(f"|{sort}|{offset}|{limit}")
        return await self.get_json(
            f"/search/car/list/general?count=true&q={quote(q)}&sr={sr}")

    async def count(self, q=BASE_Q):
        d = await self.search(0, 1, q)
        return (d or {}).get("Count", 0)

    # ── per-vehicle ──────────────────────────────────────────────────────────
    async def detail(self, listing_id):
        return await self.get_json(f"/v1/readside/vehicle/{listing_id}", interactive=True)

    async def choice_options(self, vehicle_id):
        return await self.get_json(
            f"/v1/readside/vehicles/car/{vehicle_id}/options/choice",
            interactive=True) or []

    async def record(self, vehicle_id, vehicle_no=""):
        if vehicle_no:
            d = await self.get_json(
                f"/v1/readside/record/vehicle/{vehicle_id}/open?vehicleNo={quote(vehicle_no)}",
                interactive=True)
            if d:
                return d
        return await self.get_json(f"/v1/readside/record/vehicle/{vehicle_id}/summary", interactive=True)

    async def inspection(self, vehicle_id):
        return await self.get_json(f"/v1/readside/inspection/vehicle/{vehicle_id}", interactive=True)

    async def diagnosis(self, vehicle_id):
        return await self.get_json(f"/v1/readside/diagnosis/vehicle/{vehicle_id}", interactive=True)

    # ── option dictionaries (global, cached in-process for a day) ────────────
    async def option_dicts(self):
        if self._opt_cache["standard"] and time.time() - self._opt_cache["at"] < 86400:
            return self._opt_cache
        std = await self.get_json("/v1/readside/vehicles/car/options/standard", interactive=True) or {}
        tun = await self.get_json("/v1/readside/vehicles/car/options/tuning", interactive=True) or []
        self._opt_cache = {
            "standard": flatten_options(std.get("options", [])),
            "tuning": {o["optionCd"]: o for o in tun},
            "metas": {m["key"]: m["value"] for m in std.get("metas", []) if m.get("key")},
            "at": time.time(),
        }
        return self._opt_cache


encar = EncarClient()


# ── listing normalisation ────────────────────────────────────────────────────
DIAGNOSIS_MARKS = {"EncarDiagnosisP1", "EncarDiagnosisP2", "EncarDiagnosis"}


def photo_paths(row, limit=6):
    out = []
    for p in (row.get("Photos") or [])[:limit]:
        loc = p.get("location")
        if loc:
            out.append(loc)
    if not out and row.get("Photo"):
        out.append(f"{row['Photo']}001.jpg")
    return out


def under_contract(detail):
    """Encar has a pending sale on this ad: `advertisement.salesStatus == "CONTRACT"`.

    The same fact the search feed carries as `SalesStatus`, but read from the per-car detail,
    which is the only live source once a car is already in our index.
    """
    return sales_status(detail).upper() == "CONTRACT"


def sales_status(detail):
    return ((detail or {}).get("advertisement") or {}).get("salesStatus") or ""


def detail_photo_paths(detail):
    """The gallery of one ad, in the ad's own order and without repeats.

    Encar returns the deck shuffled, and within a single `code` it repeats a picture as a
    THUMBNAIL row pointing at the SAME path — which is why an 18-photo ad looked like 24.
    Ascending code restores the real order and the THUMBNAIL copy sorts last, so the dedupe
    keeps the original.
    """
    rows = sorted(
        (detail.get("photos") or []),
        key=lambda x: (int(str(x.get("code") or "999").strip() or 999),
                       (x.get("type") or "") == "THUMBNAIL"),
    )
    out, seen = [], set()
    for p in rows:
        path = p.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def image_url(path, w=640, h=480):
    if not path:
        return None
    if path.startswith("http"):
        return path
    return (f"{CDN}{path}?impolicy=widthRate&rw={w}&cw={w}&ch={h}&cg=Center")


def vehicle_key(photos, fallback_id):
    """Encar carries MANY duplicate ads for the same physical car - dealers re-register
    listings under fresh IDs (see `reRegistered` / `ServiceCopyCar: DUPLICATION`).
    Around 30% of rows are duplicates, which would show the same car repeatedly.

    The photo path embeds the UNDERLYING vehicleId
    (/carpicture04/pic4234/42347130_001.jpg -> 42347130), which is exactly the
    Id-vs-vehicleId mismatch found during the POC. That makes a reliable dedupe key.
    """
    for p in photos or []:
        m = re.search(r"/(\d{6,})_\d+\.jpg", p)
        if m:
            return m.group(1)
    return str(fallback_id)


def normalise_row(row, recency=None):
    """Search-result row -> our listing document (no pricing yet)."""
    cond = set(row.get("Condition") or [])
    marks = set(row.get("ServiceMark") or [])
    year_month = int(row.get("Year") or 0)
    price_manwon = float(row.get("Price") or 0)
    photos = photo_paths(row)

    doc = {
        "_id": str(row.get("Id")),
        "vehicle_key": vehicle_key(photos, row.get("Id")),
        "manufacturer": row.get("Manufacturer") or "",
        "model": row.get("Model") or "",
        "badge": row.get("Badge") or "",
        "badge_detail": row.get("BadgeDetail") or "",
        # Encar marks cars with a pending sale as SalesStatus=CONTRACT
        "sales_status": row.get("SalesStatus") or "",
        "under_contract": (row.get("SalesStatus") or "").upper() == "CONTRACT",
        "fuel_type": row.get("FuelType") or "",
        "ev_type": row.get("EvType") or "",
        "year_month": year_month,
        "form_year": int(row.get("FormYear") or (year_month // 100 if year_month else 0)),
        "mileage": int(row.get("Mileage") or 0),
        "price_manwon": price_manwon,
        "price_krw": price_manwon * 10_000,   # Encar quotes in 만원
        "region": row.get("OfficeCityState") or "",
        "sell_type": row.get("SellType") or "",
        "photos": photos,
        "photo_count": len(row.get("Photos") or []),
        "has_inspection": "Inspection" in cond,
        "has_record": "Record" in cond,
        "has_resume": "Resume" in cond,
        "diagnosed": bool(marks & DIAGNOSIS_MARKS),
        "trust": list(row.get("Trust") or []),
        "service_mark": list(marks),
        "active": True,
    }
    if recency is not None:
        doc["recency"] = recency
    return doc
