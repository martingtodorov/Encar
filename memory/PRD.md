# Encar Localised Skin — PRD

## Original problem
Fully translated Bulgarian/Romanian/English skin for encar.com that bypasses own servers for
Encar (uses the visitor's IP), with:
* car search + filters, list grid, full detail page, language switcher
* caching translation layer (self-learning dictionary, Haiku-first)
* Track my vehicle shipment tracker with vessel maps + container tracking
* recommendation / taste profile
* Stripe deposits (manual capture / pre-auth)
* Admin UI panels + CMS
* Eurosign QES contract generation
* Emergent-managed Google Auth
* strict GDPR compliance
* mobile.bg bot integration

## Domain (decided 2026-08-31)
`encareurope.com` is CANONICAL; `encareu.com` is a redirecting domain onto it. The app-level
half is implemented (`canonical_host_middleware` 301s aliases, preserving path + query) and is
inert until the env vars below are set at deploy time — preview must keep its own host:

    CANONICAL_HOST=encareurope.com
    REDIRECT_HOSTS=encareu.com,www.encareu.com,www.encareurope.com
    PUBLIC_SITE_URL=https://encareurope.com
    REACT_APP_SITE_URL=https://encareurope.com

Remaining (hosting-side, not code): point both domains' DNS at the app, and issue certificates
for both so the 301 can be served over HTTPS. Optionally route `/robots.txt` to
`/api/robots.txt` in nginx so it follows `PUBLIC_SITE_URL` automatically.

## Recently completed (2026-08-31 session) — full detail in CHANGELOG.md
* **PWA Liquid Glass tab bar finished**: blur down to 3px, saturation 112%, see-through
  white/dark tint, rim refraction layer (no chromatic aberration — added then removed on
  request), capsule lowered clear of the home indicator, ONE travelling active pill that
  slides between tabs, swells under the finger, and supports drag-to-scrub (release picks the
  tab). Long-press link preview disabled.
* **Dynamic Island / sticky-bar overlaps root-caused and fixed**: the island inset is now
  reserved once on `<body>`, the header has a constant height and publishes only `--header-h`,
  and dependent bars position themselves in pure CSS (no rAF scroll tracking). `DetailStickyBar`
  is `sticky` on mobile so it cannot separate from the sticky header during iOS overscroll.
* **Favourites + saved searches are SERVER-ONLY.** No localStorage copy at all; legacy keys are
  deleted on load; mutators no-op when signed out; a `hydratedFor` guard stops an un-hydrated
  empty list from wiping the account. Cookie policy updated accordingly (bg/ro/en).
* **Notifications**: banner recoloured to the install banner's red; signed-out visitors are sent
  to sign in instead of being offered push (nothing server-side exists to notify them about);
  new `NotifyConsentDialog` asks for push the moment a buyer signs in inside the installed app.
* **Lightbox zoom is ours, not the browser's**: native zoom disabled; pinch, double-tap, pan,
  wheel/ctrl+wheel, macOS Safari `gesturechange`, `+`/`−`/`0` keys and an on-screen −/%/+
  control. Native zoom disabled entirely in the multi-photo column.

## Awaiting user decision
* (none open — the domain question is settled above)

## Recently completed (earlier sessions)
* **Encar sync retire safety guard + submodel breadcrumb + one-line breadcrumbs** (2026-02-20).
  Root-caused why the live catalogue was dropping day after day: a silent Encar 407/5xx
  return would make `encar.count()` yield 0, the crawl walked 0 rows, and the retire pass
  then flipped every `active: True` listing to `active: False`. Two lines of defence:
  1) `encar.count()` returns `None` on transport failure (was 0), and `crawl_partitioned`
     aborts before the retire pass runs; 2) even if a scope legitimately answers 0, the
     retire pass refuses to run below `RETIRE_MIN_COVERAGE` (default 50%) of the previously
     active scope. Result surfaces `retire_skipped` + `retire_skip_reason`.
  * Files: `/app/backend/encar.py`, `/app/backend/sync.py`, tests in
    `/app/backend/tests/test_sync_retire_guard.py` (3/3 pass).
  * Breadcrumbs (`/app/frontend/src/components/Breadcrumbs.js`): last item is now a
    `<Link>` when `to` is provided (buyer can jump from a car back to the model search
    with one tap), year spans (`(2019-)`, `(2014-2021)`) are stripped from labels, and
    the trail is single-line with `overflow-x-auto` on mobile so it never wraps to two
    rows.
  * Submodel: `CarDetailPage.js` breadcrumb items now run Home > Make > Model > Badge.

* **HTML Sitemap page (`/bg/sitemap`, `/ro/sitemap`, `/en/sitemap`)** (2026-02-10).
  One indexable page listing every make and every model as real `<Link>` anchors so
  Googlebot can walk the whole catalogue in a single hop, distributing internal PageRank
  without executing JS. Available in all three languages — page chrome (title, intro,
  footer link) is localized while make/model labels stay in English (proper nouns).
  * Backend: `/api/sitemap/index?lang=bg|en` — flattens `taxonomy` (levels 1 + 2) into
    `{makes:[{value, slug, label, count, models:[{value, slug, label, count}]}]}`. Uses
    the permanent `cached_label_set` for make labels and `translate_cached_only` for
    model labels (both proper nouns, always Latin), so no LLM call is made at request
    time. Rejects RO with 400.
  * Frontend: `pages/SitemapPage.js` renders 3-column model grids under each make,
    plus a total count line ("62 makes · 1263 models"). Route registered at
    `/:lang/sitemap`. Guarded to return `<NotFoundPage />` for RO. Adds `navSitemap`
    / `sitemapTitle` / `sitemapIntro` / `sitemapCounts` to `i18n_pages.js`.
  * Footer: `content/company.js` gets a `langs: ["bg", "en"]` allow-list on the sitemap
    link; `SiteFooter.js` skips rows whose `langs` list excludes the current language.
  * XML sitemap: `/api/sitemap-static.xml` now includes `/bg/sitemap` and `/en/sitemap`
    with reciprocal hreflang alternates so Google discovers the new HTML sitemap.

