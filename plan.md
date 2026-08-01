# plan.md — Encar translated skin (BG/RO/EN) + repricing

## 1) Objectives
- Provide a BG/RO/EN “skin” over Encar’s full catalogue (≈217,866 ads) with fast search, deep pagination, and detail pages.
- Reprice every listing using the landed-cost + margin + tier + **charm-up** spec in `/app/memory/pricing_spec.md` (constants runtime-editable).
- Include on detail: photos (hotlinked), translated description, option list (resolved from option dictionaries), insurance history, inspection sheet, diagnosis.
- Minimize upstream load and avoid anti-abuse circumvention: polite syncing + caching; no residential proxy pool.
- Keep the system reproducible: one POC script proves all critical integrations before building the app.

## 2) Implementation Steps

### Phase 1 — Core POC (isolation; do not proceed until all pass)
**User stories**
1. As a user, I can fetch Encar search results (limit=500) and paginate deep so I can reach any of the 217k listings.
2. As a user, I can open a listing and see vehicle detail + photos + options resolved to names.
3. As a user, I can view insurance/inspection/diagnosis documents for a vehicle.
4. As a user, I can switch language and see Korean text translated with caching (second view has 0 LLM calls).
5. As a user, I can see landed price + suggested sale computed exactly per spec.

**Web research (best practice)**
- Quick research on: respectful API polling/backoff patterns; MongoDB indexing for faceted search; LLM translation caching strategies.

**Build** `/app/test_core.py` that proves, with real calls:
- Encar list endpoint: `limit=500` works; offsets (0, 10k, 217k) work; count matches.
- Identify mapping between search `Id` and detail `vehicleId` (store both; handle mismatch).
- Detail endpoint: fetch and parse key fields + photos; confirm image URLs on `ci.encar.com` reachable.
- Option dictionaries: fetch `/v1/readside/vehicles/car/options/standard` + `/tuning`; resolve a real car’s option codes to names.
- Insurance: `/v1/readside/record/vehicle/{vehicleId}/open?vehicleNo=...` works.
- Inspection + diagnosis endpoints work.
- Translation: Emergent LLM call KO→EN/BG/RO with MongoDB cache; demonstrate cache hit on second run.
- Pricing: implement compute per `/app/memory/pricing_spec.md` with **charm-up**; assert worked examples A/B/C/D match charm-up outputs.
- FX: fetch live `fx_krw_eur` and `usd_eur` (TTL cached in script).

**Exit gate:** POC script prints PASS for every section + stores sample docs into MongoDB.

### Phase 2 — V1 App Development (MVP; build around proven core)
**User stories**
1. As a user, I can search/filter cars (make/model/year/price/mileage/fuel/transmission/region) and get instant results.
2. As a user, I can sort by newest and by computed landed/sale price so I can find the best import deals.
3. As a user, I can open a detail page and read translated description, options, and see insurance/inspection/diagnosis.
4. As a user, I can switch language (BG/RO/EN) and currency (EUR/BGN/RON) and the UI + prices update.
5. As a user, I can favorite cars and send an enquiry with a link to the car.

**Backend (FastAPI)**
- Data model (MongoDB):
  - `listings_summary` (from search pages, full catalogue), `listings_detail`, `insurance`, `inspection`, `diagnosis`.
  - `options_standard`, `options_tuning` dictionaries.
  - `translations` cache (key: hash(source)+lang, value: translated).
  - `settings` (pricing constants, VAT reclaimable, FX overrides, sync intervals).
  - `favorites` + `enquiries` (no auth initially: browser local id).
- Catalogue sync worker:
  - Periodic full sync: page through offsets with `limit=500` (~436 calls), polite delay + exponential backoff.
  - Upsert summaries, mark missing as inactive.
- API endpoints:
  - `GET /api/search` served from MongoDB (faceted filters + sort + pagination).
  - `GET /api/car/{listingId}` assembles summary+detail+options-resolve+documents, triggers on-demand fetch if missing.
  - `POST /api/translate` internal helper (batched) using Emergent LLM + cache.
  - `GET/PUT /api/admin/settings` (no auth initially; gated by env secret header).
  - `POST /api/favorites`, `GET /api/favorites`, `POST /api/enquiry`.
- Pricing service:
  - Implements `/app/memory/pricing_spec.md` exactly; constants from `settings`; computes both customs scenarios.
- FX service:
  - Live fetch with TTL cache; allow manual override in settings.

**Frontend (React + shadcn/ui)**
- Pages:
  - Search page: filter sidebar, listing grid, pagination, sort incl. landed/sale.
  - Detail page: photo gallery (hotlink), translated spec/description, options grouped, insurance/inspection/diagnosis panels, landed breakdown + profit range.
  - Favorites drawer/page; enquiry form.
  - Admin settings page (constants + FX override; guarded).
- i18n: BG/RO/EN UI strings + server-provided translated content.
- Currency switcher: EUR/BGN/RON (BGN fixed 1.95583; RON via FX).

**End of Phase 2:** run testing agent for full E2E (search→detail→translate→pricing→favorites→enquiry).

### Phase 3 — Hardening + feature expansion
**User stories**
1. As a user, I can save a search and get alerts when new matching ads appear.
2. As a user, I can see “last synced” freshness and sold/unavailable status clearly.
3. As an admin, I can change pricing constants and see immediate repricing.
4. As a user, I can report bad translations and get corrected text.
5. As an operator, I can monitor sync/429 rates and error budgets.

- Add saved searches + (optional) email/telegram alerts.
- Add observability: sync metrics, 429 handling stats, dead-letter retries.
- Add translation QA tools (flag/edit overrides).
- Optimize indexes (compound indexes for top filters/sorts).
- Optional: browser-extension companion (true per-user IP for API calls), if later required.

## 3) Next Actions (immediate)
1. Implement `/app/test_core.py` and run until 100% PASS.
2. Create MongoDB collections + indexes used by the POC.
3. Implement catalogue sync worker with `limit=500` and backoff.
4. Build FastAPI endpoints `/api/search` and `/api/car/{id}` using cached data.
5. Build minimal React UI (search + detail) and wire to backend.

## 4) Success Criteria
- POC: all endpoints + option resolution + translation caching + charm-up pricing assertions pass.
- V1: users can browse the full catalogue with fast search (DB-backed), open any detail, see translated content, options, insurance/inspection/diagnosis, and landed/sale pricing.
- Upstream load stays low: full sync completes reliably (≈436 requests per run) with 429-safe backoff; user searches cause 0 upstream calls.
- Pricing matches `/app/memory/pricing_spec.md` exactly with charm-up; constants editable without redeploy.
