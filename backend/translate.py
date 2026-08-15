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
from datetime import datetime, timezone

log = logging.getLogger("translate")

LANGS = {"en": "English", "bg": "Bulgarian", "ro": "Romanian"}
CHUNK = 60
# Seconds to wait between batched LLM calls. Sized for a free-tier RPM allowance;
# set TRANSLATE_CHUNK_PACE=0 on a paid key to run flat out.
CHUNK_PACE = float(os.environ.get("TRANSLATE_CHUNK_PACE", "6"))
MODEL = ("gemini", "gemini-3-flash-preview")
# The Anthropic model to use for CAR-DETAIL page translations. Owner's directive: the
# whole detail path (specs, options, panel labels, dealer descriptions) runs on Haiku
# because it costs ~5× less than Sonnet for output tokens and the wording is factual,
# not creative. Sonnet stays the default for label-set warm-up where a wrong marque
# spelling would then propagate everywhere.
HAIKU_MODEL = os.environ.get("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001")

# ── LLM circuit breaker ──────────────────────────────────────────────────────
# Errors that cannot possibly be fixed by retrying (no credit, bad key, no quota at all).
# NOTE: a bare HTTP 429 is NOT here. Gemini's free tier answers "You exceeded your
# current quota" for ordinary per-minute rate limiting, which recovers on its own, so
# treating that as fatal would abandon a whole warm-up run after one hiccup.
FATAL_MARKERS = ("budget has been exceeded", "insufficient_quota",
                 "insufficient balance", "api key not valid", "api_key_invalid",
                 "invalid api key", "unauthorized", "permission_denied",
                 # Anthropic answers a dead key with "API key is invalid." and
                 # authentication_error, neither of which matched the wordings above, so a
                 # dead key burned the whole retry ladder on every single call.
                 "api key is invalid", "authentication_error", "invalid_api_key",
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


_ANTHROPIC = None


def _anthropic_client():
    global _ANTHROPIC
    if _ANTHROPIC is None:
        from anthropic import AsyncAnthropic
        # max_retries=0: this module owns the retry/backoff policy (see _llm_translate),
        # so letting the SDK also retry would double every wait.
        _ANTHROPIC = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                    max_retries=0, timeout=180.0)
    return _ANTHROPIC


async def _anthropic_call(chunk, lang, model=None):
    """Primary translator: Anthropic Claude with the project's own API key."""
    import anthropic

    # Default is Haiku, per owner: the whole app pays Haiku token rates unless a caller
    # explicitly picks a heavier model.
    model = model or os.environ.get("ANTHROPIC_MODEL", HAIKU_MODEL)
    try:
        resp = await _anthropic_client().messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM.format(lang=LANGS[lang]),
            messages=[{"role": "user", "content": _user_prompt(chunk, lang)}],
        )
    except anthropic.RateLimitError as e:
        # Anthropic tells us exactly how long to wait; respect it instead of guessing.
        wait = 25.0
        r = getattr(e, "response", None)
        try:
            if r is not None:
                wait = max(wait, float(r.headers.get("retry-after")) + 2)
        except (TypeError, ValueError):
            pass
        raise RuntimeError(f"{RATE_LIMIT_PREFIX}:{wait:.0f}: anthropic 429")
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