* **Traffic counter — accurate weekly/monthly unique visitors** (2026-02-08).
  Discovered that daily-rotating salt made the week/month "unique visitors" numbers over-count
  a returning visitor once per day (up to 7× for week, 30× for month). Fixed by adding a
  second, longer-lived salt (`traffic_salt_long`, TTL 45 days) used exclusively for week/month
  aggregations, while the daily salt stays for live/today (maximum privacy). Old hits without
  `vl` fall back to `v` via `$ifNull` so no data gap on rollout; full precision after ~40 days
  as old hits expire.
  * Backend: `/app/backend/traffic.py` — `_long_salt()`, `visitor_digest_long()`, `vl` field
    per hit, `_window(key="v"|"vl")` with `$ifNull` fallback, new TTL index.
  * Tests: `/app/backend/tests/test_traffic.py` — 13/13 pass, includes new test for the long
    salt's own TTL and for `v != vl`.
  * Legal: `/app/frontend/src/content/legal.js` — cookie policy §5 (Статистика / Statistici /
    Statistics) and privacy policy §2.10 rewritten in BG/RO/EN to disclose the second salt;
    COOKIE_STAMP → v1.4, PRIVACY_STAMP → v1.5. Consent POLICY_VERSION unchanged (existing
    consent for the Statistics category still applies — this is a clarification, not a new
    tracker).

## 2026-09-01 — Description translation rewrite + AI cost monitoring (DONE)
* Dealer descriptions now go to the LLM as ONE whole text with the dedicated description
  prompt (was: chopped into comma-separated fragments and fed the UI-label prompt — the cause
  of the unreadable output). Cached by full-text hash + line level; streamed to the browser.
* Every LLM call is logged in `db.ai_calls` (tokens, model, purpose, cost, duration, errors).
* Admin tab "AI разходи": daily cost chart, breakdown by purpose/model, cache counters,
  $5/day budget with instant alert, evening report at 21:00 Sofia, report archive.
* Real invoiced amounts read from the Anthropic Admin API — needs `ANTHROPIC_ADMIN_KEY`
  (sk-ant-admin…) in the environment; without it the panel shows our own estimate only.
* Full detail in CHANGELOG.md.

## 2026-09-04 — Bounded upstream calls + emergency alerts to all admins (DONE)
* `/api/car/{id}` hung 125s (Cloudflare 524) and took the site to 502: back1 had no route to
  Encar (unfinished `deploy_nat.yml`) and interactive reads used the bulk-sync retry budget.
  Interactive Encar calls are now 12s x 2 attempts (~26s worst case).
* `watchdog.py`: probes egress / Encar / Mongo / Resend every 60s. Two failures in a row →
  web push AND email to every `is_admin` account (+ ADMIN_NOTIFY_EMAIL / OWNER_EMAIL),
  reminder every 30 min, all-clear on recovery. Incidents in `db.incidents`,
  `GET /api/admin/incidents`, red strip at the top of the admin Overview.
* Ansible: `tasks/wait_apt.yml` + `lock_timeout: 300` on every apt task; peer keys read via `delegate_to` (`peer_pubkey`) so split runs work; peer-key asserts
  in `deploy_nat.yml` so an unreachable host is named instead of a Jinja error.
* Full detail in CHANGELOG.md.

## 2026-09-05 — Seven confirmed production bugs from the 407 incident (DONE)
* `EncarUnavailable` separates "Encar says this car is gone" (404 only) from "Encar did not
  answer". Only the first may retire a listing — a CloudFront 407 used to mark live cars sold
  the moment a visitor clicked an uncached ad.
* Bounded interactive calls (12s x 2, ~26s worst case) + circuit breaker (4 failures = 60s,
  a 403/407/511 = 180s immediately).
* Index-only fallback for uncached car pages when upstream is down: real photos, model, year,
  mileage and price, `partial: true`, never cached as a permanent `car_details` record.
* `restore_false_sold.py` puts back rows retired during the incident; skips contract cars and
  stale `last_seen`, `--verify` confirms each against Encar.
* WireGuard selection is now by `ip rule uidrange` with `src` on the table-100 default; the
  fwmark design is removed and asserted against. `/etc/hosts` pin on api.encar.com removed.
* Full detail, measurements and the owner's remaining steps in CHANGELOG.md.

## 2026-06 — Landing template + sitemap canonicals + the taxonomy build (DONE, awaiting deploy)
From the owner's audit of the live site. Five findings, plus a sixth bug found while fixing them.

* **Landing template (1 315 pages, highest leverage)**: `Listings BMW | Encar Europe` (27 chars,
  inverted, no intent) → `BMW from Korea — final landed price | Encar Europe`; H1
  `Listings BMW` → `BMW cars from Korea`; description 39 chars → 120-160 naming the
  **inventory count and price range** (`_price_span`, one grouped read over the same query).
  Localised for bg/ro/pl/en in `prerender.T` and mirrored client-side in `SearchPage.LANDING`.
* **sitemap-models.xml stated every URL twice** (2 630 entries / 1 315 landings). ROOT CAUSE:
  the nightly sync calls `build_taxonomy` directly while a request can fire it through
  `refresh_taxonomy_if_stale`; both staged into the fixed `taxonomy_new`, so overlapping builds
  interleaved inserts and stored every node twice (doubling the dropdowns as well). Now: one
  build lock per event loop **and** a staging collection named per build, so interleaving is
  impossible. Plus a dedupe guard at serialisation.
