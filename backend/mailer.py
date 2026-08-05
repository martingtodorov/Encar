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

log = logging.getLogger("mailer")

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
    """
    t = DROP.get(lang) or DROP["en"]
    body = "".join(
        _row(_esc(r["title"]), f'€{r["now_eur"]:,.0f} · {t["cut"]} {r["cut_pct"]}%')
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


def send_enquiry_emails(doc):
    """Fire-and-forget both messages so the buyer's POST returns immediately."""
    async def _job():
        await notify_new_enquiry(doc)
        await acknowledge_enquiry(doc)

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass
