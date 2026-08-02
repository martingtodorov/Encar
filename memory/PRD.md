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
- Translation: Anthropic Claude (`claude-sonnet-5`) with own key → Gemini → Emergent

## Architecture
- `backend/server.py` — API routes, CORS, auth wiring
- `backend/encar.py` — polite upstream client (single slot, backoff, no IP rotation)
- `backend/sync.py` — adaptive partitioned crawler (recursive facet splitting to
  beat Encar's 20k deep-pagination cap), dedupe pass, taxonomy build
- `backend/pricing.py` — landed EUR price
- `backend/translate.py` — cached LLM translation + circuit breaker
- `backend/auth.py`, `backend/warm.py`, `backend/warm_status.py`
- `frontend/src/pages/` — SearchPage, CarDetailPage, LoginPage, AccountPage
- `frontend/src/components/` — CarRow, Hero, EnquiryDialog, NavDrawer, TaxonomySelects

## Catalogue coverage (verified 2026-06)
| Metric | Value |
|---|---|
| Ads live on Encar | ~217,800 |
| Lease (리스) + rental (렌트) ads excluded — not exportable | ~7,500 |
| Ads held in our DB | 210,435 |
| Re-registered duplicate ads hidden | ~61,000 |
| Unique physical cars shown | 149,427 |

Only `일반` (regular sale) listings are indexed. `EXCLUDED_SELL_TYPES` in `sync.py`
drops 리스 and 렌트 in BOTH import paths (the legacy sequential sync and the
partitioned crawler's `sink`), so they can never be re-introduced.

Duplicate pairs were verified as genuine re-registrations (identical
make/model/badge/year/mileage/price, byte-identical photo paths); `vehicle_key` comes
from the photo path's underlying vehicleId and shows no false collisions. There is no
crawl gap.

## Implemented
- 2026-06: **Four detail-page / search fixes** (all verified by the testing agent,
  `/app/test_reports/iteration_9.json`, 100% pass):
  1. *Back to results lost every filter.* `CarDetailPage` had a hardcoded
     `<Link to="/">`, so the in-page back button dropped the whole query string and the
     remounted search page wrote its own `?sort=newest`. `openCar` in `SearchPage` now
     passes the live search string in navigation state (`{ state: { from } }`) and the
     detail page's `goBack()` uses it, falling back to `navigate(-1)` and then `/` for
     cold/shared links. `SavedCarsPage` switched from `window.location.href` to
     `navigate` so Back works from there too. Browser Back already worked (URL-bound
     state) and was regression-checked.
  2. *Raw enum codes in the diagnosis panel.* New `_panel_label()` in `server.py`
     turns `FRONT_DOOR_LEFT` into `Front door left` (underscores out, first letter only).
  3. *Save button placement.* Moved from the bottom of the detail page to inline with
     the price, on the right-hand side and to the RIGHT of the price.
  4. *Auto-sort rules.* Now: nothing or make-only selected → `newest`; model or
     trim/submodel selected → `price_asc`. A manually chosen sort is never overridden
     (`sortTouched`), and `resetAll` clears that flag.
- 2026-06: **Lease and rental vehicles excluded entirely.** Lease (리스) was already
  dropped by the partitioned crawler, but rental (렌트) was not, and the legacy
  sequential sync filtered neither — 2,404 rental cars were live in search. Added
  `EXCLUDED_SELL_TYPES = {리스, 렌트}` and applied it in both import paths, purged the
  2,404 existing rows, and rebuilt the taxonomy (10,703 nodes). Verified: the only
  `sell_type` left in the collection is `일반`, and search/hero now report 149,427.
- 2026-06: **Catalogue counter** — was frozen at the last crawl's
  `sync_state.listings_upstream` snapshot. Added `GET /api/catalogue/size`
  (`upstream_size_cached`, 15-min memory + Mongo cache) returning
  `{upstream, unique_cars}`. Per user request the hero now shows **our own**
  inventory (`unique_cars`), and `indexNote` in all three languages reads
  "N cars in the catalogue" instead of "N of Encar listings".
- 2026-06: **Fresh dropdown counts** — `sync.py` `TAXONOMY_TTL_DAYS = 7` replaced with
  `TAXONOMY_TTL_HOURS` (default 6, env-overridable). New `refresh_taxonomy_if_stale()`
  rebuilds in the background (guarded by `_TAX_BUILDING`) and keeps serving the older
  tree, so nobody waits on the ~30s aggregation; only a completely missing taxonomy is
  built inline. Verified: backdated 9h → request returned in 0.24s and the rebuild
  (10,725 nodes) completed in the background.
- 2026-06: **Claude translations** — `_anthropic_call` added to `translate.py` as the
  primary provider (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL=claude-sonnet-5`, SDK
  `max_retries=0` so this module owns the backoff, `retry-after` honoured on 429).
  Gemini/Emergent remain fallbacks. Unblocked the warm-up that Gemini's free tier
  had been 429-ing.
- 2026-06: **Removed the landed-price breakdown panel** from the car detail page
  (`detail-price-breakdown`) per user request. QuickViewDialog and HowItWorksPage
  breakdowns are untouched.
- Adaptive partitioned crawler (full catalogue, ~212k ads indexed)
- Dedupe pass keeping the most informative ad per physical car
- 16-row desktop list view (`CarRow.js`), URL-backed search filters
- Detail page with EUR-converted insurance/damage claims
- Passkey + Argon2 password auth, `/login`, `/account`
- Mobile top-sliding NavDrawer
- Enquiry ("Прати запитване") dialog + `POST /api/enquiry`
- Context-dependent sorting, BGN removed

## Translation warm-up status
`warm_translations` now covers EVERY distinct value (the old
`max(per_field*8, 4000)` cap on badge/badge_detail left the ~1.2k rarest trims to
on-demand fills). Run with `cd /app/backend && TRANSLATE_CHUNK_PACE=0.5 python warm.py`;
check coverage with `python warm_status.py`. Remaining at handoff: ~26k strings across
badge/badge_detail × 3 languages, running in the background with zero 429s.

## Backlog
### P1
- Track my vehicle (Maersk container + MarineTraffic vessel) — BLOCKED on API keys
- Optional hero/footer line explaining ads vs unique cars

### P0 — next up (requested, NOT started)
- **Admin sync dashboard** — live crawl progress, total count, coverage per brand.
  Groundwork already established this turn: Encar's search API accepts a
  `SellType.일반.` facet, so an exact per-brand exportable upstream count is one cheap
  request per make (~62 requests, needs a cached `sync_state.brand_coverage` doc plus a
  background refresh job). Admin auth already exists via `_require_admin` (admin session
  or `x-admin-token` header, `ADMIN_TOKEN` env, default `encar-admin`).
- **Admin enquiry inbox** — list every `enquiries` doc with car title, listing id,
  contact details, message, language, guest/user flag and status (`new` by default).
  Needs `GET /api/admin/enquiries` (+ status PATCH) and an `/admin` route with a
  NavDrawer entry shown only when `user.is_admin`.

### P2
- Price-drop email alerts for saved cars
- Row comparison tool on the desktop list view