* **BUG FOUND WHILE FIXING (worse than the sitemap)**: a rebuild recreates every taxonomy
  document from the aggregation, so the tree comes out with **no slugs** — and the on-demand
  refresh never re-assigned them. Every `/bg/bmw` landing (1 315 pages) 404'd until the next
  full sync reached its separate "slugs" step. Slug assignment is now part of the build.
* **26% of listing sitemap URLs were non-canonical** (the slug-less `/car/<id>` form): the slug
  was built from the RAW make/model, which is Hangul for a quarter of the catalogue and
  slugifies to nothing, while the page derives it from the latin values. The sitemap now
  resolves the latin labels cache-only (never any LLM work) and uses `_share_title` +
  `_car_slug` — the exact pair the canonical tag uses, trim included.
* **Car page description** 68 chars → 120-160, from fields already held: title, registration,
  mileage, fuel, gearbox, price, plus a history note when it would otherwise fall short.
  Backend `car_desc_tpl` + client `seoCarDescLong`, identical wording.
* **Primary `<loc>` is now the bg variant** (`/` redirects to `/bg`, so bg is the default
  locale a crawler ignoring alternates should walk); x-default stays English and all four
  languages remain enumerated as alternates.
* Tests: `tests/test_taxonomy_build.py` (4, including the actual race), sitemap canonical/dedupe
  cases in `tests/test_sitemap_limits.py` (7 total), landing + description cases in
  `tests/test_prerender.py` (15 total). 43 green across the SEO suite.

## 2026-06 — Car page speed: the side documents no longer block it (DONE, awaiting deploy)
Owner: "car detail page loading issues… при някои обяви… просто го направи по-бърз". Measured on
production: a COLD car took **5.4 s and 15.8 s** (`?refresh=1`, two runs). Cause found: upstream
is paced at one request every **1.2 s globally** (`EncarClient.min_interval`, one lock for the
whole process), and an uncached car made **five** paced calls before answering — `detail`, then
the insurance record, inspection sheet, diagnosis and factory options. None of the last four is
above the fold.

* `car_detail` now answers as soon as it has `detail`, writes the `car_details` document
  immediately (so the next visitor is instant too) with `sections_pending: True`, and finishes
  the four side documents in a background task (`_fetch_sections` / `_arm_sections`, guarded by
  an in-flight set so five visitors on one cold car queue a single fetch).
* A section set that comes back incomplete because upstream is unwell is **not** stored and the
  pending flag stays, so the next read re-arms the fetch — self-healing, and the permanent
  record never gets a half-empty row (the original reason it waited).
* `?refresh=1` keeps the old synchronous full fetch: an explicit refresh wants the whole truth.
* The page polls for the sections at 2 s / 4 s / 7 s / 11 s (it already had this machinery for
  `description_pending`), and the insurance/inspection panels say **"Зарежда…"** instead of
  "Няма налични данни" while `sections_pending` is on — a different, and untrue, statement.
* Tests: `tests/test_car_detail_two_phase.py` (3) with a fake paced upstream, asserting it
  answers BEFORE the sections land, that the flag clears, and that a failed fetch is retried.

**Lightbox photo preloading**: opening the viewer now pulls every photo into the browser cache
**one at a time**, starting at the photo on screen and wrapping (`hooks/usePhotoPreload.js`,
used by both `Lightbox.jsx` and the mobile photo column). Chained on decode rather than fired
in parallel, so the photo being looked at is never starved. Verified in a browser: 6 preloads
at 2.5 s, 13 at 8.5 s, climbing one by one.

## 2026-06 — Merchant Listings schema + sitemap size + deploy verification (DONE, awaiting deploy)
The owner verified production as Googlebot and got the plain 3 749-byte shell everywhere: the
prerender above was written but **never deployed** (nginx still served the SPA and back1 had no
`FRONTEND_SHELL`). Nothing was silently reporting that, so this round makes the failure loud
and finishes the schema work:

* **Sitemap size defect (real bug)**: `sitemap-listings-1.xml` was 62 759 055 bytes — 40 000
  URLs × ~1.6 KB (five hreflang alternates + up to five image entries) against Google's 50 MB
  ceiling, so the file could be rejected wholesale. `_SITEMAP_CHUNK` is now **10 000**
  (~16 MB/file, 25 files for the current catalogue); the index recalculates automatically.
  Guarded by `tests/test_sitemap_limits.py`.
* **Merchant Listings schema**: the car node is now `["Product","Car"]` with `sku`,
  `productID`, `brand`, `manufacturer`, `image[]`, `description`, `itemCondition`,
  `productionDate`, `dateVehicleFirstRegistered`, `vehicleConfiguration` and an `Offer`
  carrying price, currency, availability, url, itemCondition, seller and free
  `shippingDetails` for BG/RO/PL (delivery genuinely sits inside the quoted price). No return
  policy is claimed — nothing invented. `Organization` + `WebSite` are now on **every** page.
* **The price in JSON-LD matches the visible price**, including RON for `ro` (`_price_pair`).
  A mismatch is an automatic Merchant Listings rejection.
* **JSON-LD is built with `json.dumps`**, not glued strings: the first cut escaped values with
  `_e()` and turned every `&` in a photo URL into `&amp;`, which inside a `<script>` is a
  broken image URL to Google.
* **Watchdog check `prerender`** (critical): fetches `PUBLIC_SITE_URL/bg` and fails unless the
  HTML carries an H1, a canonical, JSON-LD and the `<main class="pr">` marker — so an
  undeployed or shell-less prerender shows up in Admin → Health instead of staying invisible.
