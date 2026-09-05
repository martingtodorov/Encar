"""Server-rendered HTML for every public route.

The app is a CRA bundle: the raw HTML for /bg/car/21601161 is an empty React shell, so an
SEO auditor (and any crawler that does not run JavaScript, and Google itself when the
render queue is behind) sees no H1, no price, no photos, no canonical, no structured data
and the GENERIC home-page title on every single ad. That is what this module fixes.

Every HTML route is answered here: nginx sends the request to `/api/prerender?path=…`, we
read the shell (the built index.html, so the bundle, the fonts and the manifest are the
real ones), strip the placeholder head tags out of it, and write in:

  * a unique <title> and description,
  * a self-referencing <link rel=canonical> plus hreflang alternates for all 4 languages,
  * og:*/twitter:* tags (og:type=product on an ad, with the ad's own lead photo),
  * a <meta name=robots> that is `noindex, follow` on anything that must not be indexed,
  * and REAL markup inside #root — H1, price, spec, photos and internal links — plus
    Vehicle/Offer/BreadcrumbList/ItemList JSON-LD.

React clears #root on its first render, so the prerendered markup is what a crawler (and
the visitor, for the few hundred milliseconds before the bundle boots) sees, and the app
takes over from there untouched.

Status codes matter as much as the markup: a listing we do not have is a real 404, one that
sold is a 410, and an arbitrary filter URL (`?make=…&badge=…`) that resolves to nothing is a
410 as well, so the thousands of near-duplicate crawl-trap URLs Google picked up drop out of
the index instead of sitting there advertising "0 cars".
"""

import logging
import os
import re
import time
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

import curate
import slugs as slugs_mod
from encar import image_url
from translate import translate_listings

log = logging.getLogger("prerender")
router = APIRouter()

LANGS = ["bg", "ro", "pl", "en"]
OG_LOCALE = {"bg": "bg_BG", "ro": "ro_RO", "pl": "pl_PL", "en": "en_GB"}

# Routes that exist only for a signed-in person. Never indexed, always crawlable (a
# Disallow would hide the noindex and publish the URL shape in robots.txt).
PRIVATE = {"login", "account", "admin", "saved", "searches", "purchases", "payment",
           "verify-email", "forgot-password", "reset-password"}
# Evergreen pages with their own copy.
STATIC = ("how-it-works", "fees", "contact", "terms", "privacy", "cookies", "track",
          "sitemap")
# Query keys the search page writes. `sort` and `page` alone do not make a filter URL.
FILTER_KEYS = {"make", "model", "badge", "badgeDetail", "fuels", "regions",
               "transmissions", "year_min", "year_max", "mileage_min", "mileage_max",
               "price_min", "price_max", "only_inspection", "only_record",
               "only_diagnosed", "q"}

CARS_ON_PAGE = 24
SIMILAR_ON_PAGE = 8

# ── injected by server.py (this module never imports it back) ─────────────────
_db = None
H = {}


def set_db(db):
    global _db
    _db = db


def configure(**fns):
    """listing_out, publish_prices, build_query, sorts, share_base, fmt_int,
    share_price, car_slug, apply_home_floor, unfiltered, sanitise."""
    H.update(fns)


# ── copy ─────────────────────────────────────────────────────────────────────
T = {
    "bg": {
        "home_title": "Автомобили от Корея с крайна цена до България | Encar",
        "home_desc": "Разгледайте обявите от Encar на български с крайна цена до "
                     "България — мито, ДДС, морски транспорт и доставка включени.",
        "home": "Начало",
        "listings": "Обяви",
        "results": "{n} автомобила",
        "no_results": "В момента няма обяви по това търсене.",
        "similar": "Подобни автомобили",
        "view": "Виж обявата",
        "km": "км",
        "mileage": "Пробег",
        "year": "Първа регистрация",
        "fuel": "Гориво",
        "gearbox": "Скорости",
        "region": "Регион",
        "price_note": "Крайна цена до България — включва мито, ДДС, морски транспорт "
                      "и доставка.",
        "car_desc": "крайна цена до България.",
        "sold_title": "Тази обява вече не е активна",
        "sold_lead": "Автомобилът е продаден или свален от продажба. Вижте подобни обяви.",
        "nf_title": "Не намерихме тази страница",
        "nf_lead": "Връзката може да е стара или неточна. Върнете се към началото или "
                   "продължете търсенето на автомобил.",
        "makes": "Популярни марки",
        "models": "Модели",
        "pages": "Информация",
        "auto": "автоматична",
        "manual": "ръчна",
    },
    "ro": {
        "home_title": "Mașini din Coreea cu preț final livrat | Encar",
        "home_desc": "Vedeți anunțurile Encar în română, cu prețul final care include "
                     "taxe vamale, TVA, transport maritim și livrare.",
        "home": "Acasă",
        "listings": "Anunțuri",
        "results": "{n} mașini",
        "no_results": "Momentan nu există anunțuri pentru această căutare.",
        "similar": "Mașini similare",
        "view": "Vezi anunțul",
        "km": "km",
        "mileage": "Kilometraj",
        "year": "Prima înmatriculare",
        "fuel": "Combustibil",
        "gearbox": "Transmisie",
        "region": "Regiune",
        "price_note": "Preț final livrat — include taxe vamale, TVA, transport maritim "
                      "și livrare.",
        "car_desc": "preț final până în Bulgaria.",
        "sold_title": "Acest anunț nu mai este activ",
        "sold_lead": "Mașina a fost vândută sau retrasă. Vedeți anunțuri similare.",
        "nf_title": "Nu am găsit această pagină",
        "nf_lead": "Linkul poate fi vechi sau greșit. Întoarceți-vă la pagina principală "
                   "sau continuați căutarea unei mașini.",
        "makes": "Mărci populare",
        "models": "Modele",
        "pages": "Informații",
        "auto": "automată",
        "manual": "manuală",
    },
    "pl": {
        "home_title": "Koreańskie samochody z ceną końcową | Encar",
        "home_desc": "Przeglądaj oferty Encar po polsku z ceną końcową zawierającą cło, "
                     "VAT, transport morski i dostawę.",
        "home": "Strona główna",
        "listings": "Oferty",
        "results": "{n} samochodów",
        "no_results": "Obecnie nie ma ofert dla tego wyszukiwania.",
        "similar": "Podobne samochody",
        "view": "Zobacz ofertę",
        "km": "km",
        "mileage": "Przebieg",
        "year": "Pierwsza rejestracja",
        "fuel": "Paliwo",
        "gearbox": "Skrzynia biegów",
        "region": "Region",
        "price_note": "Cena końcowa — zawiera cło, VAT, transport morski i dostawę.",
        "car_desc": "cena końcowa dostawy.",
        "sold_title": "Ta oferta jest już nieaktywna",
        "sold_lead": "Samochód został sprzedany lub wycofany. Zobacz podobne oferty.",
        "nf_title": "Nie znaleziono tej strony",
        "nf_lead": "Link może być stary lub błędnie wpisany. Wróć na stronę główną albo "
                   "dalej przeglądaj samochody.",
        "makes": "Popularne marki",
        "models": "Modele",
        "pages": "Informacje",
        "auto": "automatyczna",
        "manual": "manualna",
    },
    "en": {
        "home_title": "Korean cars with a final landed price | Encar Europe",
        "home_desc": "Browse every Encar listing in English with a final price that "
                     "includes customs duty, VAT, sea freight and delivery.",
        "home": "Home",
        "listings": "Listings",
        "results": "{n} cars",
        "no_results": "There are no listings for this search right now.",
        "similar": "Similar cars",
        "view": "View listing",
        "km": "km",
        "mileage": "Mileage",
        "year": "First registration",
        "fuel": "Fuel",
        "gearbox": "Gearbox",
        "region": "Region",
        "price_note": "Final price to Bulgaria — customs duty, VAT, sea freight and "
                      "delivery included.",
        "car_desc": "final price to Bulgaria.",
        "sold_title": "This listing is no longer available",
        "sold_lead": "The car has been sold or withdrawn. Here are similar listings.",
        "nf_title": "We could not find that page",
        "nf_lead": "The link may be old or mistyped. Head back to the home page, or "
                   "carry on browsing cars.",
        "makes": "Popular makes",
        "models": "Models",
        "pages": "Information",
        "auto": "automatic",
        "manual": "manual",
    },
}

