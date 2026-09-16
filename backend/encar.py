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
import contextlib
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

# CloudFront in front of api.encar.com answers 403/407 to datacenter address space (Hetzner,
# AWS, the preview host) while a residential connection gets 200 for the same request. So
# there is more than one way out, and they are tried IN ORDER — cheapest first:
#
#   1. direct            — straight out of front1. Free and fastest when Encar allows it.
#   2. home_exit         — tinyproxy on the Mac mini over WireGuard (http://10.99.0.3:8888).
#                          A residential address that Encar does allow, and it costs nothing.
#   3. residential_proxy — IPRoyal. Metered and paid for, so it is the last resort.
#
# Each proxy tier has its OWN environment variable, because the old single `ENCAR_PROXY_URL`
# slot made the Mac and IPRoyal mutually exclusive: the template wrote one or the other and
# the chain could not exist. Both URLs are secrets — never logged, never in an exception; see
# `_scrub`. Format http://USER:PASS@host:port with the credentials URL-encoded.
TIER_ENV = {"home_exit": "ENCAR_HOME_EXIT_URL",
            "residential_proxy": "ENCAR_RESIDENTIAL_PROXY_URL"}
# Read as the residential tier when the new variable is absent, so a server that has not had
# the new backend.env yet keeps the exit it has instead of silently going direct into a 403.
PROXY_ENV = "ENCAR_PROXY_URL"
# The order, overridable without a code change: ENCAR_ROUTES=direct,home_exit
ROUTES_ENV = "ENCAR_ROUTES"
DEFAULT_CHAIN = ("direct", "home_exit", "residential_proxy")

# Bounded by design: a human or the sync is waiting, and Cloudflare cuts us off at 100s.
CONNECT_TIMEOUT = 8
# Keep-alive, and it matters more here than almost anywhere: api.encar.com is reached through
# a tunnel and a proxy, so a fresh connection is TCP + CONNECT + TLS — 150-180ms paid BEFORE
# the request is even sent. httpx's default keepalive_expiry is 5s, and the catalogue sweep
# now leaves ~17s between pages, so every single page was paying that toll. Ninety seconds
# comfortably covers the sweep's gap (and its 60s ceiling), and ten idle connections is plenty
# for one worker with six interactive slots.
KEEPALIVE = httpx.Limits(max_keepalive_connections=10, max_connections=20,
                         keepalive_expiry=90.0)
TOTAL_TIMEOUT = 15
ATTEMPTS = 2                # one retry, never for 404
RETRY_AFTER_MAX_WAIT = 5    # longer than this and the circuit opens for that long instead


# Which way Encar traffic leaves, decided at RUNTIME rather than by the presence of an env
# var. Every tier can fail on its own — Encar blocks the datacentre address, the Mac is
# asleep or its tunnel is down, IPRoyal runs out of traffic — and on 06/09 every request
# through the residential proxy timed out at exactly 15s while a direct call from back1
# answered in 0.4s. So the route is a SETTING: an admin can pin it, it walks the chain by
# itself, and the pin survives a restart because server.py loads it from the database.
#   "auto"              - walk the chain: the first tier that is not shut out right now
#   "direct"            - insist on leaving from the server, whatever happens
#   "home_exit"         - insist on the Mac mini
#   "residential_proxy" - insist on IPRoyal
_mode = {"route": "auto"}
ROUTE_MODES = ("auto",) + DEFAULT_CHAIN
# "proxy" is what the single-slot era called the one proxy there was. Stored settings and old
# bookmarks still say it, and a 400 from the admin panel is not the way to find that out.
MODE_ALIASES = {"proxy": "residential_proxy"}

# One circuit breaker PER TIER, so a tier Encar has blocked does not shut out the tier that
# works — that was the whole failing of the single breaker: one 403 from Hetzner and nothing
# went anywhere for three minutes, with a perfectly good Mac exit sitting next to it.
_breakers = {}

