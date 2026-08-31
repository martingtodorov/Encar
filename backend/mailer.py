"""Transactional email via Resend.

Two messages, both triggered by a buyer enquiry:
  * a notification to the operator's inbox, so nobody has to poll the admin inbox
  * an acknowledgement to the buyer, in the language they were browsing in

Sending is best-effort and NEVER blocks or fails the enquiry itself - a lost email is a
nuisance, a lost enquiry is a lost sale.
"""

import asyncio
import logging
import os
import time

import httpx

from encar import image_url

# The card tier the WEBSITE uses is 570x320 (16:9, centre-cropped, small watermark). Emails
# render the same crop at half that, which is also 2x the 150x84 box in `_digest_car`, so the
# picture stays sharp on a retina phone. One constant, so an email can never quietly drift to
# a different photo or a different aspect than the site.
CARD_W, CARD_H = 300, 169


def car_thumb(photos):
    """The car's lead photo, cropped exactly like its card on the website."""
    return image_url((photos or [None])[0], CARD_W, CARD_H)

log = logging.getLogger("mailer")

# `configured()` only proves a key STRING is present. Resend can still reject it, and `_send`
# swallows that so an enquiry is never lost — which meant the admin dashboard reported email as
# healthy while every single letter was being dropped. This asks Resend directly, cached, so a
# rejected key is visible instead of silent.
_auth = {"at": 0.0, "ok": None, "error": ""}
_AUTH_TTL = 300.0


async def key_ok(force=False):
    """Does Resend actually ACCEPT our key? `{"ok": bool|None, "error": str}`."""
    if not os.environ.get("RESEND_API_KEY"):
        return {"ok": False, "error": "no RESEND_API_KEY set"}
    if not force and _auth["ok"] is not None and time.time() - _auth["at"] < _AUTH_TTL:
        return {"ok": _auth["ok"], "error": _auth["error"]}
    try:
        async with httpx.AsyncClient(timeout=6.0) as http:
            r = await http.get("https://api.resend.com/domains", headers={
                "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
        ok = r.status_code < 400
        error = "" if ok else (r.json().get("message") or r.text)[:200]
    except Exception as e:                      # network trouble is not a rejected key
        return {"ok": None, "error": f"could not reach Resend: {str(e)[:120]}"}
    _auth.update({"at": time.time(), "ok": ok, "error": error})
    if not ok:
        log.warning("Resend rejected our API key: %s", error)
    return {"ok": ok, "error": error}


async def health():
    """`status()` plus whether the key really works — for the admin dashboard."""
    return {**status(), "auth": await key_ok()}

# Resend's shared sender works without owning a domain, but it only DELIVERS to the
# address that owns the Resend account. Set SENDER_EMAIL to an address on a verified
# domain before real buyers are expected to receive anything.
SHARED_SENDER = "onboarding@resend.dev"


def sender():
    return os.environ.get("SENDER_EMAIL") or SHARED_SENDER


def configured():
    return bool(os.environ.get("RESEND_API_KEY"))


def status():
    """Surfaced on the admin dashboard so a silent email outage is visible."""
    return {
        "configured": configured(),
        "sender": sender(),
        "shared_sender": sender() == SHARED_SENDER,
        "notify_email": os.environ.get("ADMIN_NOTIFY_EMAIL", ""),
    }


async def _send(to, subject, html):
    if not configured():
        log.info("email skipped (no RESEND_API_KEY): %s -> %s", subject, to)
        return None
    if not to:
        return None

    # On the shared sender Resend will only deliver to the address that owns the account,
    # so anything aimed at a buyer would vanish without a trace. Send it to the owner
    # instead, with the intended recipient in the subject, until SENDER_EMAIL points at a
    # verified domain.
    owner = os.environ.get("ADMIN_NOTIFY_EMAIL", "").strip()
    if sender() == SHARED_SENDER and to.lower() != owner.lower():
        if not owner:
            log.warning("email to %s dropped: shared sender and no ADMIN_NOTIFY_EMAIL", to)
            return None
        log.info("email for %s redirected to %s (shared sender)", to, owner)
        subject = f"[would go to {to}] {subject}"
        to = owner

    import resend

    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {"from": sender(), "to": [to], "subject": subject, "html": html}
    try:
        # the SDK is synchronous, so keep it off the event loop
        res = await asyncio.to_thread(resend.Emails.send, params)
        log.info("email sent to %s (%s)", to, (res or {}).get("id"))
        return res
    except Exception as e:
        log.warning("email to %s failed: %s", to, str(e)[:200])
        return None


# ── templates ────────────────────────────────────────────────────────────────
# Inline CSS and a table shell only: everything else is unreliable in mail clients.
def _logo_html():
    """The wordmark, hosted on our own site. Mail clients need an absolute URL, so with no
    PUBLIC_SITE_URL configured we fall back to text rather than a broken image."""
    base = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if not base:
        return '<span style="font-size:18px;font-weight:700;color:#d0021b">Europe Encar</span>'
    return (f'<img src="{base}/logo-220.png" alt="Europe Encar" width="127" height="36" '
            'style="display:block;border:0;outline:none;text-decoration:none;height:36px;'
            'width:auto">')


def _shell(heading, rows_html, footer):
    return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f7;padding:24px 0;font-family:Helvetica,Arial,sans-serif">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e5e7;border-radius:14px;overflow:hidden">
<tr><td style="padding:20px 24px;border-bottom:1px solid #e5e5e7">
{_logo_html()}
</td></tr>
<tr><td style="padding:24px">
<h1 style="margin:0 0 16px;font-size:19px;line-height:1.3;color:#111">{heading}</h1>
<table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#111">{rows_html}</table>
</td></tr>
<tr><td style="padding:16px 24px;border-top:1px solid #e5e5e7;font-size:12px;color:#6b6b70">{footer}</td></tr>
</table>
</td></tr></table>"""


def _row(label, value):
    if not value:
        return ""
    return (f'<tr><td style="padding:6px 0;color:#6b6b70;width:38%;vertical-align:top">{label}</td>'
            f'<td style="padding:6px 0;color:#111">{value}</td></tr>')


ACK = {
    "bg": {
        "subject": "Получихме вашето запитване",
        "heading": "Благодарим ви - получихме вашето запитване",
        "body": ("Ще се свържем с вас възможно най-скоро с наличност, крайна цена "
                 "и срокове за доставка."),
        "car": "Автомобил",
        "message": "Вашето съобщение",
        "footer": "Това е автоматично потвърждение. Няма нужда да отговаряте.",
    },
    "ro": {
        "subject": "Am primit solicitarea dumneavoastră",
        "heading": "Vă mulțumim - am primit solicitarea dumneavoastră",
        "body": ("Vă vom contacta în cel mai scurt timp cu disponibilitatea, prețul "
                 "final și termenul de livrare."),
        "car": "Mașină",
        "message": "Mesajul dumneavoastră",
        "footer": "Aceasta este o confirmare automată. Nu este nevoie să răspundeți.",
    },
    "en": {
        "subject": "We received your enquiry",
        "heading": "Thank you - we have your enquiry",
        "body": ("We will come back to you shortly with availability, the final landed "
                 "price and delivery timing."),
        "car": "Car",
        "message": "Your message",
        "footer": "This is an automatic confirmation. No need to reply.",
    },
}


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


async def notify_new_enquiry(doc):
    to = os.environ.get("ADMIN_NOTIFY_EMAIL", "").strip()
    if not to:
        log.info("enquiry %s: no ADMIN_NOTIFY_EMAIL set, notification skipped", doc["_id"])
        return
    rows = "".join([
        _row("Car", _esc(doc.get("car_title"))),
        _row("Listing", _esc(doc.get("listing_id"))),
        _row("Name", _esc(doc.get("name"))),
        _row("Email", _esc(doc.get("email"))),
        _row("Phone", _esc(doc.get("phone"))),
        _row("Language", _esc(doc.get("lang"))),
        _row("Account", "guest" if doc.get("is_guest") else "signed in"),
        _row("Message", _esc(doc.get("message")).replace("\n", "<br>")),
    ])
    html = _shell("New buyer enquiry", rows,
                  "Sent automatically when a buyer submits the enquiry form.")
    await _send(to, f"New enquiry: {doc.get('car_title') or 'a car'}", html)


async def acknowledge_enquiry(doc):
    to = (doc.get("email") or "").strip()
    if not to:
        return
    c = ACK.get(doc.get("lang")) or ACK["en"]
    rows = "".join([
        f'<tr><td colspan="2" style="padding:0 0 14px;color:#111;line-height:1.55">{c["body"]}</td></tr>',
        _row(c["car"], _esc(doc.get("car_title"))),
        _row(c["message"], _esc(doc.get("message")).replace("\n", "<br>")),
    ])
    await _send(to, c["subject"], _shell(c["heading"], rows, c["footer"]))


# ── price drop on a saved car ────────────────────────────────────────────────
DROP = {
    "bg": {
        "subject": "Запазена кола падна в цената",
        "heading": "Кола от запазените ви е по-евтина",
        "body": "Цената падна при следните автомобили от списъка ви:",
        "cut": "по-евтина с",
        "footer": ("Получавате това, защото сте запазили колата. Можете да изключите тези "
                   "известия в профила си."),
    },
    "ro": {
        "subject": "Un automobil salvat a scăzut la preț",
        "heading": "Un automobil din lista ta este mai ieftin",
        "body": "Prețul a scăzut la următoarele automobile din lista ta:",
        "cut": "mai ieftin cu",
        "footer": ("Primești acest mesaj pentru că ai salvat automobilul. Poți opri aceste "
                   "notificări din profilul tău."),
    },
    "en": {
        "subject": "A saved car dropped in price",
        "heading": "A car on your list got cheaper",
        "body": "The price came down on these cars you saved:",
        "cut": "down",
        "footer": ("You are getting this because you saved the car. You can turn these "
                   "alerts off in your profile."),
    },
}


async def send_price_drop(to, rows, lang="en"):
    """One email per person, listing every car of theirs that fell.

    One message per car would punish exactly the people who save the most cars.

    Rendered with the same car block as the weekly digest, so a price drop arrives with the
    car's PHOTO — the identical crop the website shows on its cards. It used to be a bare
    line of text: the one email whose whole job is "look at this car again" was the one that
    never showed the car.
    """
    t = DROP.get(lang) or DROP["en"]
    body = "".join(
        _digest_car(r, lang, note=f'{t["cut"]} {r["cut_pct"]}%')
        for r in rows)
    html = _shell(t["heading"],
                  f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{t["body"]}'
                  f'</td></tr>{body}',
                  t["footer"])
    return await _send(to, t["subject"], html)


# ── new cars matching a saved search ─────────────────────────────────────────
MATCHES = {
    "bg": {
        "subject": "Нови автомобили по вашето търсене",
        "heading": "Нови обяви по запазено търсене",
        "body": "Открихме {n} нови автомобила по търсенето „{name}“:",
        "body_unnamed": "Открихме {n} нови автомобила по едно от запазените ви търсения:",
        "more": "и още {n}",
        "footer": ("Получавате това, защото сте включили известия за това търсене. "
                   "Можете да ги изключите в „Запазени търсения“."),
    },
    "ro": {
        "subject": "Automobile noi pentru căutarea ta",
        "heading": "Anunțuri noi pentru o căutare salvată",
        "body": "Am găsit {n} automobile noi pentru căutarea „{name}”:",
        "body_unnamed": "Am găsit {n} automobile noi pentru una dintre căutările tale salvate:",
        "more": "și încă {n}",
        "footer": ("Primești acest mesaj pentru că ai activat notificările pentru această "
                   "căutare. Le poți opri din „Căutări salvate”."),
    },
    "en": {
        "subject": "New cars match your search",
        "heading": "New listings for a saved search",
        "body": "We found {n} new cars for your search “{name}”:",
        "body_unnamed": "We found {n} new cars for one of your saved searches:",
        "more": "and {n} more",
        "footer": ("You are getting this because you turned alerts on for this search. "
                   "You can turn them off under Saved searches."),
    },
}


def _car_link(car_id, text, lang):
    """The title links to the ad when we know our own address; plain text otherwise."""
    base = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if not base:
        return text
    return (f'<a href="{base}/{lang}/car/{car_id}" '
            f'style="color:#d0021b;text-decoration:none">{text}</a>')


# ── weekly saved-search digest ───────────────────────────────────────────────
DIGEST = {
    "bg": {
        "subject": "Нови коли по твоите запазени търсения",
        "heading": "Ето какво е ново тази седмица",
        "body": "Открихме {n} нови автомобила по запазените ти търсения от последния имейл.",
        "search": "Търсене: {name}",
        "unnamed": "Запазено търсене",
        "more": "и още {n} по това търсене",
        "cta": "Виж всички в сайта",
        "popular": "Най-гледаните тази седмица",
        "people": "{n} души я разгледаха",
        "footer": ("Получаваш този имейл, защото си включил известия за запазено търсене. "
                   "Можеш да ги спреш по всяко време от профила си."),
    },
    "ro": {
        "subject": "Mașini noi pentru căutările tale salvate",
        "heading": "Iată ce este nou săptămâna aceasta",
        "body": "Am găsit {n} mașini noi pentru căutările tale salvate de la ultimul e-mail.",
        "search": "Căutare: {name}",
        "unnamed": "Căutare salvată",
        "more": "și încă {n} pentru această căutare",
        "cta": "Vezi toate pe site",
        "popular": "Cele mai vizualizate săptămâna aceasta",
        "people": "{n} persoane au deschis-o",
        "footer": ("Primești acest e-mail pentru că ai activat notificările pentru căutări "
                   "salvate. Le poți opri oricând din contul tău."),
    },
    "en": {
        "subject": "New cars for your saved searches",
        "heading": "Here is what is new this week",
        "body": "We found {n} new cars for your saved searches since the last email.",
        "search": "Search: {name}",
        "unnamed": "Saved search",
        "more": "and {n} more for this search",
        "cta": "See them all on the site",
        "popular": "Most viewed this week",
        "people": "{n} people opened it",
        "footer": ("You are getting this because you turned on saved-search alerts. "
                   "You can switch them off in your account at any time."),
    },
}


def _digest_car(car, lang, note=""):
    """One car: its own photo, then the title and the numbers a buyer scans for.

    A two-cell table rather than a flex row, and every dimension inline, because that is the
    only layout Outlook and Gmail both honour. The photo is the ad's own lead shot straight
    from the CDN - an absolute URL, since a mail client has no site to resolve against.
    """
    facts = " · ".join(x for x in [
        f'€{car["price_eur"]:,.0f}' if car.get("price_eur") else "",
        str(car["year"]) if car.get("year") else "",
        f'{car["mileage"]:,} km' if car.get("mileage") else "",
    ] if x)
    extra = (f'<div style="padding-top:3px;color:#d0021b;font-size:12.5px;font-weight:600">'
             f'{note}</div>') if note else ""
    title = _car_link(car["car_id"], _esc(car.get("title") or ""), lang)
    photo = car.get("image") or ""
    # 150x84 is CARD_W:CARD_H halved. Email clients honour the width/height ATTRIBUTES, so a
    # box in a different ratio than the file squashes the car rather than cropping it.
    img = (f'<img src="{photo}" width="150" height="84" alt="" '
           'style="display:block;border:0;outline:none;text-decoration:none;'
           'width:150px;height:84px;object-fit:cover;border-radius:8px;background:#eeeef0">'
           ) if photo else "&nbsp;"
    return (
        '<tr><td colspan="2" style="padding:0 0 10px">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="150" style="width:150px;vertical-align:top">{img}</td>'
        '<td style="padding-left:12px;vertical-align:top;font-size:14px;color:#111">'
        f'<div style="font-weight:600;line-height:1.35">{title}</div>'
        f'<div style="padding-top:4px;color:#6b6b70;font-size:13px">{facts}</div>'
        f'{extra}'
        '</td></tr></table></td></tr>'
    )


async def send_search_digest(to, groups, lang="en", popular=None):
    """ONE email a week per buyer, covering every saved search that picked something up.

    `groups` is a list of {name, cars, total}; `cars` carry title, car_id, image, price_eur,
    year and mileage. Searches with nothing new are left out by the caller, and an empty
    digest is never sent.

    `popular` is the week's most opened ads, each with a `people` count of DISTINCT viewers -
    never raw refreshes. It rides along with a letter that was going out anyway; it is never a
    reason to send one.
    """
    t = DIGEST.get(lang) or DIGEST["en"]
    total = sum(g.get("total") or len(g["cars"]) for g in groups)
    body = (f'<tr><td colspan="2" style="padding:0 0 16px;color:#111">'
            f'{t["body"].format(n=total)}</td></tr>')
    for g in groups:
        heading = t["search"].format(name=_esc(g["name"])) if g.get("name") else t["unnamed"]
        body += ('<tr><td colspan="2" style="padding:6px 0 10px;font-size:12px;'
                 'text-transform:uppercase;letter-spacing:.04em;color:#6b6b70;'
                 f'border-top:1px solid #e5e5e7">{heading}</td></tr>')
        body += "".join(_digest_car(c, lang) for c in g["cars"])
        left = (g.get("total") or len(g["cars"])) - len(g["cars"])
        if left > 0:
            body += ('<tr><td colspan="2" style="padding:0 0 12px;font-size:13px;'
                     f'color:#6b6b70">{t["more"].format(n=left)}</td></tr>')

    if popular:
        body += ('<tr><td colspan="2" style="padding:6px 0 10px;font-size:12px;'
                 'text-transform:uppercase;letter-spacing:.04em;color:#6b6b70;'
                 f'border-top:1px solid #e5e5e7">{t["popular"]}</td></tr>')
        body += "".join(
            _digest_car(c, lang, note=t["people"].format(n=f'{c.get("people", 0):,}'))
            for c in popular)

    base = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if base:
        body += ('<tr><td colspan="2" style="padding:8px 0 0">'
                 f'<a href="{base}/{lang}/searches" style="display:inline-block;'
                 'background:#d0021b;color:#ffffff;text-decoration:none;font-weight:600;'
                 f'font-size:14px;padding:11px 18px;border-radius:10px">{t["cta"]}</a>'
                 '</td></tr>')

    return await _send(to, t["subject"], _shell(t["heading"], body, t["footer"]))


async def send_new_matches(to, name, rows, total, lang="en"):
    """One email per saved search, listing the newest cars that now match it."""
    t = MATCHES.get(lang) or MATCHES["en"]
    intro = (t["body"].format(n=total, name=_esc(name)) if name
             else t["body_unnamed"].format(n=total))
    body = "".join(
        _row(_car_link(r["car_id"], _esc(r["title"]), lang),
             " · ".join(x for x in [
                 f'€{r["price_eur"]:,.0f}' if r.get("price_eur") else "",
                 str(r["year"]) if r.get("year") else "",
                 f'{r["mileage"]:,} km' if r.get("mileage") else "",
             ] if x))
        for r in rows)
    if total > len(rows):
        body += _row("", t["more"].format(n=total - len(rows)))
    html = _shell(t["heading"],
                  f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{intro}'
                  f'</td></tr>{body}',
                  t["footer"])
    return await _send(to, t["subject"], html)


# ── deposit returned ─────────────────────────────────────────────────────────
RETURNED = {
    "bg": {
        "subject": "Депозитът ви е върнат",
        "heading": "Върнахме депозита ви",
        "body": ("Сумата е изпратена обратно към картата, с която платихте. Според банката "
                 "ви може да отнеме няколко работни дни."),
        "car": "Автомобил", "returned": "Върната сума", "kept": "Задържана комисиона",
        "footer": "Ако нещо не е ясно, просто отговорете на този имейл.",
    },
    "ro": {
        "subject": "Depozitul tău a fost returnat",
        "heading": "Am returnat depozitul tău",
        "body": ("Suma a fost trimisă înapoi pe cardul cu care ai plătit. În funcție de "
                 "bancă, pot trece câteva zile lucrătoare."),
        "car": "Automobil", "returned": "Sumă returnată", "kept": "Comision reținut",
        "footer": "Dacă ceva nu este clar, răspunde pur și simplu la acest e-mail.",
    },
    "en": {
        "subject": "Your deposit has been returned",
        "heading": "We have returned your deposit",
        "body": ("The money is on its way back to the card you paid with. Depending on your "
                 "bank it can take a few working days to appear."),
        "car": "Car", "returned": "Returned", "kept": "Commission kept",
        "footer": "If anything is unclear, just reply to this email.",
    },
}


async def send_deposit_returned(to, car_title, returned_eur, commission_eur, lang="en"):
    t = RETURNED.get(lang) or RETURNED["en"]
    rows = (f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{t["body"]}</td></tr>'
            + _row(t["car"], _esc(car_title))
            + _row(t["returned"], f"€{returned_eur:,.0f}")
            + _row(t["kept"], f"€{commission_eur:,.0f}"))
    return await _send(to, t["subject"], _shell(t["heading"], rows, t["footer"]))



# ── hold captured / hold released ────────────────────────────────────────────
# A pre-authorisation is money the buyer can see missing from their card without ever having
# been charged, so both of these letters exist to prevent the phone call that follows.
CAPTURED = {
    "bg": {
        "subject": "Взехме част от блокираната сума",
        "heading": "Депозитът ви е усвоен",
        "body": ("Взехме сумата по-долу от блокираната по картата ви. Ако е останала "
                 "разлика, тя се освобождава от банката ви и се връща по картата."),
        "car": "Автомобил", "taken": "Усвоена сума", "back": "Освободена сума",
        "footer": "Ако нещо не е ясно, просто отговорете на този имейл.",
    },
    "ro": {
        "subject": "Am încasat o parte din suma blocată",
        "heading": "Depozitul tău a fost încasat",
        "body": ("Am încasat suma de mai jos din suma blocată pe cardul tău. Diferența, "
                 "dacă există, este eliberată de bancă și revine pe card."),
        "car": "Automobil", "taken": "Sumă încasată", "back": "Sumă eliberată",
        "footer": "Dacă ceva nu este clar, răspunde pur și simplu la acest e-mail.",
    },
    "en": {
        "subject": "We have taken part of the amount held",
        "heading": "Your deposit has been taken",
        "body": ("We have taken the amount below from the sum held on your card. Anything "
                 "left over is released by your bank and returns to your card."),
        "car": "Car", "taken": "Taken", "back": "Released",
        "footer": "If anything is unclear, just reply to this email.",
    },
}

RELEASED = {
    "bg": {
        "subject": "Блокираната сума е освободена",
        "heading": "Освободихме блокираната сума",
        "body": ("Не сме взели нищо от картата ви. Блокираната сума е освободена и според "
                 "банката ви може да отнеме няколко работни дни, докато изчезне от извлечението."),
        "expired": ("Блокирането на сума важи 7 дни и това време изтече, затова я освободихме "
                    "и върнахме автомобила в обявите. Ако още го искате, започнете резервацията отново."),
        "car": "Автомобил", "amount": "Освободена сума",
        "footer": "Ако нещо не е ясно, просто отговорете на този имейл.",
    },
    "ro": {
        "subject": "Suma blocată a fost eliberată",
        "heading": "Am eliberat suma blocată",
        "body": ("Nu am încasat nimic de pe cardul tău. Suma blocată a fost eliberată și, în "
                 "funcție de bancă, pot trece câteva zile lucrătoare până dispare din extras."),
        "expired": ("Blocarea sumei este valabilă 7 zile, iar termenul a expirat, așa că am "
                    "eliberat-o și am repus automobilul în listă. Dacă îl mai dorești, "
                    "începe rezervarea din nou."),
        "car": "Automobil", "amount": "Sumă eliberată",
        "footer": "Dacă ceva nu este clar, răspunde pur și simplu la acest e-mail.",
    },
    "en": {
        "subject": "The amount held has been released",
        "heading": "We have released the hold",
        "body": ("We have taken nothing from your card. The held amount has been released "
                 "and, depending on your bank, can take a few working days to disappear."),
        "expired": ("A hold on a card lasts 7 days and that time has now passed, so we have "
                    "released it and put the car back on the market. If you still want it, "
                    "start the reservation again."),
        "car": "Car", "amount": "Released",
        "footer": "If anything is unclear, just reply to this email.",
    },
}


VERIFY = {
    "bg": {
        "subject": "Кодът за потвърждение: {code}",
        "heading": "Потвърдете имейл адреса си",
        "body": ("Въведете този код в отворената страница, за да потвърдите адреса си. "
                 "Кодът е валиден 15 минути и важи само веднъж."),
        "code": "Код", "ignore": "Ако не сте се регистрирали при нас, просто изтрийте това писмо.",
    },
    "ro": {
        "subject": "Codul de confirmare: {code}",
        "heading": "Confirmă adresa de e-mail",
        "body": ("Introdu acest cod în pagina deschisă pentru a confirma adresa. Codul este "
                 "valabil 15 minute și poate fi folosit o singură dată."),
        "code": "Cod", "ignore": "Dacă nu te-ai înregistrat la noi, șterge acest e-mail.",
    },
    "en": {
        "subject": "Your confirmation code: {code}",
        "heading": "Confirm your email address",
        "body": ("Enter this code on the open page to confirm your address. The code is valid "
                 "for 15 minutes and works only once."),
        "code": "Code", "ignore": "If you did not register with us, just delete this email.",
    },
}


async def send_verify_code(to, code, name="", lang="en"):
    """The code goes in the SUBJECT too: on a phone it is readable from the notification."""
    t = VERIFY.get(lang) or VERIFY["en"]
    hello = f"{_esc(name)}, " if name else ""
    rows = (f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{hello}{t["body"]}</td></tr>'
            + f'<tr><td colspan="2" style="padding:8px 0 4px"><div style="font:700 30px/1.2 '
              f'-apple-system,Segoe UI,Roboto,Arial,sans-serif;letter-spacing:6px;color:#111">'
              f'{_esc(code)}</div></td></tr>')
    return await _send(to, t["subject"].format(code=code),
                       _shell(t["heading"], rows, t["ignore"]))


RESET = {
    "bg": {
        "subject": "Възстановяване на паролата",
        "heading": "Задайте нова парола",
        "body": ("Натиснете бутона по-долу, за да зададете нова парола. Връзката е валидна "
                 "{minutes} минути и може да се използва само веднъж."),
        "button": "Задай нова парола",
        "fallback": "Ако бутонът не работи, отворете тази връзка:",
        "ignore": ("Ако не сте поискали смяна на паролата, изтрийте това писмо — паролата "
                   "ви остава непроменена."),
    },
    "ro": {
        "subject": "Resetarea parolei",
        "heading": "Setează o parolă nouă",
        "body": ("Apasă butonul de mai jos pentru a seta o parolă nouă. Linkul este valabil "
                 "{minutes} minute și poate fi folosit o singură dată."),
        "button": "Setează parola nouă",
        "fallback": "Dacă butonul nu funcționează, deschide acest link:",
        "ignore": ("Dacă nu ai cerut schimbarea parolei, șterge acest e-mail — parola ta "
                   "rămâne neschimbată."),
    },
    "en": {
        "subject": "Reset your password",
        "heading": "Set a new password",
        "body": ("Press the button below to set a new password. The link is valid for "
                 "{minutes} minutes and works only once."),
        "button": "Set a new password",
        "fallback": "If the button does not work, open this link:",
        "ignore": ("If you did not ask to change your password, delete this email — your "
                   "password stays as it is."),
    },
}


async def send_password_reset(to, link, name="", lang="en", minutes=30):
    t = RESET.get(lang) or RESET["en"]
    hello = f"{_esc(name)}, " if name else ""
    safe = _esc(link)
    rows = (f'<tr><td colspan="2" style="padding:0 0 16px;color:#111">{hello}'
            f'{t["body"].format(minutes=minutes)}</td></tr>'
            f'<tr><td colspan="2" style="padding:0 0 16px"><a href="{safe}" '
            f'style="display:inline-block;background:#111;color:#fff;text-decoration:none;'
            f'padding:13px 22px;border-radius:10px;font:600 15px/1 -apple-system,Segoe UI,'
            f'Roboto,Arial,sans-serif">{t["button"]}</a></td></tr>'
            f'<tr><td colspan="2" style="padding:0 0 4px;color:#666;font-size:12px">'
            f'{t["fallback"]}<br><a href="{safe}" style="color:#666;word-break:break-all">'
            f'{safe}</a></td></tr>')
    return await _send(to, t["subject"], _shell(t["heading"], rows, t["ignore"]))



EXPIRING = {
    "bg": {
        "subject": "Блокираната сума пада утре",
        "heading": "Резервацията ви изтича утре",
        "body": ("Блокирането на сума по карта важи 7 дни. Ако не потвърдим автомобила до "
                 "срока по-долу, сумата се освобождава сама и автомобилът се връща в обявите. "
                 "Ако още го искате, просто ни отговорете на този имейл и ще го задържим."),
        "car": "Автомобил", "amount": "Блокирана сума", "until": "Изтича",
        "footer": "Не сме взели нищо от картата ви.",
    },
    "ro": {
        "subject": "Suma blocată expiră mâine",
        "heading": "Rezervarea ta expiră mâine",
        "body": ("Blocarea sumei pe card este valabilă 7 zile. Dacă nu confirmăm automobilul "
                 "până la termenul de mai jos, suma se eliberează singură, iar automobilul "
                 "revine în listă. Dacă îl mai dorești, răspunde la acest e-mail."),
        "car": "Automobil", "amount": "Sumă blocată", "until": "Expiră",
        "footer": "Nu am încasat nimic de pe cardul tău.",
    },
    "en": {
        "subject": "The hold on your card expires tomorrow",
        "heading": "Your reservation expires tomorrow",
        "body": ("A hold on a card lasts 7 days. If we do not confirm the car by the time "
                 "below, the amount is released by itself and the car goes back on the "
                 "market. If you still want it, just reply to this email and we will keep it."),
        "car": "Car", "amount": "Amount held", "until": "Expires",
        "footer": "We have taken nothing from your card.",
    },
}


async def send_deposit_expiring(to, car_title, amount_eur, expires_at, lang="en"):
    t = EXPIRING.get(lang) or EXPIRING["en"]
    when = ""
    if expires_at:
        when = (expires_at.strftime("%d.%m.%Y %H:%M UTC")
                if hasattr(expires_at, "strftime") else str(expires_at)[:16])
    rows = (f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{t["body"]}</td></tr>'
            + _row(t["car"], _esc(car_title))
            + _row(t["amount"], f"\u20ac{amount_eur:,.0f}")
            + _row(t["until"], when))
    return await _send(to, t["subject"], _shell(t["heading"], rows, t["footer"]))



async def send_deposit_captured(to, car_title, taken_eur, released_eur, lang="en"):
    t = CAPTURED.get(lang) or CAPTURED["en"]
    rows = (f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{t["body"]}</td></tr>'
            + _row(t["car"], _esc(car_title))
            + _row(t["taken"], f"\u20ac{taken_eur:,.0f}"))
    if released_eur:
        rows += _row(t["back"], f"\u20ac{released_eur:,.0f}")
    return await _send(to, t["subject"], _shell(t["heading"], rows, t["footer"]))


async def send_deposit_released(to, car_title, amount_eur, payment_status="released",
                                lang="en"):
    t = RELEASED.get(lang) or RELEASED["en"]
    body = t["expired"] if payment_status == "expired" else t["body"]
    rows = (f'<tr><td colspan="2" style="padding:0 0 12px;color:#111">{body}</td></tr>'
            + _row(t["car"], _esc(car_title))
            + _row(t["amount"], f"\u20ac{amount_eur:,.0f}"))
    return await _send(to, t["subject"], _shell(t["heading"], rows, t["footer"]))


# ── call-back requests ───────────────────────────────────────────────────────
# These used to borrow the enquiry letters, which meant the owner's inbox showed a call-back
# booked for Monday 09:00 as "New enquiry" — indistinguishable from a message with no deadline,
# and the buyer was thanked for an "enquiry" instead of being told when we would ring.
CALLBACK_ACK = {
    "bg": {
        "subject": "Ще ви се обадим",
        "heading": "Записахме обаждането",
        "body": "Ще ви потърсим на посочения телефон в избрания час.",
        "when": "Час на обаждане",
        "phone": "Телефон",
        "car": "Автомобил",
        "footer": "Ако часът вече не ви е удобен, отговорете на този имейл.",
    },
    "ro": {
        "subject": "Te vom suna",
        "heading": "Am notat apelul",
        "body": "Te vom suna la numărul indicat, la ora aleasă.",
        "when": "Ora apelului",
        "phone": "Telefon",
        "car": "Automobil",
        "footer": "Dacă ora nu îți mai convine, răspunde la acest email.",
    },
    "en": {
        "subject": "We will call you",
        "heading": "Your call is booked",
        "body": "We will ring the number you left at the time you chose.",
        "when": "Call time",
        "phone": "Phone",
        "car": "Car",
        "footer": "If the time no longer suits you, just reply to this email.",
    },
}


async def notify_new_callback(doc):
    to = os.environ.get("ADMIN_NOTIFY_EMAIL", "").strip()
    if not to:
        log.info("callback %s: no ADMIN_NOTIFY_EMAIL set, notification skipped", doc["_id"])
        return
    when = doc.get("when_label") or ""
    rows = "".join([
        _row("Call at", f'<b>{_esc(when)}</b> ({_esc(doc.get("timezone"))})'),
        _row("Phone", f'<a href="tel:{_esc(doc.get("phone"))}">{_esc(doc.get("phone"))}</a>'),
        _row("Name", _esc(doc.get("name"))),
        _row("Email", _esc(doc.get("email"))),
        _row("Car", _esc(doc.get("car_title"))),
        _row("Listing", _esc(doc.get("listing_id"))),
        _row("Language", _esc(doc.get("lang"))),
        _row("Message", _esc(doc.get("message")).replace("\n", "<br>")),
    ])
    html = _shell("Call-back request", rows,
                  "Sent automatically when a buyer asks to be called back outside working hours.")
    await _send(to, f"Call back {when}: {doc.get('phone') or 'a buyer'}", html)


async def acknowledge_callback(doc):
    to = (doc.get("email") or "").strip()
    if not to:
        return
    c = CALLBACK_ACK.get(doc.get("lang")) or CALLBACK_ACK["en"]
    rows = "".join([
        f'<tr><td colspan="2" style="padding:0 0 14px;color:#111;line-height:1.55">'
        f'{c["body"]}</td></tr>',
        _row(c["when"], f'<b>{_esc(doc.get("when_label"))}</b>'),
        _row(c["phone"], _esc(doc.get("phone"))),
        _row(c["car"], _esc(doc.get("car_title"))),
    ])
    await _send(to, c["subject"], _shell(c["heading"], rows, c["footer"]))


def send_callback_emails(doc):
    """Both letters, fire-and-forget, so the buyer's POST returns immediately."""
    async def _job():
        await notify_new_callback(doc)
        await acknowledge_callback(doc)

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass


def send_enquiry_emails(doc):
    """Fire-and-forget both messages so the buyer's POST returns immediately."""
    async def _job():
        await notify_new_enquiry(doc)
        await acknowledge_enquiry(doc)

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass
