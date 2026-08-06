"""The consultancy contract a buyer signs once their deposit has cleared.

The template is the owner's own document, kept in `settings` so it can be edited from the
admin panel without a deploy, in each of the three languages. Everything the ad and the
account already know is filled in; what only the buyer can know — their ID card, their
address — is theirs to type.

Nothing is invented: a placeholder with no value renders as a dotted blank exactly as it does
on the paper original, so an unfinished contract looks unfinished instead of looking wrong.
"""
import io
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import auth

log = logging.getLogger("contracts")
router = APIRouter()
_db = None

DOC_ID = "contract_template"
LANGS = ("bg", "ro", "en")
BLANK = "\u2026" * 24                       # the dotted line of the paper original

# What the buyer fills in. `required` decides whether the contract counts as complete.
BUYER_FIELDS = ("buyer_name", "buyer_egn", "buyer_id_no", "buyer_id_date",
                "buyer_id_issuer", "buyer_address", "buyer_phone")


def set_db(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


# ── the seller's own details, editable in the admin panel ─────────────────────
DEFAULT_SELLER = {
    "name": "„АТЛАНТИК ДРАЙВ“ ЕООД",
    "eik": "208414795",
    "address": "гр. София, р-н Триадица, ул. Григор Чешмеджиев 29",
    "email": "atlanticdrivebg@gmail.com",
    "manager": "Иван Лещарски",
    "city": "София",
}

# The owner pasted the opening of their paper contract; the clauses that follow are theirs to
# paste into the admin editor, which is why the body ends where their text ended.
_BG = """ДОГОВОР ЗА КОНСУЛТАНТСКИ УСЛУГИ ЗА ИЗБОР, ДОСТАВКА И ПОКУПКО-ПРОДАЖБА НА МОТОРНИ ПРЕВОЗНИ СРЕДСТВА

№ {{contract_no}}

Днес, {{date}} г., в гр. {{city}}, между:

{{seller_name}}, ЕИК: {{seller_eik}}, със седалище и адрес на управление: {{seller_address}}, ел. поща: {{seller_email}}, представлявано от {{seller_manager}}, в качеството му на Управител, наричано по-долу за кратко ИЗПЪЛНИТЕЛ,

и

{{buyer_name}}, с ЕГН {{buyer_egn}}, притежаващ лична карта № {{buyer_id_no}}, издадена на {{buyer_id_date}} от {{buyer_id_issuer}}, с постоянен адрес {{buyer_address}}, телефон {{buyer_phone}}, ел. поща {{buyer_email}}, наричан/-о по-долу за кратко ВЪЗЛОЖИТЕЛ,

наричани заедно СТРАНИТЕ, а всеки поотделно СТРАНА, се сключи настоящият договор за следното:

ПРЕДМЕТ НА ДОГОВОРА

Чл. 1. ВЪЗЛОЖИТЕЛЯТ с подписването на настоящия договор декларира и заявява своето желание да получи консултантски услуги от ИЗПЪЛНИТЕЛЯ относно закупуването на употребявано и/или повредено превозно средство (наричано по-долу Стоката) от автомобилни търгове и площадки в Южна Корея.

Чл. 2. Стоката, предмет на настоящия договор, е:
    Автомобил: {{car_title}}
    Рама (VIN): {{vin}}
    Регистрационен номер (Корея): {{plate}}
    Първа регистрация: {{year}}
    Пробег: {{mileage}}
    Крайна цена: {{car_price}}

Чл. 3. ВЪЗЛОЖИТЕЛЯТ е заплатил депозит в размер на {{deposit}}, с който ИЗПЪЛНИТЕЛЯТ закупува Стоката за негова сметка. Остатъкът в размер на {{balance}} се заплаща по банков път. След заплащането му депозитът се връща на ВЪЗЛОЖИТЕЛЯ, а ИЗПЪЛНИТЕЛЯТ задържа възнаграждение в размер на {{commission}}, което е включено в крайната цена.

[Тук се допълват останалите клаузи на договора — редактира се от административния панел.]

ЗА ИЗПЪЛНИТЕЛЯ: ............................        ЗА ВЪЗЛОЖИТЕЛЯ: ............................
"""

_RO = """CONTRACT DE SERVICII DE CONSULTANȚĂ PENTRU SELECȚIA, LIVRAREA ȘI VÂNZAREA-CUMPĂRAREA DE AUTOVEHICULE

Nr. {{contract_no}}

Astăzi, {{date}}, în {{city}}, între:

{{seller_name}}, cod fiscal: {{seller_eik}}, cu sediul: {{seller_address}}, e-mail: {{seller_email}}, reprezentată de {{seller_manager}}, în calitate de Administrator, denumită în continuare PRESTATOR,

și

{{buyer_name}}, CNP {{buyer_egn}}, posesor al cărții de identitate nr. {{buyer_id_no}}, eliberată la {{buyer_id_date}} de {{buyer_id_issuer}}, cu domiciliul {{buyer_address}}, telefon {{buyer_phone}}, e-mail {{buyer_email}}, denumit în continuare BENEFICIAR,

denumite împreună PĂRȚILE, s-a încheiat prezentul contract:

OBIECTUL CONTRACTULUI

Art. 1. BENEFICIARUL declară că dorește serviciile de consultanță ale PRESTATORULUI pentru achiziția unui autovehicul rulat și/sau avariat (denumit în continuare Bunul) de la licitații și platforme din Coreea de Sud.

Art. 2. Bunul care face obiectul contractului:
    Autovehicul: {{car_title}}
    Serie de șasiu (VIN): {{vin}}
    Număr de înmatriculare (Coreea): {{plate}}
    Prima înmatriculare: {{year}}
    Rulaj: {{mileage}}
    Preț final: {{car_price}}

Art. 3. BENEFICIARUL a plătit un avans de {{deposit}}, cu care PRESTATORUL cumpără Bunul pe seama sa. Diferența de {{balance}} se achită prin transfer bancar. După achitarea acesteia, avansul se restituie BENEFICIARULUI, iar PRESTATORUL reține un comision de {{commission}}, inclus în prețul final.

[Restul clauzelor se completează din panoul de administrare.]

PRESTATOR: ............................        BENEFICIAR: ............................
"""

_EN = """CONSULTANCY AGREEMENT FOR THE SELECTION, DELIVERY AND PURCHASE OF MOTOR VEHICLES

No. {{contract_no}}

Today, {{date}}, in {{city}}, between:

{{seller_name}}, company number {{seller_eik}}, registered address: {{seller_address}}, e-mail: {{seller_email}}, represented by {{seller_manager}} as Manager, hereinafter the AGENT,

and

{{buyer_name}}, national ID {{buyer_egn}}, holder of identity card no. {{buyer_id_no}}, issued on {{buyer_id_date}} by {{buyer_id_issuer}}, permanent address {{buyer_address}}, telephone {{buyer_phone}}, e-mail {{buyer_email}}, hereinafter the CLIENT,

together the PARTIES, have agreed as follows:

SUBJECT OF THE AGREEMENT

Art. 1. The CLIENT declares that they wish to receive the AGENT's consultancy services for the purchase of a used and/or damaged vehicle (the Goods) from auctions and dealers in South Korea.

Art. 2. The Goods under this agreement are:
    Vehicle: {{car_title}}
    Chassis (VIN): {{vin}}
    Registration number (Korea): {{plate}}
    First registration: {{year}}
    Mileage: {{mileage}}
    Final price: {{car_price}}

Art. 3. The CLIENT has paid a deposit of {{deposit}}, with which the AGENT buys the Goods on their behalf. The balance of {{balance}} is paid by bank transfer. Once it is paid the deposit is returned to the CLIENT and the AGENT keeps a fee of {{commission}}, which is included in the final price.

[The remaining clauses are edited from the admin panel.]

AGENT: ............................        CLIENT: ............................
"""

DEFAULT_BODIES = {"bg": _BG, "ro": _RO, "en": _EN}


async def _doc():
    doc = await _db.settings.find_one({"_id": DOC_ID})
    if not doc:
        doc = {"_id": DOC_ID, "seller": dict(DEFAULT_SELLER),
               "bodies": dict(DEFAULT_BODIES), "updated_at": _now()}
        await _db.settings.insert_one(doc)
    return doc


# ── rendering ────────────────────────────────────────────────────────────────
_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _money(v):
    return f"{round(v or 0):,}".replace(",", " ") + " \u20ac"


def _fill(body, values):
    """A missing value becomes the dotted blank of the paper form, never an empty gap."""
    return _TOKEN.sub(lambda m: str(values.get(m.group(1)) or BLANK), body)


async def _plate(car_id):
    """Encar publishes the Korean registration number, never a VIN — so the contract carries
    the plate, and the VIN stays a blank until the car is in hand and someone types it in."""
    for coll in ("purchased_listings", "car_details"):
        doc = await _db[coll].find_one({"_id": car_id}, {"detail.vehicleNo": 1})
        plate = ((doc or {}).get("detail") or {}).get("vehicleNo")
        if plate:
            return plate
    return ""


async def _values(record, car, user, seller, lang):
    price = record.get("car_price_eur") or 0
    deposit = record.get("amount") or 0
    ym = car.get("year_month") or 0
    return {
        # Readable and stable: the ad number and the day it was paid. A Stripe session id is
        # 60-odd characters of noise and means nothing to either party.
        "contract_no": f"{record['car_id']}/{(record.get('created_at') or _now()):%d%m%Y}",
        "date": (record.get("created_at") or _now()).strftime("%d.%m.%Y"),
        "city": seller.get("city") or "",
        "seller_name": seller.get("name"),
        "seller_eik": seller.get("eik"),
        "seller_address": seller.get("address"),
        "seller_email": seller.get("email"),
        "seller_manager": seller.get("manager"),
        "buyer_email": user.get("email") or "",
        "car_title": record.get("car_title") or "",
        # Filled in by an operator on the deposit record once the car is inspected; blank
        # until then, because nobody upstream knows it.
        "vin": record.get("vin") or "",
        "plate": await _plate(record["car_id"]),
        "year": f"{ym % 100:02d}/{ym // 100}" if ym else "",
        "mileage": f"{car.get('mileage'):,}".replace(",", " ") + " km" if car.get("mileage") else "",
        "car_price": _money(price),
        "deposit": _money(deposit),
        "balance": _money(price - deposit),
        "commission": _money(record.get("commission_eur") or 300),
        **{k: (user.get("contract") or {}).get(k) or "" for k in BUYER_FIELDS},
    }


async def _own_deposit(session_id, user):
    record = await _db.deposits.find_one({"session_id": session_id})
    if not record or record.get("user_id") != user["_id"]:
        raise HTTPException(404, "no such payment")
    if record.get("payment_status") != "paid":
        raise HTTPException(409, "the deposit has not cleared yet")
    return record


async def _render(session_id, user, lang=""):
    record = await _own_deposit(session_id, user)
    car = await _db.listings.find_one(
        {"_id": record["car_id"]},
        {"vin": 1, "year_month": 1, "mileage": 1}) or {}
    doc = await _doc()
    lang = (lang or record.get("lang") or "bg")[:2].lower()
    if lang not in LANGS:
        lang = "bg"
    values = await _values(record, car, user, doc.get("seller") or DEFAULT_SELLER, lang)
    body = (doc.get("bodies") or {}).get(lang) or DEFAULT_BODIES[lang]
    return {
        "session_id": session_id,
        "lang": lang,
        "contract_no": values["contract_no"],
        "text": _fill(body, values),
        "buyer": {k: values[k] for k in BUYER_FIELDS},
        "missing": [k for k in BUYER_FIELDS if not values[k]],
        "car_title": record.get("car_title") or "",
    }


class BuyerBody(BaseModel):
    buyer_name: str = Field("", max_length=140)
    buyer_egn: str = Field("", max_length=20)
    buyer_id_no: str = Field("", max_length=20)
    buyer_id_date: str = Field("", max_length=20)
    buyer_id_issuer: str = Field("", max_length=140)
    buyer_address: str = Field("", max_length=300)
    buyer_phone: str = Field("", max_length=32)


@router.get("/contract/{session_id}")
async def get_contract(session_id: str, lang: str = "", user=Depends(auth.current_user)):
    return await _render(session_id, user, lang)


@router.put("/contract/{session_id}")
async def save_contract(session_id: str, body: BuyerBody, lang: str = "",
                        user=Depends(auth.current_user)):
    """The buyer's own details live on the ACCOUNT, so a second purchase is already filled in."""
    await _own_deposit(session_id, user)
    fields = {k: v.strip() for k, v in body.model_dump().items()}
    await _db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"contract": fields, "contract_updated_at": _now()}})
    user = await _db.users.find_one({"_id": user["_id"]})
    return await _render(session_id, user, lang)


