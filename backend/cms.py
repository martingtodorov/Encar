"""Owner-editable pages: SEO metadata, page bodies as raw HTML, and the company details.

Everything here is an OVERRIDE. A slug/language with no document simply falls back to the
copy that ships in the frontend, so the site is never blank because nobody has written
anything yet, and deleting an override puts the built-in text back.

The owner writes Bulgarian; `POST /admin/cms/page/{slug}/translate` sends that document to
Claude and stores the Romanian and English versions, which can then be edited by hand like
any other page.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("cms")
router = APIRouter()

# Every page the owner can edit. "home" is the search page: it has SEO and the hero copy,
# but no body of its own.
SLUGS = ["home", "how-it-works", "faq", "fees", "contact", "terms", "privacy", "cookies"]
LANGS = ["bg", "ro", "en"]
BODY_SLUGS = [s for s in SLUGS if s != "home"]

COMPANY_FIELDS = ["name", "eik", "vat", "address", "phone", "email", "site",
                  "ga_id", "response_hours",
                  "geo_lat", "geo_lng", "google_maps_url"]

_db = None
_require_admin = None
_audit = None
# One small read serves every visitor for a few seconds; page views must not each cost a
# round trip to Mongo for copy that changes once a month.
_cache = {"at": 0.0, "site": {}}
_TTL = 15.0


def set_db(db):
    global _db
    _db = db


def set_admin_guard(fn):
    """server.py owns the admin check and injects it, so this module never imports it back."""
    global _require_admin
    _require_admin = fn


def set_audit(fn):
    global _audit
    _audit = fn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check(slug, lang):
    if slug not in SLUGS:
        raise HTTPException(404, "no such page")
    if lang not in LANGS:
        raise HTTPException(400, "language must be bg, ro or en")


# ── HTML hygiene ──────────────────────────────────────────────────────────────
# The author is the owner, so this is not a defence against a hostile author; it stops a
# pasted tracking snippet or a stray onerror from ending up in every visitor's browser.
_STRIP_TAGS = re.compile(
    r"<\s*(script|style|iframe|object|embed|form|link|meta)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.I | re.S)
_STRIP_SELF = re.compile(r"<\s*(script|iframe|object|embed|link|meta)\b[^>]*/?>", re.I)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS_URL = re.compile(r"(href|src)\s*=\s*(\"|')?\s*javascript:[^\"'>\s]*(\"|')?", re.I)


def sanitise(html: str):
    out = _STRIP_TAGS.sub("", html or "")
    out = _STRIP_SELF.sub("", out)
    out = _ON_ATTR.sub("", out)
    out = _JS_URL.sub("", out)
    return out.strip()


# ── payloads ─────────────────────────────────────────────────────────────────
class PageBody(BaseModel):
    seo_title: str = ""
    seo_description: str = ""
    html: str = ""
    hero_title: str = ""
    hero_subtitle: str = ""


class CompanyBody(BaseModel):
    name: str = ""
    eik: str = ""
    vat: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    site: str = ""
    ga_id: str = ""
    response_hours: str = ""
    geo_lat: str = ""
    geo_lng: str = ""
    google_maps_url: str = ""


def _page_out(doc):
    doc = doc or {}
    return {
        "seo_title": doc.get("seo_title") or "",
        "seo_description": doc.get("seo_description") or "",
        "html": doc.get("html") or "",
        "hero_title": doc.get("hero_title") or "",
        "hero_subtitle": doc.get("hero_subtitle") or "",
        "updated_at": doc.get("updated_at") or "",
        "updated_by": doc.get("updated_by") or "",
    }


# ── public ───────────────────────────────────────────────────────────────────
@router.get("/cms/site")
async def cms_site(lang: str = "bg"):
    """Everything the shell needs in one request: company details, the SEO overrides for
    every page and the home hero copy. Only values the owner actually set are returned, so
    the frontend can keep its own text as the fallback."""
    if lang not in LANGS:
        lang = "bg"
    now = time.monotonic()
    cached = _cache["site"].get(lang)
    if cached and now - _cache["at"] < _TTL:
        return cached

    company = {}
    doc = await _db.site_settings.find_one({"_id": "company"})
    if doc:
        company = {k: doc.get(k) or "" for k in COMPANY_FIELDS if doc.get(k)}

    seo, hero = {}, {}
    async for row in _db.site_pages.find({"lang": lang}):
        slug = row.get("slug")
        entry = {}
        if row.get("seo_title"):
            entry["title"] = row["seo_title"]
        if row.get("seo_description"):
            entry["description"] = row["seo_description"]
        if entry:
            seo[slug] = entry
        if slug == "home":
            if row.get("hero_title"):
                hero["title"] = row["hero_title"]
            if row.get("hero_subtitle"):
                hero["subtitle"] = row["hero_subtitle"]

    out = {"lang": lang, "company": company, "seo": seo, "hero": hero}
    # A single timestamp for all three languages: they are written in the same sitting.
    if now - _cache["at"] >= _TTL:
        _cache["site"] = {}
        _cache["at"] = now
    _cache["site"][lang] = out
    return out


@router.get("/cms/page/{slug}")
async def cms_page(slug: str, lang: str = "bg"):
    """The owner's own body for a page, or nothing at all when they have not written one."""
    _check(slug, lang)
    doc = await _db.site_pages.find_one({"_id": f"{slug}|{lang}"})
    html = sanitise((doc or {}).get("html") or "")
    return {"slug": slug, "lang": lang, "html": html,
            "updated_at": (doc or {}).get("updated_at") or ""}