# When a tier trips and there is somewhere else to go, it is shut out for this long rather
# than for the few seconds the failure itself earns: traffic should settle on the tier that
# works instead of stepping back onto the blocked one every half minute. It is also how long
# until the preferred tiers are quietly probed again, so the chain climbs back to `direct` on
# its own once Encar stops blocking it — a background request, never on a visitor's page load.
AUTO_PROBE_GAP = 900
# The cheapest thing on api.encar.com that proves a route works: the standard options
# dictionary. No search parameters to get wrong, a small body, and it is already fetched
# (and cached) in normal operation.
PROBE_PATH = "/v1/readside/vehicles/car/options/standard"
_auto = {"since": 0.0, "probe_at": 0.0, "probing": False, "last_probe": None}

# How a route change is written down, so it survives a restart. server.py registers a
# coroutine that stores it in `site_settings.encar_routing`; without one, a change is
# in-process only (that is what the tests use).
_persist = {"fn": None}


def set_persist(fn):
    _persist["fn"] = fn


def _b(tier):
    """This tier's circuit breaker."""
    return _breakers.setdefault(tier, {"fails": 0, "open_until": 0.0, "reason": "",
                                       "trips": 0, "blocks": []})


def chain():
    """The tiers to try, in order, that this server actually has.

    A tier with no URL is not a tier: offering it would mean sending traffic nowhere.
    """
    raw = (os.environ.get(ROUTES_ENV) or "").strip()
    order = [t.strip() for t in raw.split(",") if t.strip()] if raw else list(DEFAULT_CHAIN)
    out = [t for t in order if t in DEFAULT_CHAIN and tier_configured(t)]
    # Direct needs nothing to be configured and must never be the tier that does not exist:
    # with every proxy missing it is the only way out there is.
    return tuple(out) if out else ("direct",)


def tier_url(tier):
    """The proxy URL for a tier, or None for `direct`."""
    if tier == "direct":
        return None
    env = TIER_ENV.get(tier)
    url = (os.environ.get(env, "").strip() if env else "")
    if not url and tier == "residential_proxy":
        url = os.environ.get(PROXY_ENV, "").strip()     # the single-slot variable, still read
    return url or None


def tier_configured(tier):
    return True if tier == "direct" else bool(tier_url(tier))


def tier_blocked(tier):
    return time.monotonic() < _b(tier)["open_until"]


def all_blocked():
    """Is EVERY route in the chain shut out right now?

    The difference between "the sync is wedged" and "Encar is not answering anyone". A
    catalogue sweep restarted into a closed door just stops again in the same place, which
    is what made the sync look like it kept getting stuck at the end.
    """
    ch = chain()
    return bool(ch) and all(tier_blocked(t) for t in ch)


def blocked_reason():
    ch = chain()
    for t in ch:
        if tier_blocked(t):
            b = _b(t)
            return (f"{b['reason'] or 'upstream unavailable'} "
                    f"(още {b['open_until'] - time.monotonic():.0f}s)")
    return ""


def blocked_for():
    """Seconds until the SOONEST route opens again; 0 when one is open right now.

    Worth waiting out rather than failing on, for the handful of calls that decide whether a
    whole sweep happens at all.
    """
    ch = chain()
    if not ch or not all_blocked():
        return 0.0
    return max(min(_b(t)["open_until"] for t in ch) - time.monotonic(), 0.0)


def set_route(mode):
    """Choose the route. Returns the mode actually in force."""
    mode = MODE_ALIASES.get(mode, mode)
    if mode in ROUTE_MODES:
        _mode["route"] = mode
        # Choosing by hand is also how an admin says "try them all again, now".
        reset_breakers()
    return _mode["route"]


def reset_breakers():
    _breakers.clear()
    _auto["since"] = 0.0
    _auto["probe_at"] = 0.0


def route_mode():
    return _mode["route"]


def route():
    """Which tier traffic leaves through RIGHT NOW.

    In `auto` this is the chain walk itself: the first tier that is not currently shut out.
    No separate failover machinery, no crutch to pick up and put down — a tier that fails
    opens its own breaker and the next request simply leaves by the next door.
    """
    ch = chain()
    mode = _mode["route"]
    if mode != "auto":
        return mode if mode in ch else ch[0]
    for tier in ch:
        if not tier_blocked(tier):
            return tier
    # Everything is shut out. Name the tier that opens SOONEST, so traffic resumes at the
    # first possible second — and so the logs do not claim we are back on `direct` while its
    # fifteen-minute cooldown still has fourteen minutes to run.
    return min(ch, key=lambda t: _b(t)["open_until"])