* **`deploy_nginx.yml` verifies itself**: after the reload it fetches `/bg` **as Googlebot**
  and asserts H1 + canonical + hreflang + JSON-LD + the prerender marker, and asserts
  `/bg/car/00000000` answers 404/410. The deploy now FAILS instead of quietly leaving the SPA
  in place.

## 2026-06 — Server-side rendering for every public route (DONE)
Answer to the owner's SEO audit of encareurope.com. Owner's choices: render for ALL visitors
(not bots only), full scope at once, noindex **plus** fast cleanup (410) for junk filter URLs.

* `backend/prerender.py` — `GET /api/prerender?path=…` returns real HTML for every public
  route: unique title/description, self-referencing canonical, hreflang (bg/ro/pl/en +
  x-default), og/twitter tags (`og:type=product` + the ad's lead photo on a car), a robots
  meta, and REAL markup inside `#root` (H1, price, spec, photos, breadcrumbs, similar cars,
  make/model link blocks) plus Car/Offer + BreadcrumbList + ItemList + Organization/WebSite
  JSON-LD. React's `createRoot` clears `#root`, so the app takes over untouched.
* Honest status codes: unknown ad or unknown make slug = **404**, sold/retired ad = **410**,
  junk or empty filter URL = **410**, filter URLs = `noindex, follow` with the canonical
  pointing at the clean landing page, private routes = `noindex, nofollow`.
* nginx (`templates/nginx-encar.conf.j2`): extensionless paths → `@prerender`
  (`?path=$uri&$args`), `^~` on /api/ /static/ /fonts/ so the regex cannot touch them,
  `error_page 5xx = @spa` so a backend problem just serves the old SPA shell. Social
  crawlers still get `/api/share/*`. Config validated with a real nginx render + route matrix.
* The shell: `deploy_frontend.yml` pushes the built `index.html` to back1
  (`FRONTEND_SHELL={{ app_dir }}/shell/index.html`); fallback is an HTTP fetch of
  `PUBLIC_SITE_URL/index.html`. Re-read once a minute, cached per path 5–30 min in-process.
* Client side: `useSeo` gained `follow` and `ogType`; car pages are `og:type=product` and go
  `noindex, follow` when sold or unloadable; the search page is `noindex, follow` on any
  filter param, page > 1, zero results or a load error.
* **Soft-404 root-caused and fixed**: `/bg/junk-make` resolved to nothing, the URL mirror
  rewrote the address to `/bg`, App.js remounted SearchPage on the new path, `notFound` reset
  and the visitor got an indexable 200 home page. The mirror now stands down when `notFound`.
* `gen-lang-html.js` writes canonical + hreflang into each `build/<lang>/index.html`;
  `seo-landing.json` gained the missing **pl** entry (its absence crashed the postbuild).
* Tests: `tests/test_prerender.py` (11) + testing agent's `test_prerender_extended.py` (10),
  all green; iteration_46 report: 25/25 backend, frontend 100%.

## 2026-06 — Duplicate ads for one physical car (dedupe second pass, DONE)
Owner reported the same car twice in "Подбрани за теб". The shelf itself cannot repeat an id
(curated dedupes on `seen`, the popular/taste paths draw from one query), so the duplicate is
two Encar ads for one car that `dedupe_pass` missed: `vehicle_key` is parsed from the photo
path, and when a dealer re-uploads photos the re-registered ad gets a folder named after its
own id, so the key no longer matches the original. `sync.dedupe_pass` now runs a **second**
pass over the survivors keyed on make + model + badge + `year_month` + exact `mileage`
(mileage > 0 only), same keep-order (record → inspection → resume → photos → freshness).
Tests in `tests/test_dedupe_twins.py`. **Takes effect on the next sync, or immediately via
`POST /api/admin/dedupe`.** Still waiting on the owner's concrete example (the two ad ids) to
confirm this is the pair they saw.

## 2026-09-06 — Encar route is a setting, with auto-failover (DONE)
The residential proxy timed out at exactly 15s on every request while a direct call answered in
0.4s, the circuit opened, background syncs failed and the only cure was an env change + restart.
Now:
* `encar.py`: route MODE (`auto` | `proxy` | `direct`) decided at runtime. `switch_route()` does
  the three things that have to happen together — change the setting, throw away the cached
  `httpx.AsyncClient` (it holds the old proxy) and clear the circuit breaker, so the new route
  does not sit out the cooldown earned by the old one. Credentials are still never logged
  (`_scrub`); `status()` is credential-free by construction.
* **Auto-failover**: an opened circuit asks for the other route to be tried (`proxy ⇄ direct`)
  BEFORE anybody is woken up, at most once per 10 min (`FAILOVER_MIN_GAP`) so a dead upstream
  cannot flap. The switch is persisted, so a restart keeps it. Bug found and fixed while
  testing: `other_route()` used to offer `direct` when the mode was `auto` with no proxy
  configured — i.e. a failover to the route that had just failed.
* Persistence: `site_settings.encar_routing` (`mode`, `reason`, `changed_by`, `updated_at`),
  read on startup in `server.py`, written by `_store_encar_route` (registered via
  `encar.set_persist`).
* Admin API: `GET /api/admin/encar-route`, `POST /api/admin/encar-route` {mode} (audited,
  refuses `proxy` when `ENCAR_PROXY_URL` is unset), `POST /api/admin/encar-route/test` (one real
  upstream request, reports latency or the sanitized error).
* Admin UI: `components/admin/AdminEncarRoute.js` inside Admin → Overview → Здраве на системата:
  three mode buttons, current route, live breaker state (open/closed, seconds left, consecutive
  failures), the last auto-failover with its reason, and "Пробвай сега".
* Watchdog: new WARNING check `route` (an automatic switch in the last 24h is a warning, not an
  emergency — pages still serve); the critical `proxy` check now skips cleanly when the mode is
  `direct` instead of reporting the absence of a proxy as a failure.
* Backup permissions: already handled in `deploy_backend.yml` (`{{ backup_dir }}` 0700
  www-data:www-data) — verified, nothing to add.
* Tests: `tests/test_encar_route.py` (6) incl. the failover with a dead transport and a
  no-credential-leak assertion; 46 green across the touched SEO/sync suites. Endpoints verified
  by curl on the preview host (407 from Encar there is expected: datacentre IP, no proxy).

## 2026-09-06 — Ask everybody again + the guest decision follows them into an account (DONE)
Owner: "almost all of our users have not been asked about personalisation and statistics… a
button for the admin which gives the users the pop up next time they visit" and "if a user who
is not logged in has consented, transfer his choice using the 90-day cookies so if he makes an
account in the upcoming 90 days we have his choice." The database agreed: 500 accounts, ZERO
consent records — a guest's decision lived only in their own cookie and nothing ever carried it
up.

* **Ask everyone again**: `POST /api/admin/consent/reask {on, note}` stamps
  `site_settings.consent_reask`; `GET /api/consent/policy` is public so every browser learns
  the stamp on its first page view. ONE timestamp, not a flag per person — a guest has no row
  of ours to flag. Any decision taken before it stops counting: `hasDecision()` is false so the
  blocking dialog opens, and `allows()` is false meanwhile so nothing optional is written while
  the answer is outstanding. Cancelling restores every decision already on record.
* **Admin UI** (`components/admin/AdminConsent.js`): "Ask everyone again" / "Cancel the
  request", the counters that matter (never decided / asked again and still waiting / carried
  from a pre-account cookie), and per-row "asked again — waiting" and "carried" badges.
* **The 90-day carry**: `save()` writes a SECOND copy of the decision to `ab_consent_carry`
  (90 days, exactly the retention asked for) alongside the 365-day `ab_consent`. On the first
  sign-in `AuthContext` calls `carryConsent(user)` → `POST /api/auth/consent`, which stores it
  with the visitor's OWN timestamp plus our `recorded_at` and `source:
  "pre_account_cookie"`, then drops the carry cookie. An older carried decision NEVER
  overwrites a newer one already on the account (enforced server-side), and a refusal is
  carried just as an agreement is.
* Tests: `tests/test_consent_reask.py` (7, module pinned to one xdist worker — the stamp is
  global). Frontend verified end to end by the testing agent (iteration_47): admin toggle both
  ways, an old decision reopening the dialog, ~90-day carry cookie on accept AND on reject, and
  a guest choosing statistics-only whose brand-new account came out with exactly that record,
  same timestamp, `source: pre_account_cookie`, carry cookie dropped.

## 2026-09-06 — Exterior colour filter + the three real sitemap gaps (DONE)
Owner: "add an exterior and interior colors as filters while keeping the same scraping" and
"why did you not do the new sitemaps, at least they have better formatting".

### Sitemaps — what was actually missing
The owner's list came from the other project (Shopify/PurePeptide). Checked item by item:
type-split index, dead URLs excluded, HEAD 200, cache headers and real `lastmod` on the
LISTINGS file were already here; the chunk is 10 000 rather than 5 000 on purpose (each
`<url>` weighs ~2.3 KB with four hreflang alternates and five images). Three gaps were real
and are now closed:
* **`lastmod` was TODAY, recomputed per fetch**, on the index, the static file and the model
  file — a claim that the whole site changed this morning, every morning. Each child now
  states its own clock: `_lastmod_pages()` (newest CMS edit), `_lastmod_taxonomy()`
  (`sync_state.taxonomy.built_at`), `_lastmod_listings()` (newest `last_seen`). Full W3C
  datetime to the second.
* **`image:title` on every photo and ONE `image:caption` on the lead photo**, in Bulgarian to
  match the primary `<loc>` (`_photo_caption`: registration + mileage + the delivered-price
  promise, from fields already in the row — no fuel/gearbox, which are raw Korean on a
  quarter of the catalogue and a sitemap must never trigger translation).
* **Pretty-printed** with real newlines and indentation; `s-maxage` added.
* Tests: `tests/test_sitemap_limits.py` now 12 — well-formed XML for all four files, the
  pretty-print shape, per-child `lastmod` (static ≠ listings), title/caption counts, and a
  BYTES-PER-URL projection onto a full chunk (preview holds few cars, so file size alone
  cannot guard the 50 MB ceiling).

### Colour — what the data actually allows
* **Exterior colour: yes, and without changing how we scrape.** The search feed we crawl
  carries no colour at all; only the per-car detail does (`spec.colorName`), and we hold a
  detail for <1% of the catalogue. But colour IS an upstream facet, exactly like transmission
  (`sync.MANUAL_Q`, which has worked for a year), so `sync.tag_colors` runs ONE id-only pass
  per colour on the same endpoint with the same pacing. The colours partition the catalogue,
  so the whole job is ~490 requests — about one extra sweep, not one request per car
  (245 000 requests / three days, which is what per-car detail enrichment would have cost).
  Runs nightly after `tag_transmission`.
* `COLOR_GROUPS` maps our 13 slugs to the Korean values Encar itself uses. **Every value was
  read out of real Encar data** in our own `car_details`, never guessed; a value Encar does
  not know returns Count 0 and its cars stay UNTAGGED rather than being filed under "other",
  which would turn a missing facet value into a false statement about the car. Coverage is
  reported so a gap shows up as evidence.
* Free half, no upstream cost: `_colors_from_details` folds in colours from details we
  already hold (it runs FIRST, so an upstream failure cannot lose it), and `_learn_color`
  writes the colour of any car a visitor opens. In preview that alone coloured 1 050 rows.
* Filter plumbing: `colors` in `SearchBody`/`build_query`/`_NARROWING`, `color` on every
  card, colour facets in `/meta/filters` and scoped counts in `/meta/facet-counts`,
  `GET /api/admin/colors` (coverage, per-colour counts, last run) and
  `POST /api/admin/colors/tag` (run it now — this is how the facet gets verified against
  live Encar). Index on `listings.color`.
* Frontend: swatch grid in `FilterSidebar` (fixed order, only colours the catalogue has,
  live counts), `?colors=black~white` in the URL, applied-filter chips, and labels in
  bg/ro/pl/en.
* **Interior colour: NOT possible — researched, not assumed.** Encar's data holds no interior
  colour anywhere we can reach: `detail.spec` has `colorName` + an always-null `customColor`;
  `inspection.master.detail.colorType` is a two-value PAINT-TYPE taxonomy (무채색) and null on
  80% of cars; `inspection.inners` is the mechanical self-diagnosis (engine, gearbox, leaks).
  Nothing was invented to fill the gap.
* **STILL TO VERIFY ON PRODUCTION**: preview cannot reach api.encar.com (CloudFront 407 to
  datacentre IPs), so the facet passes cannot run here — `POST /api/admin/colors/tag` honestly
  reports `ok:false` with the 407. On production: run that endpoint once, then read
  `GET /api/admin/colors`. If coverage is low, the Korean value list needs extending from what
  the response shows, not from guesswork.
* Tests: `tests/test_colors.py` (7). Testing agent iteration_47: 100% backend and frontend —
  colour narrowing, unknown colour = 0, union of two colours, scoped counts, reload from URL,
  deselect, chips, mobile panel and all four locales.

## 2026-09-06 — the deploy check no longer depends on one car being for sale (DONE)
Another session reported a hardcoded listing id in the deploy playbook. Checked: NOT in this
repository — no such id anywhere, `git diff deploy/` clean, the playbook runs
`python -m encar --verify` with no argument. That edit exists only on the server checkout.
But the concern was right about the wrong file: `encar.verify()` had a hardcoded DEFAULT id
(`42207598`), and the playbook does `assert encar_verify.rc == 0`, so the day that car sold, a
good release would have been blocked with "test vehicle is gone".
`verify()` now asks the CATALOGUE for its count — a question with no expiry date — and an
optional id is still accepted for hand debugging, where an authoritative 404 counts as
SUCCESS: a 404 is Encar answering, and a blocked route 407s, 403s or times out instead.
Tests: 4 added to `tests/test_encar_route.py` (10 total), covering the success path, a sold
car, a blocked route, and `count() == None` (a failed request, never a zero).

## 2026-09-06 — the colour pass was wired to the wrong job (FIXED)
Owner asked whether the catalogue sync also looks for exterior colour. It did NOT.
`tag_colors` had been hung off `sync.sync_all` — the legacy full sweep, which nothing
schedules. The job that actually runs nightly is `syncjob` (the partitioned catalogue crawl,
`catalogue_partition_*`), and it would have crawled every night while the colour filter stayed
frozen at whatever the cached details had taught it.
* `syncjob`: new `colour` phase between `manual` and `dedupe`, with its own weight and label
  ("Tagging colours") so a multi-minute phase does not look like a hung job.
* `crawl.py --all` / `--make`: tags colours too, scoped to the makes crawled.
* Guard: `tests/test_colors.py` now asserts the pass is referenced by BOTH the sync job and
  the CLI, that the phase is named in the progress bar, and that a colour query keeps the
  shared base filters (a pass without them would tag hidden and lease cars). 9 tests green.

## 2026-09-06 — hardcoded car ids in the deploy probes, and two bugs found while fixing them
Another session flagged committed hardcoded vehicle ids. **True this time**, and worse than
reported: `deploy_nat.yml` had TWO curl probes pinned to vehicle 42207598, one of them wrapped
in `assert stdout == '200'` ("that is the whole point of the home exit"). That car has since
sold, so api.encar.com answers 404 for it — a perfectly healthy home exit would have failed
the play. A third copy sat in `home-exit/setup-mac.sh` as a hint. All three now ask the
CATALOGUE for a count (`encar_probe_url`, percent-encoded exactly as `EncarClient.search`
builds it) — a question with no expiry date.
* Guard: `tests/test_deploy_probes.py` (3) fails on ANY `readside/vehicle/<id>` or
  `encar --verify <id>` under `deploy/`, and checks the probe URL still matches what the
  client itself would request.

### Two real bugs surfaced while fixing that
1. **A regression I introduced with the failover work**: `client()` rebuilt whenever
   `self._route != route()`, and `__init__` set `_route = None`. Tests inject a mock
   transport by assigning `c._client` directly, so the check threw the mock away and built a
   REAL client — 13 unit tests had silently become live network calls. `client()` now leaves
   a client it did not build alone (`_route is None`), and `close()` clears `_route`.
2. **The failover was firing on the wrong kind of failure.** A 403/407 means the route WORKS
   and Encar refused us; switching to `direct` then is worse than useless — if CloudFront
   blocks the residential address it blocks the datacentre one harder, and going direct puts
   the server's own IP in front of the blocklist that started the whole problem. Only a
   TRANSPORT fault (no HTTP status came back at all — the 15s proxy timeout that started
   this) now moves traffic: `_trip(..., failover=...)`, armed only from
   `_fail(..., transport=last_status is None)`. Test added for the block case.
* Suites green: `test_encar_proxy.py` 16, `test_encar_route.py` 11, `test_colors.py` 9,
  `test_deploy_probes.py` 3.
* NOTE on the full suite: 39 failures / 24 errors are PRE-EXISTING and environmental — the
  preview catalogue holds 6 cars because Encar answers 407 to this host, so every suite that
  needs the real catalogue fails on shapes like `assert 6 > 100000`. The endpoints themselves
  answer 200.

## 2026-09-06 — the mobile photo column: froze the phone, killed touch at the bottom (FIXED)
Owner, in his own words: "absolutely a fucked buggy mess", "it absolutely freezes", "when I
get to the bottom it disables all of my touch inputs", "when I get to the bottom too fast it
stops loading the photos". All four were real and all four had different causes. Measured on a
390x844 viewport with a 20-photo car before touching anything: twenty parallel CDN requests
the instant the viewer opened, plus a preload chain fetching the same twenty AGAIN, at
`rw=1600` (~8 MB of decoded bitmap each); 11 of 20 slots at zero height thanks to
`content-visibility: auto` + `containIntrinsicSize`; and the column's `scrollHeight` moving
from 2325 to 4509 while scrolling.

* **Resolution**: new `full_column` variant at `rw=800` (uncropped). The column shows a photo
  ~390 CSS px wide, so 800 is already 2x retina — roughly four times faster to land and a
  quarter of the memory. Full `rw=1600` stays for the pinch-zoom viewer, the one place the
  extra pixels are visible.
* **Loading** (`components/PhotoColumn.jsx`, new): a queue with a hard limit of TWO requests
  in flight. What the visitor is looking at (and the next few below) goes first, the rest is
  filled in from the top; nothing is skipped, nothing downloads twice, no `loading="lazy"`,
  and nothing is ever unloaded, so scrolling back up never re-fetches. The scheduler also
  runs on a 1.2s tick, so a stalled request or a cache hit that fires no event cannot wedge
  the queue — that wedge is exactly what "scroll down fast and it stops loading" was: the
  visible photo finishing used to drag the sequential cursor to the end of the list, which
  opened every slot in between at once. Measured after: peak 2 parallel, all 19 photos in
  ~3s, 17 requests for 19 photos.
* **Dead touch at the bottom**: while the dialog is open Radix locks the page behind it
  (`body { pointer-events: none; overflow: hidden }`), and the column was a centred
  `max-h-[92vh]` card — so reaching the last photo handed the scroll chain to a scroll-locked
  body and iOS stopped delivering touches. The viewer is now a true full-screen layer
  (geometry set INLINE, because the dialog's own utilities centre it with `left/top: 50%` and
  a translate) with `overscroll-behavior: contain` and `-webkit-overflow-scrolling: touch`.
  Side effect: the install banner can no longer show through around the card, so the close
  button lost its `mt-14` dodge.
* **No more layout jumping**: each slot reserves 4/3 and then takes the photo's real aspect
  ratio; a blurred `thumb` (already in cache from the card and strip) shows instantly instead
  of a black box. Measured after: zero zero-height slots, 0px scroll drift.
* **Silent warm-up** (owner's request): the detail page pulls the column's photos into cache
  in order, one at a time, 1.5s after load — skipped on `saveData` or a 2G link. Measured:
  all 20 warm before the viewer is opened, and it then opens with every photo already there.
* `usePhotoPreload` takes a `limit`; the swipe viewer warms 5 photos ahead instead of all 40.
* Verified on 390x844 and on desktop 1920 (zoom viewer, arrows, thumbnail strip, clean
  close, body styles restored).

## Encar upstream (2026-06)
* PRIMARY route now: sticky residential proxy (IPRoyal) via protected `encar_proxy_url` →
  `ENCAR_PROXY_URL`. Only api.encar.com; CDN/Stripe/Claude/Resend/GitHub direct. Owner must put
  the URL in an ansible-vault group_vars file (never chat/repo) and run
  `deploy_backend.yml --tags config,service`; deploy aborts before restart if Encar ≠ 200+JSON.
* Health: 17 watchdog checks in Admin → Overview ("Здраве на системата"), emergency push to all
  admins, email fallback.
* api.encar.com 407s all datacenter IPs; 200 from the owner's home. Encar calls go through the
  owner's Mac mini (third WireGuard peer, tinyproxy) via `ENCAR_PROXY_URL` — see
  `deploy/hetzner/home-exit/README.md`. STATUS: code + playbooks done, owner must run
  `setup-mac.sh`, set `home_exit_pubkey`, re-run deploy_nat + deploy_backend --tags config,service.

## Broken integrations (blocked on user)
* **Resend** — API key invalid in preview (owner says production has a valid one).
* **Anthropic** — API key returns 401. System silently falls back to the Emergent universal
  key (Gemini). If Haiku/Sonnet is required specifically, the user must supply a valid key.

## Open backlog (P0 → P3)

### P0 — none open.

### P1
* Real Reviews (#15): testimonials shelf on the home page with an admin moderation UI.

### P2
* Case studies (#6): 3–4 delivered cars as short "from Encar to Sofia" stories with photos and
  timeline.
* Team photo / About panel (#20) on the Contact page.
* Maps + Directions (#14): office map with "Get directions" button using the Google Maps link
  already in the CMS.
* Desktop row-comparison tool for the list view.
* Custom SVG for the Body Diagram (blocked — awaiting user file).

### P3
* Track my vehicle shipment tracker (full implementation).

## Architecture (unchanged)
* Frontend: React + shadcn/ui, `src/content/legal.js` for all legal texts.
* Backend: FastAPI, MongoDB (`translations`, `listings`, `label_sets`, `traffic_hits`,
  `traffic_salt`, `traffic_salt_long`), Motor.
* Translation cache: sha256-hashed source → `db.translations` (typed per surface), Haiku-first,
  identity cache for non-Hangul.
* Traffic: cookieless, two-salt scheme (daily + 45-day) with GDPR-legitimate-interest basis.
* Integrations: Google OAuth (Emergent), Stripe, JSONCargo, Resend, Anthropic (via emergent
  universal key when Anthropic own key fails).

## Files most likely to change next
* `/app/backend/server.py` (still ~4500 lines; refactoring candidate)
* `/app/frontend/src/components/admin/` (new AdminTestimonials.js for P1)
* `/app/frontend/src/pages/Home.js` (testimonials shelf placement)

## 2026-06 Mobile photo column zoom (in-place overlay)
* `ColumnPhoto.jsx`: removed the fixed full-screen black stage used while zoomed. A zoomed
  photo now stays in its own slot: the slot drops `overflow-hidden` and gets `z-index: 60`,
  so the magnified picture spills OVER its neighbours while the whole vertical column stays
  visible. Zooming back out (double tap / pinch out) restores the column exactly as it was —
  the slot never moves or resizes, so nothing reflows.
* Full-resolution file is still swapped in over the 800px column copy while zoomed.
* Verified with the screenshot tool: double tap -> data-zoom 2.50 with neighbours visible
  above/below; double tap again -> data-zoom 1, stage removed, slot box identical.

### Follow-up fixes (same session)
* Malката снимка отгоре: базовият `<img>` в слота се рисуваше СЛЕД зуум слоя (по-късен sibling
  = по-горе). Зуум слоят вече се рендира последен, а базовият/thumb слой е скрит докато е
  зуумнато (`opacity-0`).
* Touch навсякъде: зуумнатата снимка е `pointer-events-none`, а жестовете се хващат от
  прозрачен `fixed inset-0` capture слой (`{testId}-capture`) — пръст върху разлялата се част
  над съседните снимки вече мести същата снимка.
* Заклещен зуум: случаен двупръстов допир оставяше scale 1.05 (невидимо) → колоната спираше да
  скролва и close бутонът беше под слоя. Добавен SNAP = 1.2: всичко под това се връща на 1 при
  вдигане на пръста или при `pointercancel` (iOS отменя докосвания често).
* Close бутонът: sticky rail вдигнат от z-20 на z-[80], над зуум слота (z-60).

### Follow-up 2 (same session) — zoom core rewritten, column memory
* `ColumnPhoto.jsx`: жестовете вече са НАТИВНИ listener-и на самия слот (addEventListener в
  useEffect + refs), защото React сменяше prop-овете по средата на жеста и `pointercancel`
  се губеше → снимка заклещена на 1.05x (невидимо) със спрян скрол и close бутон под слоя.
  Добавени: PINCH_START = 1.15 (пинч под този праг не прави нищо — това е двупръстов скрол),
  SNAP = 1.25 (при вдигане/cancel всичко под това пада на 1), window-level pointercancel/blur
  като последна защита, imperative touchAction (pan-y в покой, none при 2-ри пръст/зуум).
* Зуумът се чисти при затваряне: `PhotoColumn` се монтира само докато `lightbox` е true
  (CarDetailPage), така че при повторно отваряне всички снимки са нормални.
* Crash при бърз скрол до долу: (1) `content-visibility: auto` на слотовете (изключено при
  зуум, защото носи paint containment), (2) IntersectionObserver вече комитва `looking` след
  140 ms престой — flick не стартира декодиране за всеки прелетял слот, (3) scheduler-ът
  стартира само индекси в реално рендирания прозорец и забравя започнатите, които са излезли
  от него; преди това стартирани-но-немонтирани снимки заемаха in-flight слотове по 9 s и
  зареждането спираше след бърз скрол.
* Проверено: flick до долу → само 6 декодирани снимки, всички резки; връщане нагоре
  презарежда горните; зуум/пан/затваряне работят. iOS crash-ът НЕ е репродуцируем в теста —
  чака потвърждение от устройството на потребителя.

### Follow-up 3 — scroll lock оставаше след затваряне със зуум
* Sticky X бутонът вика `setLightbox(false)` директно, без да минава през `onOpenChange` на
  Radix Dialog → `photoZoom` оставаше true → при повторно отваряне диалогът беше с
  `overflowY: hidden` и `touchAction: none`, т.е. без скрол. Флагът вече се чисти с ефект
  `useEffect(() => { if (!lightbox) setPhotoZoom(false); }, [lightbox])` в CarDetailPage.
* Проверено: зуум → X → отваряне отново → overflowY `auto`, touchAction `pan-y`, скролът
  работи (scrollTop 900), всички снимки с `data-zoom = 1`.
* ОТВОРЕН ВЪПРОС към потребителя: кой "друг lightbox с миниатюри отдолу" да се премахне за
  мобилни — `Lightbox.jsx` (в момента се отваря само при ≥1024px) или хоризонталната лента
  `detail-thumb-strip` под голямата снимка.

### Follow-up 4 — тап по status bar-а вече не връща колоната в началото
* CarDetailPage: `scrollerRef` на `DialogContent` + ефект, който отменя всяко движение
  НАГОРЕ на скрола без жест зад него (`el.scrollTop = keep`). Маркери: touchstart/move/end,
  pointerdown, wheel, keydown; grace 1500 ms, защото momentum скролът продължава дълго след
  вдигане на пръста. Ефектът чака ref-а през requestAnimationFrame, защото Radix монтира
  диалога един-два commit-а по-късно.
* Проверено: wheel надолу/нагоре работи, програмен скок към 0 без жест се връща на 1020,
  ръчен flick до горе работи, зуум/пан/скрол след това непокътнати.