# ── admin ────────────────────────────────────────────────────────────────────
@router.get("/admin/cms/pages")
async def admin_pages(request: Request, x_admin_token: str = Header(default="")):
    """Which pages have been touched, in which languages."""
    await _require_admin(request, x_admin_token)
    rows = {r["_id"]: r async for r in _db.site_pages.find({})}
    items = []
    for slug in SLUGS:
        langs = {}
        for lang in LANGS:
            r = rows.get(f"{slug}|{lang}") or {}
            langs[lang] = {
                "seo": bool(r.get("seo_title") or r.get("seo_description")),
                "body": bool(r.get("html")),
                "updated_at": r.get("updated_at") or "",
            }
        items.append({"slug": slug, "body_allowed": slug in BODY_SLUGS, "langs": langs})
    return {"items": items}


@router.get("/admin/cms/page/{slug}/{lang}")
async def admin_page(slug: str, lang: str, request: Request,
                     x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    _check(slug, lang)
    doc = await _db.site_pages.find_one({"_id": f"{slug}|{lang}"})
    return {"slug": slug, "lang": lang, **_page_out(doc)}


@router.put("/admin/cms/page/{slug}/{lang}")
async def admin_page_save(slug: str, lang: str, body: PageBody, request: Request,
                          x_admin_token: str = Header(default="")):
    admin = await _require_admin(request, x_admin_token)
    _check(slug, lang)
    who = (admin or {}).get("email") or "master token"
    doc = {
        "slug": slug,
        "lang": lang,
        "seo_title": body.seo_title.strip()[:200],
        "seo_description": body.seo_description.strip()[:400],
        "html": sanitise(body.html)[:200000] if slug in BODY_SLUGS else "",
        "hero_title": body.hero_title.strip()[:200] if slug == "home" else "",
        "hero_subtitle": body.hero_subtitle.strip()[:400] if slug == "home" else "",
        "updated_at": _now(),
        "updated_by": who,
    }
    await _db.site_pages.update_one({"_id": f"{slug}|{lang}"}, {"$set": doc}, upsert=True)
    _cache["at"] = 0.0
    await _audit(request, who, "page edited", f"{slug} ({lang})",
                 "seo + body" if doc["html"] else "seo")
    return {"saved": True, **_page_out(doc)}


@router.delete("/admin/cms/page/{slug}/{lang}")
async def admin_page_reset(slug: str, lang: str, request: Request,
                           x_admin_token: str = Header(default="")):
    """Throw the override away: the built-in copy comes back."""
    admin = await _require_admin(request, x_admin_token)
    _check(slug, lang)
    who = (admin or {}).get("email") or "master token"
    res = await _db.site_pages.delete_one({"_id": f"{slug}|{lang}"})
    _cache["at"] = 0.0
    if res.deleted_count:
        await _audit(request, who, "page reset to default", f"{slug} ({lang})")
    return {"removed": bool(res.deleted_count)}


_TRANSLATE_SYSTEM = (
    "You are translating the website of a company that imports used cars from South Korea "
    "into Europe. Translate into {name}, in the natural register a native speaker would "
    "expect on a commercial website - never word for word, never machine-sounding.\n"
    "RULES:\n"
    "- The input is JSON. Answer with JSON only, the same keys, no commentary, no markdown "
    "fence.\n"
    "- `html` is HTML. Keep every tag, attribute, class and URL EXACTLY as it is and "
    "translate only the human-readable text between the tags.\n"
    "- Keep company names, brand names, model names, email addresses, URLs, currency "
    "symbols and numbers unchanged.\n"
    "- `seo_title` must stay under 60 characters and `seo_description` under 155, because "
    "search engines cut them off."
)
_NAMES = {"ro": "Romanian", "en": "English", "bg": "Bulgarian"}


async def _translate_doc(payload: dict, lang: str):
    """Claude first, Gemini as the standby.

    The fallback is not decoration: the owner's Anthropic key has expired at least once, and
    a dead key must not take the page editor down with it.
    """
    import translate as tr

    system = _TRANSLATE_SYSTEM.format(name=_NAMES[lang])
    body = json.dumps(payload, ensure_ascii=False)
    text = ""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            # Default to Haiku, as everywhere else in the app: the owner pays Haiku token
            # rates for the whole translation surface. `ANTHROPIC_MODEL` env var can still
            # promote a page-save to Sonnet if a lawyer's document ever calls for it.
            resp = await tr._anthropic_client().messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", tr.HAIKU_MODEL),
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": body}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        except Exception as e:
            log.warning("cms translation via anthropic failed, trying gemini: %s", str(e)[:200])
    if not text and os.environ.get("GEMINI_API_KEY"):
        import httpx

        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        r = await httpx.AsyncClient(timeout=180).post(
            tr.GEMINI_URL.format(m=model),
            params={"key": os.environ["GEMINI_API_KEY"]},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": body}]}],
                "generationConfig": {"temperature": 0.2,
                                     "responseMimeType": "application/json"},
            },
        )
        if r.status_code != 200:
            log.warning("cms translation via gemini failed: %s %s", r.status_code, r.text[:200])
        else:
            cands = r.json().get("candidates") or []
            parts = (cands[0].get("content") or {}).get("parts") if cands else []
            text = "".join(p["text"] for p in (parts or []) if isinstance(p.get("text"), str))
    if not text:
        raise HTTPException(503, "no working translation key: check ANTHROPIC_API_KEY")
    try:
        # _extract_json already parses: it strips any fence and returns the dict.
        return tr._extract_json(text)
    except Exception as e:
        log.warning("cms translation for %s came back unparseable: %s", lang, str(e)[:200])
        raise HTTPException(502, "the translation came back in an unexpected shape")


