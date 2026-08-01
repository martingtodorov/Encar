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
MODEL = ("gemini", "gemini-3-flash-preview")

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


async def _llm_translate(chunk, lang):
    """Translate a list of strings in one call. Returns {source: translation}."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        log.error("EMERGENT_LLM_KEY missing - cannot translate")
        return {}

    payload = {str(i): t for i, t in enumerate(chunk)}
    chat = LlmChat(
        api_key=key,
        session_id=f"trans-{lang}-{int(time.time()*1000)}",
        system_message=SYSTEM.format(lang=LANGS[lang]),
    ).with_model(*MODEL)

    for attempt in range(3):
        try:
            resp = await chat.send_message(UserMessage(
                text=f"Translate each value to {LANGS[lang]}. Reply with ONLY a JSON "
                     f"object using the same keys.\n\n"
                     + json.dumps(payload, ensure_ascii=False)))
            got = _extract_json(resp)
            return {chunk[int(i)]: v.strip()
                    for i, v in got.items()
                    if str(i).isdigit() and int(i) < len(chunk)
                    and isinstance(v, str) and v.strip()}
        except Exception as e:
            log.warning("translate attempt %s failed (%s): %s", attempt + 1, lang, str(e)[:160])
            await asyncio.sleep(1.2 * (attempt + 1))
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
        got = await _llm_translate(chunk, lang)
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


async def translate_listings(db, rows, lang, fields=("manufacturer", "model", "badge",
                                                     "fuel_type", "region"),
                             background=True):
    """Attach *_t translated variants to listing dicts.

    background=True (the default for user-facing search) reads ONLY the cache and
    schedules misses for later, so search latency stays flat regardless of how much
    Korean text is new. Untranslated values fall back to the Korean original rather
    than blanking out. The sync warms the common values, so misses are rare.
    """
    if lang not in LANGS:
        for r in rows:
            for f in fields:
                r[f"{f}_t"] = r.get(f)
        return rows

    texts = [r.get(f) for r in rows for f in fields if r.get(f)]
    tmap = (await translate_cached_only(db, texts, lang) if background
            else await translate_many(db, texts, lang))

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
            if not hit:
                misses.append(key)

    if background and misses:
        schedule_translation(db, list(dict.fromkeys(misses)), lang)
    return rows


async def warm_translations(db, langs=None, per_field=600):
    """Pre-translate the bounded, high-traffic label sets (makes, models, fuels,
    regions) in every language so real searches are ~100% cache hits and instant.

    Distinct makes/models are only in the low thousands, so this is a handful of
    batched calls - not per-listing work.
    """
    langs = langs or list(LANGS)
    stats = {}
    for field, limit in (("manufacturer", 200), ("model", per_field),
                         ("fuel_type", 60), ("region", 60)):
        pipe = [
            {"$match": {"active": True, field: {"$nin": [None, ""]}}},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ]
        values = [d["_id"] async for d in db.listings.aggregate(pipe)]
        for lang in langs:
            cached = await translate_cached_only(db, values, lang)
            todo = [v for v in values if v not in cached]
            if todo:
                await translate_many(db, todo, lang)
            stats[f"{field}:{lang}"] = {"values": len(values), "translated": len(todo)}
    log.info("translation warm-up done: %s", stats)
    return stats
