"""Emergency notifications: when the site cannot do its job, every administrator hears it.

This exists because of a real outage. back1 lost its WireGuard tunnel, so the backend had no
route to Encar. Every car page then hung until Cloudflare gave up at 100s (524) and, with one
uvicorn worker, a handful of those requests took the whole site down. Nothing raised a hand —
the outage was found by hand, hours later, by loading a car page.

Every check has a severity and its own cadence:
  * CRITICAL — the site is broken or about to be, right now: egress, the Encar route (proxy
    and upstream), the public site itself, Mongo, disk, memory, a burst of 5xx. Push with
    require_interaction, a hard vibrate and a reminder every 30 minutes until it clears.
  * WARNING — money, data or the ability to alert is at risk but pages still serve: mail key,
    Stripe key, tracking key, TLS certificate, stale catalogue sync, stale FX, translation
    budget, nightly backup, no push device. One quiet push, reminder every 12 hours.

A check has to fail FAIL_STREAK times in a row before anything is sent — a single timeout is
weather, not an outage. Every incident is recorded in `db.incidents`; the admin Overview shows
the live state of every check, and `?run=1` probes everything on the spot.
"""
import asyncio
import logging
import os
import shutil
import socket
import ssl
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import mailer
import notify

log = logging.getLogger("watchdog")

_db = None

PROBE_EVERY = 60          # seconds between scheduler rounds; each check has its own cadence
FAIL_STREAK = 2           # consecutive failures before an alert
REMIND = {"critical": timedelta(minutes=30), "warning": timedelta(hours=12)}
EGRESS_URL = "https://1.1.1.1/cdn-cgi/trace"
ERRORS_WINDOW = 300       # seconds of 5xx history kept
ERRORS_LIMIT = 10         # 5xx in that window that counts as an outage
DISK_MIN_FREE_PCT = 10
DISK_MIN_FREE_GB = 2
MEM_MIN_AVAILABLE_PCT = 5
SYNC_STALE_H = 36
SYNC_STUCK_H = 6
FX_STALE_D = 3
CERT_MIN_DAYS = 10
BACKUP_STALE_H = 48

