# Encar Localised Skin — PRD

## Original problem statement
Create a fully translated skin for encar.com in Bulgarian, Romanian and English.
All current encar.com ads must be present. Do NOT proxy the Encar connection through our
own servers — the visitor's own IP must reach Encar (images load straight from Encar's
CDN). We only re-price cars based on our landed costs.

Product requirements: car search with filters, listing grid, full detail page (photos,
spec, inspection report, landed price breakdown), language switcher, caching translation
layer.

## Stack
- Frontend: React + Tailwind + shadcn/ui
- Backend: FastAPI
- DB: MongoDB
- Auth: Passkeys (py_webauthn) + Argon2 passwords
- Translation: Anthropic Claude (`claude-sonnet-5`, own key) → Gemini → Emergent
- Email: Resend (shared test sender until a domain is verified)

## Architecture
- `backend/server.py` — API routes, CORS, auth wiring, admin endpoints, FX watchdog
- `backend/encar.py` — polite upstream client (single slot, backoff, no IP rotation).
  `BASE_Q` restricts to `SellType.일반.` so lease/rental are filtered upstream.
- `backend/sync.py` — adaptive partitioned crawler (recursive facet splitting to beat
  Encar's 20k deep-pagination cap), dedupe pass, taxonomy build, brand coverage,
  `reprice_all` / `reprice_if_fx_drifted`
- `backend/pricing.py` — landed EUR price, charm rounding (rounds UP to a 99-ending price)
- `backend/fx.py` — rates + the exchange buffer (see below)
- `backend/translate.py` — cached LLM translation + circuit breaker
- `backend/mailer.py` — Resend, fire-and-forget
- `backend/auth.py`
- Operator scripts: `warm.py`, `warm_status.py`, `fxcheck.py`, `reprice.py`, `seed_admin.py`
- `frontend/src/pages/` — SearchPage, CarDetailPage, LoginPage, AccountPage, SavedCarsPage,
  AdminPage
- `frontend/src/components/` — CarRow, CarCard, PhotoSwiper, Hero, EnquiryDialog,
  NavDrawer, TaxonomySelects, DescriptionPanelBody, `admin/*`

## Pricing model
`encar_eur = price_krw / fx_krw_eur` → `+ $2,900 Autowini fee` → `customs_base = 18%` →
`duty 10%` → `VAT 20%` → `+ €1,600 domestic` = **landed** → `+ margin (max(1.4%, €500))`
→ charm-rounded **UP** to a 99-ending price = **suggested sale**.

### Exchange buffer
`fx.HAIRCUT = 0.995319` is applied to the market EUR/KRW rate. A LOWER KRW-per-EUR means
each car costs slightly more euros, which is the buffer. `fx_krw_eur_market` (raw) is kept
next to `fx_krw_eur` (published) on every quote so the buffer is auditable. The haircut is
SKIPPED when an operator sets the rate by hand, so a manual override is never
double-discounted.

**Google Finance was investigated and rejected as the rate source.** It has no API, and
its quote page carries no stable hook — no `data-last-price`, no `data-source`/
`data-target`, no `aria-label`. The only marker available (`jsname="Pdsbrc"`) repeats for
~40 unrelated currency pairs on the same page, and a positional match returned **1,070.98**
for EUR/KRW instead of ~1,650 — a 54% mis-price across the whole catalogue, from markup
Google can reorder at any time. `open.er-api.com` is used instead (Frankfurter/ECB is
unreachable from this pod). The two mid-market quotes differ by ~0.5%, well inside the
buffer.

### Keeping stored prices in step
Listings store a precomputed `sale_eur` while detail pages quote live, so a rate move that
is not followed by a reprice makes the price JUMP when a buyer clicks a search row. Guarded
two ways:
- `fx.get_rates` flags `reprice_needed` when the fetched rate moves more than
  `REPRICE_EPS` (0.2%), comparing raw-to-raw so it is independent of the haircut.
- `server._fx_watchdog` refreshes the bundle every 30 min and lets
  `sync.reprice_if_fx_drifted` run the pass detached.
- Manual trigger: `cd /app/backend && python reprice.py`.

## Catalogue coverage (verified 2026-06)
| Metric | Value |
|---|---|
| Exportable ads on Encar (lease/rental excluded upstream) | ~210,250 |
| Ads held in our DB | 210,435 |
| Re-registered duplicate ads hidden | ~61,000 |
| Unique physical cars shown | 149,427 |

Only `일반` (regular sale) listings are indexed; `EXCLUDED_SELL_TYPES` drops 리스 (lease)
and 렌트 (rental) in BOTH import paths, and `BASE_Q` filters them upstream so they are
never fetched. Duplicate pairs were verified as genuine re-registrations (identical
make/model/badge/year/mileage/price, byte-identical photo paths). Our index can read
slightly ABOVE the upstream count because it still holds a few ads Encar has since retired.

## Translation status — COMPLETE
100% of distinct taxonomy values cached in all three languages (18,399 strings):
makes 62, models 1,260, trims 4,231, sub-trims 525. Note that taxonomy levels 3/4 store one
node per make/model/badge/sub-trim PATH, so 6,017 trim paths collapse to 4,231 distinct
values and 3,356 sub-trim paths collapse to 525 — count DISTINCT values, never nodes.
Check with `python warm_status.py`; top up with `python warm.py`.

Dealer descriptions are deliberately NOT auto-translated (long, unique per car, rarely
read). The visitor asks via a button; cached permanently. Because output length is the
bottleneck (~750 tokens for a 657-char description), this task uses the FAST model
(`ANTHROPIC_FAST_MODEL`, `claude-haiku-4-5-20251001`) and is **streamed** over SSE
(`GET /api/car/{id}/translate-description/stream`) so the first words land in ~0.7s
instead of after a 10-20s spinner. The non-streaming POST route remains as a fallback.
The SSE response must keep `X-Accel-Buffering: no` or the proxy buffers the whole stream.

## Admin (`/admin`, admin-only)
Guarded by `_require_admin` — admin session OR `x-admin-token` header (`ADMIN_TOKEN`,
default `encar-admin`). Three tabs: **Overview** (index size, crawl progress, translation
health, email status), **Brand coverage** (per-brand our-vs-Encar counts, Latin-script
labels, refreshed by one count-only upstream request per make), **Enquiries** (full inbox
with contact details, search, status filters and new/contacted/closed workflow).

## Email
Resend. On a new enquiry: notify the operator and acknowledge the buyer in their language.
Fire-and-forget so a lost email never costs an enquiry. **Two things still needed from the
owner:** `ADMIN_NOTIFY_EMAIL` (no notifications are sent until it is set) and a verified
sending domain — the shared `onboarding@resend.dev` sender only delivers to the address
that owns the Resend account.

## Recent (2026-06, latest session)
- Admin panel has a **Catalogue sync** tab: manual full-crawl button with a live progress bar
  plus an optional daily run at a chosen time/zone (currently ON, 03:30 Europe/Sofia).
- Description translation: prompt hardened for Bulgarian/Romanian grammar (owner chose prompt
  work over a bigger model), temperature 0.2, cached descriptions cleared, and the panel no
  longer collapses while the translation streams in.
- Photo swiper: one macOS trackpad flick now advances exactly one photo (momentum stream is
  treated as a single gesture), and the dot rail is capped at five sliding, animated dots.
- Mobile header: centred logo, hamburger on the right, theme toggle moved into the drawer.
- Language switch now switches currency (RO -> RON, BG/EN -> EUR) on every switch, not just
  on first load.
- Saved searches: `/searches` page (live match count, "N new since saved" badge, thumbnail
  of the newest match, rename/delete), reachable from both the desktop nav and the mobile
  drawer, stored locally for guests and synced to the account. Each record already carries
  an `alerts` flag for "email me when a new car matches this search".
- Language URL prefixes: every page lives under `/bg`, `/ro` or `/en`; bare and legacy URLs
  redirect to the detected language keeping path and query; per-page title, description,
  canonical and hreflang tags; generated `robots.txt` + `sitemap.xml`
  (`frontend/scripts/gen-seo.js` — re-run with the real domain at go-live).
- Car detail pages now open scrolled to the top.
- URL filters are English slugs (`?make=hyundai&model=all-new-tucson&fuels=diesel~electric`),
  resolved back to upstream values by `GET /api/meta/resolve`. Old Korean-value links and
  saved searches still work. Also fixed a duplicate-taxonomy bug that had every dropdown
  option listed twice.
- Passkeys are no longer offered on the registration form; a "Sign in faster next time"
  dialog appears after registration instead (only on devices with a platform authenticator).
  Email verification is deliberately NOT built — deferred by the owner until a sending domain
  is verified in Resend.
- Mobile car page: back arrow in the header, always-visible car bar (title/subtitle/price/
  save), no duplicated title block, enquiry button directly after the photos, and a white
  circular close button pinned to the top-right of the photo viewer at any scroll depth.
  Header back and menu buttons enlarged to 48x48.

## Fixed 2026-06 (this session)
- **Admin cost & margin on the car page**: the backend already returned an `admin` block for
  signed-in admins but NOTHING in the frontend rendered it. `CarDetailPage` now shows a
  "Cost & margin (admin only)" panel (`data-testid="detail-admin-pricing"`): Encar price in
  KRW, car cost, Autowini fee, duty+VAT, inland+buffer, landed cost (range when the two
  customs scenarios differ), sale price and margin. `pricing.admin_range` was extended with
  `price_krw / encar_eur / car_eur / autowini_fee_eur / duty / vat / domestic_total`.
  The panel now lists BOTH customs scenarios explicitly, per owner request: duty+VAT,
  landed cost and margin each on a 10% base row and an 18% base row. `admin_range` gained
  `taxes_low/high`, `landed_at_low/high`, `margin_at_low/high`, `floored_low/high`, and
  `price_car` now returns the full `secondary` scenario dict.
  Note: on cheap cars the USD 3,000 customs-value floor replaces BOTH percentage bases, so
  the two rows show the same number and a note explains why — that is correct, not a bug.
- **List price vs car-page price disagreed by ~EUR 100.** Rows serve the `sale_eur` stored
  at the last reprice while the car page quotes live FX; drift plus charm rounding moved the
  figure by one 100-step. `server.publish_prices()` now recomputes live in the same request
  and publishes the HIGHER of stored vs live on search, `/listings/by-ids` and the car page
  (owner's rule: never undercut the advertised price). Verified: 12/12 sampled cars match.
- **Dark-mode control backgrounds**: make/model/submodel/trim selects, the band they sit in,
  the sort select, the mobile filters/sort buttons and the filter panel + its inputs moved
  from `bg-card` (12% L, lighter) to `bg-background` (8% L) so they match the page. No change
  in light mode, where `--card` and `--background` are both white.

- **Makes and models are never localised.** They are proper nouns, so both are always
  resolved from the ENGLISH cache whatever the page language (BG was producing "Дайхацу",
  "Серия 2 Gran Coupe"; RO produced "Seria 3"). `translate.LATIN_FIELDS` covers the listing
  rows; `meta_taxonomy` uses English for levels 1-2; `meta_filters` uses English for makes;
  `car_detail` resolves manufacturer/model in English. Submodel/trim is still localised —
  question put to the owner, unanswered.
- **Placeholder ads blocked and purged.** Dealers park listings with sentinel values
  (Price 99,999 or 999,999 만원 = KRW 1bn+, Mileage 999,999 km), which priced out at
  EUR 667,499 / EUR 6.6m in the grid. `sync.skip_row` now drops them at import in both
  paths, and the 14 already indexed were deleted with their cached details.
- **Car page first view: 8.0s -> 0.8-1.5s.** Upstream was never the problem (detail 0.9s +
  4 documents in parallel 0.4s). The cost was the leftover-Korean pass calling Claude
  synchronously: per-car freeform strings (dealer branch, address, plate) can NEVER be a
  cache hit, so every first view paid ~6.5s of blocking LLM time. That pass is now
  cache-only; misses are scheduled in the background, the payload carries
  `translation_pending`, and the client refetches twice (4s, 8s) to pick them up. Repeat
  views stay at ~0.13s.
- **Photo swiper rebuilt on native CSS scroll-snap** (`PhotoSwiper.js`, ~150 lines, no
  carousel library), to the owner's specification:
  - scroller is `snap-x snap-mandatory` + `snap-start snap-always` per slide, so inertia,
    momentum and the snap animation are the browser's own
  - `touch-action: pan-x pan-y` (NOT `pan-x` alone, which kills vertical page scrolling as
    soon as a finger lands on a photo in the result list)
  - tap vs swipe: a 6px horizontal move marks the gesture as a swipe and the synthesised
    click is swallowed in the CAPTURE phase, so a swipe never opens the car
  - active slide from an `IntersectionObserver` at threshold 0.55 (no scroll listener, no
    flickering dots mid-swipe)
  - slide 0 loads eagerly (LCP), the rest wait for the first hover/touch/pointerdown
  - `.no-scrollbar` utility added to `index.css`; arrows and the detail page's thumbnail
    column drive the scroller with `scrollTo`/`scrollBy`, guarded by a 450ms lock so the
    observer's updates cannot restart the animation

- **Hover warms a car so the click is instant.** `lib/api.warmCar` holds the payload
  PROMISE per (id, lang) with a 5 min TTL, so a hover and the click that follows share one
  request; it also pulls the first full-size photo into the browser cache. `useCarWarm`
  arms after 280ms of sustained hover (a pointer sweeping the list warms nothing) and after
  120ms of touch, cancelled by `touchmove` so the start of a scroll flick is not mistaken
  for a tap. Measured: sweep = 0 requests, settle = 1 request, click -> car page rendered in
  **0.14s** with the hero photo already decoded. Retries bypass the cache via `forgetCar`.

- **Final CTA slide in the desktop row gallery.** After the 4 photos the deck ends on a
  panel — arrow, "Виж обявата" and a small "Натисни за отваряне" eyebrow, on a subtle
  gradient — so the visitor feels the end of the preview and gets an obvious way in rather
  than a "+26 photos" overlay. It only appears when there are at least 2 photos, the dot
  rail marks it with a wider accent dot, and the photo counter hides while it is showing.
  It is on BOTH layouts — desktop row and mobile card (the owner's "only desktop" referred
  to the viewport work, not the CTA). The viewport meta tag was not touched.
- **The whole ad card is clickable**, desktop row and mobile card: the root is the single
  click/keyboard target (Enter and Space), the heart and the "View details" button stop
  propagation, and the swiper's capture-phase guard still means a swipe never opens the car.
  New i18n keys: `viewListing`, `tapToOpen` (BG/RO/EN).
- **Reaching the last photo warms the car.** `PhotoSwiper` fires `onCtaReached` once the
  active slide is the final photo (one before the CTA panel), which calls the same
  `warmCar` used on hover. `useCarWarm` now returns `[props, warmNow]`. Verified on mobile
  and desktop: swiping photos 2-3 sends nothing, arriving at photo 4 fires exactly one
  request, and opening from there renders straight away.

- **Desktop car-page gallery chrome** (owner kept the existing 16:9 + full scrolling thumb
  column, only the chrome changed): arrows are invisible until the gallery is hovered
  (`group/photos`), the photo counter moved onto the image as a bottom-right pill reading
  "12/43 · Увеличи" (hover-only on desktop, always visible on mobile) and the row under the
  gallery is gone. `overscroll-behavior-x: contain` stops a trackpad flick from triggering
  the browser back gesture, and arrows now step from the slide they are already heading for
  while the observer stays quiet until `scrollend` (900ms fallback for Safari < 18) — 8
  rapid clicks land on slide 9, not 5. New i18n key: `zoom`.
- The CTA dot in the card rail is plain white like the others, not accent-coloured.

## Code review pass (2026-06)
Applied: seed password moved out of `seed_admin.py` into `backend/.env`
(`ADMIN_SEED_PASSWORD`, no default so a missing value fails the seed); stable React keys
for the two photo lists in `CarDetailPage` (thumb strip, lightbox) which had a real URL
available.

Rejected after checking the source — do NOT "fix" these again:
- The 18 flagged `is` / `is not` comparisons are all `is None` / `is not None`. That is the
  correct Python; switching them to `==` would be a regression.
- `_ANTHROPIC` (translate.py) is a module global initialised to `None`; `resp` is assigned
  in the `try` and the `except` path always raises; `pct` (syncjob.py) is assigned on every
  branch of an if/elif/else. No path leaves them undefined.
- No `console.*` statements exist anywhere in `frontend/src`.
- The four "empty" catch blocks are deliberate best-effort paths (favourites merge, saved
  search merge, the anonymous `/auth/me` probe, passkey list) and each already carries a
  comment. Logging an expected anonymous visit as an error would be noise.
- Index keys in `PhotoSwiper` dots and `CarGrid` skeletons are `Array.from({length})`
  placeholder lists with no other identity — index is the right key there.

Not done on purpose (would be a large, risky rewrite with no user-visible gain): splitting
`car_detail`, `build_query`, `normalise_row`, `SearchPage` and `CarDetailPage`, and the
exhaustive-deps sweep. On `SearchPage`/`AppContext` the omitted deps are intentional (URL is
the single source of truth); adding them mechanically invites render loops. Worth doing as
its own scoped task with the testing agent, not folded into a feature.

- **The sync no longer dies badly on a restart.** Measured first: during a live crawl the
  API is unaffected (search 0.33s vs 0.32s baseline, car page 0.14s) and the catalogue stays
  fully visible (149,379 results mid-crawl), so the sync does NOT take the site down. The
  real failure was the shutdown order — `client.close()` ran while the detached sync task
  was still writing, so it died with `InvalidOperation: Cannot use MongoClient after close`
  and left the job doc stuck on "running", jamming the Sync button until the next boot.
  Now `syncjob.stop()` cancels the task and records the interruption while Mongo is still
  open (called from `on_shutdown` before `encar.close()`/`client.close()`), and
  `resume_if_interrupted()` on startup picks the crawl back up ONCE (`resumed` flag, 6h
  window) so a restart mid-sync does not leave the catalogue half-refreshed, while a crash
  loop cannot turn into an endless crawl. Verified end to end: clean "catalogue sync stopped
  for shutdown" with no traceback, one "resuming the catalogue sync" on the next boot, and
  the admin panel correctly reporting `interrupted` in between.
  Note: `/api/admin/sync/status` is the LEGACY endpoint (old `run_full_sync` doc) and can
  report a stale "running"; the panel uses `/api/admin/catalogue-sync`.

- **The crawl resumes from the last completed slice.** `crawl_partitioned` now keeps resume
  state per run in `sync_state.catalogue_partition_resume`: `done` (slice query strings
  already written to the index, recorded only AFTER their rows land) and `plan` (bisection
  counts already probed). Both are stored as pair arrays because every key is a query string
  full of dots, which Mongo forbids in field names. On resume the walk skips done slices and
  reuses the cached counts, so it neither re-fetches nor re-probes the completed portion, and
  the doc is deleted when the crawl finishes.
  CRITICAL: a resumed run keeps the ORIGINAL `run_id`. The retire pass deactivates anything
  whose `last_crawl != run_id`, so a fresh id would retire everything the interrupted crawl
  had already indexed. If the interruption happened after the crawl (phase past "crawl"),
  the resume skips straight to the post-crawl passes. Progress adds the interrupted
  process's cars (`already`) to the in-process `seen`, so the bar does not jump backwards.
  Verified: seen 5151 → clean shutdown → "resuming crawl 20260803190948: 22 slices already
  indexed (5565 cars), 38 counts cached" → seen 6854, moving forward, API 200 throughout.

## Track my vehicle (2026-06)
Shipment tracking page shipped, wired for real data, nothing mocked.
- `backend/tracking.py`: Maersk Track & Trace Plus client per the integration playbook —
  client-credentials token cached in-process, `Consumer-Key` retained on every call,
  `GET /track-and-trace-private/events` by `equipmentReference` (container) or
  `transportDocumentReference` (B/L). Every response is cached in `tracking_cache`
  (15 min; AIS 30 min) because the quota is per consumer key (~120/min, 5,000/hour) and a
  buyer refreshing must never cost a call. DCSA events are normalised to
  `{code, when, estimated, location, vessel, voyage}`; ETA prefers the forecast `ARRI` at
  the destination port over the trailing gate-out. Vessel position comes from
  MarineTraffic/Kpler when a key is present and is never fatal when it is not.
- Endpoints: `GET /api/tracking?ref=&by=container|bol`, and per-account saved shipments
  (`GET/POST /api/tracking/saved`, `DELETE /api/tracking/saved/{ref}`, max 20, stored on
  `users.tracked_shipments`).
- `frontend/src/pages/TrackPage.js` at `/:lang/track`, in the header and drawer nav:
  container/B/L toggle, status, ETA, last event, vessel card with an IMO link, milestone
  timeline (dashed markers for forecasts) and saved-reference chips for signed-in users.
  Shipping event copy lives in the page (`EVENTS` per language), not in i18n.
- WAITING ON CREDENTIALS. Without them `/api/tracking` returns `{"configured": false}` and
  the page shows an honest "tracking is not connected yet" card — no fake data anywhere.
  Needed in `backend/.env`: `MAERSK_CONSUMER_KEY`, `MAERSK_CONSUMER_SECRET` (and
  `MAERSK_BASE_URL`/`MAERSK_TOKEN_URL` pointing at `api-stage.maersk.com` while testing),
  plus `MARINETRAFFIC_API_KEY` (and `MARINETRAFFIC_URL` if the Kpler endpoint differs from
  the classic `exportvessel` one).
- Verified: honest not-connected state, validation (`by` must be container|bol), and a
  render test with a real DCSA-shaped payload seeded into the cache — 9 milestones, status
  in_transit, ETA ARRI Piraeus, vessel MAERSK SELETAR IMO 9525338, zero console errors.
  The seeded doc and the placeholder key were removed afterwards.

## Backlog
### P0 (blocked on the owner)
- **Price drop alerts** — agreed shape: the BUYER gets the email (no admin copy), on ANY
  drop in the final landed price of a car saved to their account, batched into one message
  per user. Still needed before it can ship: the owner's email address for testing
  (`ADMIN_NOTIFY_EMAIL`) and, for real buyers, a domain verified in Resend — the shared
  `onboarding@resend.dev` sender only delivers to the Resend account owner.
- **New-match alerts for saved searches** — owner said yes; the data already has the flag.

### P1
- **Language URL prefixes** — DONE (2026-06): `/bg`, `/ro`, `/en` on every route, redirects
  for bare and legacy URLs, canonical + hreflang tags, generated robots.txt and sitemap.xml.
  Remaining: re-run `frontend/scripts/gen-seo.js` with the real domain, and consider
  server-rendered pages if listing-level SEO ever matters.
- **Track my vehicle** — Maersk container + MarineTraffic vessel. BLOCKED on API keys.
- FX policy options offered to the owner but not yet chosen: pin the rate daily instead of
  live, and/or change charm rounding (off, or nearest €50/€100 instead of x99).

### P2
- Price-drop email alerts for saved cars (Resend key is already in place)
- Row comparison tool on the desktop list view
- Hoist the dealer-description translation cache into context so revisits are instant

## Reference
- Test credentials: `/app/memory/test_credentials.md`
- Implementation log: `/app/memory/CHANGELOG.md`
- Test reports: `/app/test_reports/iteration_1.json` … `iteration_12.json`