def proxy_url():
    """The proxy for the tier in force — what httpx is actually handed."""
    return tier_url(route())


def proxy_configured():
    """Is there a proxy tier to fall through to, whatever the current mode is?"""
    return any(tier_configured(t) for t in TIER_ENV)


def other_route(mode=None):
    """The next tier the chain would use after the one in force."""
    ch = chain()
    current = route() if (mode is None or mode == "auto") else MODE_ALIASES.get(mode, mode)
    if current in ch:
        rest = ch[ch.index(current) + 1:]
        return rest[0] if rest else None
    return ch[0] if ch else None


def auto_on_proxy():
    """Is traffic anywhere other than the first choice? (The admin screen says so out loud.)"""
    ch = chain()
    return _mode["route"] == "auto" and len(ch) > 1 and route() != ch[0]


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
    """Strip EVERY tier's proxy URL (and any user:pass@ in a URL) out of a message before it
    is logged or raised. httpx repeats the proxy URL in some transport errors.

    All configured tiers, not just the active one: credentials must be scrubbed whether or
    not traffic happens to be going through them at this second, and with a chain there is
    more than one secret in play.
    """
    text = str(text)
    for tier in TIER_ENV:
        p = tier_url(tier)
        if not p:
            continue
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
# An ISOLATED block is not a closed door. Measured on the live server on 14/09: 14 blocks in
# 5,130 calls (0.3%), each clearing by itself within seconds — and each one buying a full
# three minutes during which every uncached car fell back to catalogue data. So a single
# block costs a short pause, and only a RUN of them earns the long one. No retry is added
# here and no address is rotated: the door is still not knocked on while it is shut.
BLOCK_COOLDOWN_FIRST = 25
BLOCK_REPEAT_WINDOW = 300
BLOCK_REPEAT_N = 3


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
        # A test-injected transport. When set it wins over the pool below: discarding it
        # silently turned unit tests into live network calls.
        self._client = None
        # ONE long-lived client per tier, kept warm for the life of the process. Every new
        # connection costs TCP + CONNECT + TLS, and through the Mac's tunnel that is
        # 150-180ms on top of every single request — the difference between ~580ms and
        # ~350ms per call. So clients are never closed between requests, and falling through
        # to another tier does not throw away the pool of the tier it came from: when traffic
        # climbs back, the connections are still there.
        self._clients = {}
        # `last_ok_at` / `last_error_at` exist so /api/health can tell the truth: during the
        # 14/09 outage it answered ok:true with 35,842 consecutive failures behind it.
        self.stats = {"requests": 0, "backoffs": 0, "errors": 0, "last_status": None,
                      "last_ok_at": None, "last_error_at": None}
        self._opt_cache = {"standard": None, "tuning": None, "metas": None, "at": 0}
        # An optional callable that returns the gap to leave before the NEXT non-interactive
        # request, replacing `min_interval` while a paced sweep is running (see
        # sync.paced_sweep). A callable rather than a number because a bisecting crawl does
        # not know how many requests it will make until it has made them: the gap has to be
        # recomputed against the remaining budget, or an estimate that is out by 2x turns a
        # two-hour sweep into a four-hour one.
        self.pacer = None
        # Called when upstream refuses us, so a sweep in progress can slow itself down
        # instead of walking into the next block (three in five minutes and every route's
        # cooldown goes from twenty-five seconds to three minutes).
        self.on_block = None
        self._route = None
        # The last automatic move between tiers, for the admin screen and the watchdog.
        self._failover = None

    async def client(self):
        # A transport injected by a test is not ours to replace.
        if self._client is not None:
            return self._client
        tier = route()
        c = self._clients.get(tier)
        if c is None or c.is_closed:
            c = httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, proxy=tier_url(tier),
                limits=KEEPALIVE,
                timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT))
            self._clients[tier] = c
            log.info("encar client ready route=%s", tier)
        self._route = tier
        return c

    async def switch_route(self, mode):
        """Move traffic to another route, immediately.

        Two things have to happen together or the switch is a no-op: the setting changes and
        the circuit breakers are cleared — otherwise the new route sits out the cooldown
        earned by the old one and looks just as broken. The clients are NOT thrown away:
        there is one per tier, so the next request already picks the right one, and the pool
        of the tier we are leaving stays warm for when traffic comes back to it.
        """
        set_route(mode)
        self.reset_breaker()
        log.warning("encar route switched mode=%s route=%s", route_mode(), route())
        return route()

    def reset_breaker(self):
        reset_breakers()

    async def close(self):
        """Shut the pools down. For process shutdown and for the deploy-time check — NOT
        something to do between requests, which is what made every call pay for a new TLS
        handshake through the tunnel."""
        if self._client:
            await self._client.aclose()
            self._client = None
        for c in list(self._clients.values()):
            with contextlib.suppress(Exception):
                await c.aclose()
        self._clients.clear()
        self._route = None

    async def _throttle(self):
        async with self._lock:
            wanted = self.pacer() if self.pacer else self.min_interval
            gap = time.monotonic() - self._last
            if gap < wanted:
                await asyncio.sleep(wanted - gap)
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
        # Somewhere other than the first choice? Then this is also the moment to wonder, at
        # most once every quarter of an hour, whether the tier we would rather be on is back.
        # It happens in the background — this request is not made to wait for the answer.
        self._maybe_probe_preferred()
        tier = route()
        b = _b(tier)
        if now < b["open_until"]:
            # Every tier in the chain is shut out (otherwise `route()` would have returned
            # one that is not): fail immediately rather than queue behind a door we know is
            # shut.
            raise EncarUnavailable(
                f"upstream circuit open for another {b['open_until'] - now:.0f}s "
                f"on every route ({b['reason']})")

        c = await self.client()
        cap = 2.0 if interactive else RETRY_AFTER_MAX_WAIT
        delay = 1.0
        last = "no attempt made"
        last_status = None
        # Two separate budgets. `tries` is the retry allowance on the CURRENT tier (transport
        # errors and rate limits). `doors` is how many tiers of the chain have been tried:
        # a block is not retried on the same tier — it is retried on the NEXT one.
        tries = 0
        doors = 0
        while True:
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
                self.stats["last_error_at"] = time.time()
                last = f"transport error: {_why(e)}"
                log.warning("encar route=%s status=- latency_ms=%d circuit=%s path=%s %s",
                            route(), (time.monotonic() - t0) * 1000, self._state(), path,
                            last)
                tries += 1
                if tries >= ATTEMPTS:
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
            if r.status_code not in (200, 404):
                self.stats["last_error_at"] = time.time()
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
                # Blocked on THIS tier. Its circuit opens straight away — briefly for a
                # one-off, properly for a run of them — and then the SAME request goes out
                # the next door instead of failing.
                #
                # Falling through here is the whole point of having a chain. Without it the
                # chain only ever helped the request AFTER the blocked one, and the catalogue
                # sync — whose very first upstream call is a single count probe — died on the
                # spot every time Hetzner's address was refused, which then earned the long
                # cooldown on every retry. "As soon as we start the sync we get the rate
                # limit" was this branch.
                self._trip(f"HTTP {r.status_code} from upstream",
                           self._block_cooldown(tier), tier=tier, stick=True)
                if self.on_block:
                    with contextlib.suppress(Exception):
                        self.on_block()
                last = f"HTTP {r.status_code} on {tier}"
                nxt = route()
                if doors < len(chain()) - 1 and nxt != tier and not tier_blocked(nxt):
                    doors += 1
                    tries = 0
                    tier = nxt
                    c = await self.client()          # one client per tier
                    log.warning("encar %s — same request going out via route=%s",
                                last, tier)
                    continue
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
                    raise EncarUnavailable(f"rate limited, retry after {asked}s", 429)
                if asked is not None:
                    wait = asked
                tries += 1
                if tries >= ATTEMPTS:
                    break
                await asyncio.sleep(wait)
                delay *= 2
                continue
            # Unexpected status: no retry (we do not know what it means), no None either.
            self._fail(f"HTTP {r.status_code}")
            raise EncarUnavailable(f"unexpected HTTP {r.status_code} from upstream",
                                   r.status_code)

        # No HTTP status at all means nothing came back down this tier: its breaker opens and
        # the chain moves on by itself — the next request leaves by the next door.
        self._fail(last, transport=last_status is None)
        raise EncarUnavailable(f"upstream did not answer for {path}: {last}", last_status)

    def _state(self, tier=None):
        return "open" if tier_blocked(tier or route()) else "closed"

    def _ok(self, tier=None):
        b = _b(tier or route())
        b["fails"] = 0
        self.stats["last_ok_at"] = time.time()

    def _fail(self, reason, transport=False):
        tier = route()
        b = _b(tier)
        b["fails"] += 1
        reason = _scrub(reason)
        if b["fails"] >= BREAKER_FAILS:
            # A tier that does not answer at all is dead, not busy: leave it alone until the
            # probe says otherwise. On 06/09 every request through the residential proxy
            # timed out at exactly 15s while a direct call answered in 0.4s.
            self._trip(reason, BREAKER_COOLDOWN, tier=tier, stick=transport)

    def _block_cooldown(self, tier):
        """How long an upstream block shuts THIS tier: short for one, long for a run."""
        now = time.monotonic()
        b = _b(tier)
        b["blocks"] = [t for t in b["blocks"] if now - t < BLOCK_REPEAT_WINDOW]
        b["blocks"].append(now)
        if len(b["blocks"]) >= BLOCK_REPEAT_N:
            return BLOCK_COOLDOWN
        return BLOCK_COOLDOWN_FIRST

    def _trip(self, reason, cooldown, tier=None, stick=False):
        """Shut one tier out. The chain does the rest: the next request leaves by the next
        door, and nobody has to be woken up to move it.

        `stick` is for a tier that is REFUSING or DEAD — a block or a transport fault. With
        somewhere to fall through to, it is shut out for the full AUTO_PROBE_GAP instead of
        the few seconds the failure earns, because otherwise traffic steps back onto the
        blocked route every half minute, takes another 403, and spends the whole day
        flapping — which is exactly what one shared breaker did on 14/09. A rate limit is
        NOT sticky: Encar named a number of seconds and that number is honoured.
        """
        tier = tier or route()
        b = _b(tier)
        was = route()
        if stick and other_route(tier) and route_mode() == "auto":
            cooldown = max(cooldown, AUTO_PROBE_GAP)
        b["fails"] = 0
        b["trips"] += 1
        b["open_until"] = time.monotonic() + cooldown
        b["reason"] = _scrub(reason)
        self.stats["last_error_at"] = time.time()
        log.error("encar circuit=open for %ss tier=%s: %s", cooldown, tier, b["reason"])
        now_on = route()
        if now_on != was:
            # Not a "failover" any more, just the chain moving on — but the admin screen and
            # the watchdog have always reported it, and it is still worth saying out loud.
            self._failover = {"at": time.time(), "from": was, "to": now_on,
                              "mode": route_mode(), "reason": b["reason"], "auto": True}
            _auto["since"] = time.time()
            _auto["probe_at"] = time.monotonic() + AUTO_PROBE_GAP
            log.error("encar route moved on %s -> %s after: %s", was, now_on, b["reason"])

    async def _probe_tier(self, tier):
        """Is a tier we stepped off working again? Asked in the background.

        A visitor never pays for this: their request keeps going through the tier that works
        while one cheap call goes out through the tier being tested, and only a clean answer
        clears its breaker and hands traffic back. The alternative — trying the preferred
        tier on a real page load — costs the connect timeout every quarter of an hour, on
        somebody's phone.
        """
        ok, why = False, ""
        try:
            async with httpx.AsyncClient(
                    headers=HEADERS, follow_redirects=True, proxy=tier_url(tier),
                    timeout=httpx.Timeout(10, connect=5)) as c:
                r = await c.get(f"{API}{PROBE_PATH}")
            ok = r.status_code == 200
            why = f"HTTP {r.status_code}"
        except Exception as e:                                  # noqa: BLE001
            why = _why(e)
        _auto["last_probe"] = {"at": time.time(), "ok": ok, "tier": tier, "detail": why[:160]}
        if not ok:
            log.info("encar %s is still down, staying on %s: %s", tier, route(), why[:160])
            return False
        was = route()
        _b(tier).update({"open_until": 0.0, "fails": 0, "reason": "", "blocks": []})
        log.warning("encar %s answers again (%s) — moving back from %s", tier, why, was)
        fn = _persist["fn"]
        if fn:
            try:
                await fn(route_mode(), f"{tier} отговаря отново")
            except Exception as e:                              # noqa: BLE001
                log.warning("could not store the new encar route: %s", _scrub(e)[:160])
        return True

    async def _probe_preferred(self):
        """Try the tiers we would rather be on, best first, until one answers."""
        _auto["probing"] = True
        try:
            for tier in chain():
                if tier == route():
                    break                                       # nothing better is shut out
                if await self._probe_tier(tier):
                    return True
            return False
        finally:
            _auto["probing"] = False
            _auto["probe_at"] = time.monotonic() + AUTO_PROBE_GAP

    def _maybe_probe_preferred(self):
        """Start the fifteen-minute probe if one is due. Never blocks the caller."""
        if not auto_on_proxy() or _auto["probing"]:
            return
        if not _auto["probe_at"] or time.monotonic() < _auto["probe_at"]:
            return
        _auto["probe_at"] = time.monotonic() + AUTO_PROBE_GAP   # do not stack probes
        asyncio.create_task(self._probe_preferred())

    def status(self):
        """Everything the admin screen and the watchdog need — and no credentials."""
        left = _auto["probe_at"] - time.monotonic() if auto_on_proxy() else 0
        ch = chain()
        return {"mode": route_mode(), "route": route(), "alternate": other_route(),
                "proxy_configured": proxy_configured(), "modes": list(ROUTE_MODES),
                "breaker": self.breaker(), "trips": _b(route())["trips"],
                "last_failover": self._failover, "stats": dict(self.stats),
                # The chain, in order, with each tier's own state — the admin screen shows
                # all three, so "the Mac is answering while Hetzner is blocked" is readable
                # at a glance instead of being guessed from one shared breaker.
                "chain": list(ch),
                "tiers": [{"tier": t, "configured": tier_configured(t),
                           "in_chain": t in ch, "active": t == route(),
                           "breaker": self.breaker(t)} for t in DEFAULT_CHAIN],
                # Traffic is somewhere other than the first choice: since when, and when the
                # preferred tiers are asked again.
                "auto_on_proxy": auto_on_proxy(),
                "auto_since": _auto["since"] or None,
                "probe_in_s": max(0, round(left)) if auto_on_proxy() else None,
                "last_probe": _auto["last_probe"]}

    def breaker(self, tier=None):
        """For the admin screen and the watchdog: is this tier currently shut out?"""
        b = _b(tier or route())
        left = b["open_until"] - time.monotonic()
        return {"open": left > 0, "retry_in_s": max(0, round(left)),
                "reason": b["reason"] if left > 0 else "",
                "consecutive_failures": b["fails"]}

    # ── catalogue ────────────────────────────────────────────────────────────
    async def search(self, offset=0, limit=500, q=BASE_Q, sort="ModifiedDate",
                     interactive=False):
        """One page of the catalogue feed. `interactive=True` for the handful of calls a
        VISITOR waits on: those must not queue behind the sweep pacer, which hands out gaps
        of up to a minute and holds the single-file lock while it sleeps."""
        sr = quote(f"|{sort}|{offset}|{limit}")
        return await self.get_json(
            f"/search/car/list/general?count=true&q={quote(q)}&sr={sr}",
            interactive=interactive)

    async def count(self, q=BASE_Q, interactive=False):
        """Number of upstream matches, or None if the request itself failed.

        The old shape returned 0 on failure, which is indistinguishable from a legitimate
        empty scope — and that ambiguity is exactly what let a bad crawl silently retire
        the whole catalogue. `None` lets callers refuse to act instead of guessing.
        """
        d = await self.search(0, 1, q, interactive=interactive)
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

    THE RESIZE ONLY HAPPENS IF A CROP HEIGHT COMES WITH IT. `impolicy=widthRate&rw=N`
    on its own is silently IGNORED: the CDN hands back the untouched source, which for
    every listing measured is 2200x1238 - 1.2 MB on the wire and about 11 MB of bitmap
    once decoded. A column of those is what was freezing iPhones, and it looked like a
    640px request the whole time. Adding `ch` well ABOVE the scaled height makes the
    resize stick while leaving the aspect alone: the CDN scales to `rw` and ignores the
    box (`rw=640&ch=2560` returns 640x360, 24 KB). A `ch` at or below the scaled height
    is ignored again, hence the deliberately generous multiplier - four times the width
    survives anything short of a source taller than it is wide by 4:1.

    `impolicy=Resize` returns 503; this is the closest thing to a plain resize the CDN
    offers.
    """
    if not path:
        return None
    if path.startswith("http"):
        return path
    base = path if path.startswith("/carpicture/") else f"/carpicture{path}"
    return (f"{CDN}{base}?impolicy=widthRate&rw={max_side}&ch={max_side * 4}"
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


async def verify(listing_id=None):
    """Deploy-time proof that Encar answers through AT LEAST ONE tier of the chain.

    It walks the chain in order and stops at the first tier that answers, because that is
    the question a deploy needs settled: can this release reach Encar at all? Insisting on
    `direct` blocked every release on the days CloudFront was refusing Hetzner, while the
    Mac exit sat there answering perfectly.

    It asks the CATALOGUE how many cars it holds, because that question has no expiry date.
    It used to fetch one hardcoded car, which made every deploy depend on that car still
    being for sale: the day it sold, the check would have printed "test vehicle is gone",
    exited 1, and the playbook's `assert rc == 0` would have blocked a perfectly good
    release for a reason that has nothing to do with the release.

    An optional listing id is still accepted for hand debugging, and an authoritative 404
    there counts as SUCCESS — a 404 is Encar answering us, which is the whole question. A
    blocked or missing route does not 404; it 407s, 403s or times out.
    """
    client = EncarClient(min_interval=0)
    tiers = chain()
    failures = []
    try:
        for tier in tiers:
            set_route(tier)                 # pin, so one tier is proven at a time
            t0 = time.monotonic()
            try:
                total = await client.count()
                if total is None:
                    failures.append(f"{tier}: the catalogue count did not come back")
                    continue
                extra = ""
                if listing_id:
                    body = await client.get_json(f"/v1/readside/vehicle/{listing_id}",
                                                 allow_404=True, interactive=True)
                    extra = (f" vehicle={listing_id} status=404 (sold or withdrawn — the "
                             f"route is still proven)" if body is None
                             else f" vehicle={listing_id} status=200")
                skipped = (f" (skipped: {', '.join(failures)})" if failures else "")
                print(f"OK route={tier} status=200 "
                      f"latency_ms={int((time.monotonic() - t0) * 1000)} "
                      f"catalogue={total}{extra}{skipped}")
                return 0
            except EncarUnavailable as e:
                failures.append(f"{tier}: status={e.status or '-'} {_scrub(e)}")
            # No explicit close between tiers: `client()` rebuilds itself when the tier
            # changes, and closing here would throw away a transport a test injected.
    finally:
        await client.close()
        set_route("auto")
    print(f"FAIL no route answered — {'; '.join(failures) or 'nothing configured'}")
    return 1


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        logging.basicConfig(level=logging.WARNING)
        arg = [a for a in sys.argv[1:] if a.isdigit()]
        sys.exit(asyncio.run(verify(*arg)))
    print("usage: python -m encar --verify [listing_id]")
    sys.exit(2)