# Title + description for the evergreen pages, per language. Overridden by the CMS when the
# owner has written their own (site_pages.seo_title / seo_description).
PAGES = {
    "how-it-works": {
        "bg": ("Как работи · Encar Europe",
               "Купувате директно от корейския пазар, а ние поемаме износа и доставката. "
               "Цената, която виждате, е крайната цена до България."),
        "ro": ("Cum funcționează · Encar Europe",
               "Cumpărați direct de pe piața coreeană, iar noi ne ocupăm de export și "
               "livrare. Prețul afișat este prețul final până în Bulgaria."),
        "pl": ("Jak to działa · Encar Europe",
               "Kupujesz bezpośrednio z rynku koreańskiego, a my zajmujemy się eksportem "
               "i dostawą. Cena, którą widzisz, to cena końcowa."),
        "en": ("How it works · Encar Europe",
               "You buy straight from the Korean market while we handle export and "
               "delivery. The price you see is the final price to Bulgaria."),
    },
    "fees": {
        "bg": ("Такси и комисионни · Encar Europe",
               "Какво точно влиза в крайната цена: мито, ДДС, морски транспорт, "
               "комисиона и доставка."),
        "ro": ("Taxe și comisioane · Encar Europe",
               "Ce include exact prețul final: taxe vamale, TVA, transport maritim, "
               "comision și livrare."),
        "pl": ("Opłaty i prowizje · Encar Europe",
               "Co dokładnie zawiera cena końcowa: cło, VAT, transport morski, prowizja "
               "i dostawa."),
        "en": ("Fees and commissions · Encar Europe",
               "Exactly what the final price covers: customs duty, VAT, sea freight, "
               "our commission and delivery."),
    },
    "contact": {
        "bg": ("Контакти и данни за фирмата · Encar Europe",
               "Свържете се с нас за оферта или въпрос по конкретна обява от Корея."),
        "ro": ("Contact și date despre firmă · Encar Europe",
               "Contactați-ne pentru o ofertă sau o întrebare despre un anunț din Coreea."),
        "pl": ("Kontakt i dane firmy · Encar Europe",
               "Skontaktuj się z nami w sprawie wyceny lub pytania o ofertę z Korei."),
        "en": ("Contact and company details · Encar Europe",
               "Get in touch for a quote or a question about a specific Korean listing."),
    },
    "terms": {
        "bg": ("Общи условия · Encar Europe",
               "Условията за използване на сайта и за поръчка на автомобил от Корея."),
        "ro": ("Termeni și condiții · Encar Europe",
               "Condițiile de utilizare a site-ului și de comandă a unei mașini din Coreea."),
        "pl": ("Regulamin · Encar Europe",
               "Zasady korzystania ze strony i zamawiania samochodu z Korei."),
        "en": ("Terms and conditions · Encar Europe",
               "The terms for using the site and for ordering a car from Korea."),
    },
    "privacy": {
        "bg": ("Политика за поверителност · Encar Europe",
               "Какви лични данни обработваме, на какво основание и за колко време."),
        "ro": ("Politica de confidențialitate · Encar Europe",
               "Ce date personale prelucrăm, în ce scop și pentru cât timp."),
        "pl": ("Polityka prywatności · Encar Europe",
               "Jakie dane osobowe przetwarzamy, na jakiej podstawie i jak długo."),
        "en": ("Privacy policy · Encar Europe",
               "What personal data we process, on what basis and for how long."),
    },
    "cookies": {
        "bg": ("Политика за бисквитки · Encar Europe",
               "Сайтът работи без проследяващи бисквитки. Ето какво съхраняваме и защо."),
        "ro": ("Politica de cookie-uri · Encar Europe",
               "Site-ul funcționează fără cookie-uri de urmărire. Iată ce stocăm și de ce."),
        "pl": ("Polityka plików cookie · Encar Europe",
               "Strona działa bez plików śledzących. Oto co przechowujemy i dlaczego."),
        "en": ("Cookie policy · Encar Europe",
               "The site runs without tracking cookies. Here is what we store and why."),
    },
    "track": {
        "bg": ("Проследи автомобила си · Encar Europe",
               "Проследи контейнера с автомобила си от Корея до пристанището на доставка."),
        "ro": ("Urmărește mașina ta · Encar Europe",
               "Urmărește containerul mașinii tale din Coreea până în portul de livrare."),
        "pl": ("Śledź swój samochód · Encar Europe",
               "Śledź kontener z Twoim samochodem od Korei do portu dostawy."),
        "en": ("Track my vehicle · Encar Europe",
               "Track your car's container from Korea to the port of delivery."),
    },
    "sitemap": {
        "bg": ("Карта на сайта · Encar Europe",
               "Всички марки и модели от каталога на една страница."),
        "ro": ("Harta site-ului · Encar Europe",
               "Toate mărcile și modelele din catalog pe o singură pagină."),
        "pl": ("Mapa strony · Encar Europe",
               "Wszystkie marki i modele z katalogu na jednej stronie."),
        "en": ("Sitemap · Encar Europe",
               "Every make and model in the catalogue on a single page."),
    },
}