@router.get("/contract/{session_id}/docx")
async def download_contract(session_id: str, lang: str = "", user=Depends(auth.current_user)):
    """A Word file, built here rather than converted: no LibreOffice on the box, and the
    buyer can print it or hand it to a notary as it is."""
    from docx import Document
    from docx.shared import Pt

    out = await _render(session_id, user, lang)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for i, block in enumerate(out["text"].split("\n")):
        p = doc.add_paragraph(block)
        if i == 0:
            p.runs[0].bold = True if p.runs else False
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    name = f"contract-{out['contract_no']}.docx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── admin ────────────────────────────────────────────────────────────────────
class TemplateBody(BaseModel):
    seller: dict = Field(default_factory=dict)
    bodies: dict = Field(default_factory=dict)


# server.py owns the admin check and injects it here, so this module never imports it back.
_require_admin = None


def set_admin_guard(fn):
    global _require_admin
    _require_admin = fn


@router.get("/admin/contract-template")
async def admin_get_template(request: Request, x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    doc = await _doc()
    return {"seller": doc.get("seller") or DEFAULT_SELLER,
            "bodies": doc.get("bodies") or DEFAULT_BODIES,
            "langs": list(LANGS),
            "placeholders": sorted(set(_TOKEN.findall("".join(DEFAULT_BODIES.values())))),
            "updated_at": doc.get("updated_at")}


@router.put("/admin/contract-template")
async def admin_put_template(body: TemplateBody, request: Request,
                             x_admin_token: str = Header(default="")):
    await _require_admin(request, x_admin_token)
    doc = await _doc()
    seller = {**(doc.get("seller") or DEFAULT_SELLER),
              **{k: str(v)[:200] for k, v in (body.seller or {}).items()}}
    bodies = dict(doc.get("bodies") or DEFAULT_BODIES)
    for lang, text in (body.bodies or {}).items():
        if lang in LANGS and isinstance(text, str) and text.strip():
            bodies[lang] = text
    await _db.settings.update_one(
        {"_id": DOC_ID},
        {"$set": {"seller": seller, "bodies": bodies, "updated_at": _now()}})
    return {"saved": True, "seller": seller, "bodies": bodies}


@router.post("/admin/contract-template/reset")
async def admin_reset_template(request: Request, lang: str = "bg",
                               x_admin_token: str = Header(default="")):
    """Back to the shipped wording for one language, when an edit has gone wrong."""
    await _require_admin(request, x_admin_token)
    if lang not in LANGS:
        raise HTTPException(400, "unknown language")
    await _db.settings.update_one(
        {"_id": DOC_ID},
        {"$set": {f"bodies.{lang}": DEFAULT_BODIES[lang], "updated_at": _now()}})
    return {"reset": lang, "body": DEFAULT_BODIES[lang]}
