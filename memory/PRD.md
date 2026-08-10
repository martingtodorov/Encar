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

## Recently completed (this session)
* **HTML Sitemap page (`/bg/sitemap`, `/en/sitemap`)** (2026-02-10).
  One indexable page listing every make and every model as real `<Link>` anchors so
  Googlebot can walk the whole catalogue in a single hop, distributing internal PageRank
  without executing JS. Owner asked for BG and EN only — Romanian version is intentionally
  404'd and its footer link is hidden.
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

## Broken integrations (blocked on user)
* **Resend** — API key invalid. Emails failing.
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