# check → (severity, seconds between probes, label, explanation for the alert)
CHECKS = {
    "egress": ("critical", 60, "Изход към интернет",
               "Бекендът не може да излезе в интернет — почти винаги WireGuard тунелът към "
               "front1 е паднал. Провери: sudo wg show и ./run.sh playbooks/deploy_nat.yml"),
    "proxy": ("critical", 300, "Encar прокси",
              "Резидентното прокси за Encar не отговаря или отказва данните за вход. "
              "Encar заявките ще падат; кешираните коли се отварят нормално."),
    "encar": ("critical", 60, "Encar upstream",
              "Има изход към интернет, но Encar не връща данни — тяхна повреда или блокиран "
              "IP. Кешираните коли се отварят нормално; новите не могат да се заредят."),
    "site": ("critical", 120, "Публичен сайт",
             "Сайтът не отговаря през публичния адрес (Cloudflare → front1 nginx → back1). "
             "Провери: systemctl status nginx на front1 и encar-backend на back1."),
    "prerender": ("critical", 300, "Сървърен рендер (SEO)",
                  "Публичните страници не се сървър-рендерират: Googlebot получава празна "
                  "React обвивка без H1, цена, canonical и JSON-LD. Или nginx не праща "
                  "страниците към /api/prerender (пусни deploy_nginx.yml), или бекендът не "
                  "намира построения index.html (FRONTEND_SHELL — пусни deploy_frontend.yml)."),
    "mongo": ("critical", 60, "База данни",
              "MongoDB не отговаря на ping. Сайтът не може да покаже нищо. Провери: "
              "sudo systemctl status mongod и дисковото място."),
    "disk": ("critical", 300, "Дисково място",
             "Дискът е почти пълен. MongoDB спира да пише при пълен диск, снимките на "
             "купените коли не могат да се архивират. Изчисти /opt/encar/releases и логовете."),
    "memory": ("critical", 60, "Памет",
               "Свободната памет е под 5%. OOM killer-ът ще убие MongoDB или бекенда. "
               "Провери: free -m, journalctl -k | grep -i oom"),
    "errors": ("critical", 60, "Грешки 5xx",
               "Бекендът връща сървърни грешки в серия. Провери: journalctl -u "
               "encar-backend -n 200"),
    "mail": ("warning", 1800, "Имейли (Resend)",
             "Resend отказва ключа. Никакъв имейл не тръгва — потвърждения, капаро, "
             "падащи цени, нито тези предупреждения."),
    "stripe": ("warning", 1800, "Stripe",
               "Stripe отказва секретния ключ. Никой не може да плати капаро."),
    "cargo": ("warning", 10800, "Проследяване (JSONCargo)",
              "Доставчикът на контейнерно проследяване отказва ключа или квотата е "
              "изчерпана. „Проследи колата ми“ ще показва последното известно състояние."),
    "cert": ("warning", 3600, "TLS сертификат",
             "Сертификатът на сайта изтича скоро. След изтичането браузърите ще спрат "
             "достъпа. Поднови го на front1."),
    "sync": ("warning", 600, "Синхронизация на каталога",
             "Каталогът не е обновяван навреме или синхронизацията е зациклила. Цените и "
             "наличностите остаряват. Провери: Админ → Каталог."),
    "fx": ("warning", 600, "Валутни курсове",
           "Курсът KRW/EUR не е обновяван дни наред. Цените в евро се смятат по стар курс."),
    "translate": ("warning", 300, "Преводи (AI)",
                  "Преводният слой е спрян — най-често изчерпан бюджет на ключа. Новите "
                  "обяви ще излизат на корейски, докато не се презареди."),
    "route": ("warning", 300, "Маршрут към Encar",
              "Encar трафикът беше превключен автоматично, защото основният маршрут спря да "
              "отговаря. Сайтът работи, но провери проксито (трафик, кредитиали) и върни "
              "маршрута от Админ → Здраве на системата."),
    "backup": ("warning", 3600, "Нощен бекъп",
               "Няма пресен mongodump. Провери cron-а encar-mongodump и мястото в "
               "/var/backups/encar."),
    "push": ("warning", 600, "Push устройства",
             "Нито един администратор няма включени push известия. Авариите ще стигат "
             "само по имейл — а имейлът също може да е паднал."),
}


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    """Mongo hands back naive datetimes (BSON stores UTC without a zone)."""
    if dt is None:
        return _now()
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Skip(Exception):
    """This check does not apply here (not configured, not this host). Not a failure."""


# ── 5xx counter, fed by the HTTP middleware ──────────────────────────────────
_errors = deque()


def note_status(code):
    if code >= 500:
        _errors.append(time.monotonic())


def _recent_errors():
    cutoff = time.monotonic() - ERRORS_WINDOW
    while _errors and _errors[0] < cutoff:
        _errors.popleft()
    return len(_errors)


# ── probes: return a short detail string on success, raise on failure ────────
async def _probe_mongo():
    await asyncio.wait_for(_db.command("ping"), timeout=8)
    return "ping ok"


async def _probe_egress():
    import httpx
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(EGRESS_URL)
    if r.status_code != 200:
        raise RuntimeError(f"{EGRESS_URL} answered {r.status_code}")
    ip = next((ln[3:] for ln in r.text.splitlines() if ln.startswith("ip=")), "?")
    return f"излиза като {ip}"


async def _probe_proxy():
    import httpx
    from encar import _scrub, proxy_configured, proxy_url, route_mode
    if route_mode() == "direct":
        raise Skip("маршрутът е зададен на директен — проксито не се използва")
    if not proxy_configured():
        raise Skip("ENCAR_PROXY_URL не е зададен — директен маршрут")
    if not proxy_url():
        raise Skip("проксито не се използва при този маршрут")
    try:
        async with httpx.AsyncClient(timeout=10, proxy=proxy_url()) as c:
            r = await c.get(EGRESS_URL)
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(_scrub(e)) from None
    if r.status_code != 200:
        raise RuntimeError(f"през проксито 1.1.1.1 отговори {r.status_code}")
    ip = next((ln[3:] for ln in r.text.splitlines() if ln.startswith("ip=")), "?")
    return f"резидентен изход {ip}"