@router.post("/admin/cms/page/{slug}/translate")
async def admin_page_translate(slug: str, request: Request, source: str = "bg",
                               x_admin_token: str = Header(default="")):
    """Take the source-language page and write the other two, so the owner types once."""
    admin = await _require_admin(request, x_admin_token)
    _check(slug, source)
    who = (admin or {}).get("email") or "master token"
    src = await _db.site_pages.find_one({"_id": f"{slug}|{source}"})
    if not src:
        raise HTTPException(400, f"write the {source} version first")
    payload = {k: src.get(k) or "" for k in
               ("seo_title", "seo_description", "html", "hero_title", "hero_subtitle")}
    payload = {k: v for k, v in payload.items() if v}
    if not payload:
        raise HTTPException(400, "there is nothing to translate")

    done = []
    for lang in [l for l in LANGS if l != source]:
        out = await _translate_doc(payload, lang)
        doc = {
            "slug": slug, "lang": lang,
            "seo_title": str(out.get("seo_title") or "").strip()[:200],
            "seo_description": str(out.get("seo_description") or "").strip()[:400],
            "html": sanitise(str(out.get("html") or ""))[:200000] if slug in BODY_SLUGS else "",
            "hero_title": str(out.get("hero_title") or "").strip()[:200] if slug == "home" else "",
            "hero_subtitle": (str(out.get("hero_subtitle") or "").strip()[:400]
                              if slug == "home" else ""),
            "updated_at": _now(),
            "updated_by": f"{who} (translated)",
        }
        await _db.site_pages.update_one({"_id": f"{slug}|{lang}"}, {"$set": doc}, upsert=True)
        done.append(lang)
    _cache["at"] = 0.0
    await _audit(request, who, "page translated", slug, f"{source} -> {', '.join(done)}")
    return {"translated": done}


@router.get("/admin/cms/company")
async def admin_company(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    doc = await _db.site_settings.find_one({"_id": "company"}) or {}
    return {k: doc.get(k) or "" for k in COMPANY_FIELDS}


@router.put("/admin/cms/company")
async def admin_company_save(body: CompanyBody, request: Request,
                             x_admin_token: str = Header(default="")):
    """The registered details, which appear in the footer, the legal pages and the emails."""
    admin = await _require_admin(request, x_admin_token)
    who = (admin or {}).get("email") or "master token"
    doc = {k: (getattr(body, k) or "").strip()[:200] for k in COMPANY_FIELDS}
    await _db.site_settings.update_one({"_id": "company"}, {"$set": doc}, upsert=True)
    _cache["at"] = 0.0
    await _audit(request, who, "company details edited", doc.get("name") or "company")
    return {"saved": True, **doc}
