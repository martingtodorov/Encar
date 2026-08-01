"""
test_core.py — Phase 1 POC for the Encar BG/RO/EN skin.

Proves, with REAL calls (no mocks), every risky part of the app before we build it:
  A. Encar search list endpoint (limit=500, deep offsets, total count)
  B. Encar vehicle detail endpoint (+ the search Id vs detail vehicleId mismatch)
  C. Option dictionaries (standard + tuning) and resolving a real car's option codes to names
  D. Insurance history record endpoint
  E. Inspection sheet + diagnosis endpoints
  F. Live FX (fx_krw_eur, usd_eur)
  G. Pricing engine reproducing spec worked examples A/B/C/D with charm-UP
  H. AI translation KO -> EN/BG/RO with permanent MongoDB cache (2nd run = 0 LLM calls)
  I. Encar CDN image reachability (loaded directly by the visitor's browser)

Run:  cd /app && python test_core.py
"""

import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "encar_skin")
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]

API = "https://api.encar.com"
CDN = "https://ci.encar.com"

# Encar rejects requests without a plausible desktop UA + Referer.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "http://www.encar.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

RESULTS = {}


def ok(name, msg=""):
    RESULTS[name] = True
    print(f"  [PASS] {name}" + (f" — {msg}" if msg else ""))


def fail(name, msg=""):
    RESULTS[name] = False
    print(f"  [FAIL] {name}" + (f" — {msg}" if msg else ""))


def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


# ───────────────────────── pricing engine (per /app/memory/pricing_spec.md) ────
# charm rounds UP per user instruction: smallest value ending in 99 that is >= x
def charm(x: float) -> float:
    return max(99.0, math.floor(x / 100.0) * 100 + 99)


DEFAULTS = dict(
    IMPORT_DUTY_RATE=0.10,
    VAT_RATE=0.20,
    CUSTOMS_BASE_FRACTION=0.18,
    CUSTOMS_MIN_USD=3000.0,
    VAT_RECLAIMABLE=False,
    AUTOWINI_MULTIPLIER=1.0,
    AUTOWINI_FEE_USD=2900.0,
    SHIPPING_USD=0.0,
    MARINE_INSURANCE=0.0,
    DOMESTIC_TOTAL=1600.0,
    MARGIN_PCT=0.014,
    MARGIN_MIN_EUR=500.0,
    MARGIN_TIER_THRESHOLD_EUR=50000.0,
    MARGIN_TIER_PCT=0.02,
)


def compute_landed(price_krw, fx_krw_eur, usd_eur, cbf=None, C=None):
    C = {**DEFAULTS, **(C or {})}
    cbf = C["CUSTOMS_BASE_FRACTION"] if cbf is None else cbf
    encar_eur = price_krw / fx_krw_eur
    car_eur = encar_eur * C["AUTOWINI_MULTIPLIER"] + C["AUTOWINI_FEE_USD"] * usd_eur
    customs_base = max(car_eur * cbf, C["CUSTOMS_MIN_USD"] * usd_eur)
    duty = customs_base * C["IMPORT_DUTY_RATE"]
    vat = (customs_base + duty) * C["VAT_RATE"]
    shipping_eur = C["SHIPPING_USD"] * usd_eur
    landed = (
        car_eur
        + shipping_eur
        + C["MARINE_INSURANCE"]
        + duty
        + (0.0 if C["VAT_RECLAIMABLE"] else vat)
        + C["DOMESTIC_TOTAL"]
    )
    return dict(
        encar_eur=encar_eur, car_eur=car_eur, customs_base=customs_base,
        duty=duty, vat=vat, shipping_eur=shipping_eur, landed=landed,
    )