async def _probe_encar():
    import encar as encar_mod
    # One row is enough to prove the door opens, and it is the same call the sync makes.
    got = await asyncio.wait_for(encar_mod.encar.search(offset=0, limit=1), timeout=25)
    if not got:
        raise RuntimeError("search returned nothing")
    return (f"route={encar_mod.route()} (режим {encar_mod.route_mode()}), "
            f"{got.get('Count', '?')} обяви upstream")


async def _probe_route():
    """Did the client have to move traffic itself? That is a warning, not an emergency."""
    import encar as encar_mod
    st = encar_mod.encar.status()
    fo = st.get("last_failover") or {}
    if fo and time.time() - float(fo.get("at") or 0) < 86400:
        raise RuntimeError(f"автоматично превключен {fo.get('from')} → {fo.get('to')}: "
                           f"{fo.get('reason') or '?'}")
    return f"{st['route']} (режим {st['mode']})"


def _site_url():
    return (os.environ.get("PUBLIC_SITE_URL") or "").strip().rstrip("/")


async def _probe_site():
    import httpx
    url = _site_url()
    if not url.startswith("https://"):
        raise Skip("PUBLIC_SITE_URL не е https адрес")
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(f"{url}/api/csrf")
    if r.status_code != 200:
        raise RuntimeError(f"{url} отговори {r.status_code}")
    return f"200 за {int((time.monotonic() - t0) * 1000)} ms"


async def _probe_disk():
    worst = None
    for path in {"/", os.environ.get("MEDIA_ROOT") or "/"}:
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        free_pct = u.free * 100 / u.total
        free_gb = u.free / 2**30
        if worst is None or free_pct < worst[1]:
            worst = (path, free_pct, free_gb)
        if free_pct < DISK_MIN_FREE_PCT or free_gb < DISK_MIN_FREE_GB:
            raise RuntimeError(f"{path}: свободни {free_gb:.1f} GB ({free_pct:.0f}%)")
    return f"{worst[0]}: свободни {worst[2]:.0f} GB ({worst[1]:.0f}%)" if worst else "?"


async def _probe_memory():
    try:
        with open("/proc/meminfo") as fh:
            info = {ln.split(":")[0]: int(ln.split()[1]) for ln in fh if ":" in ln}
    except (OSError, ValueError, IndexError):
        raise Skip("няма /proc/meminfo") from None
    total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
    if not total:
        raise Skip("MemTotal липсва")
    pct = avail * 100 / total
    if pct < MEM_MIN_AVAILABLE_PCT:
        raise RuntimeError(f"свободни {avail // 1024} MB от {total // 1024} MB ({pct:.0f}%)")
    return f"свободни {avail // 1024} MB ({pct:.0f}%)"


async def _probe_errors():
    n = _recent_errors()
    if n >= ERRORS_LIMIT:
        raise RuntimeError(f"{n} сървърни грешки за {ERRORS_WINDOW // 60} минути")
    return f"{n} за последните {ERRORS_WINDOW // 60} мин"


async def _probe_mail():
    if not mailer.configured():
        raise RuntimeError("RESEND_API_KEY is not set")
    if not await mailer.key_ok():
        raise RuntimeError("Resend rejected the API key")
    return "ключът е валиден"


async def _probe_stripe():
    import stripe
    if not (os.environ.get("STRIPE_SECRET_KEY") or "").strip():
        raise Skip("STRIPE_SECRET_KEY не е зададен")
    try:
        bal = await asyncio.wait_for(asyncio.to_thread(stripe.Balance.retrieve), timeout=20)
    except stripe.error.AuthenticationError as e:
        raise RuntimeError(f"Stripe отказа ключа: {str(e)[:120]}") from None
    live = bool(getattr(bal, "livemode", False))
    return "ключът е валиден (" + ("live" if live else "test") + ")"


