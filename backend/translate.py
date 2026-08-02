"""KO -> EN/BG/RO translation with a permanent MongoDB cache.

Design (per the user's "AI translation with caching of every word"):
  * every unique source string is translated exactly ONCE, ever
  * cache key = sha256(lang \x00 source) so it is stable and collision-free
  * requests are BATCHED — one LLM call translates up to CHUNK strings
  * on malformed JSON we retry, then fall back to the Korean source rather than
    showing the user an empty field
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time

log = logging.getLogger("translate")

LANGS = {"en": "English", "bg": "Bulgarian", "ro": "Romanian"}
CHUNK = 60
# Seconds to wait between batched LLM calls. Sized for a free-tier RPM allowance;
# set TRANSLATE_CHUNK_PACE=0 on a paid key to run flat out.
CHUNK_PACE = float(os.environ.get("TRANSLATE_CHUNK_PACE", "6"))
MODEL = ("gemini", "gemini-3-flash-preview")

# ── LLM circuit breaker ──────────────────────────────────────────────────────
# Errors that cannot possibly be fixed by retrying (no credit, bad key, no quota at all).
# NOTE: a bare HTTP 429 is NOT here. Gemini's free tier answers "You exceeded your
# current quota" for ordinary per-minute rate limiting, which recovers on its own, so
# treating that as fatal would abandon a whole warm-up run after one hiccup.
FATAL_MARKERS = ("budget has been exceeded", "insufficient_quota",
                 "insufficient balance", "api key not valid", "api_key_invalid",
                 "invalid api key", "unauthorized", "permission_denied",
                 "limit: 0")
RATE_LIMIT_PREFIX = "RATE_LIMIT"
FATAL_COOLDOWN = 900        # 15 min before we probe the provider again
SOFT_COOLDOWN = 60          # transient failures
MAX_ATTEMPTS = 6            # generous, because free-tier RPM limits are common
# Only the offline warm-up script may block waiting for a rate-limit window to pass.
# Inside a web request we always fail fast and fall back to cached/Korean text.
PATIENT = os.environ.get("TRANSLATE_PATIENT") == "1"
_BREAKER = {"open_until": 0.0, "reason": None, "trips": 0}


def _breaker_open():
    return time.time() < _BREAKER["open_until"]


def _breaker_trip(reason, cooldown):
    _BREAKER["open_until"] = time.time() + cooldown
    _BREAKER["reason"] = reason[:200]
    _BREAKER["trips"] += 1
    log.error("translation circuit breaker OPEN for %ss: %s", cooldown, reason[:200])


def _breaker_reset():
    if _BREAKER["open_until"] or _BREAKER["reason"]:
        log.info("translation circuit breaker closed")
    _BREAKER["open_until"] = 0.0
    _BREAKER["reason"] = None


def breaker_status():
    """Surfaced on /api/health so an exhausted LLM budget is visible, not silent."""
    return {
        "open": _breaker_open(),
        "reason": _BREAKER["reason"],
        "trips": _BREAKER["trips"],
        "retry_in_s": max(0, round(_BREAKER["open_until"] - time.time())),
    }

SYSTEM = (
    "You are a professional automotive translator localising South Korean used-car "
    "listing data from Encar for European car buyers. Translate Korean -> {lang}.\n"
    "RULES:\n"
    "- Use correct automotive industry terminology, never literal word-for-word.\n"
    "- Manufacturer, model and trim names keep their standard Latin-script marketing "
    "form (Kia, Grandeur, Exclusive). Never transliterate letter by letter.\n"
    "- Keep numbers, units, cc, km, dates and model codes exactly as given.\n"
    "- Colours: use the normal trade colour name.\n"
    "- Korean region names use the conventional romanisation or local exonym.\n"
    "- Be concise: most of these are UI labels and spec values, not prose.\n"
    "- Return ONLY a JSON object mapping each input id to its translation. No prose, "
    "no markdown fences."
)


def cache_key(text, lang):
    return hashlib.sha256(f"{lang}\x00{text}".encode()).hexdigest()


def _extract_json(s):
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    return json.loads(s)


def _user_prompt(chunk, lang):
    payload = {str(i): t for i, t in enumerate(chunk)}
    return (f"Translate each value to {LANGS[lang]}. Reply with ONLY a JSON "
            f"object using the same keys.\n\n"
            + json.dumps(payload, ensure_ascii=False))


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


async def _gemini_call(chunk, lang):
    """Direct Google Gemini REST call using the project's own API key."""
    import httpx

    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM.format(lang=LANGS[lang])}]},
        "contents": [{"role": "user", "parts": [{"text": _user_prompt(chunk, lang)}]}],
        # responseMimeType makes the model emit strict JSON, so no fence-stripping games
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(GEMINI_URL.format(m=model), params={"key": key}, json=body)
    if r.status_code == 429:
        # Free-tier RPM limiting. Google returns a RetryInfo hint we should respect.
        wait = 25.0
        try:
            for d in (r.json().get("error", {}).get("details") or []):
                delay = str(d.get("retryDelay") or "")
                if delay.endswith("s"):
                    wait = max(wait, float(delay[:-1]) + 2)
        except Exception:
            pass
        raise RuntimeError(f"{RATE_LIMIT_PREFIX}:{wait:.0f}: gemini 429 {r.text[:200]}")
    if r.status_code != 200:
        raise RuntimeError(f"gemini {r.status_code}: {r.text[:300]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"gemini returned no candidates: {str(data)[:300]}")
    # 2.5 models interleave 'thought' parts; keep only the real text parts.
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p["text"] for p in parts if isinstance(p.get("text"), str))