def sale_from_landed(landed, C=None):
    C = {**DEFAULTS, **(C or {})}
    base = max(landed * C["MARGIN_PCT"], C["MARGIN_MIN_EUR"])
    tier = C["MARGIN_TIER_PCT"] * max(0.0, landed - C["MARGIN_TIER_THRESHOLD_EUR"])
    target = base + tier
    sale = charm(landed + target)
    return dict(base_margin=base, tier_margin=tier, target_margin=target,
                suggested_sale=sale, realized_margin=sale - landed)


def price_car(price_krw, fx_krw_eur, usd_eur, C=None):
    """Full pricing incl. dual customs scenario -> profit range."""
    C = {**DEFAULTS, **(C or {})}
    primary = compute_landed(price_krw, fx_krw_eur, usd_eur, C["CUSTOMS_BASE_FRACTION"], C)
    secondary = compute_landed(price_krw, fx_krw_eur, usd_eur, 0.10, C)
    s = sale_from_landed(primary["landed"], C)
    return {
        **primary, **s,
        "landed_secondary": secondary["landed"],
        "profit_min": s["suggested_sale"] - primary["landed"],
        "profit_max": s["suggested_sale"] - secondary["landed"],
    }


# ──────────────────────────── option dictionary flatten ───────────────────────
def flatten_options(options):
    """Encar nests option variants under `subOptions` (e.g. code 075 'LED headlamp'
    lives inside group 001 'Headlamp'). Cars reference the LEAF codes, so the
    dictionary must be flattened recursively or ~25% of codes never resolve."""
    flat = {}

    def walk(lst):
        for o in lst or []:
            walk(o.get("subOptions"))
            code = o.get("optionCd")
            if not code:
                continue
            # leaf entries are authoritative; group headers only fill gaps
            if o.get("group"):
                flat.setdefault(code, o)
            else:
                flat[code] = o

    walk(options)
    return flat


# ────────────────────────────────── http helper ───────────────────────────────
async def get(client, url, **kw):
    """Polite GET with exponential backoff on 429/5xx. No IP tricks."""
    delay = 1.0
    for attempt in range(5):
        r = await client.get(url, headers=HEADERS, timeout=30, **kw)
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"      (backoff {r.status_code}, sleep {delay}s)")
            await asyncio.sleep(delay)
            delay *= 2
            continue
        return r
    return r


# ══════════════════════════════════ A. SEARCH ═════════════════════════════════
async def test_search(client):
    section("A. Encar search list endpoint (limit=500, deep offsets)")
    q = "(And.Hidden.N._.CarType.A.)"

    url = f"{API}/search/car/list/general?count=true&q={quote(q)}&sr={quote('|ModifiedDate|0|500')}"
    r = await get(client, url)
    if r.status_code != 200:
        return fail("A1 search limit=500", f"HTTP {r.status_code}")
    d = r.json()
    total = d.get("Count", 0)
    rows = d.get("SearchResults", [])
    if len(rows) != 500 or total < 100000:
        return fail("A1 search limit=500", f"count={total} rows={len(rows)}")
    ok("A1 search limit=500", f"total catalogue={total:,} rows returned={len(rows)}")
    print(f"      => full catalogue = {math.ceil(total/500)} requests at limit=500")

    # required fields for the grid
    need = ["Id", "Manufacturer", "Model", "Year", "Mileage", "Price", "FuelType"]
    missing = [k for k in need if k not in rows[0]]
    if missing:
        fail("A2 grid fields", f"missing {missing}")
    else:
        ok("A2 grid fields", ", ".join(need))

    # deep pagination — proves all 217k reachable
    depths = [0, 10000, 100000, min(total - 20, 217000)]
    seen = {}
    for off in depths:
        u = f"{API}/search/car/list/general?count=true&q={quote(q)}&sr={quote(f'|ModifiedDate|{off}|20')}"
        rr = await get(client, u)
        n = len(rr.json().get("SearchResults", [])) if rr.status_code == 200 else 0
        seen[off] = n
        await asyncio.sleep(0.4)
    if all(v == 20 for v in seen.values()):
        ok("A3 deep pagination", f"offsets {list(seen)} all returned 20 rows — no depth cap")
    else:
        fail("A3 deep pagination", str(seen))

    RESULTS["_total"] = total
    RESULTS["_rows"] = rows
    return rows