async def _emergent_call(chunk, lang):
    """Fallback: Emergent universal key via the emergentintegrations wrapper."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"trans-{lang}-{int(time.time()*1000)}",
        system_message=SYSTEM.format(lang=LANGS[lang]),
    ).with_model(*MODEL)
    return await chat.send_message(UserMessage(text=_user_prompt(chunk, lang)))


def _providers(model=None):
    """Every provider we can use, in order of preference.

    `model` overrides the Anthropic model for this call chain, so any caller can force
    a different model, but the default (via ANTHROPIC_MODEL env) is Haiku everywhere.
    A CHAIN, not a single choice. The old code picked one provider by which key was present
    and gave up there, so when the owner's Anthropic key expired every model name quietly
    stopped being translated even though a working Gemini key sat right next to it.
    """
    out = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append((lambda chunk, lang: _anthropic_call(chunk, lang, model=model), "anthropic"))
    if os.environ.get("GEMINI_API_KEY"):
        out.append((_gemini_call, "gemini"))
    if os.environ.get("EMERGENT_LLM_KEY"):
        out.append((_emergent_call, "emergent"))
    return out


async def _llm_translate(chunk, lang, *, model=None):
    """Translate a list of strings in one call. Returns {source: translation}."""
    chain = _providers(model=model)
    if not chain:
        log.error("no translation API key configured "
                  "(ANTHROPIC_API_KEY/GEMINI_API_KEY/EMERGENT_LLM_KEY)")
        return {}

    # Circuit breaker: make/model/spec translation used to be SYNCHRONOUS on a cache miss, so
    # a dead provider (exhausted budget, bad key) must never turn into 3 retries with
    # backoff on every single request.
    if _breaker_open():
        return {}

    last = ""
    for call, provider in chain:
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
                last = f"{provider}: {msg}"
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
                # A budget or credential failure cannot be retried into working. Move to the
                # NEXT provider instead of taking translation down with this one.
                if any(m in low for m in FATAL_MARKERS):
                    log.warning("%s is unusable, falling through to the next provider",
                                provider)
                    break
                await asyncio.sleep(1.2 * (attempt + 1))
    _breaker_trip(f"every provider failed ({last[:140]})", SOFT_COOLDOWN)
    return {}


# Wording the owner has fixed by hand, which must survive a cache rebuild and must never be
# handed to the LLM again. "가솔린+전기" literally reads "petrol + electricity"; buyers call
# that car a hybrid, so that is what it is called on every page in every language.
OVERRIDES = {
    "가솔린+전기": {"bg": "Хибрид", "ro": "Hibrid", "en": "Hybrid"},
    "디젤+전기": {"bg": "Дизелов хибрид", "ro": "Hibrid diesel", "en": "Diesel hybrid"},
    "LPG+전기": {"bg": "Газов хибрид", "ro": "Hibrid GPL", "en": "LPG hybrid"},
}


def _apply_overrides(out, sources, lang):
    for src in sources:
        fixed = OVERRIDES.get(src, {}).get(lang)
        if fixed:
            out[src] = fixed


async def translate_many(db, texts, lang, *, model=None, type=None):
    """Cache-around-LLM batch translate. Returns {source: translated}.

    `type` (optional, e.g. "fuel", "model", "feature", "description_line") tags every
    row this call writes to `db.translations` so the dictionary can be reviewed and
    audited by column. Callers pass it when the field they are translating is known.

    Unknown/unsupported lang, or Korean itself, is a pass-through. `model` (optional)
    forces a specific Anthropic model — the car-detail page passes Haiku so nothing on a
    listing view is ever billed at Sonnet rates.
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

    _apply_overrides(out, uniq, lang)

    todo = [t for t in uniq if t not in out]
    if not todo:
        return out

    from pymongo import UpdateOne

    # Latin-only strings — proper nouns like "BMW", "M2 (F87)", "GMC", "Grandeur HG" —
    # ARE their own translation in every language, so asking a provider to translate
    # them just spends tokens to be told back what we sent. Persist them as identity
    # rows and short-circuit the LLM call entirely. Massive savings on the search page
    # because every make and every English trim was billing one identity round-trip on
    # first sight.
    identity = [t for t in todo if not _has_hangul(t)]
    if identity:
        docs = [{"_id": cache_key(t, lang), "source": t, "lang": lang, "target": t,
                 **({"type": type} if type else {})}
                for t in identity]
        await db.translations.bulk_write(
            [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in docs],
            ordered=False)
        for t in identity:
            out[t] = t
        identity_set = set(identity)
        todo = [t for t in todo if t not in identity_set]
        log.info("translate_many[%s]: identity-cached %s Latin values (skipped LLM)",
                 lang, len(identity))
    if not todo:
        return out
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i + CHUNK]
        # Proactive pacing between chunks. Free Gemini tiers allow only a handful of
        # requests per minute, so spacing the calls out is far cheaper than discovering
        # the limit through 429s and backoff.
        if i and CHUNK_PACE:
            await asyncio.sleep(CHUNK_PACE)
        got = await _llm_translate(chunk, lang, model=model)
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
                             "lang": lang, "target": tr,
                             **({"type": type} if type else {})})
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


