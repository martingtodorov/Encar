# Encar API — verified surface (all confirmed HTTP 200 during Phase 1 POC)

Base: `https://api.encar.com` · Images: `https://ci.encar.com`

## Required headers (Encar rejects requests without these)

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36
Referer: http://www.encar.com/
Accept: application/json, text/plain, */*
Accept-Language: ko-KR,ko;q=0.9,en;q=0.8
```

## 1. Search / catalogue list

```
GET /search/car/list/general?count=true&q={q}&sr=|{sort}|{offset}|{limit}
```

- `q` example (all visible cars): `(And.Hidden.N._.CarType.A.)`
- `sr` = `|ModifiedDate|{offset}|{limit}` — newest first.
- **`limit` up to 500 CONFIRMED.** **`offset` up to 217,000 CONFIRMED — no depth cap.**
- Response: `{"Count": 217866, "SearchResults": [...]}`
- **Full catalogue = ceil(Count/500) ≈ 436 requests.**

Row fields used by the grid: `Id`, `Manufacturer`, `Model`, `Badge`, `FuelType`, `EvType`,
`GreenType`, `Year` (YYYYMM float), `FormYear`, `Mileage`, `Price` (**만원 — multiply by 10,000
for KRW**), `OfficeCityState`, `Photo`, `Photos[]`, `Condition[]` (`Inspection`/`Record`/`Resume`),
`Trust[]`, `ServiceMark[]`, `SellType`, `Separation[]`.

## 2. Vehicle detail

```
GET /v1/readside/vehicle/{id}
```

Accepts the search `Id`. **The returned `vehicleId` MAY DIFFER from the search `Id`**
(observed 42011523 -> 42001084). Store BOTH; use `vehicleId` for all document endpoints below.

Key paths: `category.{manufacturerName, manufacturerEnglishName, modelName, modelGroupName,
modelGroupEnglishName, gradeName, gradeEnglishName, yearMonth, formYear, originPrice, domestic}`,
`advertisement.{price (만원), status, trust[], diagnosisCar, homeService, extendWarranty}`,
`spec.{mileage, displacement, transmissionName, fuelName, colorName, seatCount, bodyName}`,
`photos[].{code, path, type}` (~30 per car), `options.{standard[], choice[], etc[], tuning[]}`
(CODES only), `contents.text` (Korean dealer description), `partnership.dealer.*`,
`contact.*`, `vin`, `vehicleNo`, `condition.*`.

## 3. Option dictionaries — THE TRICKY PART

```
GET /v1/readside/vehicles/car/options/standard      # global, 3-digit codes
GET /v1/readside/vehicles/car/options/tuning        # global, tuning codes
GET /v1/readside/vehicles/car/{vehicleId}/options/choice   # PER-VEHICLE, 4-digit codes
```

**CRITICAL: `options/standard` is NESTED.** Entries with `group: true` carry a `subOptions[]`
array, and cars reference the LEAF codes. Flattening recursively takes 53 top-level entries
to 63 usable codes. Without the flatten, ~25% of a car's option codes never resolve
(e.g. `075` = LED headlamp lives inside group `001` = Headlamp).

`metas[]` maps `optionTypeCd` -> category name (4 categories: exterior/interior, safety,
convenience/multimedia, seats). Use it to group options in the UI.

`options/choice` is per-vehicle and returns `{optionCd, optionName, price (만원), description}` —
factory-fitted option packages WITH their original prices. Not in any global dictionary.

## 4. Insurance history ("보험이력")

```
GET /v1/readside/record/vehicle/{vehicleId}/open?vehicleNo={urlencoded}
GET /v1/readside/record/vehicle/{vehicleId}/summary        # lighter variant, no vehicleNo needed
```

Fields: `myAccidentCnt`, `otherAccidentCnt`, `accidentCnt`, `ownerChangeCnt`, `robberCnt`,
`totalLossCnt`, `floodTotalLossCnt`, `floodPartLossCnt`, `government`, `business`, `loan`,
`firstDate`, `carShape`, `fuel`, `displacement`, `myAccidentCost`, `otherAccidentCost`.
Only present when the listing has `Record` in `Condition[]`.

## 5. Inspection sheet ("성능점검기록부")

```
GET /v1/readside/inspection/vehicle/{vehicleId}
```

`master.{accdient (sic), simpleRepair, registrationDate}`, `master.detail.{recordNo, modelYear,
validityStartDate, validityEndDate, firstRegistrationDate, vin, mileage, motorType,
guarantyType.{code,title}, boardStateType.{code,title}}`.
Only present when the listing has `Inspection` in `Condition[]`.

## 6. Encar diagnosis ("엔카진단")

```
GET /v1/readside/diagnosis/vehicle/{vehicleId}
```

`items[].{code, name (English panel id e.g. FRONT_DOOR_LEFT), result (Korean), resultCode
(NORMAL/…)}`, plus `diagnosisDate`, `centerCode`, `reservationCenterName`.
Only present when `advertisement.diagnosisCar == true`. Absence is normal, not an error.

## 7. Images (never proxied — the visitor's browser loads these directly)

```
https://ci.encar.com{photo.path}?impolicy=widthRate&rw=1160&cw=1160&ch=696&cg=Center
```

- **No Referer check — hotlinking works.** Confirmed 200 with only a User-Agent.
- ~112 KB per resized image, ~30 images per car (~3.4 MB/car) — all served by Encar's CDN.
- This is the part of "the user's IP, not our server" that genuinely works, and it is ~98%
  of total bandwidth.

## 8. Politeness policy (NO circumvention)

- Single-worker queue, ~2 s between catalogue requests.
- Exponential backoff on 429/500/502/503/504 (1s -> 2s -> 4s -> 8s -> 16s).
- Full catalogue sync ≈ 436 requests ≈ 15 min. Detail/documents fetched once per car, ever.
- User searches hit our own MongoDB index -> ZERO upstream calls.
- No residential proxy pool, no IP rotation, no rate-limit evasion.
- 2026-06: ONE fixed exit — the owner's own home connection (deploy/hetzner/home-exit) via
  `ENCAR_PROXY_URL`, because CloudFront 407s datacenter ranges. Still a single address.