# CMS slug for a route, where they differ.
CMS_SLUG = {"how-it-works": "how-it-works", "fees": "fees", "contact": "contact",
            "terms": "terms", "privacy": "privacy", "cookies": "cookies"}


def _e(s):
    return (str(s or "").replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _lang(code):
    return code if code in LANGS else "bg"


# ── the shell ────────────────────────────────────────────────────────────────
# The built index.html. In production Ansible drops a copy next to the backend
# (FRONTEND_SHELL); otherwise it is fetched over HTTP from the site itself, which is what
# the preview environment does. Either way it is re-read once a minute, so a fresh deploy
# starts serving the new bundle without a backend restart.
_shell = {"at": 0.0, "html": ""}
_SHELL_TTL = 60.0


async def _shell_html(base):
    now = time.monotonic()
    if _shell["html"] and now - _shell["at"] < _SHELL_TTL:
        return _shell["html"]
    path = os.environ.get("FRONTEND_SHELL", "")
    html = ""
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
        except OSError as e:
            log.warning("shell %s unreadable: %s", path, e)
    if not html and base:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
                r = await c.get(f"{base}/index.html")
            if r.status_code == 200 and "<div id=\"root\"" in r.text:
                html = r.text
        except Exception as e:
            log.warning("shell fetch failed: %s", str(e)[:160])
    if html:
        _shell.update({"at": now, "html": html})
    return _shell["html"]


_STRIP_TITLE = re.compile(r"<title>.*?</title>", re.S | re.I)
_STRIP_META = re.compile(
    r'<meta\s+(?:name|property)="(?:description|robots|og:[^"]*|twitter:[^"]*)"'
    r'[^>]*>', re.I)
_STRIP_CANON = re.compile(r'<link[^>]+rel="(?:canonical|alternate)"[^>]*>', re.I)
# The postbuild patch script (frontend/scripts/gen-lang-html.js) rewrites the title from
# the URL's language segment the moment the page loads. On a prerendered ad that would
# throw away the car's own title, so it goes.
_STRIP_PATCH = re.compile(r"<script>/\*gen-lang-html\*/.*?</script>", re.S)
_ROOT = re.compile(r'(<div id="root"[^>]*>)')


def _compose(shell, lang, head, body):
    html = _STRIP_PATCH.sub("", shell)
    html = _STRIP_TITLE.sub("", html)
    html = _STRIP_META.sub("", html)
    html = _STRIP_CANON.sub("", html)
    html = re.sub(r'<html([^>]*?)\slang="[^"]*"', rf'<html\1 lang="{lang}"', html, count=1)
    if "</head>" in html:
        html = html.replace("</head>", head + "</head>", 1)
    if _ROOT.search(html):
        html = _ROOT.sub(lambda m: m.group(1) + body, html, count=1)
    return html


# ── head ─────────────────────────────────────────────────────────────────────
def _head(*, lang, title, description, canonical, base, alt_path, image="",
          og_type="website", robots="index, follow, max-image-preview:large",
          jsonld=()):
    tags = [f"<title>{_e(title)}</title>",
            f'<meta name="description" content="{_e(description)}">',
            f'<meta name="robots" content="{_e(robots)}">',
            f'<link rel="canonical" href="{_e(canonical)}">']
    for code in LANGS:
        tags.append(f'<link rel="alternate" hreflang="{code}" '
                    f'href="{_e(base)}/{code}{_e(alt_path)}">')
    tags.append(f'<link rel="alternate" hreflang="x-default" '
                f'href="{_e(base)}/en{_e(alt_path)}">')
    tags += [f'<meta property="og:type" content="{_e(og_type)}">',
             '<meta property="og:site_name" content="Encar Europe">',
             f'<meta property="og:locale" content="{OG_LOCALE[lang]}">',
             f'<meta property="og:title" content="{_e(title)}">',
             f'<meta property="og:description" content="{_e(description)}">',
             f'<meta property="og:url" content="{_e(canonical)}">',
             '<meta name="twitter:card" content="summary_large_image">',
             f'<meta name="twitter:title" content="{_e(title)}">',
             f'<meta name="twitter:description" content="{_e(description)}">']
    if image:
        tags += [f'<meta property="og:image" content="{_e(image)}">',
                 f'<meta property="og:image:secure_url" content="{_e(image)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 f'<meta property="og:image:alt" content="{_e(title)}">',
                 f'<meta name="twitter:image" content="{_e(image)}">']
    for block in jsonld:
        tags.append('<script type="application/ld+json">'
                    + block.replace("</", "<\\/") + "</script>")
    tags.append(CSS)
    return "".join(tags)


# One stylesheet for the prerendered markup. It is on screen for the few hundred
# milliseconds before the bundle boots, so it has to look like the site rather than like
# an unstyled document.
CSS = (
    "<style id=\"pr-css\">"
    ".pr{max-width:1180px;margin:0 auto;padding:24px 20px 64px;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;"
    "color:#111;line-height:1.5}"
    ".pr a{color:inherit;text-decoration:none}"
    ".pr nav.pr-crumbs{font-size:13px;color:#6b7280;margin-bottom:14px}"
    ".pr nav.pr-crumbs a{color:#6b7280}"
    ".pr h1{font-size:28px;line-height:1.2;margin:0 0 8px;font-weight:650}"
    ".pr h2{font-size:18px;margin:36px 0 14px;font-weight:600}"
    ".pr .pr-price{font-size:24px;font-weight:700;color:hsl(355,77%,50%);margin:0 0 4px}"
    ".pr .pr-note{font-size:13px;color:#6b7280;margin:0 0 20px}"
    ".pr ul.pr-spec{list-style:none;padding:0;margin:0 0 24px;display:flex;flex-wrap:wrap;"
    "gap:8px 10px}"
    ".pr ul.pr-spec li{background:#f4f4f5;border-radius:10px;padding:8px 12px;font-size:13px}"
    ".pr ul.pr-spec b{font-weight:600}"
    ".pr .pr-shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));"
    "gap:10px;margin:0 0 8px}"
    ".pr .pr-shots img{width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;"
    "border-radius:12px;background:#e5e7eb;display:block}"
    ".pr .pr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));"
    "gap:16px;list-style:none;padding:0;margin:0}"
    ".pr .pr-grid img{width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;"
    "border-radius:12px;background:#e5e7eb;display:block}"
    ".pr .pr-grid strong{display:block;font-size:14px;font-weight:600;margin:8px 0 2px}"
    ".pr .pr-grid span{font-size:13px;color:#6b7280}"
    ".pr .pr-links{display:flex;flex-wrap:wrap;gap:6px 14px;padding:0;margin:0;"
    "list-style:none;font-size:14px}"
    ".pr .pr-links a{color:hsl(355,77%,50%)}"
    ".pr .pr-body{font-size:15px;max-width:70ch}"
    "</style>"
)


# ── shared markup pieces ─────────────────────────────────────────────────────
def _crumbs(lang, trail):
    """trail: [(label, href or "")], last one is the current page."""
    out = []
    for i, (label, href) in enumerate(trail):
        if i:
            out.append(" / ")
        out.append(f'<a href="{_e(href)}">{_e(label)}</a>' if href else _e(label))
    return '<nav class="pr-crumbs">' + "".join(out) + "</nav>"


def _crumb_ld(base, trail):
    items = []
    for i, (label, href) in enumerate(trail, start=1):
        item = f',"item":"{_e(base + href)}"' if href else ""
        items.append('{"@type":"ListItem","position":%d,"name":"%s"%s}'
                     % (i, _e(label).replace('"', ""), item))
    return ('{"@context":"https://schema.org","@type":"BreadcrumbList",'
            '"itemListElement":[' + ",".join(items) + "]}")


def _car_title(row):
    # The same cleanup a shared link gets: production years and factory generation codes in
    # brackets, Korean filler trims and "All New" marketing all come out.
    clean = H["share_title"](row)
    if clean:
        return clean
    parts = []
    for field in ("manufacturer", "model", "badge"):
        value = (row.get(f"{field}_t") or row.get(field) or "").strip()
        if not value or value.startswith("("):
            continue
        if any(value.casefold() in p.casefold() for p in parts):
            continue
        parts.append(value)
    return " ".join(parts).strip()


def _ym(row, lang):
    ym = str(row.get("year_month") or "")
    return f"{ym[4:6]}/{ym[:4]}" if len(ym) >= 6 else (str(row.get("form_year") or ""))


async def _price(row, lang):
    return await H["share_price"](row.get("sale_eur"), lang)


def _card(row, lang, base):
    """One car in a grid: real anchor, real <img>, real price."""
    title = _car_title(row) or row["id"]
    href = f"{base}/{lang}/car/{row['id']}"
    slug = H["car_slug"](title)
    if slug:
        href += f"/{slug}"
    img = row.get("image") or ""
    facts = " · ".join([f for f in [_ym(row, lang),
                                    (f"{H['fmt_int'](row.get('mileage'), lang)} "
                                     f"{T[lang]['km']}") if row.get("mileage") else ""]
                        if f])
    shot = (f'<img src="{_e(img)}" alt="{_e(title)}" width="570" height="320" '
            f'loading="lazy">') if img else ""
    price = row.get("_price") or ""
    return (f'<li><a href="{_e(href)}">{shot}<strong>{_e(title)}</strong>'
            f'<span>{_e(facts)}{" · " if facts and price else ""}{_e(price)}</span>'
            f"</a></li>")


async def _cards(rows, lang, base):
    if not rows:
        return f'<p class="pr-note">{_e(T[lang]["no_results"])}</p>'
    items = [H["listing_out"](d) for d in rows]
    await H["publish_prices"](items)
    for it in items:
        it.pop("landed_eur", None)
        it["_price"] = await _price(it, lang)
    return '<ul class="pr-grid">' + "".join(_card(i, lang, base) for i in items) + "</ul>"


async def _top_makes(lang, base, limit=28):
    rows = [r async for r in _db.taxonomy.find(
        {"level": 1, "slug": {"$nin": [None, ""]}}, {"slug": 1, "value": 1, "count": 1}
    ).sort([("count", -1)]).limit(limit)]
    if not rows:
        return ""
    await translate_listings(_db, [{"manufacturer": r["value"]} for r in rows], lang)
    links = []
    for r in rows:
        label = r.get("value") or r["slug"]
        links.append(f'<li><a href="{_e(base)}/{lang}/{_e(r["slug"])}">{_e(label)}'
                     f"</a></li>")
    return (f"<h2>{_e(T[lang]['makes'])}</h2>"
            '<ul class="pr-links">' + "".join(links) + "</ul>")


def _page_links(lang, base):
    labels = {slug: PAGES[slug][lang][0].split(" · ")[0] for slug in STATIC}
    links = [f'<li><a href="{_e(base)}/{lang}/{slug}">{_e(labels[slug])}</a></li>'
             for slug in STATIC]
    return (f"<h2>{_e(T[lang]['pages'])}</h2>"
            '<ul class="pr-links">' + "".join(links) + "</ul>")


# ── the car page ─────────────────────────────────────────────────────────────
async def _similar(listing, listing_id, lang, base):
    query = H["build_query"]({})
    query["_id"] = {"$ne": listing_id}
    if listing.get("manufacturer"):
        query["manufacturer"] = listing["manufacturer"]
    rows = [d async for d in _db.listings.find(query).sort(H["sorts"]["newest"])
            .limit(SIMILAR_ON_PAGE)]
    if not rows:
        query.pop("manufacturer", None)
        rows = [d async for d in _db.listings.find(query).sort(H["sorts"]["newest"])
                .limit(SIMILAR_ON_PAGE)]
    await translate_listings(_db, rows, lang)
    return await _cards(rows, lang, base)


def _car_ld(row, lang, canonical, photos, price, title):
    fields = [f'"@type":"Car"', f'"name":"{_e(title)}"', f'"url":"{_e(canonical)}"']
    if photos:
        fields.append('"image":[' + ",".join(f'"{_e(p)}"' for p in photos[:8]) + "]")
    make = row.get("manufacturer_t") or row.get("manufacturer")
    if make:
        fields.append('"brand":{"@type":"Brand","name":"%s"}' % _e(make))
    model = row.get("model_t") or row.get("model")
    if model:
        fields.append(f'"model":"{_e(model)}"')
    if row.get("form_year"):
        fields.append(f'"vehicleModelDate":"{_e(row["form_year"])}"')
    if row.get("mileage"):
        fields.append('"mileageFromOdometer":{"@type":"QuantitativeValue",'
                      '"value":%d,"unitCode":"KMT"}' % int(row["mileage"]))
    fuel = row.get("fuel_type_t") or row.get("fuel_type")
    if fuel:
        fields.append(f'"fuelType":"{_e(fuel)}"')
    if row.get("transmission"):
        gear = T[lang]["auto"] if row["transmission"] == "auto" else T[lang]["manual"]
        fields.append(f'"vehicleTransmission":"{_e(gear)}"')
    if row.get("sale_eur"):
        fields.append('"offers":{"@type":"Offer","price":%s,"priceCurrency":"EUR",'
                      '"availability":"https://schema.org/InStock","url":"%s",'
                      '"itemCondition":"https://schema.org/UsedCondition"}'
                      % (int(row["sale_eur"]), _e(canonical)))
    return '{"@context":"https://schema.org",' + ",".join(fields) + "}"


async def _car_page(lang, listing_id, base):
    doc = await _db.listings.find_one({"_id": listing_id})
    if not doc:
        return _not_found(lang, base, f"/car/{listing_id}")

    await curate.refresh(_db)
    await translate_listings(_db, [doc], lang)
    row = H["listing_out"](doc)
    await H["publish_prices"]([row])
    row.pop("landed_eur", None)
    title = _car_title(row) or listing_id
    slug = H["car_slug"](title)
    alt_path = f"/car/{listing_id}/{slug}" if slug else f"/car/{listing_id}"
    canonical = f"{base}/{lang}{alt_path}"
    photos = [image_url(p, 1280, 720) for p in (doc.get("photos") or [])][:8]
    lead = f"{base}/api/og/{listing_id}.jpg" if photos else ""

    gone = (not doc.get("active", True) or doc.get("sold")
            or doc.get("under_contract") or doc.get("duplicate"))
    if gone:
        crumbs = [(T[lang]["home"], f"/{lang}"), (title, "")]
        body = ('<main class="pr">' + _crumbs(lang, [(a, base + b if b else "")
                                                     for a, b in crumbs])
                + f"<h1>{_e(title)} — {_e(T[lang]['sold_title'])}</h1>"
                + f'<p class="pr-note">{_e(T[lang]["sold_lead"])}</p>'
                + f"<h2>{_e(T[lang]['similar'])}</h2>"
                + await _similar(doc, listing_id, lang, base)
                + "</main>")
        head = _head(lang=lang, title=f"{title} · {T[lang]['sold_title']}",
                     description=T[lang]["sold_lead"], canonical=canonical, base=base,
                     alt_path=alt_path, image=lead, robots="noindex, follow")
        return 410, head, body, 300

    price = await _price(row, lang)
    ym = _ym(row, lang)
    mileage = (f"{H['fmt_int'](row.get('mileage'), lang)} {T[lang]['km']}"
               if row.get("mileage") else "")
    fuel = row.get("fuel_type_t") or row.get("fuel_type") or ""
    gear = ""
    if row.get("transmission"):
        gear = T[lang]["auto"] if row["transmission"] == "auto" else T[lang]["manual"]
    region = row.get("region_t") or row.get("region") or ""
    facts = " · ".join([f for f in [ym, mileage, fuel, price] if f])
    description = f"{facts} — {T[lang]['car_desc']}" if facts else T[lang]["car_desc"]

    spec = []
    for label, value in ((T[lang]["year"], ym), (T[lang]["mileage"], mileage),
                         (T[lang]["fuel"], fuel), (T[lang]["gearbox"], gear),
                         (T[lang]["region"], region)):
        if value:
            spec.append(f"<li><b>{_e(label)}:</b> {_e(value)}</li>")

    shots = "".join(
        '<img src="%s" alt="%s" width="1280" height="720" loading="%s">'
        % (_e(p), _e(f"{title} — {i + 1}"), "eager" if not i else "lazy")
        for i, p in enumerate(photos[:6]))

    make_label = row.get("manufacturer_t") or row.get("manufacturer") or ""
    make_row = await _db.taxonomy.find_one(
        {"level": 1, "value": doc.get("manufacturer")}, {"slug": 1}) or {}
    trail = [(T[lang]["home"], f"/{lang}")]
    if make_label and make_row.get("slug"):
        trail.append((make_label, f"/{lang}/{make_row['slug']}"))
    trail.append((title, ""))

    body = ('<main class="pr">'
            + _crumbs(lang, [(a, base + b if b else "") for a, b in trail])
            + f"<h1>{_e(title)}{f' — {_e(ym)}' if ym else ''}</h1>"
            + (f'<p class="pr-price">{_e(price)}</p>' if price else "")
            + f'<p class="pr-note">{_e(T[lang]["price_note"])}</p>'
            + ('<ul class="pr-spec">' + "".join(spec) + "</ul>" if spec else "")
            + (f'<div class="pr-shots">{shots}</div>' if shots else "")
            + f"<h2>{_e(T[lang]['similar'])}</h2>"
            + await _similar(doc, listing_id, lang, base)
            + "</main>")
    head = _head(
        lang=lang, title=f"{title} · Encar Europe", description=description,
        canonical=canonical, base=base, alt_path=alt_path, image=lead, og_type="product",
        jsonld=(_car_ld(row, lang, canonical, photos, price, title),
                _crumb_ld(base, trail)))
    return 200, head, body, 600


# ── list pages: home, make/model landings, filter URLs ───────────────────────
async def _resolve_path_tax(make_slug, model_slug):
    """Path slugs -> (make value, make label slug, model value, model row). None = unknown."""
    make = await _db.taxonomy.find_one({"level": 1, "slug": make_slug},
                                       {"value": 1, "slug": 1, "count": 1})
    if not make:
        return None, None
    if not model_slug:
        return make, None
    model = await _db.taxonomy.find_one(
        {"level": 2, "slug": model_slug, "make": make["value"]},
        {"value": 1, "slug": 1, "count": 1})
    if not model:
        return make, False
    return make, model


async def _query_tax(params):
    """Query-string taxonomy tokens -> upstream values. Missing means unresolvable."""
    tax = await slugs_mod.resolve_taxonomy(
        _db, params.get("make", ""), params.get("model", ""),
        params.get("badge", ""), params.get("badgeDetail", ""))
    out, bad = {}, False
    levels = {"make": 1, "model": 2, "badge": 3, "badge_detail": 4}
    for key, dim in (("make", "make"), ("model", "model"), ("badge", "badge"),
                     ("badgeDetail", "badge_detail")):
        token = params.get(key, "")
        if not token:
            continue
        value = tax.get(dim) or ""
        # resolve_taxonomy echoes a token it cannot place, so a value that is not in the
        # taxonomy at that level is a made-up URL rather than a real filter.
        known = value and await _db.taxonomy.find_one(
            {"level": levels[dim], "value": value}, {"_id": 1})
        if not known:
            bad = True
        else:
            out[dim] = value
    for key, dim in (("fuels", "fuel"), ("regions", "region")):
        tokens = [t for t in (params.get(key) or "").split("~") if t]
        if not tokens:
            continue
        by_slug, _ = await slugs_mod.facet_slugs(_db, dim)
        values = [by_slug.get(t) for t in tokens]
        if any(v is None for v in values):
            bad = True
        out[dim + "s"] = [v for v in values if v]
    return out, bad


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def _list_page(lang, segs, params, base):
    """One renderer for the language home, the make/model landings and filter URLs."""
    await curate.refresh(_db)
    make_slug = segs[0] if segs else ""
    model_slug = segs[1] if len(segs) > 1 else ""

    make = model = None
    if make_slug:
        make, model = await _resolve_path_tax(make_slug, model_slug)
        if make is None or model is False:
            # A pretty URL whose make or model does not exist: never was a page.
            return _not_found(lang, base, "/" + "/".join(segs))

    qtax, bad_tokens = await _query_tax(params)
    filters = {k: v for k, v in params.items() if k in FILTER_KEYS and v not in ("", None)}
    page = max(1, _int(params.get("page")) or 1)
    has_filters = bool(filters) or page > 1

    p = {
        "makes": [make["value"]] if make else ([qtax["make"]] if qtax.get("make") else []),
        "models": [model["value"]] if model else ([qtax["model"]] if qtax.get("model")
                                                 else []),
        "badges": [qtax["badge"]] if qtax.get("badge") else [],
        "badge_details": [qtax["badge_detail"]] if qtax.get("badge_detail") else [],
        "fuels": qtax.get("fuels") or [],
        "regions": qtax.get("regions") or [],
        "transmissions": [t for t in (params.get("transmissions") or "").split("~") if t],
        "year_min": _int(params.get("year_min")),
        "year_max": _int(params.get("year_max")),
        "mileage_min": _int(params.get("mileage_min")),
        "mileage_max": _int(params.get("mileage_max")),
        "price_min": _int(params.get("price_min")),
        "price_max": _int(params.get("price_max")),
        "only_inspection": params.get("only_inspection") == "1",
        "only_record": params.get("only_record") == "1",
        "only_diagnosed": params.get("only_diagnosed") == "1",
        "q": params.get("q") or "",
    }
    query = H["build_query"](p)
    if H["unfiltered"](p):
        H["apply_home_floor"](query)

    total = await _db.listings.count_documents(query)
    skip = (page - 1) * CARS_ON_PAGE
    rows = [d async for d in _db.listings.find(query).sort(H["sorts"]["newest"])
            .skip(skip).limit(CARS_ON_PAGE)]
    await translate_listings(_db, rows, lang)

    # Labels come from the taxonomy values, translated the same way the grid is.
    label_src = {}
    if make:
        label_src["manufacturer"] = make["value"]
    if model:
        label_src["model"] = model["value"]
    if label_src:
        await translate_listings(_db, [label_src], lang)
    sel = " ".join([x for x in [label_src.get("manufacturer_t")
                                or label_src.get("manufacturer"),
                                label_src.get("model_t") or label_src.get("model")] if x])

    path = f"/{make_slug}" if make_slug else ""
    if model_slug:
        path += f"/{model_slug}"
    # A filter URL is never its own canonical: it points at the clean landing page for the
    # make/model it filters, or at the language home when it filters nothing indexable.
    canon_path = path
    if not path and (qtax.get("make") or qtax.get("model")):
        mrow = await _db.taxonomy.find_one(
            {"level": 1, "value": qtax.get("make"), "slug": {"$nin": [None, ""]}},
            {"slug": 1}) if qtax.get("make") else None
        if mrow:
            canon_path = f"/{mrow['slug']}"
            if qtax.get("model"):
                mdl = await _db.taxonomy.find_one(
                    {"level": 2, "value": qtax["model"], "make": qtax.get("make"),
                     "slug": {"$nin": [None, ""]}}, {"slug": 1})
                if mdl:
                    canon_path += f"/{mdl['slug']}"
    canonical = f"{base}/{lang}{canon_path}"

    if sel:
        title = f"{T[lang]['listings']} {sel} | Encar Europe"
        description = f"{T[lang]['listings']} {sel} — {T[lang]['car_desc']}"
        h1 = f"{T[lang]['listings']} {sel}"
    else:
        title = T[lang]["home_title"]
        description = T[lang]["home_desc"]
        h1 = T[lang]["home_title"].split(" | ")[0]
    cms = await _cms_seo("home" if not sel else "", lang)
    if cms and not sel:
        title = cms.get("seo_title") or title
        description = cms.get("seo_description") or description

    # Indexability. An arbitrary filter combination is a crawl trap: it is never indexed and
    # it points at the clean landing page. One that matches nothing at all is 410 Gone, so
    # the junk Google already picked up ("0 cars") leaves the index quickly.
    status, robots = 200, "index, follow, max-image-preview:large"
    if bad_tokens or (has_filters and total == 0):
        status, robots = 410, "noindex, follow"
    elif has_filters:
        robots = "noindex, follow"
    elif total == 0:
        robots = "noindex, follow"

    trail = [(T[lang]["home"], f"/{lang}")]
    if make and make_slug:
        trail.append((label_src.get("manufacturer_t") or make["value"],
                      f"/{lang}/{make_slug}"))
    if model and model_slug:
        trail.append((label_src.get("model_t") or model["value"], ""))

    tail = ""
    if make and not model:
        rows_m = [r async for r in _db.taxonomy.find(
            {"level": 2, "make": make["value"], "slug": {"$nin": [None, ""]}},
            {"slug": 1, "value": 1, "count": 1}).sort([("count", -1)]).limit(40)]
        if rows_m:
            await translate_listings(_db, [{"model": r["value"]} for r in rows_m], lang)
            links = "".join(
                f'<li><a href="{_e(base)}/{lang}/{_e(make_slug)}/{_e(r["slug"])}">'
                f'{_e(r.get("value"))}</a></li>' for r in rows_m)
            tail = (f"<h2>{_e(T[lang]['models'])}</h2>"
                    f'<ul class="pr-links">{links}</ul>')
    if not make_slug:
        tail = await _top_makes(lang, base) + _page_links(lang, base)

    count_line = (T[lang]["results"].replace("{n}", H["fmt_int"](total, lang))
                  if total else T[lang]["no_results"])
    body = ('<main class="pr">'
            + (_crumbs(lang, [(a, base + b if b else "") for a, b in trail])
               if len(trail) > 1 else "")
            + f"<h1>{_e(h1)}</h1>"
            + f'<p class="pr-note">{_e(count_line)} · {_e(T[lang]["price_note"])}</p>'
            + await _cards(rows, lang, base)
            + tail
            + "</main>")

    ld = [_crumb_ld(base, trail)] if len(trail) > 1 else []
    if rows:
        items = ",".join(
            '{"@type":"ListItem","position":%d,"url":"%s"}'
            % (i + 1, _e(f"{base}/{lang}/car/{d['_id']}"))
            for i, d in enumerate(rows))
        ld.append('{"@context":"https://schema.org","@type":"ItemList",'
                  f'"numberOfItems":{len(rows)},"itemListElement":[{items}]}}')
    if not make_slug and not has_filters:
        ld.append('{"@context":"https://schema.org","@graph":['
                  '{"@type":"Organization","name":"Encar Europe","url":"%s/%s",'
                  '"logo":"%s/icons/icon-512.png"},'
                  '{"@type":"WebSite","name":"Encar Europe","url":"%s/%s",'
                  '"inLanguage":"%s","potentialAction":{"@type":"SearchAction",'
                  '"target":"%s/%s?q={search_term_string}",'
                  '"query-input":"required name=search_term_string"}}]}'
                  % (_e(base), lang, _e(base), _e(base), lang, lang, _e(base), lang))

    head = _head(lang=lang, title=title, description=description, canonical=canonical,
                 base=base, alt_path=canon_path, image=f"{base}/og.png", robots=robots,
                 jsonld=tuple(ld))
    return status, head, body, 300


# ── static + private pages ───────────────────────────────────────────────────
async def _cms_seo(slug, lang):
    if not slug:
        return None
    doc = await _db.site_pages.find_one({"_id": f"{slug}|{lang}"},
                                        {"seo_title": 1, "seo_description": 1, "html": 1})
    return doc or None


async def _static_page(lang, slug, base):
    title, description = PAGES[slug][lang]
    cms = await _cms_seo(CMS_SLUG.get(slug, ""), lang)
    html = ""
    if cms:
        title = cms.get("seo_title") or title
        description = cms.get("seo_description") or description
        html = H["sanitise"](cms.get("html") or "")
    path = f"/{slug}"
    trail = [(T[lang]["home"], f"/{lang}"), (title.split(" · ")[0], "")]
    body = ('<main class="pr">'
            + _crumbs(lang, [(a, base + b if b else "") for a, b in trail])
            + f"<h1>{_e(title.split(' · ')[0])}</h1>"
            + f'<p class="pr-body">{_e(description)}</p>'
            + (f'<div class="pr-body">{html}</div>' if html else "")
            + _page_links(lang, base)
            + "</main>")
    head = _head(lang=lang, title=title, description=description,
                 canonical=f"{base}/{lang}{path}", base=base, alt_path=path,
                 image=f"{base}/og.png", jsonld=(_crumb_ld(base, trail),))
    return 200, head, body, 1800


def _private_page(lang, path, base):
    head = _head(lang=lang, title="Encar Europe", description="",
                 canonical=f"{base}/{lang}{path}", base=base, alt_path=path,
                 robots="noindex, nofollow")
    return 200, head, "", 3600


def _not_found(lang, base, path):
    head = _head(lang=lang, title=f"{T[lang]['nf_title']} · Encar Europe",
                 description=T[lang]["nf_lead"], canonical=f"{base}/{lang}{path}",
                 base=base, alt_path=path, robots="noindex, follow")
    body = (f'<main class="pr"><h1>{_e(T[lang]["nf_title"])}</h1>'
            f'<p class="pr-body">{_e(T[lang]["nf_lead"])}</p>'
            f'<ul class="pr-links"><li><a href="{_e(base)}/{lang}">'
            f'{_e(T[lang]["home"])}</a></li></ul></main>')
    return 404, head, body, 600


# ── the endpoint ─────────────────────────────────────────────────────────────
_cache = {}
_CACHE_MAX = 1500


def _remember(key, ttl, status, html):
    if len(_cache) > _CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.monotonic() + ttl, status, html)


