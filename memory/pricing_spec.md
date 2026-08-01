# Encar → BG/RO/EN pricing spec (landed + margin + tier + charm)

Source: user handoff spec (verified against production `landed.py compute()` + `expenses.yaml`).
All money EUR unless suffixed `_usd` / `_krw`.

> AMENDMENT (user instruction): charm rounding rounds **UP**, not down.
> `charm(x) = max(99, floor(x/100)*100 + 99)` = smallest value ending in 99 that is >= x.
> This removes the banker's-rounding tiebreak (old gotcha #8) and means realized margin
> can never fall below the EUR 500 floor (old gotcha #7 no longer applies).

## 1. Inputs

| Input | Meaning | Example |
|---|---|---|
| `price_krw` | Encar ask in KRW = `encar_manwon * 10_000` (Encar quotes in 만원) | 11,400만원 -> 114_000_000 |
| `fx_krw_eur` | KRW per 1 EUR | ~1664 |
| `usd_eur` | EUR per 1 USD | ~0.867 |
| `customs_base_fraction` | scenario: 0.18 primary / 0.10 secondary | 0.18 |

## 2. Constants (current — live in admin-editable settings, mirror of expenses.yaml)

```
IMPORT_DUTY_RATE=0.10   VAT_RATE=0.20   CUSTOMS_BASE_FRACTION=0.18  (secondary 0.10)
CUSTOMS_MIN_USD=3000    VAT_RECLAIMABLE=False
AUTOWINI_MULTIPLIER=1.0 AUTOWINI_FEE_USD=2900   SHIPPING_USD=0   MARINE_INSURANCE=0
DOMESTIC_TOTAL = 900 + 700 = 1600     # inland_transport_bg + extra_cost_buffer
MARGIN_PCT=0.014        MARGIN_MIN_EUR=500
MARGIN_TIER_THRESHOLD_EUR=50000       MARGIN_TIER_PCT=0.02
```

Formula structure is stable; constant VALUES change. They must be editable at runtime.

## 3. Landed cost

```
encar_eur    = price_krw / fx_krw_eur
car_eur      = encar_eur * AUTOWINI_MULTIPLIER + AUTOWINI_FEE_USD * usd_eur
customs_base = max( car_eur * customs_base_fraction , CUSTOMS_MIN_USD * usd_eur )
duty         = customs_base * IMPORT_DUTY_RATE
vat          = (customs_base + duty) * VAT_RATE        # VAT base = customs_base * (1 + duty_rate)
shipping_eur = SHIPPING_USD * usd_eur
LANDED       = car_eur + shipping_eur + MARINE_INSURANCE + duty
             + (vat if not VAT_RECLAIMABLE else 0) + DOMESTIC_TOTAL
```

Collapsed with current constants: `LANDED = car_eur + customs_base * 0.32 + 1600`
(0.32 = duty 0.10 + VAT 1.10*0.20).
The $3000 floor governs when `car_eur * 0.18 < 3000 * usd_eur` (car_eur <= ~EUR 14,400).

## 4. Margin (base + floor + tier)

```
base_margin   = max( LANDED * 0.014 , 500 )
tier_margin   = 0.02 * max( 0 , LANDED - 50000 )    # additive; 0 below EUR 50k
target_margin = base_margin + tier_margin
```

## 5. Charm rounding -> sale  (AMENDED: rounds up)

```
suggested_sale  = charm(LANDED + target_margin)
realized_margin = suggested_sale - LANDED           # sale == landed + realized_margin

charm(x) = max(99, floor(x/100)*100 + 99)
```

charm(48557.67)=48599 · charm(48540)=48599 · charm(81720)=81799 · charm(81700)=81799 · charm(50)=99

## 6. Two customs scenarios

Run section 3 with `customs_base_fraction=0.18` (primary) and `=0.10` (secondary, same $3000
floor). Profit reported as a range: `[sale - landed_0.18 -> sale - landed_0.10]`.

## 7. Reference implementation (charm amended to round up)

```python
import math

def charm(x):
    return max(99.0, math.floor(x / 100.0) * 100 + 99)

def price_car(price_krw, fx_krw_eur, usd_eur, cbf=0.18):
    encar = price_krw / fx_krw_eur
    car   = encar * 1.0 + 2900 * usd_eur
    cb    = max(car * cbf, 3000 * usd_eur)
    duty  = cb * 0.10
    vat   = (cb + duty) * 0.20
    landed = car + 0 * usd_eur + 0 + duty + vat + 1600     # VAT_RECLAIMABLE=False
    base  = max(landed * 0.014, 500)
    tier  = 0.02 * max(0.0, landed - 50000)
    sale  = charm(landed + base + tier)
    return {"landed": landed, "suggested_sale": sale, "realized_margin": sale - landed}
```

Keep full float precision; round only for display.

## 8. Worked examples (fx=1664, usd_eur=0.867 -> 2900*0.867=2514.30, floor 3000*0.867=2601.00)

Recomputed with charm-UP:

- **A — cheap, $ floor + margin floor, no tier (₩15,000,000):**
  car=11,528.72 · cb=2,601.00 (floor) · duty=260.10 · vat=572.22 · landed=13,961.04 ·
  base=500 tier=0 · charm(14,461.04)=**14,499** · realized **537.96**
- **B — 18% governs (₩50,000,000):**
  car=32,562.38 · cb=5,861.23 · duty=586.12 · vat=1,289.47 · landed=36,037.97 ·
  base=504.53 tier=0 · charm(36,542.50)=**36,599** · realized **561.03**
- **C — tier active (landed=80,000):**
  base=1,120 · tier=0.02*30,000=600 · target=1,720 · charm(81,720)=**81,799** · realized **1,799**
- **D — real: Maybach S580 (₩114,000,000):**
  car=71,023.92 · cb=12,784.31 · duty=1,278.43 · vat=2,812.55 · landed=76,714.89 ·
  base=1,074.01 tier=534.30 · charm(78,323.20)=**78,399** · realized **1,684**

## 9. Gotchas

1. Encar price is 만원 -> multiply by 10,000.
2. `fx_krw_eur` DIVIDES (KRW per EUR); `usd_eur` MULTIPLIES (EUR per USD).
3. The $ floor is FX-dependent (`3000 * usd_eur`), not a fixed EUR amount.
4. VAT base = `customs_base * (1 + duty_rate)`.
5. `VAT_RECLAIMABLE=True` => drop VAT from landed.
6. Margin and tier are computed on LANDED, not on car price.
7. ~~Charm can push realized margin under the EUR 500 floor~~ — no longer possible with charm-UP.
8. ~~Banker's rounding in charm~~ — no longer applicable with charm-UP.
9. charm floor = EUR 99.
10. FX-drift reprice (only-raises, reads committed KRW) is separate logic, NOT part of this spec.
