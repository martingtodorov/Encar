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
  Note: for cheap cars the USD 3,000 customs-value floor makes both scenarios equal, so the
  landed cost and margin show as a single figure, not a range — that is correct, not a bug.
- **Dark-mode control backgrounds**: make/model/submodel/trim selects, the band they sit in,
  the sort select, the mobile filters/sort buttons and the filter panel + its inputs moved
  from `bg-card` (12% L, lighter) to `bg-background` (8% L) so they match the page. No change
  in light mode, where `--card` and `--background` are both white.

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