async def _render(path, base, extra_params=None):
    sp = urlsplit(path or "/")
    segs = [s for s in sp.path.split("/") if s]
    # nginx hands the route as `?path=$uri&$args`, so the page's own query string arrives as
    # top-level parameters; a query inside `path` (how the endpoint is called by hand and in
    # the tests) is read as well.
    params = dict(parse_qsl(sp.query, keep_blank_values=False))
    params.update({k: v for k, v in (extra_params or {}).items() if k != "path" and v})
    if not segs or segs[0] not in LANGS:
        return _not_found("bg", base, "/" + "/".join(segs))
    lang = segs[0]
    rest = segs[1:]

    if not rest:
        return await _list_page(lang, [], params, base)
    if rest[0] == "car":
        if len(rest) < 2 or not rest[1]:
            return _not_found(lang, base, "/car")
        return await _car_page(lang, rest[1], base)
    if rest[0] in PRIVATE:
        return _private_page(lang, "/" + "/".join(rest), base)
    if rest[0] == "faq":
        return await _static_page(lang, "how-it-works", base)
    if rest[0] in PAGES and len(rest) == 1:
        return await _static_page(lang, rest[0], base)
    if rest[0] == "track":
        return await _static_page(lang, "track", base)
    if len(rest) <= 2:
        return await _list_page(lang, rest, params, base)
    return _not_found(lang, base, "/" + "/".join(rest))


