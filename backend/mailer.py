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
def _shell(heading, rows_html, footer):
    return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f7;padding:24px 0;font-family:Helvetica,Arial,sans-serif">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e5e7;border-radius:14px;overflow:hidden">
<tr><td style="padding:20px 24px;border-bottom:1px solid #e5e5e7">
<span style="font-size:18px;font-weight:700;color:#d0021b">Encar</span>
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


def send_enquiry_emails(doc):
    """Fire-and-forget both messages so the buyer's POST returns immediately."""
    async def _job():
        await notify_new_enquiry(doc)
        await acknowledge_enquiry(doc)

    try:
        asyncio.get_running_loop().create_task(_job())
    except RuntimeError:
        pass
