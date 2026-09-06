"""Encar API client.

Politeness policy (deliberate — see /app/memory/encar_api.md section 8):
  * ONE shared worker slot, minimum interval between upstream requests
  * backoff on 429/5xx, Retry-After honoured
  * NO IP rotation, NO residential proxy pool, NO rate-limit circumvention — ENCAR_PROXY_URL
    is ONE sticky residential address, chosen because CloudFront 407s datacenter ranges

Everything here is read-only public JSON. Images are never proxied through us;
the browser loads them straight from Encar's CDN.
"""

import asyncio
import logging
import os
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import httpx

log = logging.getLogger("encar")

API = "https://api.encar.com"
CDN = "https://ci.encar.com"

# CloudFront in front of api.encar.com answers 407 to datacenter address space (Hetzner, AWS,
# the preview host) while a residential connection gets 200 for the same request. When set,
# every api.encar.com call — and nothing else — goes through this ONE sticky HTTP proxy.
# Format: http://USER:PASS@host:port (URL-encode the credentials). It is a secret: it is
# never logged and never appears in an exception; see `_scrub`.
PROXY_ENV = "ENCAR_PROXY_URL"

# Bounded by design: a human or the sync is waiting, and Cloudflare cuts us off at 100s.
CONNECT_TIMEOUT = 8
TOTAL_TIMEOUT = 15
ATTEMPTS = 2                # one retry, never for 404
RETRY_AFTER_MAX_WAIT = 5    # longer than this and the circuit opens for that long instead


# Which way Encar traffic leaves, decided at RUNTIME rather than by the presence of an env
# var. The residential proxy is the normal route (Encar's CloudFront blocks datacentre IPs),
# but a proxy can fail on its own — traffic exhausted, credentials rotated, the vendor down —
# and on 06/09 every request through it timed out at exactly 15s while a direct call from
# back1 answered in 0.4s. So the route is a SETTING: an admin can flip it, the watchdog flips
# it automatically before it wakes anybody up, and it survives a restart because server.py
# loads it from the database on startup.
#   "auto"   - use the proxy when one is configured (the previous behaviour)
#   "proxy"  - insist on the proxy
#   "direct" - ignore the proxy entirely
_mode = {"route": "auto"}
ROUTE_MODES = ("auto", "proxy", "direct")

# How a route change is written down, so it survives a restart. server.py registers a
# coroutine that stores it in `site_settings.encar_routing`; without one, a change is
# in-process only (that is what the tests use).
_persist = {"fn": None}

# An automatic switch is allowed at most this often. Without a floor, a genuinely dead
# upstream would make traffic flap between proxy and direct on every fourth failure.
FAILOVER_MIN_GAP = 600


def set_persist(fn):
    _persist["fn"] = fn


def set_route(mode):
    """Choose the route. Returns the mode actually in force."""
    if mode in ROUTE_MODES:
        _mode["route"] = mode
    return _mode["route"]


def route_mode():
    return _mode["route"]


def proxy_url():
    if _mode["route"] == "direct":
        return None
    return os.environ.get(PROXY_ENV, "").strip() or None


def proxy_configured():
    """Is there a proxy to switch TO, whatever the current mode is?"""
    return bool(os.environ.get(PROXY_ENV, "").strip())


def route():
    """Where Encar traffic leaves from — the only thing about the proxy that is ever logged."""
    return "residential_proxy" if proxy_url() else "direct"


def other_route(mode=None):
    """The route to try when the current one has stopped working."""
    current = mode or _mode["route"]
    if current == "direct":
        return "proxy" if proxy_configured() else None
    if not proxy_configured():
        # "auto" with no proxy configured is already a direct route: there is nowhere else
        # to go, and offering "direct" would be a failover to the route that just failed.
        return None
    return "direct"


def _why(e):
    """A transport failure described in words that survive the log.

    `str()` on most httpx transport exceptions is EMPTY — `ProxyError()`, `ConnectError()`,
    `ReadTimeout()` all carry no message — so incidents read "transport error: " and told
    nobody anything (that is exactly what the 06/09 02:33 upstream alarm said). The class
    name is always there, and which route the request took is the first thing worth knowing
    when the residential proxy is the suspect.
    """
    msg = _scrub(e).strip()
    name = type(e).__name__
    detail = f"{name}: {msg}" if msg and msg != name else name
    return f"{detail} (route={route()})"


def _scrub(text):
    """Strip the proxy URL (and any user:pass@ in a URL) out of a message before it is logged
    or raised. httpx repeats the proxy URL in some transport errors."""
    text = str(text)
    p = proxy_url()
    if p:
        text = text.replace(p, "<proxy>")
        host = urlsplit(p).hostname
        if host:
            text = text.replace(host, "<proxy>")
    return re.sub(r"//[^/\s@]+:[^/\s@]+@", "//<redacted>@", text)


def _retry_after(r):
    """Seconds Encar asked us to wait, from a delta or an HTTP-date; None when absent."""
    v = r.headers.get("retry-after")
    if not v:
        return None
    v = v.strip()
    if v.isdigit():
        return int(v)
    try:
        return max(0, int(parsedate_to_datetime(v).timestamp() - time.time()))
    except (TypeError, ValueError, OverflowError):
        return None

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


RATE_LIMIT_STATUSES = (429, 500, 502, 503, 504, 408, 425)
# "You are blocked", not "try again": CloudFront in front of api.encar.com answers 407 when
# it does not like where the request came from, and 403 when a WAF rule fires. Retrying
# either one is a storm against a door that is already shut.
BLOCK_STATUSES = (403, 407, 511)

BREAKER_FAILS = 4          # consecutive upstream failures before the circuit opens
BREAKER_COOLDOWN = 60      # seconds it stays open for a rate limit or a 5xx
BLOCK_COOLDOWN = 180       # ... and for an outright block, which needs longer to clear


class EncarUnavailable(RuntimeError):
    """Upstream could not answer — transport error, WAF block, rate limit, 5xx, junk body.

    Emphatically NOT "this car does not exist". That distinction is the whole point of this
    class. Before it existed, `get_json` returned None for every unexpected status, and
    `car_detail` read a falsy detail as Encar retiring the ad: one CloudFront 407 while a
    buyer clicked an uncached car marked a perfectly live listing sold, pulled it from the
    catalogue and stamped `sold_at`. Only a 404 (or a 200 that really says "no such car")
    may ever be treated as authoritative absence.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class EncarClient:
    def __init__(self, min_interval=1.2, interactive_concurrency=6):
        self.min_interval = min_interval
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
        # Circuit breaker. A blocked or broken upstream must be asked politely and rarely,
        # not hammered by every visitor who happens to open an uncached car.
        self._fails = 0
        self._open_until = 0.0
        self._open_reason = ""
        self._trips = 0
        self._route = None
        # Auto-failover bookkeeping: an opened circuit asks for the other route to be
        # tried BEFORE anybody's phone rings.
        self._pending_failover = False
        self._last_failover = 0.0
        self._failover = None

    async def client(self):
        # Rebuild when the route changes. The client is cached for the process lifetime, so
        # without this check flipping the setting would do nothing until a restart — which
        # is exactly the trap the old env-var-only switch was.
        if self._client is not None and self._route != route():
            await self.close()
        if self._client is None:
            self._route = route()
            self._client = httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, proxy=proxy_url(),
                timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT))
            log.info("encar client ready route=%s", self._route)
        return self._client

    async def switch_route(self, mode):
        """Move traffic to another route, immediately.

        Three things have to happen together or the switch is a no-op: the setting changes,
        the cached client is thrown away (it holds the old proxy), and the circuit breaker is
        cleared — otherwise the new route sits out the remaining cooldown earned by the old
        one and looks just as broken.
        """
        set_route(mode)
        await self.close()
        self.reset_breaker()
        log.warning("encar route switched mode=%s route=%s", route_mode(), route())
        return route()

    def reset_breaker(self):
        self._fails = 0
        self._open_until = 0.0
        self._open_reason = ""

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
        """One paced GET. Returns the parsed body, or None ONLY for an authoritative 404.

        Anything else that is not a clean 200 raises `EncarUnavailable`. Callers must be
        able to tell "Encar says this car is gone" from "Encar did not answer", because one
        of those retires a listing and the other must never touch the database.

        Bounded: 8s to connect, 15s in total, two attempts at most (429/5xx/transport only —
        a 404 is final and a block is not retried at all). A 429 with Retry-After is
        honoured: a short wait is waited out, a long one opens the circuit for that long.
        Logs carry route, status, latency and circuit state — never the proxy.
        """
        now = time.monotonic()
        if now < self._open_until:
            # Circuit open: fail immediately rather than queue behind a door we know is shut.
            raise EncarUnavailable(
                f"upstream circuit open for another {self._open_until - now:.0f}s "
                f"({self._open_reason})")

        c = await self.client()
        cap = 2.0 if interactive else RETRY_AFTER_MAX_WAIT
        delay = 1.0
        last = "no attempt made"
        last_status = None
        for attempt in range(ATTEMPTS):
            # interactive = one human opening one car: bounded concurrency, no forced
            # gap. Bulk sync keeps the strict single-file pacing.
            if interactive:
                await self._sem.acquire()
            else:
                await self._throttle()
            t0 = time.monotonic()
            try:
                r = await c.get(f"{API}{path}")
            except Exception as e:
                self.stats["errors"] += 1
                last = f"transport error: {_why(e)}"
                log.warning("encar route=%s status=- latency_ms=%d circuit=%s path=%s %s",
                            route(), (time.monotonic() - t0) * 1000, self._state(), path,
                            last)
                if attempt == ATTEMPTS - 1:
                    break
                await asyncio.sleep(min(delay, cap))
                delay *= 2
                continue
            finally:
                if interactive:
                    self._sem.release()

            latency_ms = int((time.monotonic() - t0) * 1000)
            self.stats["requests"] += 1
            self.stats["last_status"] = last_status = r.status_code
            log.info("encar route=%s status=%s latency_ms=%d circuit=%s path=%s",
                     route(), r.status_code, latency_ms, self._state(), path)

            if r.status_code == 200:
                if not r.text.strip():
                    # A 200 with nothing in it says nothing. Treating it as "car gone" is
                    # how live cars used to get retired.
                    last = "empty 200 body"
                    break
                try:
                    body = r.json()
                except Exception:
                    last = "200 with a body that is not JSON (WAF interstitial?)"
                    break
                self._ok()
                return body
            if r.status_code == 404:
                # The only authoritative "there is no such car". Never retried.
                self._ok()
                return None
            if r.status_code in BLOCK_STATUSES:
                # Blocked. One attempt, no retries, and the circuit opens straight away.
                self._trip(f"HTTP {r.status_code} from upstream", BLOCK_COOLDOWN)
                await self._failover_if_pending()
                raise EncarUnavailable(f"upstream refused the request "
                                       f"(HTTP {r.status_code})", r.status_code)
            if r.status_code in RATE_LIMIT_STATUSES:
                self.stats["backoffs"] += 1
                last = f"HTTP {r.status_code}"
                wait = min(delay, cap)
                asked = _retry_after(r) if r.status_code == 429 else None
                if asked is not None and asked > RETRY_AFTER_MAX_WAIT:
                    # Encar named a wait we cannot make a caller sit through: honour it by
                    # keeping everyone away for exactly that long.
                    self._trip(f"HTTP 429, Retry-After {asked}s", min(asked, 600))
                    await self._failover_if_pending()
                    raise EncarUnavailable(f"rate limited, retry after {asked}s", 429)
                if asked is not None:
                    wait = asked
                if attempt == ATTEMPTS - 1:
                    break
                await asyncio.sleep(wait)
                delay *= 2
                continue
            # Unexpected status: no retry (we do not know what it means), no None either.
            self._fail(f"HTTP {r.status_code}")
            await self._failover_if_pending()
            raise EncarUnavailable(f"unexpected HTTP {r.status_code} from upstream",
                                   r.status_code)

        self._fail(last)
        await self._failover_if_pending()
        raise EncarUnavailable(f"upstream did not answer for {path}: {last}", last_status)

    def _state(self):
        return "open" if time.monotonic() < self._open_until else "closed"

    def _ok(self):
        self._fails = 0

    def _fail(self, reason):
        self._fails += 1
        reason = _scrub(reason)
        if self._fails >= BREAKER_FAILS:
            self._trip(reason, BREAKER_COOLDOWN)

    def _trip(self, reason, cooldown):
        self._fails = 0
        self._trips += 1
        self._open_until = time.monotonic() + cooldown
        self._open_reason = _scrub(reason)
        # The circuit is open because THIS route stopped working. If there is another way
        # out, ask for it to be tried; `_failover_if_pending` decides (it needs to await).
        self._pending_failover = bool(other_route())
        log.error("encar circuit=open for %ss route=%s: %s", cooldown, route(),
                  self._open_reason)

    async def _failover_if_pending(self):
        """Try the other way out before anybody's phone rings.

        On 06/09 every request through the residential proxy timed out at exactly 15s while
        a direct call from back1 answered in 0.4s — a working site was taken down by one
        broken hop with a perfectly good alternative sitting next to it. So an opened
        circuit now moves traffic to the other route and clears the cooldown: one request
        proves whether the outage was the route or Encar itself. The move is recorded and
        surfaced as a WARNING by the watchdog, not an emergency, because pages still serve.
        """
        if not self._pending_failover:
            return None
        self._pending_failover = False
        alt = other_route()
        now = time.monotonic()
        if not alt or (self._last_failover and now - self._last_failover < FAILOVER_MIN_GAP):
            return None
        self._last_failover = now
        was, reason = route(), self._open_reason
        await self.switch_route(alt)
        self._failover = {"at": time.time(), "from": was, "to": route(),
                          "mode": route_mode(), "reason": reason, "auto": True}
        log.error("encar auto-failover %s -> %s after: %s", was, route(), reason)
        fn = _persist["fn"]
        if fn:
            try:
                await fn(route_mode(), reason)
            except Exception as e:                              # noqa: BLE001
                log.warning("could not store the new encar route: %s", _scrub(e)[:160])
        return self._failover

    def status(self):
        """Everything the admin screen and the watchdog need — and no credentials."""
        return {"mode": route_mode(), "route": route(), "alternate": other_route(),
                "proxy_configured": proxy_configured(), "modes": list(ROUTE_MODES),
                "breaker": self.breaker(), "trips": self._trips,
                "last_failover": self._failover, "stats": dict(self.stats)}

    def breaker(self):
        """For the admin screen and the watchdog: is upstream currently shut out?"""
        left = self._open_until - time.monotonic()
        return {"open": left > 0, "retry_in_s": max(0, round(left)),
                "reason": self._open_reason if left > 0 else "",
                "consecutive_failures": self._fails}

    # ── catalogue ────────────────────────────────────────────────────────────
    async def search(self, offset=0, limit=500, q=BASE_Q, sort="ModifiedDate"):
        sr = quote(f"|{sort}|{offset}|{limit}")
        return await self.get_json(
            f"/search/car/list/general?count=true&q={quote(q)}&sr={sr}")

    async def count(self, q=BASE_Q):
        """Number of upstream matches, or None if the request itself failed.

        The old shape returned 0 on failure, which is indistinguishable from a legitimate
        empty scope — and that ambiguity is exactly what let a bad crawl silently retire
        the whole catalogue. `None` lets callers refuse to act instead of guessing.
        """
        d = await self.search(0, 1, q)
        if d is None:
            return None
        return d.get("Count", 0)

    # ── per-vehicle ──────────────────────────────────────────────────────────
    async def detail(self, listing_id):
        return await self.get_json(f"/v1/readside/vehicle/{listing_id}", interactive=True)

    async def choice_options(self, vehicle_id):
        return await self.get_json(
            f"/v1/readside/vehicles/car/{vehicle_id}/options/choice",
            interactive=True) or []

    async def record(self, vehicle_id, vehicle_no=""):
        if vehicle_no:
            try:
                d = await self.get_json(
                    f"/v1/readside/record/vehicle/{vehicle_id}/open?vehicleNo={quote(vehicle_no)}",
                    interactive=True)
            except EncarUnavailable:
                # The open endpoint is the richer of the two but also the flakier. Losing it
                # must not cost us the summary, which is often perfectly available.
                d = None
            if d:
                return d
        return await self.get_json(f"/v1/readside/record/vehicle/{vehicle_id}/summary", interactive=True)

    async def inspection(self, vehicle_id):
        return await self.get_json(f"/v1/readside/inspection/vehicle/{vehicle_id}", interactive=True)

    async def diagnosis(self, vehicle_id):
        return await self.get_json(f"/v1/readside/diagnosis/vehicle/{vehicle_id}", interactive=True)

    # ── option dictionaries (global, cached in-process for a day) ────────────
    async def option_dicts(self):
        """Human names for option codes. Decoration — never a reason to fail a page.

        These dictionaries are global and change about never. When upstream is unreachable
        the last copy we hold, stale or empty, is worth infinitely more than an exception: a
        fully cached car page used to return 500 right here the moment the circuit breaker
        opened, which is a working page destroyed by a missing glossary.
        """
        if self._opt_cache["standard"] and time.time() - self._opt_cache["at"] < 86400:
            return self._opt_cache
        try:
            std = await self.get_json("/v1/readside/vehicles/car/options/standard",
                                      interactive=True) or {}
            tun = await self.get_json("/v1/readside/vehicles/car/options/tuning",
                                      interactive=True) or []
        except EncarUnavailable as e:
            log.warning("option dictionaries unavailable (%s); keeping what we have",
                        str(e)[:120])
            return self._opt_cache
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
    # Two things Encar's CDN does that a naive URL gets wrong:
    #   1. The picture lives under /carpicture/carpictureNN/... - the outer /carpicture/
    #      folder is where the site's own detail page fetches from (see fem.encar.com
    #      output). Skipping it still returns bytes, but the CDN then treats the request
    #      as "unknown source" and slaps a full-frame 엔카 watermark across the photo.
    #   2. `impolicy=widthRate` PLUS `cw={w}&ch={h}` scales the source to width `rw`
    #      and centre-crops to a `w x h` landscape rectangle - so a portrait ad photo
    #      no longer arrives as a tall picture that our aspect-video card then crops
    #      down to a low-res sliver. The CDN honours the exact requested resolution
    #      instead of clamping to whatever the source's native aspect can produce
    #      (which is what `heightRate` did: a portrait source gave 379x506 for a
    #      requested 900x506, so retina cards blurred). Use `full_image_url` for
    #      the gallery/lightbox where the crop is a bug, not a feature.
    #   3. Passing `wtmk=` explicitly asks for w_mark_04.png - a small transparent brand
    #      plate in the corner. Without it, the CDN falls back to the giant default mark
    #      that ruins every chat preview.
    base = path if path.startswith("/carpicture/") else f"/carpicture{path}"
    return (f"{CDN}{base}?impolicy=widthRate&rw={w}&cw={w}&ch={h}&cg=Center"
            f"&wtmk={CDN}/wt_mark/w_mark_04.png")


def full_image_url(path, max_side=1600):
    """Uncropped variant for the gallery + lightbox.

    Using the same `widthRate + cw/ch` crop as `image_url` was hacking the top and
    bottom off portrait source photos at the CDN before they ever reached the
    browser - `object-contain` in the lightbox then had nothing to work with.

    This variant sends `impolicy=widthRate&rw=<N>` WITHOUT `cw`/`ch`, which is what
    the CDN uses to scale-only (no crop): the source's native aspect is preserved,
    so a portrait photo comes back portrait and the lightbox picks its own contain.
    Empirically `impolicy=Resize` returns 503; `widthRate` without a crop rectangle
    is the closest thing to a plain resize the CDN offers.
    """
    if not path:
        return None
    if path.startswith("http"):
        return path
    base = path if path.startswith("/carpicture/") else f"/carpicture{path}"
    return (f"{CDN}{base}?impolicy=widthRate&rw={max_side}"
            f"&wtmk={CDN}/wt_mark/w_mark_04.png")


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

    manufacturer = row.get("Manufacturer") or ""
    model = row.get("Model") or ""
    badge = row.get("Badge") or ""

    doc = {
        "_id": str(row.get("Id")),
        "vehicle_key": vehicle_key(photos, row.get("Id")),
        "manufacturer": manufacturer,
        "model": model,
        "badge": badge,
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


async def verify(listing_id="42207598"):
    """Deploy-time proof that Encar answers through the configured route: HTTP 200 and a JSON
    body. Prints only sanitized fields; exit 1 on anything else."""
    t0 = time.monotonic()
    client = EncarClient(min_interval=0)
    try:
        body = await client.get_json(f"/v1/readside/vehicle/{listing_id}", interactive=True)
    except EncarUnavailable as e:
        print(f"FAIL route={route()} status={e.status or '-'} "
              f"latency_ms={int((time.monotonic() - t0) * 1000)} reason={_scrub(e)}")
        return 1
    finally:
        await client.close()
    if body is None:
        print(f"FAIL route={route()} status=404 (test vehicle {listing_id} is gone — pick "
              f"another id)")
        return 1
    if not isinstance(body, dict):
        print(f"FAIL route={route()} status=200 body is not a JSON object")
        return 1
    print(f"OK route={route()} status=200 latency_ms={int((time.monotonic() - t0) * 1000)} "
          f"vehicle_id={body.get('vehicleId', '?')}")
    return 0


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        logging.basicConfig(level=logging.WARNING)
        arg = [a for a in sys.argv[1:] if a.isdigit()]
        sys.exit(asyncio.run(verify(*arg)))
    print("usage: python -m encar --verify [listing_id]")
    sys.exit(2)