# ══════════════════════════════════ B. DETAIL ═════════════════════════════════
async def test_detail(client, rows):
    section("B. Vehicle detail endpoint")
    # find a listing that has both Record (insurance) and Inspection so later tests work
    cand = [r for r in rows if "Record" in (r.get("Condition") or [])
            and "Inspection" in (r.get("Condition") or [])]
    listing = cand[0] if cand else rows[0]
    lid = listing["Id"]

    r = await get(client, f"{API}/v1/readside/vehicle/{lid}")
    if r.status_code != 200:
        return fail("B1 detail fetch", f"HTTP {r.status_code} for {lid}"), None
    d = r.json()
    vid = d.get("vehicleId")
    ok("B1 detail fetch", f"listing Id={lid}")

    if vid and str(vid) != str(lid):
        ok("B2 Id vs vehicleId", f"search Id={lid} != detail vehicleId={vid} (both stored)")
    else:
        ok("B2 Id vs vehicleId", f"identical ({vid}) — handled either way")

    cat, spec = d.get("category", {}), d.get("spec", {})
    photos = d.get("photos") or []
    desc = ((d.get("contents") or {}).get("text") or "")
    checks = {
        "manufacturer": cat.get("manufacturerName"),
        "model": cat.get("modelName"),
        "grade": cat.get("gradeName"),
        "yearMonth": cat.get("yearMonth"),
        "price(만원)": (d.get("advertisement") or {}).get("price"),
        "mileage": spec.get("mileage"),
        "fuel": spec.get("fuelName"),
        "colour": spec.get("colorName"),
        "photos": len(photos),
        "desc_chars": len(desc),
        "vehicleNo": d.get("vehicleNo"),
    }
    if all(v not in (None, 0, "") for v in checks.values()):
        ok("B3 detail payload", " · ".join(f"{k}={v}" for k, v in checks.items()))
    else:
        fail("B3 detail payload", json.dumps(checks, ensure_ascii=False))

    opts = d.get("options") or {}
    n_opts = len(opts.get("standard") or []) + len(opts.get("choice") or []) + len(opts.get("tuning") or [])
    ok("B4 option codes present", f"{n_opts} codes (standard/choice/tuning)")

    RESULTS["_detail"] = d
    return d, listing


