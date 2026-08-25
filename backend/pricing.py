"""Landed-cost pricing engine.

Implements /app/memory/pricing_spec.md EXACTLY, with the user's amendment that
charm rounding rounds UP. Verified against spec worked examples A/B/C/D in test_core.py.

All constants are runtime-editable (they mirror a changing expenses.yaml), so every
function takes a settings dict rather than reading module globals.
"""

import math

# Encar's raw label for a pure electric car. Hybrids like "가솔린+전기" (petrol+electric) do
# NOT get the EV surcharge — the freight-forwarder only marks vehicles with a full
# traction battery as Class 9 dangerous goods.
EV_FUEL_TYPES = {"전기", "수소"}


def is_ev_fuel(fuel_type):
    """Whether a listing's raw upstream fuel type triggers the EV shipping surcharge."""
    return (fuel_type or "").strip() in EV_FUEL_TYPES


# Mirror of expenses.yaml. Values change; the formula structure does not.
DEFAULT_SETTINGS = {
    "IMPORT_DUTY_RATE": 0.10,
    "VAT_RATE": 0.20,
    "CUSTOMS_BASE_FRACTION": 0.18,        # primary scenario
    "CUSTOMS_BASE_FRACTION_SECONDARY": 0.10,
    "CUSTOMS_MIN_USD": 3000.0,
    "VAT_RECLAIMABLE": False,
    "AUTOWINI_MULTIPLIER": 1.0,
    "AUTOWINI_FEE_USD": 2900.0,
    "SHIPPING_USD": 0.0,
    "MARINE_INSURANCE": 0.0,
    "DOMESTIC_TOTAL": 1600.0,            # inland_transport_bg 900 + extra_cost_buffer 700
    # Electric cars ship on a different vessel schedule and need a special dangerous-goods
    # (Class 9 lithium battery) declaration, which the freight-forwarder charges extra for.
    # Applied only when the listing's fuel type is electric.
    "EV_EXTRA_SHIPPING_EUR": 0.0,
    "MARGIN_PCT": 0.016,
    "MARGIN_MIN_EUR": 600.0,
    "MARGIN_TIER_THRESHOLD_EUR": 50000.0,
    "MARGIN_TIER_PCT": 0.02,
}

NUMERIC_KEYS = [k for k in DEFAULT_SETTINGS if k != "VAT_RECLAIMABLE"]


def charm(x: float) -> float:
    """Charm rounding, rounds UP (user instruction).

    Returns the smallest value ending in 99 that is >= x, floored at 99.
    Because it never rounds down, realized margin can never fall below MARGIN_MIN_EUR.
    """
    return max(99.0, math.floor(x / 100.0) * 100 + 99)


def merge_settings(overrides=None):
    s = dict(DEFAULT_SETTINGS)
    for k, v in (overrides or {}).items():
        if k in DEFAULT_SETTINGS:
            s[k] = bool(v) if k == "VAT_RECLAIMABLE" else float(v)
    return s


def compute_landed(price_krw, fx_krw_eur, usd_eur, customs_base_fraction, S, is_ev=False):
    """Spec section 3, with an EV surcharge that lands only on electric cars."""
    encar_eur = price_krw / fx_krw_eur
    car_eur = encar_eur * S["AUTOWINI_MULTIPLIER"] + S["AUTOWINI_FEE_USD"] * usd_eur
    customs_base = max(car_eur * customs_base_fraction, S["CUSTOMS_MIN_USD"] * usd_eur)
    duty = customs_base * S["IMPORT_DUTY_RATE"]
    vat = (customs_base + duty) * S["VAT_RATE"]
    shipping_eur = S["SHIPPING_USD"] * usd_eur
    # Battery packs ship as Class 9 dangerous goods, so the forwarder charges more for
    # any electric car. Zero for combustion.
    ev_extra_eur = S["EV_EXTRA_SHIPPING_EUR"] if is_ev else 0.0
    landed = (
        car_eur
        + shipping_eur
        + S["MARINE_INSURANCE"]
        + duty
        + (0.0 if S["VAT_RECLAIMABLE"] else vat)
        + S["DOMESTIC_TOTAL"]
        + ev_extra_eur
    )
    return {
        "encar_eur": encar_eur,
        "car_eur": car_eur,
        "autowini_fee_eur": S["AUTOWINI_FEE_USD"] * usd_eur,
        "customs_base": customs_base,
        "customs_base_floored": customs_base > car_eur * customs_base_fraction,
        "duty": duty,
        "vat": 0.0 if S["VAT_RECLAIMABLE"] else vat,
        "vat_gross": vat,
        "shipping_eur": shipping_eur,
        "marine_insurance": S["MARINE_INSURANCE"],
        "domestic_total": S["DOMESTIC_TOTAL"],
        "ev_extra_eur": ev_extra_eur,
        "is_ev": bool(is_ev),
        "landed": landed,
    }


def sale_from_landed(landed, S):
    """Spec sections 4 + 5."""
    base = max(landed * S["MARGIN_PCT"], S["MARGIN_MIN_EUR"])
    tier = S["MARGIN_TIER_PCT"] * max(0.0, landed - S["MARGIN_TIER_THRESHOLD_EUR"])
    target = base + tier
    sale = charm(landed + target)
    return {
        "base_margin": base,
        "tier_margin": tier,
        "target_margin": target,
        "suggested_sale": sale,
        "realized_margin": sale - landed,
    }


def price_car(price_krw, fx_krw_eur, usd_eur, settings=None, is_ev=False):
    """Full pricing incl. the dual customs scenario (spec section 6) -> profit range."""
    S = merge_settings(settings)
    primary = compute_landed(price_krw, fx_krw_eur, usd_eur, S["CUSTOMS_BASE_FRACTION"], S,
                             is_ev=is_ev)
    secondary = compute_landed(price_krw, fx_krw_eur, usd_eur,
                               S["CUSTOMS_BASE_FRACTION_SECONDARY"], S, is_ev=is_ev)
    margin = sale_from_landed(primary["landed"], S)
    sale = margin["suggested_sale"]
    return {
        **primary,
        **margin,
        "price_krw": price_krw,
        "fx_krw_eur": fx_krw_eur,
        "usd_eur": usd_eur,
        "customs_base_fraction": S["CUSTOMS_BASE_FRACTION"],
        "landed_secondary": secondary["landed"],
        "customs_base_secondary": secondary["customs_base"],
        "secondary": secondary,
        "profit_min": sale - primary["landed"],
        "profit_max": sale - secondary["landed"],
    }


def admin_range(quote):
    """The landed-cost range an admin sees: the two customs-value scenarios.

    Low  = duty and VAT on 10% of the car cost, High = on 18%, both with the USD 3,000
    customs-value floor already applied by compute_landed().
    """
    if not quote:
        return None
    low = quote.get("landed_secondary")
    high = quote.get("landed")
    if low is None or high is None:
        return None
    lo, hi = (low, high) if low <= high else (high, low)
    sec = quote.get("secondary") or {}
    sale = quote.get("suggested_sale") or 0
    return {
        # Per-scenario figures, keyed by the customs base fraction, so the panel can show
        # BOTH landed costs and BOTH margins instead of one collapsed number.
        "taxes_low": round((sec.get("duty") or 0) + (sec.get("vat") or 0), 2),
        "taxes_high": round((quote.get("duty") or 0) + (quote.get("vat") or 0), 2),
        "landed_at_low": round(sec.get("landed") or 0, 2),
        "landed_at_high": round(quote.get("landed") or 0, 2),
        "margin_at_low": round(sale - (sec.get("landed") or 0), 2),
        "margin_at_high": round(sale - (quote.get("landed") or 0), 2),
        # True when the USD 3,000 customs-value floor replaced the percentage base, which
        # is why the two scenarios can land on exactly the same number.
        "floored_low": bool(sec.get("customs_base_floored")),
        "floored_high": bool(quote.get("customs_base_floored")),
        "price_krw": quote.get("price_krw"),
        "encar_eur": round(quote.get("encar_eur") or 0, 2),
        "car_eur": round(quote.get("car_eur") or 0, 2),
        "autowini_fee_eur": round(quote.get("autowini_fee_eur") or 0, 2),
        "duty": round(quote.get("duty") or 0, 2),
        "vat": round(quote.get("vat") or 0, 2),
        "domestic_total": round(quote.get("domestic_total") or 0, 2),
        "ev_extra_eur": round(quote.get("ev_extra_eur") or 0, 2),
        "is_ev": bool(quote.get("is_ev")),
        "landed_low": round(lo, 2),
        "landed_high": round(hi, 2),
        "customs_base_low": round(quote.get("customs_base_secondary") or 0, 2),
        "customs_base_high": round(quote.get("customs_base") or 0, 2),
        "customs_fraction_low": DEFAULT_SETTINGS["CUSTOMS_BASE_FRACTION_SECONDARY"],
        "customs_fraction_high": DEFAULT_SETTINGS["CUSTOMS_BASE_FRACTION"],
        "sale_eur": round(quote.get("suggested_sale") or 0, 2),
        "profit_min": round(quote.get("profit_min") or 0, 2),
        "profit_max": round(quote.get("profit_max") or 0, 2),
    }


def quick_sale_eur(price_krw, fx_krw_eur, usd_eur, S, is_ev=False):
    """Hot path used when repricing 200k+ listings: landed + sale only, no dict churn."""
    encar_eur = price_krw / fx_krw_eur
    car_eur = encar_eur * S["AUTOWINI_MULTIPLIER"] + S["AUTOWINI_FEE_USD"] * usd_eur
    customs_base = max(car_eur * S["CUSTOMS_BASE_FRACTION"], S["CUSTOMS_MIN_USD"] * usd_eur)
    duty = customs_base * S["IMPORT_DUTY_RATE"]
    vat = 0.0 if S["VAT_RECLAIMABLE"] else (customs_base + duty) * S["VAT_RATE"]
    ev_extra_eur = S["EV_EXTRA_SHIPPING_EUR"] if is_ev else 0.0
    landed = (car_eur + S["SHIPPING_USD"] * usd_eur + S["MARINE_INSURANCE"]
              + duty + vat + S["DOMESTIC_TOTAL"] + ev_extra_eur)
    base = max(landed * S["MARGIN_PCT"], S["MARGIN_MIN_EUR"])
    tier = S["MARGIN_TIER_PCT"] * max(0.0, landed - S["MARGIN_TIER_THRESHOLD_EUR"])
    return landed, charm(landed + base + tier)
