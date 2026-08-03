"""Read Maersk's PUBLIC track & trace with a real browser.

We have no API contract with Maersk, and their edge (Akamai) answers a plain HTTP client
with 403 Access Denied. A real Chromium session, however, loads
`https://www.maersk.com/tracking/<ref>` normally, and the page itself calls
`https://api.maersk.com/synergy/tracking/<ref>?operator=MAEU` — no key, no quota. So the
browser is used as the session: it solves the edge challenge, and the JSON its own page
fetched is captured on the way past.

Every read is expensive (a browser page, several seconds), so callers must go through the
cache in tracking.py, and a global rate cap keeps a busy day from turning into a fleet of
Chromiums.

The response shape is not documented anywhere and Maersk can change it, so nothing here
counts positions or trusts a field name: events are recognised BY SHAPE — a dict that
carries a date and a description — exactly like the EDI parser does with segments.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

log = logging.getLogger("maersk.public")

PAGE_URL = "https://www.maersk.com/tracking/{ref}"
DATA_URL = "https://api.maersk.com/synergy/tracking/{ref}?operator=MAEU"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

NAV_TIMEOUT = 60_000
SETTLE_MS = 1_500
WAIT_MS = 25_000
MAX_PER_MIN = int(os.environ.get("MAERSK_PUBLIC_MAX_PER_MIN", "10"))

_pw = None
_browser = None
_lock = asyncio.Lock()          # one page at a time: a browser is not a connection pool
_calls = []                     # timestamps of recent reads, for the rate cap

# Maersk writes its milestones as English prose. Mapped onto the same code vocabulary the
# EDI feed uses so the UI keeps ONE label map. Order matters: first match wins.
PHRASES = [
    ("empty to shipper", "EE"), ("empty returned", "RD"), ("empty return", "RD"),
    ("gate in", "AG"), ("gate-in", "AG"), ("received at", "AG"), ("arrival in", "AG"),
    ("stuff", "STUF"), ("load", "AR"), ("discharg", "UV"), ("unload", "UV"),
    ("depart", "VD"), ("sail", "VD"), ("arriv", "VA"),
    ("gate out", "AE"), ("gate-out", "AE"), ("released for delivery", "AE"),
    ("customs", "CU"), ("deliver", "D"), ("available", "AV"),
    ("rail depart", "VD"), ("rail arriv", "VA"),
]

DATE_KEYS = ("date", "time", "when", "timestamp", "eventdate", "actual", "estimated")
TEXT_KEYS = ("event", "activity", "status", "description", "milestone", "name", "type")
ESTIMATED_WORDS = ("estimat", "expect", "planned", "forecast", "scheduled")


def enabled():
    return os.environ.get("MAERSK_PUBLIC_TRACK", "1") not in ("0", "false", "no")


def _rate_ok():
    now = time.time()
    _calls[:] = [t for t in _calls if now - t < 60]
    if len(_calls) >= MAX_PER_MIN:
        return False
    _calls.append(now)
    return True


async def _get_browser():
    global _pw, _browser
    if _browser and _browser.is_connected():
        return _browser
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(args=[
        "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled"])
    return _browser


async def close():
    global _pw, _browser
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw:
        try:
            await _pw.stop()
        except Exception:
            pass
        _pw = None


async def read(ref):
    """Load the public page for one reference and return its raw payload.

    Returns {"json": <payload or None>, "empty": bool} — `empty` means Maersk itself said
    it has nothing public for this reference, which is an answer, not a failure.
    """
    if not enabled():
        return None
    if not _rate_ok():
        log.warning("public track rate cap hit, skipping %s", ref)
        return None

    async with _lock:
        browser = await _get_browser()
        ctx = await browser.new_context(user_agent=UA, locale="en-US",
                                       viewport={"width": 1440, "height": 900})
        try:
            page = await ctx.new_page()
            grabbed = []

            def on_response(resp):
                if "/synergy/tracking" in resp.url and resp.status == 200:
                    grabbed.append(asyncio.ensure_future(_body(resp)))

            page.on("response", on_response)
            await page.goto(PAGE_URL.format(ref=ref), wait_until="domcontentloaded",
                            timeout=NAV_TIMEOUT)

            # Either the page's own call lands, or the page says it found nothing.
            deadline = time.time() + WAIT_MS / 1000
            body = ""
            while time.time() < deadline:
                await page.wait_for_timeout(SETTLE_MS)
                if grabbed:
                    break
                body = (await page.inner_text("body")).lower()
                if "no results found" in body or "couldn't find" in body:
                    return {"json": None, "empty": True}

            payload = None
            for fut in grabbed:
                payload = await fut or payload

            if payload is None:
                # The page's own request can be reset by the edge mid-flight. Repeat it from
                # inside the page, where the session cookies already are.
                payload = await page.evaluate(
                    """async (u) => {
                        try {
                            const r = await fetch(u, {headers: {Accept: 'application/json'}});
                            return r.ok ? await r.json() : null;
                        } catch (e) { return null; }
                    }""", DATA_URL.format(ref=ref))

            if payload is None:
                body = (await page.inner_text("body")).lower()
                if "no results found" in body or "couldn't find" in body:
                    return {"json": None, "empty": True}
                log.warning("public track %s: page loaded but no payload", ref)
                return None
            return {"json": payload, "empty": False}
        finally:
            await ctx.close()


async def _body(resp):
    try:
        return await resp.json()
    except Exception:
        return None


def _code(text):
    low = (text or "").lower()
    for phrase, code in PHRASES:
        if phrase in low:
            return code
    return ""


def _when(value):
    """Carrier timestamps come as '2026-06-14 07:30', ISO, or epoch millis."""
    if isinstance(value, (int, float)) and value > 1e11:
        return datetime.fromtimestamp(value / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:00")
    s = str(value or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", s)
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    return f"{y}-{mo}-{d}T{hh or '00'}:{mm or '00'}:00"


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _pick(d, *needles):
    """First string value whose KEY contains one of the needles."""
    for k, v in d.items():
        kl = k.lower()
        if any(n in kl for n in needles):
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                for kk in ("name", "city", "locationName", "displayName", "value"):
                    if isinstance(v.get(kk), str) and v[kk].strip():
                        return v[kk].strip()
    return ""


def _deep(d, *needles, depth=3):
    """Same as _pick, but looks inside nested dicts too (country lives under location)."""
    got = _pick(d, *needles)
    if got or depth <= 0:
        return got
    for v in d.values():
        if isinstance(v, dict):
            got = _deep(v, *needles, depth=depth - 1)
            if got:
                return got
    return ""


def _unloc(d):
    for k, v in d.items():
        if isinstance(v, str) and re.fullmatch(r"[A-Z]{5}", v.strip()) and (
                "code" in k.lower() or "unloc" in k.lower()):
            return v.strip()
        if isinstance(v, dict):
            got = _unloc(v)
            if got:
                return got
    return ""


def _vessel(d):
    name, imo, voyage = "", "", ""
    for k, v in d.items():
        kl = k.lower()
        if "vessel" in kl or "vehicle" in kl:
            if isinstance(v, str) and v.strip() and not v.strip().isdigit():
                name = name or v.strip()
            elif isinstance(v, dict):
                name = name or _pick(v, "name")
                imo = imo or _pick(v, "imo")
        if "imo" in kl and isinstance(v, (str, int)) and re.fullmatch(r"\d{7}", str(v)):
            imo = imo or str(v)
        if "voyage" in kl and isinstance(v, (str, int)) and str(v).strip():
            voyage = voyage or str(v).strip()
    return name, imo, voyage


def _event(d, now_iso):
    """A dict is an event when it carries both a timestamp and a description."""
    when = ""
    estimated = False
    for k, v in d.items():
        kl = k.lower()
        if not any(n in kl for n in DATE_KEYS) or isinstance(v, (dict, list)):
            continue
        got = _when(v)
        if got:
            when = when or got
            if any(w in kl for w in ESTIMATED_WORDS):
                estimated = True

    text = ""
    for key in TEXT_KEYS:
        for k, v in d.items():
            if key == k.lower() and isinstance(v, str) and v.strip():
                text = v.strip()
                break
        if text:
            break
    if not text:
        text = _pick(d, *TEXT_KEYS)
    if not when or not text or len(text) > 90:
        return None

    for k, v in d.items():
        if isinstance(v, bool) and any(w in k.lower() for w in ESTIMATED_WORDS) and v:
            estimated = True
        if isinstance(v, bool) and "actual" in k.lower() and v:
            estimated = False
    if when > now_iso:
        estimated = True

    name, imo, voyage = _vessel(d)
    return {
        "code": _code(text), "text": text, "when": when, "estimated": estimated,
        "location": _pick(d, "location", "city", "port", "terminal", "place"),
        "country": _deep(d, "country"), "unloc": _unloc(d),
        "mode": _pick(d, "mode", "transport"),
        "vessel_name": name, "vessel_imo": imo, "voyage": voyage,
    }


def to_events(payload):
    """Canonical milestones, sorted, deduped — the same shape the EDI feed produces."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00")
    out, seen = [], set()
    for node in _walk(payload):
        ev = _event(node, now_iso)
        if not ev:
            continue
        key = (ev["text"].lower(), ev["when"], ev["location"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return sorted(out, key=lambda e: e["when"])
