# Encar Localised Skin — PRD

## Original problem statement
Create a fully translated skin for encar.com in Bulgarian, Romanian and English.
All current encar.com ads must be present. Do NOT proxy the Encar connection
through our own servers — the visitor's own IP must reach Encar (images load
straight from Encar's CDN). We only re-price cars based on our landed costs.

Product requirements: car search with filters, listing grid, full detail page
(photos, spec, inspection report, landed price breakdown), language switcher,
caching translation layer.

## Stack
- Frontend: React + Tailwind + shadcn/ui
- Backend: FastAPI
- DB: MongoDB
- Auth: Passkeys (py_webauthn) + Argon2 passwords
- Translation: LLM (Gemini key currently rate-limited; Claude swap pending)

## Architecture
- `backend/server.py` — API routes, CORS, auth wiring
- `backend/encar.py` — polite upstream client (single slot, backoff, no IP rotation)
- `backend/sync.py` — adaptive partitioned crawler (recursive facet splitting to
  beat Encar's 20k deep-pagination cap), dedupe pass, taxonomy build
- `backend/pricing.py` — landed EUR price
- `backend/translate.py` — cached LLM translation + circuit breaker
- `backend/auth.py`, `backend/warm.py`
- `frontend/src/pages/` — SearchPage, CarDetailPage, LoginPage, AccountPage
- `frontend/src/components/` — CarRow, Hero, EnquiryDialog, NavDrawer, TaxonomySelects

## Catalogue coverage (verified 2026-06)
| Metric | Value |
|---|---|
| Ads live on Encar | ~217,800 (live counter) |
| Lease/rental ads skipped (not exportable) | ~5,062 |
| Ads held in our DB | 212,707 (99.97% of reachable) |
| Re-registered duplicate ads hidden | 60,876 |
| Unique physical cars shown | 151,831 |

Verified that duplicate pairs are genuine re-registrations (identical
make/model/badge/year/mileage/price and byte-identical photo paths); `vehicle_key`
is parsed from the photo path's underlying vehicleId, and no false collisions were
found. Coverage is effectively complete — there is no crawl gap.

## Implemented
- 2026-06: **Live catalogue counter.** Hero figure was frozen at the last crawl's
  `sync_state.listings_upstream` snapshot. Added `GET /api/catalogue/size`
  (`upstream_size_cached`, 15-min memory + Mongo cache, one count-only upstream
  request) returning `{upstream, unique_cars}`; SearchPage now reads it via
  `getCatalogueSize()`. Verified: hero renders the live number.
- Adaptive partitioned crawler (full catalogue, ~212k ads indexed)
- Dedupe pass keeping the most informative ad per physical car
- 16-row desktop list view (`CarRow.js`), URL-backed search filters
- Detail page with EUR-converted insurance/damage claims
- Passkey + Argon2 password auth, `/login`, `/account`
- Mobile top-sliding NavDrawer
- Enquiry ("Прати запитване") dialog + `POST /api/enquiry`
- Context-dependent sorting, BGN removed, translation cache layer

## Backlog
### P0
- **Claude translation swap** — Gemini free tier returns 429; add Anthropic as the
  primary provider in `translate.py`, then run `warm.py` to cache the remaining
  ~2,140 Korean submodels. BLOCKED: needs the `sk-ant-...` key in `backend/.env`
  (not currently stored) or a decision to use the Emergent LLM key instead.
- **Stale taxonomy counts** — `sync.py` `TAXONOMY_TTL_DAYS = 7` freezes Make/Model
  dropdown counts. Switch to an hours-based TTL (~6h) and rebuild via
  `POST /api/admin/taxonomy/rebuild` (`x-admin-token`).

### P1
- Track my vehicle (Maersk container + MarineTraffic vessel) — needs API keys
- Optional hero line explaining ads vs unique cars

### P2
- Admin sync dashboard (live crawl progress, coverage per brand)
- Admin enquiry dashboard
- Price-drop email alerts for saved cars
- Row comparison tool on the desktop list view