async def _emergent_call(chunk, lang):
    """Fallback: Emergent universal key via the emergentintegrations wrapper."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"trans-{lang}-{int(time.time()*1000)}",
        system_message=SYSTEM.format(lang=LANGS[lang]),
    ).with_model(*MODEL)
    return await chat.send_message(UserMessage(text=_user_prompt(chunk, lang)))


async def _llm_translate(chunk, lang):
    """Translate a list of strings in one call. Returns {source: translation}.

    Prefers the project's own Gemini API key when present, because the shared
    Emergent universal key is subject to a small shared budget.
    """
    if os.environ.get("GEMINI_API_KEY"):
        call, provider = _gemini_call, "gemini"
    elif os.environ.get("EMERGENT_LLM_KEY"):
        call, provider = _emergent_call, "emergent"
    else:
        log.error("no translation API key configured (GEMINI_API_KEY/EMERGENT_LLM_KEY)")
        return {}

    # Circuit breaker: make/model/spec translation is SYNCHRONOUS on a cache miss, so a
    # dead provider (exhausted budget, bad key) must never turn into 3 retries with
    # backoff on every single request. While the breaker is open we fail instantly and
    # the caller falls back to the Korean source.
    if _breaker_open():
        return {}

    for attempt in range(MAX_ATTEMPTS):
        try:
            got = _extract_json(await call(chunk, lang))
            _breaker_reset()
            return {chunk[int(i)]: v.strip()
                    for i, v in got.items()
                    if str(i).isdigit() and int(i) < len(chunk)
                    and isinstance(v, str) and v.strip()}
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            # Rate limiting is expected on free tiers: wait out the window and retry
            # rather than abandoning the run.
            if msg.startswith(RATE_LIMIT_PREFIX):
                # A user-facing request must NEVER sit and wait out a rate-limit window.
                # Trip the breaker so this and following requests fall back to cached
                # text (or Korean) instantly; the background warm-up is the only caller
                # allowed to be patient.
                if not PATIENT:
                    _breaker_trip(f"rate limited: {msg[:120]}", SOFT_COOLDOWN)
                    return {}
                try:
                    wait = float(msg.split(":")[1])
                except Exception:
                    wait = 25.0
                log.warning("translate rate-limited (%s/%s), waiting %.0fs (attempt %s/%s)",
                            provider, lang, wait, attempt + 1, MAX_ATTEMPTS)
                await asyncio.sleep(wait)
                continue
            log.warning("translate attempt %s failed (%s/%s): %s",
                        attempt + 1, provider, lang, msg[:200])
            # Retrying a budget/credential failure cannot succeed - trip immediately.
            if any(m in low for m in FATAL_MARKERS):
                _breaker_trip(msg, FATAL_COOLDOWN)
                return {}
            await asyncio.sleep(1.2 * (attempt + 1))
    _breaker_trip(f"{MAX_ATTEMPTS} consecutive failures", SOFT_COOLDOWN)
    return {}


async def translate_many(db, texts, lang):
    """Cache-around-LLM batch translate. Returns {source: translated}.

    Unknown/unsupported lang, or Korean itself, is a pass-through.
    """
    if lang not in LANGS:
        return {t: t for t in texts}

    uniq = []
    seen = set()
    for t in texts:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return {}

    out = {}
    keys = {cache_key(t, lang): t for t in uniq}
    async for doc in db.translations.find({"_id": {"$in": list(keys)}}):
        out[keys[doc["_id"]]] = doc["target"]

    todo = [t for t in uniq if t not in out]
    if not todo:
        return out

    from pymongo import UpdateOne
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i + CHUNK]
        # Proactive pacing between chunks. Free Gemini tiers allow only a handful of
        # requests per minute, so spacing the calls out is far cheaper than discovering
        # the limit through 429s and backoff.
        if i and CHUNK_PACE:
            await asyncio.sleep(CHUNK_PACE)
        got = await _llm_translate(chunk, lang)
        if not got and _breaker_open():
            # provider is down/out of credit - stop hammering it, keep what we have
            log.warning("translate: provider unavailable, stopping after %s/%s",
                        i, len(todo))
            for src in todo[i:]:
                out.setdefault(src, src)
            break
        docs = []
        for src in chunk:
            tr = got.get(src)
            if tr:
                out[src] = tr
                docs.append({"_id": cache_key(src, lang), "source": src,
                             "lang": lang, "target": tr})
            else:
                out[src] = src  # graceful: show Korean rather than a blank
        if docs:
            await db.translations.bulk_write(
                [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in docs],
                ordered=False)
    return out


async def translate_one(db, text, lang):
    if not text:
        return text
    res = await translate_many(db, [text], lang)
    return res.get(text.strip(), text)


async def translate_cached_only(db, texts, lang):
    """Cache-ONLY lookup. Never calls the LLM, so it never blocks a page render."""
    if lang not in LANGS:
        return {t: t for t in texts}
    uniq = list({(t or "").strip() for t in texts if (t or "").strip()})
    if not uniq:
        return {}
    keys = {cache_key(t, lang): t for t in uniq}
    out = {}
    async for doc in db.translations.find({"_id": {"$in": list(keys)}}):
        out[keys[doc["_id"]]] = doc["target"]
    return out


def schedule_translation(db, texts, lang):
    """Fire-and-forget fill of cache misses, so the NEXT view is translated."""
    if lang not in LANGS or not texts:
        return

    async def _job():
        try:
            await translate_many(db, texts, lang)
        except Exception as e:
            log.warning("background translation failed: %s", str(e)[:160])

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass


ALWAYS_FIELDS = ("manufacturer", "model", "badge", "badge_detail")


async def translate_listings(db, rows, lang, fields=("manufacturer", "model", "badge",
                                                     "badge_detail", "fuel_type",
                                                     "region", "sell_type"),
                             background=True):
    """Attach *_t translated variants to listing dicts.

    background=True (the default for user-facing search) reads ONLY the cache and
    schedules misses for later, so search latency stays flat regardless of how much
    Korean text is new. Untranslated values fall back to the Korean original rather
    than blanking out. The sync warms the common values, so misses are rare.

    EXCEPTION: make and model (`ALWAYS_FIELDS`) must never render as Korean, so they
    are resolved synchronously even on a cache miss. One page shows at most a handful
    of distinct makes/models and they are cached permanently, so the blocking cost is
    paid once per model ever, not per search.
    """
    if lang not in LANGS:
        for r in rows:
            for f in fields:
                r[f"{f}_t"] = r.get(f)
        return rows

    lazy_fields = [f for f in fields if f not in ALWAYS_FIELDS]
    always_fields = [f for f in fields if f in ALWAYS_FIELDS]

    lazy_texts = [r.get(f) for r in rows for f in lazy_fields if r.get(f)]
    tmap = (await translate_cached_only(db, lazy_texts, lang) if background
            else await translate_many(db, lazy_texts, lang))

    always_texts = [r.get(f) for r in rows for f in always_fields if r.get(f)]
    if always_texts:
        try:
            tmap = {**tmap, **await translate_many(db, always_texts, lang)}
        except Exception as e:
            log.warning("make/model translation failed: %s", str(e)[:160])

    misses = []
    for r in rows:
        for f in fields:
            v = r.get(f)
            if not v:
                r[f"{f}_t"] = v
                continue
            key = v.strip()
            hit = tmap.get(key)
            r[f"{f}_t"] = hit or v
            if not hit and f not in ALWAYS_FIELDS:
                misses.append(key)

    if background and misses:
        schedule_translation(db, list(dict.fromkeys(misses)), lang)
    return rows


async def warm_translations(db, langs=None, per_field=600):
    """Pre-translate the bounded, high-traffic label sets (makes, models, submodels,
    fuels, regions) in every language so real searches are ~100% cache hits and instant.

    Makes/models/submodels are now translated synchronously on a cache miss (they must
    never render as Korean), so warming them is what keeps that path from ever being
    felt by a user. Distinct values are only in the low thousands, so this is a handful
    of batched calls - not per-listing work.
    """
    langs = langs or list(LANGS)
    stats = {}
    for field, limit in (("manufacturer", 0), ("model", 0),
                         ("badge", max(per_field * 8, 4000)),
                         ("badge_detail", max(per_field * 8, 4000)),
                         ("fuel_type", 60), ("region", 60)):
        pipe = [
            {"$match": {"active": True, field: {"$nin": [None, ""]}}},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ]
        # limit=0 means "every distinct value" - used for makes and models, which are
        # a small set and must be fully covered.
        if limit:
            pipe.append({"$limit": limit})
        values = [d["_id"] async for d in db.listings.aggregate(pipe, allowDiskUse=True)]
        for lang in langs:
            cached = await translate_cached_only(db, values, lang)
            todo = [v for v in values if v not in cached]
            if todo:
                await translate_many(db, todo, lang)
            stats[f"{field}:{lang}"] = {"values": len(values), "translated": len(todo)}
    log.info("translation warm-up done: %s", stats)
    return stats