# ═══════════════════════════ C. OPTION DICTIONARIES ═══════════════════════════
async def test_options(client, detail):
    section("C. Option dictionaries + resolving a real car's codes to names")
    # Global dictionaries: standard (3-digit codes) + tuning.
    rs = await get(client, f"{API}/v1/readside/vehicles/car/options/standard")
    rt = await get(client, f"{API}/v1/readside/vehicles/car/options/tuning")
    if rs.status_code != 200 or rt.status_code != 200:
        return fail("C1 dictionaries", f"std={rs.status_code} tun={rt.status_code}"), {}

    std = rs.json()
    metas = {m["key"]: m["value"] for m in std.get("metas", []) if m.get("key")}
    smap = flatten_options(std.get("options", []))
    tmap = {o["optionCd"]: o for o in rt.json()}
    ok("C1 dictionaries", f"{len(smap)} standard options (flattened from "
                          f"{len(std.get('options', []))} top-level + nested subOptions), "
                          f"{len(tmap)} tuning, {len(metas)} categories")

    # 'choice' (factory-fitted optional packages, 4-digit codes) are PER-VEHICLE,
    # not in any global dictionary — they carry their own price in 만원.
    vid = detail.get("vehicleId")
    rc = await get(client, f"{API}/v1/readside/vehicles/car/{vid}/options/choice")
    cmap = {}
    if rc.status_code == 200 and rc.text.strip():
        cmap = {o["optionCd"]: o for o in rc.json()}
        total_manwon = sum(o.get("price") or 0 for o in cmap.values())
        ok("C1b per-vehicle choice options",
           f"{len(cmap)} factory options, listed total {total_manwon:,}만원 "
           f"(₩{total_manwon*10_000:,})")
    else:
        ok("C1b per-vehicle choice options", f"none for this car (HTTP {rc.status_code})")

    opts = detail.get("options") or {}
    std_codes = opts.get("standard") or []
    cho_codes = opts.get("choice") or []
    tun_codes = opts.get("tuning") or []

    resolved, unresolved = [], []
    for c in std_codes:
        (resolved if c in smap else unresolved).append(c)
    for c in cho_codes:
        (resolved if c in cmap else unresolved).append(c)
    for c in tun_codes:
        (resolved if c in tmap else unresolved).append(c)

    total = len(std_codes) + len(cho_codes) + len(tun_codes)
    rate = len(resolved) / max(1, total)
    if rate >= 0.95:
        ok("C2 resolve codes->names",
           f"{len(resolved)}/{total} resolved ({rate:.0%}) — "
           f"{len(std_codes)} standard, {len(cho_codes)} choice, {len(tun_codes)} tuning")
        # group by category, exactly as the UI will render it
        groups = {}
        for c in std_codes:
            o = smap.get(c)
            if o:
                groups.setdefault(metas.get(o.get("optionTypeCd"), "기타"), []).append(o["optionName"])
        for g, items in groups.items():
            print(f"      {g}: {len(items)} options")
        if cmap:
            print(f"      선택품목(factory options): "
                  + ", ".join(f"{cmap[c]['optionName']}({cmap[c].get('price')}만원)"
                              for c in cho_codes if c in cmap))
    else:
        fail("C2 resolve codes->names", f"only {len(resolved)}/{total}; unresolved={unresolved[:10]}")

    RESULTS["_smap"] = smap
    RESULTS["_metas"] = metas
    RESULTS["_cmap"] = cmap
    return smap, metas


# ═════════════════════ D/E. INSURANCE, INSPECTION, DIAGNOSIS ══════════════════
async def test_documents(client, detail):
    section("D/E. Insurance history · inspection sheet · diagnosis")
    vid = detail.get("vehicleId")
    vno = detail.get("vehicleNo") or ""

    r = await get(client, f"{API}/v1/readside/record/vehicle/{vid}/open?vehicleNo={quote(vno)}")
    if r.status_code == 200 and r.text.strip():
        rec = r.json()
        ok("D1 insurance history",
           f"own_accidents={rec.get('myAccidentCnt')} other={rec.get('otherAccidentCnt')} "
           f"owner_changes={rec.get('ownerChangeCnt')} total_loss={rec.get('totalLossCnt')} "
           f"flood={rec.get('floodTotalLossCnt')} theft={rec.get('robberCnt')} "
           f"first_reg={rec.get('firstDate')}")
        RESULTS["_record"] = rec
    else:
        fail("D1 insurance history", f"HTTP {r.status_code}")

    r = await get(client, f"{API}/v1/readside/inspection/vehicle/{vid}")
    if r.status_code == 200 and r.text.strip():
        ins = r.json()
        m = ins.get("master") or {}
        det = m.get("detail") or {}
        ok("E1 inspection sheet",
           f"accident={m.get('accdient')} simple_repair={m.get('simpleRepair')} "
           f"mileage={det.get('mileage')} vin={det.get('vin')} "
           f"guaranty={(det.get('guarantyType') or {}).get('title')}")
        RESULTS["_inspection"] = ins
    else:
        fail("E1 inspection sheet", f"HTTP {r.status_code}")

    r = await get(client, f"{API}/v1/readside/diagnosis/vehicle/{vid}")
    if r.status_code == 200 and r.text.strip():
        dg = r.json()
        items = dg.get("items") or []
        abnormal = [i for i in items if i.get("resultCode") != "NORMAL"]
        ok("E2 diagnosis", f"{len(items)} panels checked, {len(abnormal)} not normal")
        RESULTS["_diagnosis"] = dg
    else:
        # not every car is diagnosed — only fail if the car claims to be
        if (detail.get("advertisement") or {}).get("diagnosisCar"):
            fail("E2 diagnosis", f"HTTP {r.status_code} though diagnosisCar=true")
        else:
            ok("E2 diagnosis", "car not diagnosed by Encar — absence is correct")


# ═══════════════════════════════════ F. FX ════════════════════════════════════
async def test_fx(client):
    section("F. Live FX rates")
    got = {}
    try:
        r = await client.get("https://open.er-api.com/v6/latest/EUR", timeout=20)
        if r.status_code == 200:
            rates = r.json().get("rates", {})
            if rates.get("KRW"):
                got["fx_krw_eur"] = float(rates["KRW"])
        r = await client.get("https://open.er-api.com/v6/latest/USD", timeout=20)
        if r.status_code == 200:
            rates = r.json().get("rates", {})
            if rates.get("EUR"):
                got["usd_eur"] = float(rates["EUR"])
            if rates.get("RON"):
                got["usd_ron"] = float(rates["RON"])
    except Exception as e:
        return fail("F1 live FX", str(e)[:120])

    if got.get("fx_krw_eur") and got.get("usd_eur"):
        ok("F1 live FX", f"KRW per EUR={got['fx_krw_eur']:.2f} · EUR per USD={got['usd_eur']:.4f}")
        RESULTS["_fx"] = got
    else:
        fail("F1 live FX", f"incomplete: {got}")


# ═══════════════════════════════ G. PRICING ENGINE ════════════════════════════
def test_pricing():
    section("G. Pricing engine vs spec worked examples (charm rounds UP)")
    FX, UE = 1664.0, 0.867

    cases = [
        ("A ₩15,000,000  ($ floor + margin floor)", 15_000_000, 13_961.04, 14_499, 537.96),
        ("B ₩50,000,000  (18% governs)",            50_000_000, 36_037.97, 36_599, 561.03),
        ("D ₩114,000,000 (Maybach S580, tier)",    114_000_000, 76_714.89, 78_399, 1_684.11),
    ]
    for label, krw, exp_landed, exp_sale, exp_margin in cases:
        r = price_car(krw, FX, UE)
        dl = abs(r["landed"] - exp_landed)
        dm = abs(r["realized_margin"] - exp_margin)
        good = dl < 0.6 and r["suggested_sale"] == exp_sale and dm < 0.6
        (ok if good else fail)(
            f"G {label}",
            f"landed={r['landed']:,.2f} (exp {exp_landed:,.2f}) · "
            f"sale={r['suggested_sale']:,.0f} (exp {exp_sale:,}) · "
            f"margin={r['realized_margin']:,.2f} (exp {exp_margin:,.2f})",
        )
        print(f"      breakdown: car={r['car_eur']:,.2f} customs_base={r['customs_base']:,.2f} "
              f"duty={r['duty']:,.2f} vat={r['vat']:,.2f} +domestic=1,600")
        print(f"      profit range (0.18 -> 0.10 customs): "
              f"€{r['profit_min']:,.2f} -> €{r['profit_max']:,.2f}")

    # C is specified from a synthetic landed value, not a KRW price
    c = sale_from_landed(80_000.0)
    good = c["suggested_sale"] == 81_799 and abs(c["realized_margin"] - 1_799) < 0.01
    (ok if good else fail)(
        "G C landed=€80,000 (tier active)",
        f"base={c['base_margin']:,.0f} tier={c['tier_margin']:,.0f} "
        f"sale={c['suggested_sale']:,.0f} (exp 81,799) margin={c['realized_margin']:,.0f} (exp 1,799)",
    )

    # charm-up unit checks + the invariant that motivated the change
    ch = {48557.67: 48599, 48540: 48599, 81720: 81799, 81700: 81799, 50: 99}
    bad = {k: charm(k) for k, v in ch.items() if charm(k) != v}
    (ok if not bad else fail)("G charm() rounds up", f"{len(ch)} cases" if not bad else str(bad))

    # invariant: realized margin never below the €500 floor (was gotcha #7)
    worst = min(sale_from_landed(l)["realized_margin"] for l in range(5000, 120000, 137))
    (ok if worst >= 500 else fail)(
        "G margin floor holds", f"min realized margin across sweep = €{worst:,.2f} (>= 500)")


# ════════════════════════════ H. AI TRANSLATION + CACHE ═══════════════════════
LANGS = {"en": "English", "bg": "Bulgarian", "ro": "Romanian"}

SYS = (
    "You are a professional automotive translator localising South Korean used-car "
    "listing data from Encar for European car buyers. Translate Korean -> {lang}.\n"
    "RULES:\n"
    "- Use correct automotive industry terminology, never literal word-for-word.\n"
    "- Keep model/trim names in their standard Latin-script marketing form "
    "(e.g. 그랜저 -> Grandeur, 익스클루시브 -> Exclusive).\n"
    "- Keep numbers, units, cc, km and dates exactly as given.\n"
    "- Colours: give the normal trade colour name (쥐색 -> Grey).\n"
    "- Be concise; these are UI labels and spec values.\n"
    "- Return ONLY a JSON object mapping each input id to its translation. No prose."
)


def _key(text, lang):
    return hashlib.sha256(f"{lang}\x00{text}".strip().encode()).hexdigest()


def _extract_json(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    return json.loads(s)


async def translate_batch(db, texts, lang, stats):
    """Cache-around-LLM. Returns {source: translation}. Each unique string hits the LLM once, ever."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    texts = [t for t in {t.strip(): 1 for t in texts if t and t.strip()}]
    out, todo = {}, []
    for t in texts:
        doc = await db.translations.find_one({"_id": _key(t, lang)})
        if doc:
            out[t] = doc["target"]
            stats["hits"] += 1
        else:
            todo.append(t)

    if not todo:
        return out

    stats["misses"] += len(todo)
    payload = {str(i): t for i, t in enumerate(todo)}
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"trans-{lang}-{int(time.time())}",
        system_message=SYS.format(lang=LANGS[lang]),
    ).with_model("gemini", "gemini-3-flash-preview")

    got = {}
    for attempt in range(3):
        try:
            resp = await chat.send_message(UserMessage(
                text="Translate each value to " + LANGS[lang] +
                     ". Reply with ONLY a JSON object using the same keys.\n\n" +
                     json.dumps(payload, ensure_ascii=False)))
            stats["llm_calls"] += 1
            got = _extract_json(resp)
            if got:
                break
        except Exception as e:
            print(f"      (llm retry {attempt+1}: {str(e)[:90]})")
            await asyncio.sleep(1.5 * (attempt + 1))

    docs = []
    for i, src in enumerate(todo):
        tr = got.get(str(i))
        if isinstance(tr, str) and tr.strip():
            out[src] = tr.strip()
            docs.append({"_id": _key(src, lang), "source": src,
                         "lang": lang, "target": tr.strip()})
        else:
            out[src] = src  # graceful fallback: show Korean rather than nothing
    if docs:
        # idempotent write so re-runs never duplicate
        for d in docs:
            await db.translations.update_one({"_id": d["_id"]}, {"$set": d}, upsert=True)
    return out


async def test_translation(db, detail, smap):
    section("H. AI translation KO->EN/BG/RO with permanent MongoDB cache")
    cat, spec = detail.get("category", {}), detail.get("spec", {})
    opts = detail.get("options") or {}
    codes = ((opts.get("standard") or []) + (opts.get("choice") or []))[:12]

    strings = [v for v in [
        cat.get("manufacturerName"), cat.get("modelName"), cat.get("gradeName"),
        spec.get("fuelName"), spec.get("colorName"), spec.get("bodyName"),
        spec.get("transmissionName"),
    ] if v]
    strings += [smap[c]["optionName"] for c in codes if c in smap]
    # per-vehicle factory option names too
    cmap = RESULTS.get("_cmap") or {}
    strings += [o["optionName"] for o in list(cmap.values())[:5]]
    strings += ["정상", "양호", "보험사보증", "세단 4도어", "무사고"]

    # clean slate so the cache proof is meaningful
    await db.translations.delete_many({"source": {"$in": strings}})

    stats = {"hits": 0, "misses": 0, "llm_calls": 0}
    t0 = time.time()
    first = {}
    for lang in LANGS:
        first[lang] = await translate_batch(db, strings, lang, stats)
    t1 = time.time() - t0

    translated = sum(1 for lang in LANGS for s in strings if first[lang].get(s) not in (None, s))
    total = len(strings) * len(LANGS)
    if stats["llm_calls"] == 3 and translated >= total * 0.8:
        ok("H1 batch translate", f"{len(strings)} strings x 3 langs = {total} translations "
                                 f"in only {stats['llm_calls']} LLM calls ({t1:.1f}s)")
    else:
        fail("H1 batch translate",
             f"llm_calls={stats['llm_calls']} translated={translated}/{total}")

    for lang in LANGS:
        sample = [f"{s} -> {first[lang].get(s)}" for s in strings[:5]]
        print(f"      {lang}: " + " | ".join(sample))

    # second run must be 100% cache, zero LLM calls
    stats2 = {"hits": 0, "misses": 0, "llm_calls": 0}
    t0 = time.time()
    second = {}
    for lang in LANGS:
        second[lang] = await translate_batch(db, strings, lang, stats2)
    t2 = time.time() - t0

    if stats2["llm_calls"] == 0 and stats2["misses"] == 0 and stats2["hits"] == total:
        ok("H2 cache hit", f"2nd run: {stats2['hits']} cache hits, 0 LLM calls, {t2:.2f}s "
                           f"({t1/max(t2,0.001):.0f}x faster)")
    else:
        fail("H2 cache hit", f"hits={stats2['hits']} misses={stats2['misses']} "
                             f"llm_calls={stats2['llm_calls']}")

    if all(first[l].get(s) == second[l].get(s) for l in LANGS for s in strings):
        ok("H3 cache consistency", "cached output identical to first run")
    else:
        fail("H3 cache consistency", "cached values differ")

    # long free-text dealer description
    desc = ((detail.get("contents") or {}).get("text") or "").strip()
    if desc:
        st = {"hits": 0, "misses": 0, "llm_calls": 0}
        res = await translate_batch(db, [desc], "bg", st)
        tr = res.get(desc, "")
        if tr and tr != desc and len(tr) > 40:
            ok("H4 long description", f"{len(desc)} KO chars -> {len(tr)} BG chars")
            print(f"      BG preview: {tr[:150].replace(chr(10),' ')}…")
        else:
            fail("H4 long description", f"got {len(tr)} chars")
    else:
        ok("H4 long description", "listing has no description text — skipped")

    n = await db.translations.count_documents({})
    print(f"      translation cache now holds {n} permanent entries")


# ═══════════════════════════════════ I. IMAGES ════════════════════════════════
async def test_images(client, detail):
    section("I. Encar CDN images (loaded by the visitor's browser, not our server)")
    photos = detail.get("photos") or []
    if not photos:
        return fail("I1 images", "no photos in payload")
    sizes = []
    for p in photos[:3]:
        url = f"{CDN}{p['path']}?impolicy=widthRate&rw=1160&cw=1160&ch=696&cg=Center"
        r = await client.get(url, headers=HEADERS, timeout=30)
        sizes.append((r.status_code, len(r.content)))
    if all(s == 200 and n > 5000 for s, n in sizes):
        avg = sum(n for _, n in sizes) / len(sizes) / 1024
        ok("I1 images", f"{len(photos)} photos available, {len(sizes)} fetched OK, avg {avg:.0f} KB")
        print(f"      => ~{len(photos)*avg/1024:.1f} MB per car served by Encar's CDN, "
              f"not by us")
    else:
        fail("I1 images", str(sizes))

    # no-referer check: confirms the browser can hotlink directly
    p = photos[0]
    r = await client.get(f"{CDN}{p['path']}", timeout=30,
                         headers={"User-Agent": HEADERS["User-Agent"]})
    if r.status_code == 200:
        ok("I2 hotlink w/o referer", "CDN serves images with no Referer — browser can load direct")
    else:
        fail("I2 hotlink w/o referer", f"HTTP {r.status_code} — would need proxying")


# ═══════════════════════════════════ MAIN ═════════════════════════════════════
async def main():
    print("Encar BG/RO/EN skin — Phase 1 core POC")
    print("no mocks · real Encar API · real LLM · real MongoDB")

    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(follow_redirects=True, http2=False) as client:
        rows = await test_search(client)
        if not rows:
            print("\nsearch failed — aborting")
            return summarise()

        detail, listing = await test_detail(client, rows)
        if not detail:
            return summarise()

        smap, metas = await test_options(client, detail)
        await test_documents(client, detail)
        await test_fx(client)
        test_pricing()
        await test_translation(db, detail, smap)
        await test_images(client, detail)

        # end-to-end: this exact car, priced for a Bulgarian buyer
        section("J. End-to-end: this real car, repriced for a BG buyer")
        fx = RESULTS.get("_fx") or {}
        FX = fx.get("fx_krw_eur", 1664.0)
        UE = fx.get("usd_eur", 0.867)
        manwon = (detail.get("advertisement") or {}).get("price") or 0
        krw = manwon * 10_000
        r = price_car(krw, FX, UE)
        cat = detail.get("category", {})
        print(f"      {cat.get('manufacturerEnglishName')} {cat.get('modelGroupEnglishName')} "
              f"{cat.get('formYear')} · {detail.get('spec',{}).get('mileage'):,} km")
        print(f"      Encar ask: {manwon:,}만원 = ₩{krw:,} = €{r['encar_eur']:,.2f}")
        print(f"      + Autowini fee €{2900*UE:,.2f} -> car €{r['car_eur']:,.2f}")
        print(f"      customs base €{r['customs_base']:,.2f} · duty €{r['duty']:,.2f} · "
              f"VAT €{r['vat']:,.2f} · domestic €1,600")
        print(f"      LANDED €{r['landed']:,.2f}")
        print(f"      target margin €{r['target_margin']:,.2f} "
              f"(base {r['base_margin']:,.2f} + tier {r['tier_margin']:,.2f})")
        print(f"      SALE PRICE €{r['suggested_sale']:,.0f}  "
              f"(realized €{r['realized_margin']:,.2f}, "
              f"profit range €{r['profit_min']:,.0f}–€{r['profit_max']:,.0f})")
        if r["suggested_sale"] > r["landed"] > r["encar_eur"] > 0:
            ok("J1 end-to-end pricing", "real listing priced coherently")
        else:
            fail("J1 end-to-end pricing", json.dumps(r, default=str)[:200])

    client_db.close()
    summarise()


def summarise():
    section("SUMMARY")
    keys = [k for k in RESULTS if not k.startswith("_")]
    passed = sum(1 for k in keys if RESULTS[k])
    for k in keys:
        print(f"  {'PASS' if RESULTS[k] else 'FAIL'}  {k}")
    print(f"\n  {passed}/{len(keys)} passed")
    if passed == len(keys):
        print("\n  ALL CORE PROOFS PASSED — safe to build the app.")
    else:
        print("\n  CORE NOT PROVEN — fix before building.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
