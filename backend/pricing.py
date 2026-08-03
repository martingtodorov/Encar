"""Landed-cost pricing engine.

Implements /app/memory/pricing_spec.md EXACTLY, with the user's amendment that
charm rounding rounds UP. Verified against spec worked examples A/B/C/D in test_core.py.

All constants are runtime-editable (they mirror a changing expenses.yaml), so every
function takes a settings dict rather than reading module globals.
"""

import math

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


def compute_landed(price_krw, fx_krw_eur, usd_eur, customs_base_fraction, S):
    """Spec section 3."""
    encar_eur = price_krw / fx_krw_eur
    car_eur = encar_eur * S["AUTOWINI_MULTIPLIER"] + S["AUTOWINI_FEE_USD"] * usd_eur
    customs_base = max(car_eur * customs_base_fraction, S["CUSTOMS_MIN_USD"] * usd_eur)
    duty = customs_base * S["IMPORT_DUTY_RATE"]
    vat = (customs_base + duty) * S["VAT_RATE"]
    shipping_eur = S["SHIPPING_USD"] * usd_eur
    landed = (
        car_eur
        + shipping_eur
        + S["MARINE_INSURANCE"]
        + duty
        + (0.0 if S["VAT_RECLAIMABLE"] else vat)
        + S["DOMESTIC_TOTAL"]
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


def price_car(price_krw, fx_krw_eur, usd_eur, settings=None):
    """Full pricing incl. the dual customs scenario (spec section 6) -> profit range."""
    S = merge_settings(settings)
    primary = compute_landed(price_krw, fx_krw_eur, usd_eur, S["CUSTOMS_BASE_FRACTION"], S)
    secondary = compute_landed(price_krw, fx_krw_eur, usd_eur,
                               S["CUSTOMS_BASE_FRACTION_SECONDARY"], S)
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
    return {
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


def quick_sale_eur(price_krw, fx_krw_eur, usd_eur, S):
    """Hot path used when repricing 200k+ listings: landed + sale only, no dict churn."""
    encar_eur = price_krw / fx_krw_eur
    car_eur = encar_eur * S["AUTOWINI_MULTIPLIER"] + S["AUTOWINI_FEE_USD"] * usd_eur
    customs_base = max(car_eur * S["CUSTOMS_BASE_FRACTION"], S["CUSTOMS_MIN_USD"] * usd_eur)
    duty = customs_base * S["IMPORT_DUTY_RATE"]
    vat = 0.0 if S["VAT_RECLAIMABLE"] else (customs_base + duty) * S["VAT_RATE"]
    landed = (car_eur + S["SHIPPING_USD"] * usd_eur + S["MARINE_INSURANCE"]
              + duty + vat + S["DOMESTIC_TOTAL"])
    base = max(landed * S["MARGIN_PCT"], S["MARGIN_MIN_EUR"])
    tier = S["MARGIN_TIER_PCT"] * max(0.0, landed - S["MARGIN_TIER_THRESHOLD_EUR"])
    return landed, charm(landed + base + tier)
