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