@router.api_route("/prerender", methods=["GET", "HEAD"])
async def prerender(request: Request, path: str = "/"):
    """The HTML for one route, rendered on the server. nginx calls this for every page."""
    base = H["share_base"](request)
    query = dict(request.query_params)
    query.pop("path", None)
    key = f"{base}|{path}|" + "&".join(f"{k}={v}" for k, v in sorted(query.items()))
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return _answer(hit[1], hit[2])

    shell = await _shell_html(base)
    if not shell:
        # nginx falls back to the static shell on a 5xx, which is exactly the right
        # behaviour: the app still works, it is just not prerendered.
        log.warning("no shell available; asking nginx to serve the static one")
        return Response(status_code=503)

    try:
        status, head, body, ttl = await _render(path, base, query)
    except Exception as e:                                  # noqa: BLE001
        log.exception("prerender failed for %s: %s", path, str(e)[:200])
        return HTMLResponse(shell, status_code=200,
                            headers={"Cache-Control": "no-store"})

    lang = _lang((path or "").strip("/").split("/")[0])
    html = _compose(shell, lang, head, body)
    _remember(key, ttl, status, html)
    return _answer(status, html)


def _answer(status, html):
    return HTMLResponse(html, status_code=status, headers={
        "Cache-Control": "public, max-age=300",
        "Vary": "Accept-Encoding",
        "X-Prerender": "1",
    })