async def _probe_cargo():
    import jsoncargo
    if not jsoncargo.configured():
        raise Skip("JSONCARGO_API_KEY не е зададен")
    got = await asyncio.wait_for(jsoncargo.stats(_db, refresh=True), timeout=25)
    if not got:
        raise RuntimeError("доставчикът не върна статистика за ключа")
    left = got.get("requests_remaining") or got.get("remaining")
    return f"остават {left} заявки" if left is not None else "ключът е валиден"


def _cert_days_left(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    return (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400


async def _probe_cert():
    host = urlsplit(_site_url()).hostname
    if not host or not _site_url().startswith("https://"):
        raise Skip("PUBLIC_SITE_URL не е https адрес")
    days = await asyncio.wait_for(asyncio.to_thread(_cert_days_left, host), timeout=20)
    if days < CERT_MIN_DAYS:
        raise RuntimeError(f"{host}: изтича след {days:.0f} дни")
    return f"{host}: валиден още {days:.0f} дни"


async def _probe_sync():
    import syncjob
    state = await _db.sync_state.find_one({"_id": "catalogue"}) or {}
    sched = await syncjob.get_schedule(_db)
    status = state.get("status") or "never"
    if status == "error":
        raise RuntimeError(f"последният sync завърши с грешка: {state.get('error', '')[:120]}")
    if status == "running":
        started = _aware(state.get("started_at"))
        if _now() - started > timedelta(hours=SYNC_STUCK_H):
            raise RuntimeError(f"sync върви от {started:%d.%m %H:%M} UTC — зациклил")
        return f"върви, {state.get('pages_done', 0)}/{state.get('pages_total', 0)} страници"
    if not sched.get("enabled"):
        return "разписанието е изключено"
    finished = state.get("finished_at")
    if not finished:
        # "never finished" on its own tells the owner nothing. Whatever the state document
        # does hold — when it started, how far it got, what upstream last said — is the
        # difference between a diagnosable alarm and a shrug.
        started = state.get("started_at")
        bits = [f"статус {status}"]
        if started:
            bits.append(f"започнал {_aware(started):%d.%m %H:%M} UTC")
        if state.get("pages_total") or state.get("pages_done"):
            bits.append(f"стигнал до {state.get('pages_done', 0)}/"
                        f"{state.get('pages_total', 0)} страници")
        if state.get("error"):
            bits.append(f"последна грешка: {str(state['error'])[:120]}")
        raise RuntimeError("никога не е завършвал успешно — " + ", ".join(bits))
    age = _now() - _aware(finished)
    if age > timedelta(hours=SYNC_STALE_H):
        raise RuntimeError(f"последният успешен sync е преди {age.days}д {age.seconds // 3600}ч")
    return f"последен успешен преди {int(age.total_seconds() // 3600)} ч"


async def _probe_fx():
    doc = await _db.fx.find_one({"_id": "rates"})
    if not doc or not doc.get("fetched_at"):
        raise RuntimeError("няма записан курс — цените са по резервна стойност")
    age = _now() - _aware(doc["fetched_at"])
    if age > timedelta(days=FX_STALE_D):
        raise RuntimeError(f"курсът е от преди {age.days} дни ({doc.get('source', '?')})")
    return f"KRW/EUR {doc.get('fx_krw_eur', '?')}, обновен преди {int(age.total_seconds() // 3600)} ч"


async def _probe_translate():
    from translate import breaker_status
    b = breaker_status()
    if b.get("open"):
        raise RuntimeError(f"прекъсвачът е отворен: {b.get('reason') or '?'} "
                           f"(отново след {b.get('retry_in_s', 0)} s)")
    return f"работи, {b.get('trips', 0)} прекъсвания досега"


async def _probe_backup():
    folder = (os.environ.get("BACKUP_DIR") or "/var/backups/encar").rstrip("/")
    if not os.path.isdir(folder):
        raise Skip(f"{folder} не съществува на този хост")
    newest = 0.0
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.name.endswith(".archive.gz"):
                    newest = max(newest, entry.stat().st_mtime)
    except PermissionError:
        # The dumps are almost certainly there; this process simply cannot look. Say so,
        # instead of reporting a raw errno as if the backup had failed.
        raise RuntimeError(
            f"{folder} не е четима от бекенда (www-data) — бекъпът вероятно работи, но "
            f"проверката не го вижда. Оправя се с: chown -R www-data:www-data {folder}")
    if not newest:
        raise RuntimeError(f"в {folder} няма нито един архив")
    age_h = (time.time() - newest) / 3600
    if age_h > BACKUP_STALE_H:
        raise RuntimeError(f"последният архив е от преди {age_h:.0f} ч")
    return f"последен архив преди {age_h:.0f} ч"


async def _probe_push():
    n = await notify.admin_devices()
    if not n:
        raise RuntimeError("0 абонирани устройства")
    return f"{n} устройства"


async def _probe_prerender():
    """Does a real page come back server-rendered, the way Googlebot must see it?

    The check is against the PUBLIC address, so it fails for either reason that matters:
    nginx not routing pages to /api/prerender, or the backend having no shell to render
    into. It looks for the marker the prerendered markup always carries plus a canonical -
    a plain SPA shell has neither.
    """
    import httpx
    url = _site_url()
    if not url.startswith("https://"):
        raise Skip("PUBLIC_SITE_URL не е https адрес")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(f"{url}/bg", headers={"User-Agent": "EncarWatchdog/1.0"})
    if r.status_code != 200:
        raise RuntimeError(f"{url}/bg отговори {r.status_code}")
    html = r.text
    missing = [name for name, needle in (("H1", "<h1"), ("canonical", 'rel="canonical"'),
                                         ("JSON-LD", "application/ld+json"),
                                         ("markup", '<main class="pr"'))
               if needle not in html]
    if missing:
        raise RuntimeError("страницата се връща без " + ", ".join(missing))
    return f"{len(html) // 1024} KB рендерирани"


PROBES = {
    "mongo": _probe_mongo, "egress": _probe_egress, "proxy": _probe_proxy,
    "encar": _probe_encar, "site": _probe_site, "disk": _probe_disk,
    "route": _probe_route,
    "prerender": _probe_prerender,
    "memory": _probe_memory, "errors": _probe_errors, "mail": _probe_mail,
    "stripe": _probe_stripe, "cargo": _probe_cargo, "cert": _probe_cert,
    "sync": _probe_sync, "fx": _probe_fx, "translate": _probe_translate,
    "backup": _probe_backup, "push": _probe_push,
}
# A failure upstream of another check is one outage, not two.
DEPENDS_ON = {"encar": ("egress", "proxy"), "proxy": ("egress",), "site": ("egress",),
              "prerender": ("egress", "site")}


def severity(check):
    return CHECKS.get(check, ("critical",))[0]


# ── alerting ─────────────────────────────────────────────────────────────────
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
    sev, _, label, explain = CHECKS.get(check, ("critical", 0, check, ""))
    critical = sev == "critical"
    if resolved:
        title = f"Отново работи: {label}"
        body = "Проверката минава. Проблемът е приключен."
    else:
        title = ("АВАРИЯ: " if critical else "Внимание: ") + label
        body = f"{explain}\n\nПричина: {reason}"
        if reminder:
            title = f"[все още] {title}"

    # Push first and push loud: it is the only channel that reaches a phone in seconds and
    # it does not depend on Resend — which is itself one of the things that can break. No
    # event name is passed on purpose, so an emergency cannot be muted by preferences.
    # `tag` per check means a reminder REPLACES the previous card instead of stacking them.
    sent = 0
    try:
        sent = await notify.push_to_admins(
            title, body[:300], url="/bg/admin?tab=overview",
            tag=f"incident-{check}", renotify=True,
            require_interaction=critical and not resolved,
            vibrate=([300, 120, 300, 120, 300] if critical else [200, 100, 200])
            if not resolved else [200],
            ttl=86400, urgency="high" if critical else "normal")
    except Exception as e:                                  # noqa: BLE001
        log.warning("incident push failed: %s", str(e)[:160])

    # Email is the backstop: only when push reached nobody, and pointless when mail itself
    # is the fault.
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
        await _db.incidents.insert_one({"check": check, "severity": severity(check),
                                        "opened_at": _now(), "closed_at": None,
                                        "reason": reason, "notified_at": _now(),
                                        "reminders": 0})
        log.error("INCIDENT %s [%s]: %s", check, severity(check), reason)
        await _alert(check, reason)
        return
    last = _aware(doc.get("notified_at") or doc["opened_at"])
    if _now() - last >= REMIND[severity(check)]:
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


# ── state for the admin screen ───────────────────────────────────────────────
_streak = {}
_last = {}       # check → {"status", "detail", "at", "latency_ms"}
_due = {}        # check → monotonic time of the next probe


def _record(check, status, detail, t0):
    _last[check] = {"status": status, "detail": str(detail)[:200],
                    "at": _now(), "latency_ms": int((time.monotonic() - t0) * 1000)}


async def probe_one(check):
    """Run one check now and record the outcome. Returns the new status."""
    if any(_streak.get(dep, 0) >= FAIL_STREAK for dep in DEPENDS_ON.get(check, ())):
        _record(check, "skip", "пропуснато — зависима проверка вече е паднала",
                time.monotonic())
        return "skip"
    t0 = time.monotonic()
    try:
        detail = await PROBES[check]()
    except Skip as e:
        _streak[check] = 0
        _record(check, "skip", e, t0)
        return "skip"
    except Exception as e:                                  # noqa: BLE001
        _streak[check] = _streak.get(check, 0) + 1
        reason = str(e)[:200] or e.__class__.__name__
        _record(check, "fail", reason, t0)
        log.warning("watchdog %s failed (%s in a row): %s", check, _streak[check], reason)
        if _streak[check] >= FAIL_STREAK:
            try:
                await _open(check, reason)
            except Exception as inner:                      # noqa: BLE001
                log.warning("could not raise %s incident: %s", check, str(inner)[:160])
        return "fail"
    # Success. Always ask whether an incident is open — the answer lives in Mongo, not in
    # this process, so an incident raised before a restart can still be closed.
    _streak[check] = 0
    _record(check, "ok", detail or "ok", t0)
    try:
        await _close(check)
    except Exception as e:                                  # noqa: BLE001
        log.warning("could not close %s incident: %s", check, str(e)[:160])
    return "ok"


async def round_once(force=False):
    """One pass: every check that is due (or all of them when forced). Never raises."""
    now = time.monotonic()
    for check in PROBES:
        if not force and _due.get(check, 0) > now:
            continue
        _due[check] = now + CHECKS[check][1]
        try:
            await probe_one(check)
        except Exception as e:                              # noqa: BLE001
            log.warning("watchdog %s crashed: %s", check, str(e)[:200])


async def health(run=False):
    """Current state of every check, for the admin screen."""
    if run:
        await round_once(force=True)
    open_now = [d async for d in _db.incidents.find({"closed_at": None})]
    recent = await _db.incidents.find({}).sort("opened_at", -1).limit(30).to_list(30)
    checks = []
    for check, (sev, every, label, _) in CHECKS.items():
        last = _last.get(check) or {}
        checks.append({"check": check, "label": label, "severity": sev, "every_s": every,
                       "status": last.get("status", "unknown"),
                       "detail": last.get("detail", "още не е проверявано"),
                       "at": last["at"].isoformat() if last.get("at") else None,
                       "latency_ms": last.get("latency_ms"),
                       "streak": _streak.get(check, 0)})
    return {
        "checks": checks,
        "labels": {c: v[2] for c, v in CHECKS.items()},
        "push_devices": await notify.admin_devices(),
        "open": [{"check": d["check"], "severity": d.get("severity", severity(d["check"])),
                  "since": _aware(d["opened_at"]).isoformat(),
                  "reason": d.get("reason") or "",
                  "reminders": d.get("reminders", 0)} for d in open_now],
        "recent": [{"check": d["check"], "opened_at": _aware(d["opened_at"]).isoformat(),
                    "closed_at": _aware(d["closed_at"]).isoformat()
                    if d.get("closed_at") else None,
                    "reason": d.get("reason") or ""} for d in recent],
    }


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
