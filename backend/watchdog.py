"""Emergency notifications: when the site cannot do its job, every administrator hears it.

This exists because of a real outage. back1 lost its WireGuard tunnel, so the backend had no
route to Encar. Every car page then hung until Cloudflare gave up at 100s (524) and, with one
uvicorn worker, a handful of those requests took the whole site down. Nothing raised a hand —
the outage was found by hand, hours later, by loading a car page.

What is watched, all of it invisible from outside the machine:
  * `egress`  — can this host reach the public internet at all (the tunnel / NAT route);
  * `encar`   — is Encar itself answering (their 5xx wall, a rate-limit block);
  * `mongo`   — is the database answering;
  * `mail`    — is the Resend key still valid, because a dead key silences every other alert.

A check has to fail FAIL_STREAK times in a row before anything is sent — a single timeout is
weather, not an outage. The alert then goes to every admin account over web push AND email,
with a reminder every REMIND_MINUTES while it stays broken and a short all-clear when it
recovers. Everything is recorded in `db.incidents` so the admin screen can show what happened
while nobody was watching.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import mailer
import notify

log = logging.getLogger("watchdog")

_db = None

PROBE_EVERY = 60          # seconds between rounds
MAIL_EVERY = 1800         # the Resend key is checked less often; it fails slowly
FAIL_STREAK = 2           # consecutive failures before an alert (≈2 minutes)
REMIND_MINUTES = 30       # reminder cadence while an incident is open
EGRESS_URL = "https://1.1.1.1/cdn-cgi/trace"

TITLES = {
    "egress": "Сървърът няма изход към интернет",
    "encar": "Encar не отговаря",
    "mongo": "Базата данни не отговаря",
    "mail": "Имейлите не работят",
}
EXPLAIN = {
    "egress": ("Бекендът не може да излезе в интернет — почти винаги WireGuard тунелът към "
               "front1 е паднал. Всяка страница на обява ще виси, докато Cloudflare върне "
               "524. Провери: sudo wg show и ansible-playbook playbooks/deploy_nat.yml"),
    "encar": ("Има изход към интернет, но Encar не връща данни — тяхна повреда или блокиран "
              "IP. Кешираните коли се отварят нормално; новите не могат да се заредят."),
    "mongo": ("MongoDB не отговаря на ping. Сайтът не може да покаже нищо. Провери: "
              "sudo systemctl status mongod и дисковото място."),
    "mail": ("Resend отказва ключа. Никакъв имейл не тръгва — потвърждения, капарa, "
             "падащи цени, нито тези предупреждения."),
}


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    """Mongo hands back naive datetimes (BSON stores UTC without a zone).

    Subtracting one of those from an aware `_now()` raises, which is how the reminder
    cadence and the all-clear notice both broke the first time a probe recovered. Anything
    read out of a document goes through here before arithmetic.
    """
    if dt is None:
        return _now()
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _probe_mongo():
    await asyncio.wait_for(_db.command("ping"), timeout=8)


async def _probe_egress():
    import httpx
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(EGRESS_URL)
    if r.status_code != 200:
        raise RuntimeError(f"{EGRESS_URL} answered {r.status_code}")


async def _probe_encar():
    import encar as encar_mod
    # One row is enough to prove the door opens, and it is the same call the sync makes.
    got = await asyncio.wait_for(encar_mod.encar.search(offset=0, limit=1), timeout=25)
    if not got:
        raise RuntimeError("search returned nothing")


async def _probe_mail():
    if not mailer.configured():
        raise RuntimeError("RESEND_API_KEY is not set")
    if not await mailer.key_ok():
        raise RuntimeError("Resend rejected the API key")


PROBES = {"mongo": _probe_mongo, "egress": _probe_egress,
          "encar": _probe_encar, "mail": _probe_mail}


async def _admin_emails():
    """Every admin account, plus the addresses configured for operational mail."""
    out = []
    async for u in _db.users.find({"is_admin": True}, {"email": 1}):
        if u.get("email"):
            out.append(u["email"])
    for key in ("ADMIN_NOTIFY_EMAIL", "OWNER_EMAIL"):
        value = (os.environ.get(key) or "").strip()
        if value:
            out.append(value)
    return sorted({e.lower() for e in out})


async def _alert(check, reason, *, reminder=False, resolved=False):
    """One announcement to every administrator, on both channels."""
    if resolved:
        title = f"Отново работи: {TITLES.get(check, check)}"
        body = "Проверката минава. Проблемът е приключен."
    else:
        title = TITLES.get(check, check)
        body = f"{EXPLAIN.get(check, '')}\n\nПричина: {reason}"
        if reminder:
            title = f"[все още] {title}"

    # Push first and push loud: it is the only channel that reaches a phone in seconds, it
    # does not depend on Resend — which is itself one of the things that can break — and the
    # owner asked for these to be push notifications. No event name is passed on purpose, so
    # an emergency cannot be muted by notification preferences.
    #
    # `tag` per check means a reminder REPLACES the previous card instead of stacking twelve
    # of them, `renotify` makes that replacement buzz anyway, `require_interaction` keeps it
    # on screen until someone touches it, and a 24h ttl means a phone that was off overnight
    # still gets it when it wakes.
    sent = 0
    try:
        sent = await notify.push_to_admins(
            title, body[:300], url="/bg/admin?tab=overview",
            tag=f"incident-{check}", renotify=True, require_interaction=not resolved,
            vibrate=[300, 120, 300, 120, 300] if not resolved else [200],
            ttl=86400, urgency="high")
    except Exception as e:                                  # noqa: BLE001
        log.warning("incident push failed: %s", str(e)[:160])

    # Email is the backstop, not the channel: it only goes out when push reached nobody
    # (no device subscribed yet, or every subscription expired). Pointless when mail itself
    # is the thing that is broken.
    if sent or check == "mail":
        if not sent:
            log.error("incident %s: no admin device subscribed and mail is the fault — "
                      "nobody was notified", check)
        return
    log.warning("incident %s: push reached no admin device, falling back to email", check)
    for to in await _admin_emails():
        try:
            await mailer.send_incident_alert(to, check, title, body)
        except Exception as e:                              # noqa: BLE001
            log.warning("incident email to %s failed: %s", to, str(e)[:160])


async def _open(check, reason):
    doc = await _db.incidents.find_one({"check": check, "closed_at": None})
    if not doc:
        await _db.incidents.insert_one({"check": check, "opened_at": _now(),
                                        "closed_at": None, "reason": reason,
                                        "notified_at": _now(), "reminders": 0})
        log.error("INCIDENT %s: %s", check, reason)
        await _alert(check, reason)
        return
    last = _aware(doc.get("notified_at") or doc["opened_at"])
    if _now() - last >= timedelta(minutes=REMIND_MINUTES):
        await _db.incidents.update_one({"_id": doc["_id"]},
                                       {"$set": {"notified_at": _now(), "reason": reason},
                                        "$inc": {"reminders": 1}})
        await _alert(check, reason, reminder=True)


async def _close(check):
    doc = await _db.incidents.find_one({"check": check, "closed_at": None})
    if not doc:
        return
    await _db.incidents.update_one({"_id": doc["_id"]}, {"$set": {"closed_at": _now()}})
    log.warning("incident %s resolved after %s", check, _now() - _aware(doc["opened_at"]))
    await _alert(check, "", resolved=True)


async def health(run=False):
    """Current state of every check, for the admin screen."""
    if run:
        await round_once()
    open_now = [d async for d in _db.incidents.find({"closed_at": None})]
    recent = await _db.incidents.find({}).sort("opened_at", -1).limit(30).to_list(30)
    return {
        "checks": sorted(PROBES),
        "push_devices": await notify.admin_devices(),
        "open": [{"check": d["check"], "since": _aware(d["opened_at"]).isoformat(),
                  "reason": d.get("reason") or "",
                  "reminders": d.get("reminders", 0)} for d in open_now],
        "recent": [{"check": d["check"], "opened_at": _aware(d["opened_at"]).isoformat(),
                    "closed_at": _aware(d["closed_at"]).isoformat()
                    if d.get("closed_at") else None,
                    "reason": d.get("reason") or ""} for d in recent],
    }


_streak = {}
_last_mail_probe = 0.0


async def round_once():
    """One pass over every probe. Never raises: a watchdog that dies is worse than none."""
    global _last_mail_probe
    for check, probe in PROBES.items():
        if check == "mail":
            now = asyncio.get_running_loop().time()
            if now - _last_mail_probe < MAIL_EVERY:
                continue
            _last_mail_probe = now
        # No point telling anyone Encar is down when the host cannot reach anything at all;
        # that is one outage, not two, and it already has an alert of its own.
        if check == "encar" and _streak.get("egress", 0) >= FAIL_STREAK:
            continue
        try:
            await probe()
        except Exception as e:                              # noqa: BLE001
            _streak[check] = _streak.get(check, 0) + 1
            reason = str(e)[:200] or e.__class__.__name__
            log.warning("watchdog %s failed (%s in a row): %s",
                        check, _streak[check], reason)
            if _streak[check] >= FAIL_STREAK:
                try:
                    await _open(check, reason)
                except Exception as inner:                  # noqa: BLE001
                    log.warning("could not raise %s incident: %s", check, str(inner)[:160])
            continue
        # Success. Reset the streak and always ask whether an incident is open — the answer
        # lives in Mongo, not in this process. Relying on the in-memory streak meant that an
        # incident raised before a restart could never be closed, and the panel would still
        # be screaming about an outage that ended hours ago. One indexed lookup per check
        # per minute is a fair price for that.
        _streak[check] = 0
        try:
            await _close(check)
        except Exception as e:                              # noqa: BLE001
            log.warning("could not close %s incident: %s", check, str(e)[:160])


async def scheduler():
    # A minute of grace: probing while the process is still opening its connections would
    # report an outage that does not exist.
    await asyncio.sleep(45)
    while True:
        try:
            await round_once()
        except Exception as e:                              # noqa: BLE001
            log.warning("watchdog round failed: %s", str(e)[:200])
        await asyncio.sleep(PROBE_EVERY)