# Grammar is where the fast model slips, so the rules it gets wrong most often are spelled
# out per language rather than left to "translate naturally".
DESC_RULES = {
    "bg": (
        "Write in correct, idiomatic Bulgarian. Watch the definite article: full article "
        "(-ът/-ят) only for a masculine subject, short article (-а/-я) otherwise; feminine "
        "-та, neuter -то, plural -те/-та. Agree adjectives with the noun in gender and "
        "number. Use the vocabulary a Bulgarian car dealer would use: \u043f\u0440\u043e\u0431\u0435\u0433, "
        "\u0441\u043a\u043e\u0440\u043e\u0441\u0442\u043d\u0430 \u043a\u0443\u0442\u0438\u044f, \u0433\u0443\u043c\u0438, \u0441\u0435\u0440\u0432\u0438\u0437\u043d\u0430 \u0438\u0441\u0442\u043e\u0440\u0438\u044f, "
        "\u0437\u0430\u0441\u0442\u0440\u0430\u0445\u043e\u0432\u0430\u0442\u0435\u043b\u043d\u043e \u0441\u044a\u0431\u0438\u0442\u0438\u0435, \u043e\u0431\u043e\u0440\u0443\u0434\u0432\u0430\u043d\u0435, \u043f\u044a\u0440\u0432\u0438 \u0441\u043e\u0431\u0441\u0442\u0432\u0435\u043d\u0438\u043a. "
        "Never transliterate a Korean word that has a Bulgarian equivalent."
    ),
    "ro": (
        "Write in correct, idiomatic Romanian with all diacritics (\u0103 \u00e2 \u00ee \u0219 \u021b). "
        "Use the enclitic definite article correctly and agree adjectives in gender and "
        "number. Use the vocabulary a Romanian dealer would use: rulaj, cutie de viteze, "
        "anvelope, istoric de service, dot\u0103ri, primul proprietar."
    ),
    "en": "Write in clear, natural British English as a dealer would.",
}

DESC_SYSTEM = (
    "You translate a Korean used-car dealer's own description of a vehicle into {lang}.\n"
    "{rules}\n"
    "Rules that always apply:\n"
    "- Convey the meaning, never the Korean word order. Rewrite the sentence so it reads "
    "as if it had been written in {lang} in the first place.\n"
    "- Keep model names, trim names, option names, dates and every number exactly as they "
    "are, including units.\n"
    "- Korean dealer shorthand (\uc6d0, \ub9cc\ud0a4\ub85c, \ubc1c\uc0dd, \ubb34\uc0ac\uace0, \uc790\uc728\uc8fc\ud589) must become the "
    "equivalent term, not a literal gloss.\n"
    "- Preserve the line breaks of the original.\n"
    "- Proofread before answering: no misspellings, no missing articles, no agreement "
    "errors, no half-finished sentences.\n"
    "- Reply with the translation only: no preamble, no notes, no quotation marks."
)


async def stream_description(db, text, lang):
    """Yield a dealer description translation in pieces.

    Legacy single-shot streamer. Kept for symmetry with the callers, but the new default
    path is `translate_description_segmented` — it splits the text into lines, serves
    everything already cached without touching the LLM, and only batches the truly new
    lines. See that function for the cost story.

    Deliberately does NOT cache the full assembled text: every dealer writes their car up
    differently, so a whole-description cache had a hit rate close to zero while filling
    the translations collection with dead rows. Line-level cache in the segmented path is
    where the real reuse happens.
    """
    async with _anthropic_client().messages.stream(
        model=HAIKU_MODEL,
        max_tokens=4000,
        temperature=0.2,   # accuracy over flair: this is a spec sheet in prose
        system=DESC_SYSTEM.format(lang=LANGS[lang], rules=DESC_RULES.get(lang, "")),
        messages=[{"role": "user", "content": text}],
    ) as stream:
        async for piece in stream.text_stream:
            yield piece


# Split a description on line breaks. Blank lines are preserved so the reassembled
# translation looks like the original — dealer boilerplate lives on a rhythm of empty
# lines and separators, and squashing them collapses a paragraph into one wall of text.
_LINE_SPLIT = re.compile(r"(\r\n|\n|\r)")

# Purely decorative dealer separator lines (─── ▒▒▒ 〓〓〓 ---- === ===): no words to
# translate, waste of a cache slot and of the LLM. Copied through as-is.
_DECORATIVE = re.compile(r"^[\s\-\=\_\.\*\#\~\▒\█\▓\░\◆\◇\◈\■\□\●\○\▶\▷\◀\◁\★\☆"
                         r"\〓\═\╬\┃\━\〰\・\·]+$")


def _segments(text):
    """Split a description into segments a cache can address one line at a time.

    Returns a list of (kind, value) pairs:
      ("break", "\n")             — preserved verbatim in the output
      ("blank", "   ")            — whitespace-only lines, preserved verbatim
      ("deco",  "▒▒▒▒▒▒▒")        — copy-through decoration, never sent to the LLM
      ("skip",  "1234-56-7890")   — has no Korean characters, so nothing to translate
      ("todo",  "무사고 차량입니다")   — a real Korean line that needs a translation
    """
    out = []
    for piece in _LINE_SPLIT.split(text or ""):
        if not piece:
            continue
        if piece in ("\n", "\r", "\r\n"):
            out.append(("break", piece))
            continue
        if not piece.strip():
            out.append(("blank", piece))
            continue
        if _DECORATIVE.match(piece):
            out.append(("deco", piece))
            continue
        if not _has_hangul(piece):
            out.append(("skip", piece))
            continue
        out.append(("todo", piece))
    return out


async def translate_description_segmented(db, text, lang, *, on_progress=None):
    """Translate a dealer description one line at a time, driven by the cache.

    Each line is stored in `db.translations` under its own hash: the second time a
    dealer sells a car with the same "무사고 차량입니다" boilerplate line, that line
    costs zero tokens. Only lines with no cache hit are batched through Haiku in ONE
    call at the end.

    `on_progress(text, done)` is called after every cache hit and after the LLM batch,
    so a caller can push incremental output to a stream. `done=True` on the last event.
    Returns the full translated text.
    """
    if not text or not text.strip():
        return text
    segs = _segments(text)

    # 1) Cache lookup for every "todo" segment in ONE indexed Mongo call.
    todo_lines = [s for kind, s in segs if kind == "todo"]
    tmap = await translate_cached_only(db, todo_lines, lang) if todo_lines else {}

    # 2) Anything already cached AND anything decorative or Latin is served instantly.
    out = []
    def emit(text_piece):
        out.append(text_piece)
        if on_progress:
            on_progress(text_piece, False)

    # 3) Batched Haiku call for the misses, ONE request per description.
    missing = [line for line in todo_lines if line not in tmap]
    if missing:
        got = await _llm_translate(list(dict.fromkeys(missing)), lang, model=HAIKU_MODEL)
        # Persist each newly translated line individually so the very next visitor to a
        # DIFFERENT car that shares this line pays nothing.
        if got:
            from pymongo import UpdateOne
            docs = [
                {"_id": cache_key(src, lang), "source": src, "lang": lang, "target": tr,
                 "type": "description_line"}
                for src, tr in got.items() if tr and _looks_translated(src, tr)
            ]
            if docs:
                await db.translations.bulk_write(
                    [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in docs],
                    ordered=False)
            tmap.update({k: v for k, v in got.items() if v})

    # 4) Stitch back together, preserving line breaks and decorative bars verbatim.
    for kind, value in segs:
        if kind in ("break", "blank", "deco", "skip"):
            emit(value)
        else:
            emit(tmap.get(value) or value)

    full = "".join(out)
    # Only the individual line rows persist. The whole-description document was
    # cached previously but had a near-zero hit rate (every dealer writes their
    # car up differently) and only bloated the translations collection.
    if on_progress:
        on_progress("", True)
    return full


def _has_hangul(s):
    return any("\uac00" <= ch <= "\ud7a3" for ch in s or "")


def _looks_translated(src, tr):
    """Is this a real answer, or the Korean handed back unchanged?

    `translate_many` deliberately falls back to the source string when a provider fails, so
    that a dropdown shows Hangul rather than a blank. That fallback must never be written into
    a permanent cache, or a single bad minute freezes Korean into the site forever.

    "BMW" and "GMC" are the exception that matters: a value already in Latin script IS its own
    label, so identity is the correct answer there. Rejecting it left every set that contains a
    western marque permanently incomplete and re-asking the provider for it on every request.
    """
    if not tr:
        return False
    if _has_hangul(tr):
        return False
    return tr != src or not _has_hangul(src)


async def cached_label_set(db, set_id, values, lang, wait=90):
    """The whole label set for one dropdown, cached permanently once it is complete.

    A make's model list is a closed set: once every model of Hyundai has been translated once,
    the answer can never change, so it is stored as ONE document and read back in one indexed
    lookup - no per-value queries, no provider call, no timeout to lose. Only a genuinely new
    value (Encar added a model) costs anything, and only that value.

    We WAIT for the provider here rather than serving Korean and filling in behind the visitor:
    a make/model/sub-model dropdown showing Hangul is worse than a slow one, and it is paid for
    exactly once per set for the lifetime of the site.
    """
    if lang not in LANGS:
        return {v: v for v in values}
    values = [v for v in dict.fromkeys(v for v in values if v)]
    if not values:
        return {}

    doc = await db.label_sets.find_one({"_id": set_id}) or {}
    labels = {k: v for k, v in (doc.get("labels") or {}).items() if _looks_translated(k, v)}
    missing = [v for v in values if v not in labels]

    if missing:
        # The shared translation cache first: another set, or the owner's curation overrides,
        # may already hold the answer - including for a value that needs a renaming rather
        # than a translation.
        labels.update({k: v for k, v in (await translate_cached_only(db, missing, lang)).items()
                       if _looks_translated(k, v)})
        missing = [v for v in values if v not in labels]

    # Whatever is left and is already in Latin script IS its own label: asking a provider about
    # "BMW" only spends money to be told "BMW", and refusing to accept that answer left every
    # set containing a western marque permanently incomplete.
    for v in missing:
        if not _has_hangul(v):
            labels[v] = v
    missing = [v for v in values if v not in labels]

    if missing:
        try:
            got = await asyncio.wait_for(translate_many(db, missing, lang), timeout=wait)
            labels.update({k: v for k, v in (got or {}).items() if _looks_translated(k, v)})
        except Exception as e:
            log.warning("label set %s: %s values unresolved: %s",
                        set_id, len(missing), str(e)[:120])

    complete = all(v in labels for v in values)
    if labels != (doc.get("labels") or {}) or doc.get("complete") != complete:
        await db.label_sets.update_one(
            {"_id": set_id},
            {"$set": {"labels": labels, "complete": complete, "n": len(values),
                      "lang": lang, "at": datetime.now(timezone.utc)}},
            upsert=True)
    return labels


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
    _apply_overrides(out, uniq, lang)
    return out


def schedule_translation(db, texts, lang, *, model=None, type=None):
    """Fire-and-forget fill of cache misses, so the NEXT view is translated.

    `model` (optional) forces a specific Anthropic model — the detail page passes Haiku
    so a background fill of a spec sheet never burns Sonnet-priced tokens. `type` tags
    the entries in the self-learning dictionary.
    """
    if lang not in LANGS or not texts:
        return

    async def _job():
        try:
            await translate_many(db, texts, lang, model=model, type=type)
        except Exception as e:
            log.warning("background translation failed: %s", str(e)[:160])

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass


ALWAYS_FIELDS = ("manufacturer", "model", "badge", "badge_detail")

# Marque and model names are PROPER NOUNS: they stay in English (Latin script) in every
# language, per the owner. Bulgarian was Cyrillicising some of them ("Дайхацу",
# "Серия 2 Gran Coupe") and Romanian was translating "Series" to "Seria", which reads
# wrong on a car and does not match what a buyer searches for.
# Marques, model names AND trim names are proper nouns: "M2 Coupe", "E220d 4MATIC AMG Line".
# They are shown in Latin in every language rather than transliterated ("M2 Купе" was wrong).
LATIN_FIELDS = ("manufacturer", "model", "badge", "badge_detail")
LATIN_LANG = "en"


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
    always_fields = [f for f in fields if f in ALWAYS_FIELDS and f not in LATIN_FIELDS]
    latin_fields = [f for f in fields if f in LATIN_FIELDS]

    lazy_texts = [r.get(f) for r in rows for f in lazy_fields if r.get(f)]
    tmap = (await translate_cached_only(db, lazy_texts, lang) if background
            else await translate_many(db, lazy_texts, lang, type="spec"))

    always_texts = [r.get(f) for r in rows for f in always_fields if r.get(f)]
    if always_texts:
        try:
            tmap = {**tmap, **await translate_many(db, always_texts, lang, type="always")}
        except Exception as e:
            log.warning("submodel translation failed: %s", str(e)[:160])

    # Kept in a separate map: these are resolved in English whatever the page language.
    lmap = {}
    latin_texts = [r.get(f) for r in rows for f in latin_fields if r.get(f)]
    if latin_texts:
        try:
            lmap = await translate_many(db, latin_texts, LATIN_LANG, type="latin")
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
            hit = (lmap if f in LATIN_FIELDS else tmap).get(key)
            r[f"{f}_t"] = hit or v
            if not hit and f not in ALWAYS_FIELDS:
                misses.append(key)

    if background and misses:
        schedule_translation(db, list(dict.fromkeys(misses)), lang, type="spec")
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
                         ("badge", 0), ("badge_detail", 0),
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
        # Makes, models and trims are shown in Latin in EVERY language, so only the English
        # cache is ever read for them — warming them in bg/ro was paying for translations
        # nothing renders.
        for lang in ([LATIN_LANG] if field in LATIN_FIELDS else langs):
            cached = await translate_cached_only(db, values, lang)
            todo = [v for v in values if v not in cached]
            if todo:
                await translate_many(db, todo, lang, type=field)
            stats[f"{field}:{lang}"] = {"values": len(values), "translated": len(todo)}
    log.info("translation warm-up done: %s", stats)
    return stats
