# Changelog

Newest first. Verified = confirmed by the testing agent, report referenced.

## 2026-08-10 — Cost cut: line-cached descriptions + Haiku on the whole car-detail path
- New `translate_description_segmented()` in `translate.py`. Splits a dealer description
  on line breaks, serves every already-cached line from `db.translations` instantly and
  batches only the misses through Haiku in ONE call. Blank lines and decorative
  separator lines (▒▒▒, ▶, ━━━, etc.) are copy-through — they never spend a cache slot
  or an LLM token. Each newly translated line is upserted individually so the next
  dealer boilerplate line "무사고 차량입니다" that another car reuses costs zero.
- `HAIKU_MODEL` (default `claude-haiku-4-5-20251001`) is now honoured by every car-detail
  call: `translate_many(..., model=HAIKU_MODEL)`, `schedule_translation(..., model=HAIKU_MODEL)`,
  and the description streamer. Sonnet stays only for the post-crawl warm-up.
- `stream_description()` now streams through Haiku on the rare path where a description
  has no cached lines at all. The primary path is segment cache.
- Verified end to end: 20-line Korean dealer boilerplate → 1 batched LLM call → 14 rows
  written to `db.translations`. Second visit to the same car: 0 LLM calls.

## 2026-08-10 — Breadcrumb navigation fixes (merges + renames + display labels)
- Root cause 1: CarDetailPage was sending `car.model` (the DISPLAY label like
  "X5 (G05) (2019-)") to the search endpoint, which filters on taxonomy VALUE
  ("X5 (G05)"). Result: 0 cars.
- Root cause 2: For merged makes/models (e.g. "쉐보레(GM대우)" folded into "쉐보레"),
  the breadcrumb pointed at the folded child value, so only that tiny slice of cars
  showed up instead of the merged category.
- Root cause 3: `apply_translations()` walked the whole payload and rewrote Korean
  taxonomy values into their localised display, so the new `_raw` fields were being
  changed back to "Chevrolet"/"Cayenne" before they left the API — the search
  filter (which reads listings.manufacturer in Korean) then matched nothing.
- Root cause 4: React Router did not remount `<SearchPage />` when the pretty URL
  depth changed (`/bg/porsche/macan` → `/bg/porsche`), so the model filter stayed
  and the URL mirror wrote the model slug straight back.

Fixes:
1. `/api/car/{id}` now returns `manufacturer_raw` and `model_raw` set to
   `curate.root(level, listing.value)` — the merge-survivor Korean taxonomy value.
2. `NO_TRANSLATE_KEYS` gained `manufacturer_raw` / `model_raw`, so
   `apply_translations` leaves them intact.
3. `curate.refresh(db)` is called at the top of `car_detail` so the merge chain is
   available on every request.
4. CarDetailPage breadcrumb links carry the raw values as `?make=...&model=...`;
   SearchPage's URL mirror rewrites to the pretty `/{lang}/{makeSlug}/{modelSlug}`
   form once it knows the slugs.
5. `App.js` keys `<SearchPage />` on the pathname across all three routes it can
   serve, so any change in URL depth resets state.
6. SearchPage renders `<NotFoundPage />` when a pretty-URL make/model slug fails to
   resolve, replacing the silent "back to home" behaviour.

Verified in the preview:
- BMW X5 G05 detail → "X5 (G05) (2019-)" breadcrumb → 588 cars.
- Merged Chevrolet (GM Daewoo) Matiz detail → Chevrolet breadcrumb → 6 686 cars
  (both GM Daewoo and Chevrolet), Matiz Creative → 80 cars.
- Renamed Cayenne (PO536) detail → Cayenne (2019-) breadcrumb → 520 cars.

## 2026-08-10 — Launch checklist: 1, 2, 5, 8, 17, 19
- **Custom 404 (#1):** New `NotFoundPage` (`/app/frontend/src/pages/NotFoundPage.js`). Wired
  as the nested `*` under `/:lang` in `App.js`. Also: SearchPage detects an unresolvable
  make/model slug (e.g. `/bg/no-such-make`) and short-circuits to the 404 with
  `noindex, nofollow` + friendly Bulgarian/Romanian/English copy.
- **Secondary hero CTA (#2):** `Hero.js` now shows a second above-the-fold outline CTA
  linking to `/contact` (i18n key `heroContactCta`), sitting next to the primary
  "Start searching" button.
- **Breadcrumbs (#5):** New `Breadcrumbs.js` component. Renders `Home > Make > Model` on
  filtered search pages and `Home > Make > Model > Car title` on `CarDetailPage`. Emits a
  BreadcrumbList JSON-LD alongside so Google can build sitelinks.
- **Response-time promise (#8):** Owner-editable `response_hours` in Admin -> Company.
  Rendered in the footer as "We reply within 24 (business) hours"; a blank field falls
  back to a soft "usually within one business day" copy.
- **LocalBusiness / AutoDealer schema (#17):** SearchPage's home JSON-LD `@graph` now
  includes an `AutoDealer` + `LocalBusiness` node with address, phone, email, geo
  coordinates and Google Maps link — all pulled from the CMS company doc.
- **Google Analytics (#19):** GA4 measurement id is owner-editable (`ga_id` field in
  Admin -> Company). `analytics.js` refactored to accept the id at runtime via
  `configureAnalytics(...)`; `AppContext` calls it as soon as the CMS company payload
  arrives, so switching GA on no longer needs a rebuild. Consent gating is unchanged.
- CMS: `COMPANY_FIELDS` grew `ga_id`, `response_hours`, `geo_lat`, `geo_lng`,
  `google_maps_url`. Verified via curl (PUT `/admin/cms/company`, GET `/cms/site`).
- Smoke-tested via Playwright: 404 renders with correct `noindex` meta and Bulgarian
  copy; home shows the new CTA + response-promise footer + AutoDealer JSON-LD; `/bg/bmw`
  shows the "Начало > BMW" breadcrumbs with BreadcrumbList schema.

## 2026-08-10 — Multiple daily crawl times
- Admin catalogue-sync schedule now stores a `times[]` array (up to 6 slots) instead of a
  single `time`. The backend scheduler fires the crawl once per configured HH:MM per day
  using a `last_runs` map keyed by slot, so a 03:30 + 12:00 + 18:00 schedule triggers three
  independent syncs. `next_run_at` returns the earliest upcoming slot.
- Backwards compat: legacy `time` payloads and stored docs are auto-migrated to
  single-entry `times`. `PUT /api/admin/catalogue-sync/schedule` accepts either
  `{time: "HH:MM"}` or `{times: ["HH:MM", ...]}`.
- Admin UI (`AdminCatalogueSync.js`) grew "Add time"/remove-row controls; validation for
  bad HH:MM, empty list, and >6 slots returns 400. Verified via curl.

## 2026-08-09 (late night) — pretty search paths /bg/bmw/m2-g87 (VERIFIED, iteration_42)
Make/model now live in the URL PATH; everything else stays in the query string.
- `App.js`: `:makeSlug` and `:makeSlug/:modelSlug` routes declared last under `/:lang` —
  static segments (car, account, track…) always outrank a param segment, verified.
- `SearchPage`: path params overlay the initial state (query still wins if both present);
  `resolving` also true when a makeSlug arrives; the URL mirror builds
  `/{lang}/{makeSlug}/{modelSlug}?rest` via `slugFor` and `navigate(replace)`, falling back
  to query params for any value whose slug is not yet known. Legacy `?make=…&model=…` URLs
  self-redirect to the pretty path on mount.
- Junk path slug (/bg/some-junk-make): the resolver echoes unknown tokens by DESIGN (old
  raw-value links), so SearchPage now drops a PATH-seeded token that comes back unresolved —
  lands on /{lang} with the full catalogue. (Query-seeded raw values keep working.)
- Testing agent iteration_42: 12/13 pass; junk-slug fix applied + self-verified after; the
  reported "scroll not restored on Назад към резултатите" was a Playwright artifact (its
  auto-scroll-to-element before click zeroes scrollY in the nav state) — verified working
  with a JS-dispatched click: 700 → car → back → 700.
Canonical/hreflang follow the pathname automatically (lib/seo.js). Saved searches store
query strings and reopen fine (mirror prettifies). Frontend-only deploy.

## 2026-08-09 (round 7) — direct-CDN experiment reverted: share-debug proved the proxy WORKS
Live share-debug showed the full story: at 20:23Z and 20:40Z (og:image = /api/og/{id}.jpg)
the phone fetched share-car AND then the image — UA `com.apple.WebKit.Networking/21624…
macOS/26.5.2` — i.e. Apple's fetcher happily downloads from OUR domain. After round 5 went
live (og:image = bare ci.encar.com) the phone's image fetch became invisible and previews
kept failing: the direct Encar fetch dies on the device (ci.encar.com has NO AAAA record;
the owner's phone sits on Vivacom IPv6 — and whatever else Encar's edge dislikes about it).
- `share_car`: iMessage special-casing REMOVED — every crawler gets `/api/og/{id}.jpg` and
  the full tag set again (the round-3 shape Apple demonstrably consumed).
- `og_image` now also logs what it ANSWERED ("og-image-resp": "{id} -> 200, 104301b
  image/jpeg"), so /api/share-debug shows the whole exchange next time.
Tested locally: iMessage UA → proxied og:image; Apple WebKit.Networking UA → 200 jpeg;
both hits + response line visible in share-debug. Backend-only deploy needed.
NOTE for next round if STILL failing with confirmed 200s: try re-encoding the JPEG
(progressive vs baseline) and reading og-image-resp lines after the owner's test.

## 2026-08-09 (round 6) — the iMessage logo mystery SOLVED by the owner's screenshot
The failing preview read "BMW M2 M2 Coupe **· Encar**" — that " · Encar" suffix exists ONLY
in the frontend useSeo document title (the backend share page has no suffix). So the preview
was built from the LIVE SPA's runtime tags — the owner shares via Safari's share sheet, and
Messages takes whatever the open page advertises at that instant. Until the car data loaded,
useSeo's og:image fallback was the og.png LOGO → Apple snapshots early → logo. NOT Encar
rate-limiting, NOT nginx, NOT Cloudflare, NOT HTTP protocol.
Fixes:
1. **CarDetailPage useSeo now advertises `/api/og/{id}.jpg` from the very first render** —
   the id is in the URL, no need to wait for data; the logo window is gone entirely.
2. **"M2 M2" stutter deduped**: `_share_title` (backend) and `seoTitle` (frontend, feeds h1 +
   doc title) both collapse consecutive case-insensitive word repeats after joining. Unit
   checks: "BMW M2 M2 Coupe"→"BMW M2 Coupe"; Mercedes/Korando titles unchanged.
Verified in browser: og:image = /api/og/… BEFORE data loads and after; doc title + h1 clean.
Needs BOTH deploy playbooks (frontend + backend).

## 2026-08-09 (night) — make/model SEO titles + sort=relevant dropped from URLs
- `SearchPage` `useSeo` now builds a landing-page title/description when a make (and
  optionally model) is selected: bg "Обяви BMW 1 Series (E82) (2008-2013) | Encar",
  ro "Anunțuri …", en "… listings", description = same phrase + `seoCarDesc`. Labels come
  from `taxLabels` (translated, with generation years), raw URL value stands in until they
  load. No make selected → the old home title, untouched.
- `stateToParams` no longer writes `sort` when it is "relevant" (the default everywhere) —
  shared/indexed URLs are clean; a deliberate non-default sort still travels. Old URLs
  carrying sort=relevant keep working (paramsToState unchanged) and self-clean on the next
  state write.
- Verified in browser: /bg?make=bmw → "Обяви BMW | Encar"; +model → full title with years;
  sort absent in both; home title/og.png logo untouched (owner asked to confirm the logo
  was NOT removed anywhere — it was not, on any page).

## 2026-08-09 (evening) — H1 now carries model + submodel + trim; share-debug read
- **CarDetailPage h1** now renders `seoTitle` (the deduped "model grade badge_detail" string
  the document title already used) instead of the short `titleModel(car.title)`; the separate
  grade·badge_detail subtitle <p> was removed (it would duplicate). `seoTitle` gained the same
  parenthetical-filler filter the backend `_share_title` has — "(No detailed trim)" no longer
  leaks into titles. Verified in browser: h1 "KG Mobility Beautiful Korando Gasoline 1.5 2WD
  C5", doc title matches.
- **share-debug (live) finally read**: the owner's iPhone DOES hit `share-car` with UA
  "Mozilla/5.0 (Macintosh …) facebookexternalhit/1.1 Facebot Twitterbot/1.0" (Bulgarian ISP
  IPv6, 4 cars at 20:48–20:50Z) — nginx UA-routing WORKS for iMessage; it receives the bot
  HTML. NO og-image / image-proxy hits follow from that IP: with round-5 live the image URL
  is ci.encar.com (fetch invisible to us). Owner still reports the logo — so the phone either
  rejects/skips the Encar image or falls back to the apple-touch-icon. The SPA og.png is NOT
  what iMessage reads for car ads (proven), so removing it would not fix cars and would break
  the homepage's Facebook preview.
- Open question for owner: remove og.png backup anyway? Also still unresolved: title-flicker
  bug (not reproducible on preview or live with probes; may be settled by the longer h1).

## 2026-08-09 (round 5) — iMessage branch now copies AutoScout24, not mobile.bg
Owner: "autoscout works the best, scratch mobile". Inspected the AutoScout24 ad page + its
picture delivery: og:image is a QUERY-LESS `…/1920x1080.jpg` on `prod.pictures.autoscout24.net`
(CloudFront, outside the main site's bot protection) answering with Last-Modified, strong
ETag, `Access-Control-Allow-Origin: *`, `Content-Disposition: inline`, `bytes=0-` → 206; the
page carries a MINIMAL tag set (og:site_name/type/image/width/height/title/description — no
twitter:*, no secure_url/image:type/alt).
Matched both halves:
1. **iMessage UA branch in `share_car`** now emits the bare Encar photo path with NO impolicy
   query (`https://ci.encar.com/carpicture07/…_001.jpg` — the S3 original, 640×360, verified
   Last-Modified + 206 + no Referer needed) with TRUE width/height 640/360, and the tag set is
   trimmed to AutoScout's minimal profile for that branch only. Every other crawler keeps the
   full rich set and `/api/og/{id}.jpg` at 1200×630 — verified byte-identical for real
   facebookexternalhit / Twitterbot / Viber UAs.
2. **`_binary` now sends the AutoScout header profile** for all proxied images: Last-Modified
   (cache-file mtime, passed from og_image/image_proxy), If-Modified-Since → 304,
   `Access-Control-Allow-Origin: *`, `Content-Disposition: inline`.
Tested: iMessage UA → 10 minimal tags with clean CDN URL; FB UA → unchanged /api/og URL;
/api/og HEAD carries Last-Modified/ACAO/inline; IMS in the future → 304; map/track.png → 200.
AWAITING DEPLOY + fresh-URL iMessage test (share-debug from round 3½ is still in place).

## 2026-08-09 (round 4) — iMessage og:image now bypasses Cloudflare, copying mobile.bg
Owner pointed at a mobile.bg ad whose iMessage preview works. Inspected their delivery:
the page HTML sits behind an aggressive Cloudflare (403 to any datacenter client), but the
og photo lives on `mobistatic.focus.bg` — a PLAIN nginx static host OUTSIDE Cloudflare:
HEAD with Last-Modified, `bytes=0-` → 206, long-lived cache headers. That is the working
recipe: the sender's iPhone fetches the preview picture from a host with no bot filtering.
Encar's own CDN (`ci.encar.com`, S3) turns out to behave EXACTLY like that host: verified
200 with no Referer, Last-Modified, 206 on `bytes=0-`, 0.26s, and it answers even the
spoofed iMessage UA. The proxy only ever existed because DATACENTER crawlers (Facebook)
get refused — a real device does not.
`share_car` now detects Apple Messages by its self-contradictory UA (contains
`facebookexternalhit` AND (`twitterbot` OR `applewebkit`) — real crawlers never mention
each other) and hands IT the direct `ci.encar.com` og:image; every other crawler keeps
`/api/og/{id}.jpg` through our domain. Tested with 5 UAs: both iMessage variants → direct
CDN, real facebookexternalhit / Twitterbot / Viber → proxied URL, byte-identical to before.
AWAITING DEPLOY (Save to GitHub → pull → Ansible) and an iMessage test with a
never-before-shared car URL.

## 2026-08-09 (later) — iMessage still failing AFTER the round-3 fixes: instrumentation added
Verified on live (encareurope.com): the round-3 code IS deployed — og:image is
`/api/og/{id}.jpg`, no meta refresh, `bytes=0-` → 206, and the share HTML answers correctly
even to the exact historical Apple UA (`Mozilla/5.0 (Macintosh …) facebookexternalhit/1.1
Facebot Twitterbot/1.0`). Cloudflare does NOT cache the HTML (cf-cache-status: DYNAMIC on
both bot and human variants), so a UA-variant cache collision is ruled out. Every
server-side protocol theory is now exhausted; the blind spot is WHAT THE SENDER'S IPHONE
ACTUALLY RECEIVES (iMessage previews are fetched by the sender's own device — no debugger
tool exists for it).
Added `_hit()` + `GET /api/share-debug`: every request to share-car / share-track /
og-image / image-proxy is recorded in `share_hits` (TTL 7 days) with ts, method, UA, Range,
If-None-Match, Accept and a 2-octet-truncated IP. Tested locally: rows appear, JSON clean.
HOW TO USE after the owner deploys: owner shares a NEVER-before-shared car in iMessage,
then `curl https://encareurope.com/api/share-debug` and read what the phone asked for.
Decision tree: (a) no Apple-device rows at all → Cloudflare is blocking the phone's
bot-UA request (Bot Fight Mode / WAF) → fix in CF dashboard, not code; (b) share-car row
but no og-image row → the phone read the HTML but never asked for the picture → inspect
the exact UA/headers it sent; (c) both rows present with 206 answered → LinkPresentation
rejects the image content itself → try re-encoding (progressive vs baseline JPEG).
The preview screenshot also disambiguates: car title = HTML read, image refused; generic
"Korean cars…" title + big logo = the phone got the SPA (UA never matched at nginx);
bare domain + small icon = HTML fetch blocked outright.

## 2026-08-09 — iMessage preview: three remaining protocol deviations removed
Facebook/Meta previews confirmed working on live by the owner; iMessage still fell back to
the site logo. Verified live (encareurope.com, behind Cloudflare) already runs the Range/206
refactor — HEAD carries real Content-Length+ETag, bytes=0-1023 answers 206. Three deltas
remained between our answers and what Apple's on-device fetcher (UA
`facebookexternalhit/1.1 Facebot Twitterbot/1.0`, fetches from the SENDER'S iPhone, not an
Apple server) tolerates:
1. **`Range: bytes=0-` answered 200, not 206.** `_binary` deliberately downgraded a range
   spanning the whole file to a plain 200; CFNetwork reads that as "server does not do
   ranges" after `Accept-Ranges: bytes` was advertised on the HEAD. Now ANY valid Range
   header gets 206 + Content-Range, whole file or not ("bytes=-" alone is not a range).
2. **og:image was one long percent-encoded query string with no file extension**
   (`/api/image-proxy?url=https%3A%2F%2Fci.encar.com%2F…`). New route
   `GET/HEAD /api/og/{listing_id}.jpg` serves the SAME cached 1200×630 lead photo under a
   clean .jpg path; `share_car` warms the photo exactly as before and points og:image /
   twitter:image at the new URL. `/api/image-proxy` stays for the gallery.
3. **`<meta http-equiv=refresh content="0;url=SAME_URL">` removed from both share pages**
   (car + track). TN2444: metadata must stand without redirects; an instant self-refresh
   reads as a redirect loop to strict fetchers. The JS `location.replace` + plain link keep
   forwarding humans.
Tested with curl on localhost AND the preview URL: og:image now `/api/og/{id}.jpg`, no
http-equiv anywhere, GET 200 valid JPEG 1200×630, HEAD real length, bytes=0- → 206
full-body Content-Range, bytes=0-1023 → 206, missing photo → 404.
AWAITING DEPLOY: Save to GitHub → git pull → Ansible. When re-testing iMessage use a car URL
never shared in that conversation before — Messages caches a failed preview per-URL.
If it STILL fails after deploy, the next suspect is Cloudflare challenging Apple-device TLS
fingerprints carrying a bot UA (Bot Fight Mode) — check CF Security Events, not nginx logs.

## 2026-06 — Desktop header nav + car detail gallery and sticky bar
Verified (iteration_15): 100%, 46 UI assertions across 1600/1920/1280/390 widths.
- **Desktop navigation is now inline in the header at all times.** On a wide screen there
  is room for it and a drawer costs a click per move, so `HeaderNav` (links, language
  pills, theme toggle, and either account+Operations or login+register) shows at `lg` and
  the hamburger `NavDrawer` is mobile-only. The owner supplied a reference screenshot of
  another site's header for the LAYOUT pattern; it was implemented with our own Encar
  palette and components rather than reproducing their branding.
- **Detail main image is smaller on desktop but still a true 16:9.** First attempt used
  `object-cover` inside a fixed-height row and squashed the photo to ~2.4:1, which the
  owner rightly rejected. Now the image keeps `aspect-[16/9]` at
  `lg:w-[calc(100%-226px)]`, so its own height defines the row, and the `<img>` box
  matches its container exactly — nothing is cropped.
- **Thumbnails moved beside the main image and got much bigger** — 214x120, up from
  96x64. The strip is `lg:absolute lg:inset-y-0 lg:right-0` so it is pinned to the main
  image's height and scrolls internally (scrollHeight 3330 vs 566 client) without
  stretching the page. Mobile keeps the stacked layout with a horizontal strip.
- **Desktop prev/next arrows** on the main photo (`arrows` prop on `PhotoSwiper`), since
  dragging is an awkward gesture with a mouse. They `stopPropagation` so they do not also
  open the lightbox.
- **New sticky detail bar** with the make/model, sub-model, price and favourite button.
  Deliberately `fixed`, not `sticky`: a sticky element stays in normal flow and was
  reserving its full 64px height under the header even while invisible, which was the
  cause of the excess whitespace above "Back to results" (73px → 8px).

## 2026-06 — Faster description translation + UI consistency
- **Dealer-description translation felt like a 10-20s hang; now first words appear in
  ~0.7s.** Measured the cause rather than guessing: a 657-char Korean description
  generates ~750 output tokens, and Sonnet took 16.9-20.7s, so output length was the
  floor — no amount of prompt tuning would fix it. Two changes: the task moved to the fast
  model (`ANTHROPIC_FAST_MODEL`, `claude-haiku-4-5-20251001`), and the translation is now
  **streamed** over SSE (`GET /api/car/{id}/translate-description/stream`) so text appears
  as it is generated. Verified (iteration_13): first text 0.6-0.9s, 99+ SSE frames, cached
  hits 0.15s, cache survives reload. Total completion is still 21-23s on the longest
  descriptions — that is generation-bound, but it is no longer dead time.
  - `X-Accel-Buffering: no` was required or the proxy held the whole stream back.
  - The frontend SSE parser keeps partial frames in a buffer, so a chunk split across TCP
    reads is never lost or double-appended.
  - Uses plain prose rather than the batch JSON envelope, so there is nothing to parse
    before text can be shown. Falls back to the non-streaming POST if the stream fails.
- **Shadows had been painting nothing app-wide.** The testing agent found (iteration_13)
  that `shadow-[var(--shadow-sm)]` makes Tailwind read the `var()` as a *colour* and emit
  an EMPTY `box-shadow`, so the class was silently invisible — 25 usages across 16 files,
  not just the controls being styled. Fixed at the source: the design tokens are now
  registered as the Tailwind shadow scale (`boxShadow.sm/md` → `var(--shadow-sm/md)`) and
  every broken usage replaced with plain `shadow-sm`/`shadow-md`, so the broken form cannot
  come back. Verified (iteration_14): 100%, the token now paints on every control, card,
  admin panel and dialog. **Never reintroduce `shadow-[var(--shadow-*)]`.**
- Make/Model/Submodel dropdowns, the Filters button and the sort dropdown now share
  `rounded-[10px]`, `border border-input` and `shadow-sm`.
- On mobile the Filters button moved into the taxonomy grid, in the same row and to the
  right of Submodel, instead of sitting down in the results header. Implemented as a
  `trailing` prop on `TaxonomySelects` so the button joins the same grid flow; hidden on
  desktop where the sidebar is used.
- Added an sr-only `SheetDescription` to the filter sheet, clearing a Radix a11y warning.

## 2026-06 — Exchange buffer + a price-consistency bug it exposed
- **Exchange buffer applied to EUR/KRW.** `fx.HAIRCUT = 0.995319` (0.4681% held back).
  Market rate 1,653.545 → published 1,645.805. `fx_krw_eur_market` is kept alongside
  `fx_krw_eur` on every quote for auditing. Skipped when a manual override is set, so an
  operator's rate is never double-discounted. Verified (iteration_12).
- **Google Finance rejected as the rate source** after investigation — see PRD for the
  full reasoning. A positional scrape returned 1,070.98 instead of ~1,650 (a 54%
  mis-price). Caught by a cross-check against the reference feed before it shipped.
- **CRITICAL bug found and fixed: search rows were €100 below detail prices.** Listings
  store a precomputed `sale_eur`; the catalogue had never been repriced after the buffer
  shipped, so rows quoted the unbuffered rate and the price jumped when a buyer clicked a
  car. Repriced all 210,435 listings; all sampled cars now match.
- **Guarded against recurrence.** `fx.get_rates` flags `reprice_needed` on a >0.2% raw
  rate move; `server._fx_watchdog` refreshes every 30 min and lets
  `sync.reprice_if_fx_drifted` run the pass detached. Added `reprice.py` as the manual
  trigger. Without this the drift would have returned on every rate move.
- Fixed duplicate React keys in the photo thumbnail strip and lightbox (keyed by index —
  car 41995353 lists the same photo URL twice). Added an sr-only `DialogTitle` and
  `DialogDescription` to the lightbox for accessibility. Console is now clean.
- Corrected `warm_status.py`, which had been overstating outstanding translation work by
  counting taxonomy PATHS instead of distinct values.
- **Translation coverage reached 100%** on Claude: 62 makes, 1,260 models, 4,231 trims,
  525 sub-trims across bg/ro/en — 18,399 strings, zero rate-limit failures.

## 2026-06 — Swipeable photos, vertical lightbox, manual description translation
Verified (iteration_11): 100% backend, 90% frontend.
- **`PhotoSwiper`** — finger-tracking carousel on result cards, result rows and the detail
  page's main photo. Locks its axis once per gesture so vertical page scrolling still
  works, rubber-bands at the ends, and treats <8px in <500ms as a tap so the same surface
  still opens the car. `listing_out` now ships an `images` array.
- **Vertical photo column** — tapping the big photo opens every photo stacked in one
  scrollable column on black, separated by thin bars.
- **Manual dealer-description translation** — button ABOVE the text, one on-demand Claude
  call via `POST /api/car/{id}/translate-description`, cached permanently, with a
  show-original toggle. Descriptions are never auto-translated on page load.
- **`/saved` made fast** — new `POST /api/listings/by-ids` reads grid rows straight from
  our index. It previously called `/car/{id}` per favourite, pulling detail, insurance,
  inspection and diagnosis from Encar for data the grid never shows. 0.83s, was ~6s.

## 2026-06 — Admin Operations area + Resend email
Verified (iteration_10): 100% both.
- **Sync dashboard** (`/admin`) — index size, crawl progress, translation health, Encar API
  error count, email status with a warning while the shared sender is in use.
- **Brand coverage** — per-brand our-vs-Encar counts with Latin-script labels, measured by
  one count-only upstream request per make (~62, paced). Established that Encar's API
  accepts a `SellType.일반.` facet, which makes the comparison exact.
- **Enquiry inbox** — every enquiry with car, contact details and message; search, status
  filters, and a new/contacted/closed workflow.
- **Resend wired** to the enquiry form: operator notification + buyer acknowledgement in
  their own language, fire-and-forget so a lost email never costs an enquiry.
- Seeded an admin test account. Note: pydantic's `EmailStr` rejects reserved TLDs, so the
  first seed on `.test` could never log in (422) — recorded in test_credentials.md.

## 2026-06 — Four search/detail fixes
Verified (iteration_9): 100% both.
- **Back to results no longer wipes filters.** Root cause was a hardcoded `<Link to="/">`
  on the detail page which dropped the query string; the remounted search page then wrote
  its own `?sort=newest`. Opening a car now carries the live search in navigation state,
  with `navigate(-1)` and `/` as fallbacks for cold/shared links. `SavedCarsPage` moved off
  `window.location.href` so Back works from there too.
- **Diagnosis panels read as words** — `_panel_label()` turns `FRONT_DOOR_LEFT` into
  `Front door left`.
- **Save button** moved inline with the price, to its right, and later reduced to an
  icon-only heart.
- **Auto-sort rules** — nothing or make-only → newest; model or trim → price ascending. A
  manually chosen sort is never overridden; `resetAll` clears the flag.
- Removed the landed-price breakdown panel from the detail page, and the divider between
  the taxonomy selects and the filters panel, both by request.

## 2026-06 — Lease and rental excluded entirely
- Lease (리스) was already dropped by the partitioned crawler, but **rental (렌트) was not**,
  and the legacy sequential sync filtered neither — 2,404 rental cars were live in search.
  Added `EXCLUDED_SELL_TYPES` to both import paths, purged the 2,404 rows, rebuilt the
  taxonomy. Later moved the filter upstream into `BASE_Q` so they are never fetched at all.

## 2026-06 — Counters and dropdown freshness
- **Catalogue counter** was frozen at the last crawl's snapshot. Added
  `GET /api/catalogue/size` (15-min cache) and, per the owner, the hero now shows OUR
  inventory (`unique_cars`) rather than Encar's ad total, with `indexNote` reworded in all
  three languages.
- **Dropdown counts** were frozen for up to a week. `TAXONOMY_TTL_DAYS = 7` became
  `TAXONOMY_TTL_HOURS` (6), and `refresh_taxonomy_if_stale()` rebuilds in the background
  while serving the older tree, so nobody waits on the ~30s aggregation. Verified: request
  returned in 0.24s while a 10,725-node rebuild ran behind it.
- **Claude became the primary translator** (`_anthropic_call`, honours `retry-after` on
  429, SDK retries disabled so backoff isn't doubled), unblocking the warm-up that
  Gemini's free tier had been rejecting.
- Established that Encar's ~217k headline is ADS, not cars: ~5k lease/rental are excluded
  and ~61k are re-registered duplicates of the same physical vehicle.

## 2026-06 — Trackpad swipe and dot rail
- **One flick = one photo.** The wheel handler used a fixed 320ms cooldown, but macOS keeps
  emitting momentum wheel events for ~1s after the fingers lift, so a single flick fired
  again after every cooldown (three photos per swipe). Replaced the cooldown with
  gesture-stream detection: after advancing, all further wheel events are ignored until the
  stream goes quiet (no event for 140ms). A quiet gap starts a fresh gesture and resets the
  accumulator; a direction reversal also resets it. Touch drag and arrows untouched.
  Verified with synthetic 14-event momentum bursts: 1/4 -> 2/4 -> 3/4 -> 2/4 on reverse.
- **Dot rail capped at five dots** (`DotRail` in `PhotoSwiper.js`). Longer galleries slide
  the rail so the active dot stays centred, animating on each swipe; inactive dots sit at
  0.72 scale / 50% opacity. Verified on a 30-photo detail gallery.

## 2026-06 — Mobile header and market currency
- **Mobile header rebuilt**: logo is now optically centred (empty 40px left cell balances
  the menu button), the hamburger sits at the right edge, and the theme toggle moved out of
  the header into the drawer as a THEME row (icon-only sun/dark segmented control, keeps
  `data-testid="theme-toggle"`). Desktop header untouched.
- **Language now switches the market currency**: `setLang()` sets RON for Romanian and EUR
  for BG/EN and persists it, so the desktop RO button repricing the page is no longer
  limited to first load. Verified: EN 15,199 EUR -> RO 79,745 RON -> BG 15,199 EUR, with
  the price-filter unit following along.

## 2026-06 — Saved searches, language URL prefixes, detail scroll
- **Saved searches.** The whole search already lived in the query string, so a saved
  search is that string plus a name: `savableQuery()` deliberately drops sort and page so
  it always reopens on page 1 with the default sort. New `/searches` page re-runs each
  stored query with `page_size: 1` for a live total plus a thumbnail of the newest match,
  shows an "N new" badge when the total has grown since it was saved (reset when opened),
  and supports rename/delete. Auto-named from the TRANSLATED taxonomy labels
  (`describeSearch`). Entry added to both the desktop header nav and the mobile drawer with
  a count badge. Storage mirrors favourites: localStorage for guests, synced to the account
  through `GET/PUT /api/auth/saved-searches` and `POST /api/auth/saved-searches/merge` on
  sign-in. `alerts: false` is already on each record for the coming email alerts.
- **Every page has a language address.** Routes are nested under `/:lang` (`LangLayout`
  validates the prefix and pushes it into app state); a bare or unknown prefix redirects to
  the detected language keeping the path and query, so old links still work. `useLangNav`
  (`path`/`go`/`switchLang`) prefixes every internal link, and switching language now
  rewrites the URL instead of only swapping strings. `useSeo` writes a localised title and
  description, a canonical URL and hreflang alternates (bg/ro/en/x-default) per page; the
  search page's canonical deliberately omits the query so filter permutations are not
  indexed. `robots.txt` and `sitemap.xml` are generated by `frontend/scripts/gen-seo.js`
  from `REACT_APP_SITE_URL` (falls back to the backend URL) — **re-run it once the real
  domain exists**. Honest limit: this is still a client-rendered SPA, so the prefixes and
  tags are the foundation, not server-rendered pages.
- **Car detail opens at the top** (`window.scrollTo(0, 0)` on id change) instead of
  inheriting the result list's scroll offset.
- Verified end to end by the testing agent (iteration_17): 16/16 backend cases, redirects,
  SEO tags, save/rename/delete, the "new" badge, merge-on-sign-in, account round-trip after
  clearing localStorage, mobile drawer entry and scroll-to-top all pass.

## 2026-06 — Make-only searches sort newest first again
- The rule (newest while browsing, cheapest once a model narrows the list) was right, but
  `sortTouched` was set from the mere PRESENCE of `sort` in the URL. Since the page writes
  the sort into the URL itself, returning from a car, switching language or opening a saved
  search all counted as "the visitor chose this sort" and froze it — so clearing back to a
  make-only search kept showing cheapest first. A URL sort now only counts as deliberate
  when it DIFFERS from the sort the rule would have picked (`autoSort(tax)`).
- Verified: make only -> newest, + model -> cheapest, model cleared -> newest again, and an
  explicit `sort=mileage_asc` still survives a reload.

## 2026-06 — Passkeys after registration, mobile car page, lightbox close
- **Passkeys removed from the registration form** and offered afterwards instead
  (`PasskeyPrompt`): the account exists and the session is live by then, so the credential
  has something to belong to. The dialog is only offered when the device actually has a
  platform authenticator (`platformPasskeyAvailable()`), and the WebAuthn ceremony starts in
  the button's click handler — moving it into an effect loses the user gesture and the
  browser cancels. Cancellation / "Maybe later" / a credential that already exists all close
  quietly; only a real failure shows a message. Sign-in keeps its passkey button.
  **Email verification does NOT exist** — the owner deferred it ("skip for now") because the
  shared Resend sender only delivers to the Resend account owner, so a verification gate
  would lock out every real user. When a domain is verified, the prompt can move behind it.
- **Mobile car detail page**: the in-page "Back to results" and the duplicated
  title/subtitle/price/"Final price" block are gone; the header carries a back arrow
  (`HeaderBar onBack`) and the condensed car bar is now ALWAYS visible below `lg` (still
  scroll-gated on desktop), with `pt-[72px]` on the container so nothing hides under it.
  The enquiry button sits immediately after the photos on mobile and beside the specs on
  desktop (two mounts, one painted per breakpoint).
- **Lightbox close button**: the stock dialog close is absolute inside the scrolling photo
  column, so it slid out of reach. Hidden in favour of a sticky zero-height rail holding a
  white circular button with a black X — pinned to the top-right of the phone at any scroll
  depth (verified: top 47 / right 13 at open and after scrolling 2,400px).
- Mobile header back and menu buttons enlarged to 48x48 with bigger glyphs.
- Testing agent iteration_18: 100% pass, including the CDP virtual-authenticator run of the
  passkey enrolment dialog (options + verify called, passkey listed on the account page).

## 2026-06 — Header button sizing gotcha
- The mobile header back/menu buttons looked unchanged after being enlarged because the
  shadcn `Button` base class forces `[&_svg]:size-4` on any nested icon, silently overriding
  `h-7 w-7`. Icons need `!h-6 !w-6` (or similar) to win that specificity. Final sizing:
  48x48 buttons with 24px glyphs, cells `w-12` so the logo stays centred.
- Lightbox close button offset settled at `mt-14` (91px from the top of the phone).

## 2026-06 — English slugs in the query string
- Filter values in the URL were percent-encoded Hangul (`?make=%ED%98%84%EB%8C%80`):
  unreadable, unshareable and worthless to a crawler. Every taxonomy node and flat facet
  now carries an English slug derived from the cached English translation
  (`backend/slugs.py`), so URLs read
  `?make=hyundai&model=all-new-tucson&badge=diesel-1-6-2wd&fuels=diesel~electric&regions=seoul`.
  `GET /api/meta/resolve` translates them back to the upstream values, and `/meta/taxonomy`
  + `/meta/filters` now return a `slug` per item so the UI can write them.
  Slug uniqueness is scoped by parent (level, make, model, badge); a value with no English
  translation deliberately keeps its raw value. Unknown slugs and raw Korean values are
  echoed back, so pre-slug links and pre-slug saved searches still work.
- `SearchPage` holds the search until the incoming slugs are resolved, and `SavedSearchesPage`
  does the same before counting matches — missing that step made every saved search with a
  slug report "0 cars now" (found by testing agent iteration_19, fixed and re-verified:
  15,466 cars with a thumbnail).
- **Duplicate taxonomy fixed**: `build_taxonomy()` never dropped its `taxonomy_new` staging
  collection, so two overlapping rebuilds doubled every node — 124 level-1 docs for 62 makes,
  i.e. every dropdown option was silently listed twice. Now 10,703 unique nodes.
- Testing agent iteration_19: backend 12/12, frontend 9/9 after the fix.

## 2026-06 — Mobile filter bar, drawer taxonomy, back-scroll restore
- **Floating filter bar redesigned** (mobile): was a red pill under the header; now an
  edge-to-edge white bar, square corners, 44px tall, flush against the header (`-mt-px`
  covers the divider so the two read as one block) and never overlapping it — it sits at
  `top-16` while the header shows and slides to `top-0` once the header collapses, at `z-30`
  under the header's `z-40`. Reads "Промени филтри", carries the live result count and a red
  dot when any filter is active.
- **It now appears only when the in-page Филтри button has actually scrolled off the top**,
  measured on scroll (rAF-throttled). An IntersectionObserver was tried first and silently
  failed: set up while the button is `display:none` in the desktop layout, it reports a zero
  rect and never recovers.
- **Filter drawer now contains make / model / submodel** (`TaxonomySelects` inside
  `FilterSidebar` when `inSheet`), because the drawer is the only filter surface on mobile.
  Accordion defaults changed to price + year + mileage open, fuel closed.
- **Back from a car returns to where you were**: the list's scroll offset rides along in the
  navigation state and is restored once the results have rendered. Captured at mount in a
  ref because SearchPage rewrites its own URL with `replace: true`, which wipes the
  navigation state before the results (and the page height) exist — that wipe was why the
  first attempt silently did nothing. Verified: left at 2200, returned at 2200.

## 2026-06 — Filter bar polish, hero scope, pagination scroll
- **The "dividing line" under the header was its own `shadow-sm`**, not a border. `HeaderBar`
  now takes a `flush` prop that drops both the shadow and the bottom border whenever the
  mobile filter bar is on screen — including while the header is collapsed, where the shadow
  was still bleeding down onto the bar.
- **Hero and trust strip are page-one, unfiltered only** (`isHome = !anyFilterActive &&
  page <= 1`). Sorting alone still counts as the home view, as the owner asked.
- **Pagination scrolls to the top of the page.** Measuring the top of the list looked right
  on paper but shifted mid-scroll: the hero unmounts from page two onwards, so the target
  moved out from under the animation and landed ~900px off. Scrolling to 0 is what the owner
  asked for and is immune to that.
- **Scroll restore made snappy**: instead of waiting for the fetch to resolve, a bounded rAF
  loop re-asserts the offset as soon as the document is tall enough (skeletons count), for up
  to 2.5s. The testing agent had caught the earlier version landing ~900px short because the
  browser clamps a scroll the document cannot yet accommodate.
- Test ids tidied per the report: the drawer copy of the filter panel is now
  `filter-sidebar-sheet` (it was a duplicate `filter-sidebar` in the DOM) and the desktop
  back button is `back-to-results-button`.

## 2026-06 — Pagination, page-two reload, logo reset, scroll restore (finally)
- **Reloading or sharing a `?page=2` link snapped back to page one.** The auto-sort effect
  called `setPage(1)`, and that effect also runs on mount and after slug resolution. Removed
  the reset from there: `changeTax` and `removeChip` already reset the page when the visitor
  actually narrows the search. A `mounted` ref was tried first and failed, because refs
  survive React StrictMode's double effect invocation.
- **Pagination now lands at the top of the page.** A smooth scroll was being interrupted by
  the results swapping underneath it, so the jump is instant and re-asserted once the new
  page has rendered. Measuring the top of the list instead was worse: the hero unmounts from
  page two onwards, moving the target mid-animation.
- **Clicking the logo starts over.** Linking to `/{lang}` alone did nothing on a filtered
  search, because the live filters immediately rewrote the query string back into the URL.
  The link now carries a `home` timestamp in navigation state and the search page clears
  every filter and scrolls to the top when it sees one.
- **Scroll restore fixed (third attempt).** The offset arrives fine, but the effect reading
  it had `[]` deps and the render carrying it is not always the mounting one, so the effect
  simply never saw it. Keyed on `location.key` instead, with the target held in a
  module-level variable because this page's own `setSearchParams(..., {replace: true})`
  wipes navigation state. Verified: 2199 restored within 1.5s and it sticks.
- **Debug lesson**: three guesses at the restore bug cost more than one round of
  `console.log` + captured browser logs would have. Instrument first.

## 2026-06 — Catalogue sync in the admin panel
- New **Catalogue sync** tab (`AdminCatalogueSync`): one button starts a whole-catalogue
  crawl and a switch schedules it daily at a chosen time and time zone. Backend is
  `syncjob.py` with `GET /api/admin/catalogue-sync`, `POST .../run` and
  `PUT .../schedule`; the job is detached (a crawl outlives any request) and everything is
  read back from `sync_state`. Post-crawl it repeats what `crawl.py` does — retire, gearbox
  tagging, dedupe, taxonomy rebuild, slug rebuild, coverage — because otherwise the
  dropdowns and English URL slugs would still describe yesterday's catalogue.
- **Live progress bar**: `crawl_partitioned` publishes `{seen, written, leaves, upstream}`
  at most every 3s (a write per batch would cost more than the crawl), and the phases after
  the crawl each report their own label so the bar keeps moving instead of parking at 100%.
  Verified live: 5%, 11,418 of ~209,966 cars, 61 slices, run button disabled while running.
- A job left `running` by a server restart is marked `interrupted` at startup
  (`clear_stale`), otherwise the button would stay jammed for ever.
- Daily schedule is currently ON at 03:30 Europe/Sofia.
- `martingtodorov@gmail.com` already had `is_admin: true`; nothing was changed.

## 2026-06 — Translation quality and UX
- The description panel no longer collapses when Translate is pressed: the box keeps the
  height it had (measured on click) while the stream fills it in.
- Owner chose prompt-only improvement over a bigger model. `DESC_SYSTEM` now carries
  per-language grammar rules (Bulgarian definite article long/short forms and adjective
  agreement, Romanian diacritics and enclitic article, dealer vocabulary in both), forbids
  Korean word order, requires Korean dealer shorthand to be converted rather than glossed,
  and asks for a proofread pass; temperature dropped to 0.2. The 36 cached description
  translations were cleared so the new prompt actually takes effect.
- Landing block tightened (hero padding, trust cards side-by-side on mobile): the first car
  now appears at 1010px instead of 1227px on a phone.
- `color-scheme: dark` added to the dark theme so native controls — the make/model selects,
  their option lists and the time picker — stop rendering in the browser's light chrome.

## 2026-06-04 — Sort default and resumable sync checkpoints
- "Подходящи" (relevant) is now the sort for EVERY search. The auto-switching rules
  (make -> newest, model/submodel -> cheapest) were removed from `SearchPage.js`, along
  with the `autoSort` helper. A sort the visitor picks themselves sticks for the session,
  including while they keep changing make/model; only "Clear all" returns to relevant.
  Verified live: `/en?make=bmw` lands on Relevant (it used to force Newest).
- Catalogue sync no longer loses progress on a server restart:
  - `syncjob.find_resumable()` reads the per-slice checkpoint
    (`sync_state/catalogue_partition_resume`) and, when the crawl had already finished,
    the live doc, and reports the run_id to continue from. The freshness window is now
    measured from the LAST checkpoint write (12h) instead of the start of the run.
  - The one-shot `resumed` flag is gone. Automatic resumes are capped by
    `resume_attempts` < MAX_AUTO_RESUMES (40) so a crash loop cannot crawl for ever,
    while an ordinary restart is always resumed.
  - `start()` continues the checkpoint by default, so the operator pressing Sync after a
    restart no longer re-crawls the ~210k cars already indexed. `POST
    /api/admin/catalogue-sync/run?fresh=true` forces a clean run.
  - `crawl_partitioned` force-flushes the checkpoint in a `finally`, so a cancellation
    loses at most the slice in flight (flush interval also 3s -> 1s), and the progress bar
    now reports cumulative slices (`len(done)`) rather than per-process ones.
  - Admin panel shows the checkpoint ("interrupted with N slices already indexed"), the
    primary button becomes "Resume the interrupted sync", and a "Start from scratch"
    button (confirm dialog) sits next to it.
  - Verified live on the running sync: three consecutive `supervisorctl restart backend`
    each resumed run 20260804023420 with monotonically growing progress
    (63 -> 92 -> 103 slices; 11.4k -> 15.5k -> 17.4k cars), and the job doc showed
    `trigger: resume`, `resume_attempts: 5`.

## 2026-06-04 (later) — Customer picker fix and the first true E2E of the purchase pipeline
- Bill-of-lading customer assignment finished and verified in the browser. The picker
  itself was sound; the bug was in `AdminShipments.js`, where it sat inside a `<label>`.
  A click on an option is forwarded by the browser to the label's control — the picker's
  own trigger — so the list reopened on every selection AND then covered the Assign
  button, which is why assignment appeared not to work at all. The wrapper is now a
  `<div>` and the trigger carries `aria-label="Customer"`.
- `CustomerPicker.js`: fetches the moment it opens (only typing is debounced), shows
  "Searching…" instead of flashing "No matching customer", and Escape closes the list.
- Verified live: opens on click with 20 accounts, "todor" narrows to Martin Todorov
  (surname search), picking closes the list and fills the trigger, Assign creates the row.
  `/api/admin/customers` matches first name, surname, email and `billing.full_name`.
- Deposit -> archive -> My Purchases tested END TO END IN A BROWSER for the first time
  (iteration_27.json, 0 defects, 100% backend and frontend). Real Stripe test-mode
  checkout on car 42341529: EUR 300 minimum applied, archive logged "29/29 photos",
  `purchased_listings` holds the full listing, all 29 JPGs on disk and served as
  image/jpeg over HTTPS, `/api/purchases` returns OUR photo URL (never encar.com),
  `/en/purchases` renders it at naturalWidth 1600, a second buyer gets HTTP 409 and the
  "already taken" banner, a fresh buyer sees the empty state, and assigning a B/L for the
  same car surfaces the Track button on the purchase row.
- Acted on one review note: `archive_later` now records `archive_ok` on the deposit, so a
  paid deposit whose archive failed can be found with a query instead of by grepping the
  log — that failure would otherwise silently cost the buyer their car page.
- Left as considered-and-declined for now: integer-cents pricing, a global archive
  semaphore, and a soft-lock on a second PENDING checkout for the same car (whoever pays
  first still wins, and the loser gets a clean 409).
- "Подбрани за теб" cards no longer show the Korean city. `CarCard` takes `showRegion`
  (default true) and `Recommended.js` passes false, so the search grid and rows keep the
  region. Verified: 0 map pins in the shelf, 32 still on `/bg?make=BMW`.
- Reservation deposit is now 10% of the car with NO floor (was 1% with a EUR 300 minimum).
  `DEPOSIT_RATE` default 0.10 and `DEPOSIT_MIN_EUR` default 0 in `deposits.py`; the quote
  endpoint returns `rate: 0.1, minimum_eur: 0`. The rule is quoted in three places besides
  the code, all updated: `i18n_account.js` (`depositWhy`, 3 languages), the FAQ and the
  fees page in `content/help.js` (3 languages x 2 entries), and the module docstring.
  `test_security_deposit.py::test_deposit_is_ten_percent_with_no_floor` rewritten.
  Verified: cheapest car in the catalogue (EUR 6,099) quotes EUR 610 on the detail page
  with no "minimum" wording anywhere, and `amount_for(500)` is EUR 50 - proof the floor is
  gone, since the old rule would have charged EUR 300.

## 2026-06-04 (later still) — One-click deposit refund
- New admin "Deposits" tab (`AdminDeposits.js`, `/en/admin?tab=deposits`): every deposit
  that reached Stripe, newest first, with stat cards (cars held, deposits held, refunded)
  and a single "Refund and release" button behind a confirm dialog.
- `deposits.refund(session_id, admin_email)` does both halves in one call: a FULL Stripe
  refund (`stripe.Refund.create(payment_intent=...)`, per the integration playbook) and
  `_free_car()`, which unsets `reserved / reserved_by / reserved_at` so the car goes back
  on the market. The existing `charge.refunded` webhook makes the same two writes, so the
  operation is idempotent either way, and a refund issued straight from the Stripe
  dashboard now settles our record instead of leaving the car held for ever (we catch
  InvalidRequestError "already been refunded" and reconcile).
- Double-click safety: Stripe idempotency key `deposit-refund-<session_id>`, plus a 409 on
  an already-refunded record. Verified only ONE Refund object is ever created.
- New routes: `GET /api/admin/deposits`, `POST /api/admin/deposits/{session_id}/refund`,
  both behind `_require_admin`.
- A refunded deposit drops out of My Purchases for free, because `/api/purchases` only
  lists `payment_status: "paid"`. The archive (`purchased_listings` + the photo files) is
  deliberately KEPT after a refund.
- The list also surfaces the `archive_ok: false` flag as a red "not archived" pill, so the
  backlog item about spotting broken archives is partly covered already.
- Tested end to end (iteration_28.json, 0 defects, 15/15 backend): real Stripe test
  payment of EUR 609.90 on car 42317775, refunded from the admin panel, after which a
  DIFFERENT buyer could reserve the same car (it had returned 409 before). I independently
  confirmed against Stripe: charge 60990 cents, exactly one refund of 60990 cents, status
  succeeded, fully refunded. (The test report's "6099000 cents" was a typo in the writeup.)
- Guard paths I checked myself: 401 anonymous, 401 signed-in non-admin, 404 unknown
  session, 409 on a pending deposit.

## 2026-06-04 (later) — Stale crawl panel and Korean names in Stripe
- The admin Overview's Crawl panel was stuck reading `sync_state/catalogue`, the doc left
  behind by the RETIRED page-based `run_full_sync`. It had been frozen at
  `status: "running", pages_done: 142, pages_total: 420` since 3 Aug because `clear_stale`
  only ever repaired `catalogue_job`. So the panel claimed "running · page 142 of 420" for
  ever, and "Last full crawl 2d ago" / "Duration 10 min" were equally stale.
  Fixes: `/api/admin/overview` now returns the REAL job (`syncjob.get_job`) plus a
  `running` flag; `AdminOverview.js` reads status, the progress bar (phase, seen of
  upstream) and the crawl timings from the job and the partition doc instead; and
  `clear_stale` now also settles the legacy doc so the ghost cannot come back.
  Verified: panel shows "done", "Last full crawl 22m ago", "Duration 24 min", and the
  "page 142 of 420" line is gone.
- The crawl itself was NOT broken (checked before touching anything): last run finished
  10:15 with 205,821 of 211,046 exportable ads indexed (97.5%), 10,489 cars first seen in
  the previous 24h (320 in the last hour), 9,247 retired as sold. The ~2.5% gap is the
  lease/rental rows we deliberately skip (3,379 that run) plus contract/placeholder ads,
  which is exactly why the per-brand table sits at 94-100%.
- Stripe showed Korean: the checkout line item and the buyer's card receipt read
  "Reservation deposit — 푸조 5008 2세대". `_car()` reads the listing straight from Mongo,
  where make/model are still Korean; the `_t` variants are attached by the translation
  layer on the way to a PAGE, which a Stripe line item never passes through. New
  `deposits._english_title()` resolves make and model through `translate_listings(..., "en",
  background=False)` before the session is created, wrapped so a translation failure can
  never break a checkout. `car_title` on the deposit record (shown in the admin Deposits
  list and My Purchases) now stores the English form too.
  Verified against Stripe: "Reservation deposit — Peugeot 5008 2nd Generation", no Hangul.
  Note: deposits created BEFORE this fix keep their Korean `car_title`.

## 2026-06-04 (evening) — Deposit is a purchase, not a holding fee + body damage diagram
Owner's clarification: the deposit BUYS the car, so it is not refundable if the buyer
withdraws; once the buyer wires the balance we return the deposit less a EUR 300 commission.
- `deposits.COMMISSION_EUR` (env `DEPOSIT_COMMISSION_EUR`, default 300). `refund()` now
  returns `max(0, amount - commission)` as a PARTIAL Stripe refund and records
  `returned_eur` / `commission_eur`. When the commission swallows the deposit it skips
  Stripe entirely (a zero refund is rejected) but still releases the car.
- Admin Deposits: button is "Return and release", the confirm dialog quotes what goes back
  and what is kept, and a refunded row reads "returned X (kept EUR 300)".
- Copy rewritten in BG/RO/EN in four places: under the deposit button, the payment success
  screen (`payDepositNext`), the FAQ and the fees page. The clause promising a full refund
  when WE cannot deliver was deliberately KEPT, scoped to our own failure.
- New mandatory acknowledgement checkbox before paying (`detail-reserve-terms`): the button
  is disabled until it is ticked. With a non-refundable deposit that explicit tick is the
  best defence in a card dispute.
- CAUSED AND FIXED A LIVE BUG in the same batch: the `COMMISSION_EUR` definition never
  landed in the file while three usages did, so `/api/deposit/car/{id}` threw NameError,
  the quote fetch failed and `ReserveCar` returned null - the owner noticed the buy button
  had vanished. Lesson: when adding a constant plus its usages, verify the DEFINITION
  landed, not just the usages.
- Body damage diagram (`BodyDiagram.js`, section "Body condition" on the car page).
  `server._body_panels()` normalises two overlapping upstream sources: the inspection sheet
  (`inspection.outers[].statusTypes[].code`, the letters X replaced / W beaten or welded /
  C corrosion / A scratch / U dent / T damage, listing only panels WITH a finding) and,
  as a fallback, Encar's own outer-skin diagnosis. P-codes and diagnosis enums map to our
  own slugs, so the drawing is our own schematic and every word comes from our own
  BG/RO/EN maps - no Korean reaches the page. A car with neither source shows no section at
  all, because an empty diagram would read as "every panel is fine".
  Verified live on car 42179408 (bonnet X, both right doors X, rear door left W, rear
  quarter left W, radiator support X as a structural chip) in BG/RO/EN, and on 42379471
  which correctly says "No panel findings recorded". Silhouette is neutral grey after the
  owner pointed out `fill-secondary` gave it a reddish tint that read as damage.

## 2026-06-04 (night) — copy corrections, autoscroll, next-image prefetch
- Verified iteration_29: PARTIAL refund (deposit - EUR 300) 100% backend (9/9) and 100%
  frontend across three languages, two real Stripe deposits paid and refunded, including
  the commission-swallows-deposit branch. Zero defects.
- BG label for status W is now just "Изправян" (was "Изправян или заваряван"), at the
  owner's request. RO and EN keep the fuller wording.
- Deposit copy now states the EUR 300 commission is ALREADY INCLUDED in the final price,
  in all three languages and in all four places (button blurb, payment success screen, FAQ,
  fees page).
- `changeTax` scrolls to the top. Choosing a make or model collapses the hero, the trust
  strip and the picked-for-you shelf, so the page shortened under the visitor and left them
  stranded mid-page. Instant, not smooth: those sections unmount as it scrolls, which a
  smooth scroll would chase. Verified 1600 -> 0 on make and 1400 -> 0 on model.
- Gallery prefetch: `PhotoSwiper` used to mount ALL photos once the visitor interacted
  (24+ downloads at once). It now keeps a watermark of the highest slide reached and mounts
  up to `active + 1`, so slides already seen stay mounted (going back is free) while only
  ONE photo is pulled ahead. Because `ImageWithFallback` is `loading="lazy"`, mounting the
  next slide is not enough - an off-screen image waits until it is nearly in view - so the
  fetch is kicked off explicitly with `new Image()` on the next src.
  Verified: 2 images mounted on load, 6 after four advances, counter 5/31, no regression.
- PANEL COVERAGE ANSWER (owner asked whether we take everything Encar offers): every one of
  the 22 distinct panel codes Encar actually returns across our cached details is mapped -
  zero unknown codes - and the map carries 34, so unseen ones are already covered. That
  includes the underbody and structure: front/rear side members, front/rear wheelhouses,
  inner panels, sills, cross member, boot floor, rear panel, A/B/C pillars and the radiator
  support, rendered as "marked on the structure" chips under the diagram. NOT included, and
  the obvious next step: the sheet's self-diagnosis sections (engine, transmission,
  drivetrain, steering, braking, electrics, fuel, high-voltage system) - mechanical, not
  panels, so they do not belong on a body diagram.

## 2026-06-04 (night) — Mechanical checks beside the body diagram
- `server._mech_checks(insp)` normalises the mechanical half of the inspection sheet
  (`inspection.inners`): 9 sections mapped by code (S01 engine, S02 transmission, S03
  drivetrain, S04 steering, S05 braking, S06 electrics, S07 fuel, S08 high-voltage on EVs,
  S00 electronic self-test) and 41 leaf item codes mapped to our own slugs. Leaves are
  walked recursively because leak checks nest one level down.
- Status mapping matters: upstream code 1 (good), 2 (adequate - used for FLUID LEVELS) and
  3 (none found) all mean "nothing to report"; 6 is slight seepage (warn) and 7 (leak) or
  10 (faulty) are real findings. Treating 2 as a problem would have flagged ~800 perfectly
  normal oil/coolant level readings across the catalogue.
- Each section reports the WORST of its items and only non-fine items are named - the sheet
  runs ~30 checks and nearly all pass, so listing them all would bury the one that matters.
  An unmapped item still counts towards the section verdict but is not named, so Korean can
  never reach the page.
- `MechChecks.js` renders it beside the body diagram: section rows with a green tick, amber
  warning or red cross, findings nested underneath, and a "N points checked, all fine"
  summary. Labels for 9 sections and 40 items in BG/RO/EN.
- Verified: car 42432304 (29 checks, engine "slight seepage" on rocker cover and block/sump,
  drivetrain "fault found" on the CV joint, everything else fine) in Bulgarian, and car
  42379471 (30 checks, all fine) in Romanian. No Korean characters in either.

## 2026-06-04 (night) — Price-drop alerts and the deposit-returned email
- New `pricewatch.py`. Keeps a per-person baseline in `price_watch` (`<user_id>:<car_id>`)
  for every saved car and alerts by email and push when the price falls.
  KEY DECISION: the baseline is the KRW price, not the EUR one. Our euro figures are derived
  through the exchange rate, so watching them would fire "the price dropped!" every time the
  won moved overnight - noise that teaches people to ignore alerts. The won price only moves
  when the seller moves it. The message still speaks in euros.
  A car seen for the first time only gets a baseline (nobody is told about a "drop" the
  moment they save something), a price that ROSE rebases quietly, and moves under
  MIN_DROP_KRW (100,000 KRW) are ignored as rounding. One email per person listing all their
  fallen cars, not one per car.
- Hooked into `syncjob._run` right after a successful sync - the one moment prices have
  actually changed - plus `POST /api/admin/price-watch/run?first_seen=` to run it by hand.
- `mailer.send_price_drop()` and `mailer.send_deposit_returned()`, both in BG/RO/EN. The
  refund email fires from `deposits.refund()` as a detached task, so a mail outage can never
  turn a completed refund into an error. Deposits now store the buyer's `lang` (parsed from
  the checkout origin) so the refund email speaks their language.
- `mailer._send()` guard: on the shared `onboarding@resend.dev` sender Resend only delivers
  to the address that owns the account, so anything aimed at a buyer used to vanish without
  trace. It now redirects to ADMIN_NOTIFY_EMAIL with "[would go to X]" in the subject, or
  logs a clear warning if that is unset.
- VERIFIED: first run recorded a baseline and sent nothing; after dropping a watched car's
  KRW price 10% the run reported 1 drop and 1 email; restoring the price (a RISE) reported
  0 drops, proving the quiet rebase. All six templates build in three languages with no
  Korean.
- NOT VERIFIED, blocked on config not code: actual delivery. `SENDER_EMAIL` is still
  `onboarding@resend.dev` and `ADMIN_NOTIFY_EMAIL` is UNSET, so nothing can reach anyone.
  The same gap has been silently dropping enquiry notifications since at least 2 Aug.
  Waiting on the owner for the address that owns the Resend account.

## 2026-06-06 — Digest test suite repaired and popular-cars coverage added
- FIXED (P0): `tests/test_search_digest.py` was failing with a `TypeError` after
  `mailer.send_search_digest` gained the `popular=` argument — the fixture's fake mailer still
  had the old three-argument signature. The fake now accepts and records `popular`.
- Added two regression tests: the digest HTML renders the "Най-гледаните тази седмица" section
  with a working `/bg/car/<id>` link, and `digest.top_viewed` ranks by DISTINCT viewers — a car
  with 99,999 raw hits from one refresher (`u`=1) loses to one seen by eight people.
- VERIFIED: `pytest tests/test_search_digest.py` → 8 passed. A manual
  `POST /api/admin/digest/run` returns 200 (0 buyers currently have an alerting saved search),
  and `top_viewed` against live data returns 6 cars with photos and distinct-viewer counts.
- NOTE (pre-existing, unrelated): ~21 other tests in the full suite fail only when the whole
  suite runs (they skip standalone because they never load `.env`). Causes seen: stale expected
  constants (`MARGIN_PCT` is 0.016, the test still wants 0.014), a renamed quote field, and
  suites using `httpx` instead of `requests`, which bypasses the conftest CSRF wrapper → 403.
  None of these touch the digest.

## 2026-06-06 (later) — Whole backend suite made green (183 passed, 3 honestly skipped)
The suite had 21 failures and 17 errors, none of them a real application bug. What was wrong,
and what it took:
- Suites SKIPPED silently when run alone (they never loaded `.env`) and only failed in the full
  run. `tests/conftest.py` now loads `backend/.env` AND `frontend/.env` once, so a file behaves
  the same either way.
- Playwright had no browser: `playwright install chromium` (now at
  `/pw-browsers/chromium_headless_shell-1234`). That alone fixed 17 errors.
- Admin token was hardcoded as `encar-admin` in six files — it comes from `ADMIN_TOKEN` in
  `.env` now, with no fallback.
- Stale expectations replaced with the live rule, never a copied number:
  `MARGIN_PCT`/`MARGIN_MIN_EUR` now checked against `pricing.DEFAULT_SETTINGS`; the tracking
  tail against `tracking.CUSTOMS_DAYS`/`DELIVERY_DAYS` (4 and 7, not the 3/7 asserted) and
  relative to the port arrival instead of fixed dates; `email.shared_sender` is config so only
  its type is asserted; the enquiry list is checked by shape, not by "at least 7 rows".
- `/api/car/{id}` exposes only `suggested_sale` (the breakdown is admin-only), so the FX test
  now recomputes the quote from the listing's own `price_krw` and the published buffered rate
  and demands agreement to the euro. It also proves the buffered price is never below the
  market-rate one.
- A deposit refund keeps the EUR 300 commission, so the Stripe charge is PARTIALLY refunded:
  the e2e test asserted `charge.refunded is True` and had been wrong since iteration 29.
- An empty taste profile deliberately returns the popular shelf (`source: "popular"`); the test
  still demanded an empty list.
- `test_fx_haircut` used httpx, which bypasses the conftest CSRF wrapper and got a truthful
  403 — switched to `requests`.
- FLAKINESS UNDER LOAD, the last and least obvious part: the two Stripe browser suites landed
  on both xdist workers at once and saturated the single preview backend, producing connection
  timeouts and a login answered `403 csrf token missing or stale` (the token fetch itself had
  timed out). Fixed with a `stripe_e2e_lock` file lock in conftest so those two modules are
  mutually exclusive across workers, a one-retry CSRF fetch, and waiting for Stripe's card
  field instead of `networkidle` (Stripe holds connections open, so idle never arrives).
- `MSKU5285725` was asserted as "seeded" but nothing seeded it; the test now runs
  `seed_track_test.py` itself and skips when `MAERSK_PUBLIC_TRACK=0` (it is), because with the
  browser reader off there is no route to that cache.
- Three skips remain, each with a truthful reason: the seeded container above, and two
  translation tests. WORTH THE OWNER'S ATTENTION: translation is currently DOWN in the live
  app — `ANTHROPIC_API_KEY` returns 401 (invalid) and Gemini answers 429 (quota spent), which
  is why untranslated Korean shows up in recommendation payloads.
- VERIFIED: two consecutive full runs, 183 passed / 3 skipped / 0 failed (~2m40s each).

## 2026-06-06 (evening) — Search heading, "Picked for you", and the owner's privacy policy v1.3
- FIXED: the results h1 read `≤ 2021 · ≤ — · ≤ — км`. `describeSearch` formatted the filter
  bounds without coercing them, and the inputs hand over STRINGS - `Number.isFinite("40000")`
  is false, so the formatters answered with a dash. It also never handled `mileage_min`. One
  `span()` helper now coerces every bound and renders real ranges; verified live:
  `≤ 2021 · 50 000 €–200 000 € · 30 000–40 000 км от Корея — 183 автомобила`.
- FIXED (the real one): "Подбрани за теб" answered a €90,000 BMW M2 with €8–9k E60s, and showed
  4 cars instead of 12. Two independent causes:
  1. `taste.fromCar()` read `car.sale_eur` / `car.mileage`, but the CAR DETAIL payload keeps the
     price in `quote.suggested_sale` and the mileage in `spec.mileage`. Every sample recorded
     from a car page was therefore [0, 0]: no price range reached the backend, the price window
     was never applied and the ranking had nothing but the make to go on, so the cheapest,
     most worn cars of that make won. `YouMightLike` seeded its sample the same wrong way.
  2. `_spread(..., per_make=4)` capped the shelf at four when every candidate shares one make -
     which is exactly what a single-brand profile produces. `per_make` now scales with how many
     makes the profile holds, and `per_model` with the requested size.
  Also windowed mileage (`<= high * 1.6`) alongside price, with ONE widening retry before
  falling back to the popular shelf, so a rare car does not empty the shelf.
  VERIFIED: an M2-class profile (samples [[90000, 30000, 5]]) now returns 12 cars, all
  €73k–99k and 20k–34k km (X5/X7/M3/7 Series/i7), instead of four €9k saloons.
- The owner's own Privacy policy v1.3 is now the BG document in `content/legal.js`, reproduced
  as they settled it (18 sections, MOL, CPDP contact details). The "Бележка / Notă / Note"
  disclaimer about a lawyer not having reviewed the text is REMOVED from every document in all
  three languages, at their request.
- RO and EN privacy deliberately still carry `Versiunea 1.1` / `Version 1.1`: they are still the
  previous text, and stamping a translation with a version it does not contain is the one lie a
  legal page cannot tell. Awaiting the owner's decision on translating v1.3 (the LLM providers
  are down, so it would be a hand translation).

## 2026-06-06 (night) — Deposits switched from a charge to a PRE-AUTHORISATION
The owner's decision: hold the money, do not take it. Confirmed with them first — 7-day hold,
manual capture from the admin panel in EUR 100 steps, car reserved on the authorisation alone,
and an expired hold releases itself and re-lists the car. Cards only (nothing else can hold).
- `deposits.py`: Checkout now creates the intent with `capture_method="manual"` and
  `payment_method_types=["card"]`, keeping `setup_future_usage` (verified against live Stripe:
  the two coexist). State machine is now pending → authorised → captured | released | expired.
  "paid" is still honoured everywhere a held car matters, so deposits taken before the change
  keep working and stay refundable through the old path.
- THE TRAP, and it would have broken everything: with manual capture Stripe reports the
  Checkout Session as `payment_status: "unpaid"` even after a perfect authorisation, and the
  old poll treated `status == "complete"` as paid. Both the poll and the webhook now read the
  PaymentIntent (`requires_capture` = held, `succeeded` = captured).
- New: `capture(session_id, amount_eur)` — round hundreds OR the whole hold (a deposit is 10%
  of a car and almost never a round number, so hundreds alone would make the last euros
  uncapturable). Stripe releases the uncaptured remainder for good, so capture is one-shot and
  the UI says so before it happens. `release()` cancels the authorisation — no refund object,
  nothing taken — and re-lists the car.
- New webhook events: `payment_intent.amount_capturable_updated`, `payment_intent.succeeded`,
  `payment_intent.canceled` (the last one frees the car whether we, the dashboard or the card
  network at expiry cancelled it).
- `sweep_expired()` + `deposits.scheduler()` (every 30 min, started at boot): a hold nobody
  captured is released and the car goes back on the market even if the webhook never arrived.
- Buyer emails added in all three languages: hold captured (with the released remainder) and
  hold released / expired. Contract signing now accepts a HELD deposit (`HELD_STATES`), and
  account deletion refuses while a hold is live, not just a charge.
- Admin panel (`AdminDeposits.js`): a EUR 100 stepper, "All €X", Capture, Release, a "held"
  badge and a days-left pill that turns red at 2 days. Buyer-facing copy in BG/RO/EN now says
  the card is not charged, that the amount is held for 7 days, and that the hold falls away by
  itself. `PaymentResultPage` treats authorised as success — waiting for "paid" would have told
  a reserved buyer their payment failed.
- TESTS REWRITTEN against real Stripe (test mode, Playwright hosted checkout):
  `test_deposit_refund_e2e.py` (19 passed) proves `requires_capture` with nothing received,
  capture refusing non-hundreds and over-the-hold amounts, release cancelling the hold with NO
  refund object, car freed, purchases emptied, double release and post-release capture both
  409. `test_partial_refund_and_commission.py` (9 passed) proves a EUR 100 capture takes
  exactly 10000 cents, releases the rest, leaves the car RESERVED, refuses a second capture,
  and that the full non-round hold can be captured. Both suites now reset their car so they
  are repeatable — the first version passed once and then skipped for ever.
- Recommendations follow-up from the same session: the widening retry was too generous (a
  €20,000 profile saw a €53,999 car) — only the MILEAGE window widens now, never the price.
  `per_model` is back to 2; `per_make` alone was what starved the shelf.
- VERIFIED: full backend suite 187 passed / 3 skipped / 0 failed, plus screenshots of the
  buyer's hold wording and the admin capture panel.

## 2026-06-07 — Link to the original Encar ad in the admin cost & margin panel
- Added an "Original ad on Encar (<id>)" link at the bottom of the admin-only Cost & margin
  panel on the car page (`CarDetailPage.js`, `data-testid="admin-encar-link"`). The address is
  fixed apart from the id: `https://fem.encar.com/cars/detail/{car.id}` — our listing id IS the
  Encar id, so nothing needs mapping. Opens in a new tab, `rel="noreferrer noopener"`.
- It sits inside the `car.admin &&` block, so it is only ever sent to and rendered for a
  signed-in admin: a buyer never sees where the car came from.
- VERIFIED live as the owner's account on /bg/car/42174890: link present exactly once, href
  `https://fem.encar.com/cars/detail/42174890`.

## 2026-06-07 (later) — mobile.bg posting queue + the hold-expiry warning
### Post queue (an OUTSIDE bot does the posting)
- New `backend/postqueue.py` + `post_queue` collection keyed by `_id = encar_id`, so there is
  exactly one row per car and asking twice just re-queues it (and clears the previous result,
  so a stale mobile.bg link cannot linger).
- Bot endpoints, both behind `Authorization: Bearer $ENCAREUROPE_API_TOKEN` (401 otherwise):
  `GET /api/post-queue` → `{"pending": ["41307034", ...]}` (that exact shape, nothing else)
  `POST /api/post-queue/{encar_id}` with `{status, mobilebg_url, note}` → `{"ok": true}`;
  404 for a car that is not queued, 400 for a status outside pending|posted|failed.
- Operator endpoints (admin session or `x-admin-token`): `GET|POST /api/admin/post-queue/{id}`
  and `GET /api/admin/post-queue` for the whole list. Queuing is audited.
- `csrf.exempt()` now also lets a `Bearer` request through: the bot has no cookies with us and
  a cross-origin page cannot set an Authorization header. Without this the bot's POST was 403.
- UI: `components/admin/PostToMobileBg.js`, inside the admin-only Cost & margin panel on the
  car page — button plus "Pending…" / "Posted" (linking to the mobile.bg ad) / "Failed: note".
- `/api/car/{id}` was NOT touched: the bot reads the final price from `quote.suggested_sale`.
- TOKEN lives in `backend/.env` as `ENCAREUROPE_API_TOKEN` (value also handed to the owner for
  the bot's own .env). Never sent to the browser.
- Tests: `tests/test_post_queue.py` (6 passed) asserts the literal wire shapes, the 401s on
  both endpoints, queue → poll → report round trip, failure with a reason, one row per car,
  and the 404/400 refusals. This is a contract another program depends on, so drift here would
  otherwise be silent: cars would just stop being posted.

### Deposit hold expiry warning
- `deposits.warn_expiring()` (in the same 30-minute scheduler as `sweep_expired`) emails the
  buyer once, 24h before a 7-day hold lapses. `warned_at` is set in the SAME update that
  selects the row, so two workers cannot send two letters.
- `mailer.send_deposit_expiring` in BG/RO/EN: says plainly that nothing has been taken, when
  the hold ends, and that replying keeps the car.
- VERIFIED with a synthetic hold expiring in 6h: warned once, second pass sent nothing,
  `warned_at` written.

### Environment note for the next agent
`/pw-browsers/chromium_headless_shell-*` is NOT persistent — it disappeared mid-session and
every Playwright test errored with "Executable doesn't exist". Fix, whenever that shows up:
`PLAYWRIGHT_BROWSERS_PATH=/pw-browsers playwright install chromium`.

## 2026-06-07 (evening) — Meta title, admin push alerts, email verification codes
### Meta title/description (owner was emphatic: never "Emergent" or "full stack app")
- `public/index.html` said `<title>Emergent | Fullstack App</title>` and
  `description="A product of emergent.sh"`. Both replaced with the site's own words:
  "Korean cars with a final landed price | Encar Europe" and a description about the final
  price including duty, VAT, freight and delivery. Per-page SEO (`lib/seo.js`) was already
  correct - this was only the pre-hydration fallback, which is exactly what a crawler that does
  not run JS sees. `manifest.json` was already clean.
- STILL OPEN: `public/sitemap.xml` lists the PREVIEW domain
  (`encar-multi-lang.preview.emergentagent.com`), which tells Google to index the preview rather
  than encareurope.com. Worth fixing before any SEO push.

### Admin push notifications for enquiries and deposits (owner: both events, push, all admins)
- Answer to their question was NO: push only ever went to buyers (saved searches, price drops).
  Enquiries emailed `ADMIN_NOTIFY_EMAIL`; a new deposit notified nobody at all.
- `notify.push_to_admins()` / `push_to_admins_later()` fan out to every `is_admin` account over
  the same proven `push_to_user` path; `deposit` added to `EVENTS`/`ChannelPrefs` so each admin
  can still switch an event off. Wired at the enquiry insert (`server.py`) and in
  `deposits._settle` when a hold is authorised.
- HONEST LIMIT: I could not verify a DELIVERED notification - that needs an admin browser with a
  live push subscription, and none exists in this environment. The fan-out and preference gate
  are covered by `test_notifications.py`; the delivery path is the one already in daily use.

### Email verification with a rotating code on first registration
- `auth.py`: registration writes `email_verified: False` and issues a fresh six-digit code
  (`secrets.randbelow`), stored ONLY as a sha256 hash in `email_codes` with `_id = user_id`, a
  15-minute TTL index, attempt counter and resend counter. Asking for a new code REPLACES the
  old one, so a code seen over a shoulder yesterday is worthless.
- Endpoints: `POST /api/auth/verify-email` {code} and `POST /api/auth/resend-code`. 5 wrong
  guesses burn the code (and then even the right code is refused), 60s resend cooldown, 8 sends
  maximum. Six digits is a million combinations - the ATTEMPT LIMIT is what makes it safe.
- Details are machine-readable (`{"code": "wrong", "left": 3}`, `expired`, `cooldown`, …) so the
  buyer reads the message in their OWN language; the wording lives in `i18n_account.js` in
  BG/RO/EN. First attempt returned English sentences on a Bulgarian page - fixed.
- Accounts created before this rollout are treated as verified (`_verified()` defaults to True
  when the field is absent), so nobody is locked out. `_public()` now exposes `email_verified`.
- Frontend: `pages/VerifyEmailPage.js` at `/:lang/verify-email` (six-digit input, resend with a
  countdown, noindex). Registration goes there instead of home, and LoginPage's redirect sends
  an unverified session to the code screen so the two redirects cannot race.
- TWO BUGS FOUND AND FIXED WHILE TESTING: `email_verified` was missing from the new user
  document, so a fresh account looked already verified; and Mongo returns NAIVE datetimes, so
  comparing `expires_at` to an aware `now` raised a 500 (`_aware()` helper now coerces).
- Tests: `tests/test_email_verification.py` (10 passed) - unverified on registration, code
  recovered from its hash (proving the clear text is never stored), right code verifies and the
  row is deleted so it cannot be replayed, five wrong guesses count down and then lock out even
  the right code, resend throttled without rotating the code, expired code refused, both
  endpoints need a session, legacy accounts read as verified.
- Also fixed: two Playwright failure-path screenshots passed `quality=` with a `.png` path,
  which errors in Playwright and masked the real failure.
- VERIFIED: full backend suite 203 passed / 2 skipped / 0 failed, plus a browser run of
  register → code screen → wrong code showing the Bulgarian message.

### Note for whoever sends test registrations
New accounts now start UNVERIFIED and land on `/verify-email`. Read the code out of the
`email_codes` collection (it is hashed - see `_code_of()` in the test for how) because the
Resend key in this environment is still rejected and no letter arrives.

## 2026-06-08 — Reservations locked behind a proved address, password reset built, privacy v1.3 in all three languages

### 1. A reservation now needs a CONFIRMED email
- `deposits.deposit_checkout` raises `403 {"code": "email_unverified"}` BEFORE it looks at the
  Stripe key: it is a fact about the buyer, not about our configuration. A hold on a card and a
  car off the market for seven days both need an address we can actually reach.
- `components/ReserveCar.js` shows the button DEAD rather than hiding it (a buyer who cannot see
  the price of reserving cannot decide to do it): disabled `detail-reserve-button` reading
  "Потвърдете имейла си, за да резервирате", plus `detail-reserve-verify-link` to
  `/{lang}/verify-email` and a one-line reason. The `pay()` catch also maps the machine-readable
  detail to our own wording instead of throwing an object at a toast.
- Accounts created before the verification rollout stay trusted (`auth._verified()` defaults to
  True when the field is absent), per the owner's explicit choice.

### 2. Password reset, built from scratch (there was none)
- There was a `login-forgot-password-link` test id in the codebase and nothing behind it: no
  endpoint, no letter, no page. Now:
  * `POST /api/auth/forgot-password` — answers `200 {"sent": true}` ALWAYS, whether the address
    is unknown, unconfirmed or fine, because a different reply is a free tool for working out who
    has an account. A link is issued only for a PROVED address. 60s cooldown, 5 per day, and a
    new request deletes any older link.
  * `POST /api/auth/reset-password` — single use, 30-minute life, `MIN_PASSWORD` enforced, and it
    deletes EVERY session the account had, the one that asked for it included.
  * `GET /api/auth/reset-valid?token=` — so the page can say "this link is dead" before taking a
    password it will then refuse.
- Tokens are `secrets.token_urlsafe(32)`, stored as sha256 only, in `password_resets` with a TTL
  index on `expires_at` and a unique index on `token_hash`. Deleted on use, not merely flagged.
- `mailer.send_password_reset` — BG/RO/EN, a real button plus the bare URL as a fallback.
- Frontend: `pages/ForgotPasswordPage.js` and `pages/ResetPasswordPage.js` at
  `/{lang}/forgot-password` and `/{lang}/reset-password`, both noindex; the forgot page swallows
  every error on purpose so the UI cannot leak what the API refuses to. LoginPage gained the link
  (login mode only — there is nothing to reset while registering).
- Link base: `PUBLIC_SITE_URL` when set, else the request's own origin, so it works on preview.

### 3. Privacy policy v1.3 in Romanian and English
- The RO and EN versions were still the older 14-section v1.1 text. Both are now translations of
  the owner's own 18-section v1.3 Bulgarian document, and `PRIVACY_STAMP` reads 1.3 for all three
  languages. `legal.js` is now ~720 lines; if it grows again, split it per language.

### Tests
- New `tests/test_password_reset.py` (8 tests): enumeration safety for unknown AND unconfirmed
  addresses, the cooldown, a dead link refused, a short password refused WITHOUT burning the
  link, single use, every session dropped, old password dead / new one working, and the 403 on
  the reservation gate. The raw token cannot be recovered from the database (that is the point),
  so the spending side runs against a row the test plants with a token it already knows.
- Five suites registered throwaway buyers and then reserved, which the new gate broke. A shared
  `conftest.mark_verified(email)` proves a test address directly; the gate itself is exercised
  for real in the new suite. Touched: `test_deposit_refund_e2e`, `test_partial_refund_and_commission`,
  `test_security_deposit`, `test_purchases`.
- VERIFIED: full backend suite 211 passed / 2 skipped / 0 failed. Testing agent iteration_37:
  10/10 frontend scenarios and 4/4 endpoint spot checks, no issues.

### Not done
- `sitemap.xml` and `robots.txt` needed no change: both already pointed at
  `https://encareurope.com`. The only stale preview URL is in `backend/backend_test.py`, an old
  standalone script that is not part of the pytest suite.

## 2026-06-08 (later) — Tracking dead on the Hetzner host: one empty line in a YAML file

### The cause, reproduced not guessed
`group_vars/all.yml.example` shipped `jsoncargo_shipping_line: ""`. Ansible writes EVERY
variable whether it was filled in or not, so that reached the server as
`JSONCARGO_SHIPPING_LINE=`. An empty env var is NOT a missing one: `os.environ.get(name,
"MAERSK")` returns `""` and the default never fires. The carrier is a REQUIRED query parameter,
so every container and B/L lookup on that host got:
`400 {"error":{"title":"Missing required parameter \`shipping_line\`..."}}` — confirmed by
calling the provider with an empty carrier. Preview had the value spelled out, so the failure
existed ONLY in production. `tracking._cargo` swallows the RuntimeError and returns None, which
is why the page showed "nothing found" instead of an error and the cause stayed invisible.

### Fixed
- `jsoncargo._env(name, fallback)` — an empty or whitespace-only env var counts as absent. Now
  used for the key (a key pasted with a trailing newline read as "tracking not configured at
  all"), the base URL and the carrier.
- `jsoncargo.ConfigError(RuntimeError)` — a rejected key (401/403) or a 400 naming
  `shipping_line` is OUR configuration, not the tracking number. It is never cached, and any row
  cached before the misconfiguration was noticed is deleted. Without this, a corrected deploy
  keeps failing for the 15-minute error TTL and looks unfixed. `/api/admin/tracking-quota`
  surfaces the message (ConfigError is a RuntimeError, which it already catches).
- Both `all.yml.example` files now ship `jsoncargo_shipping_line: "MAERSK"` with the reason.
- All three env templates now use `| default('MAERSK', true)`, which fires on an EMPTY value and
  not only an undefined one — so an all.yml already on disk with `""` is fixed by a redeploy
  without anyone editing it.

### Tests
`tests/test_jsoncargo_config.py` (8 tests, offline): empty and whitespace carrier fall back to
MAERSK, an explicit carrier is still honoured (the fallback must not become a hardcoding), a key
with stray whitespace still counts as configured, an empty key reads as not configured, the base
URL default survives an empty value, a ConfigError is never cached and clears a stale row, and an
ordinary failure IS still cached (the plan is metered — a bad number must cost one call, not one
per view).

VERIFIED: full backend suite 219 passed / 2 skipped. Live check on preview:
`GET /api/tracking?ref=MRSU5757040&by=container` → source `jsoncargo`, vessel GENOVA EXPRESS.
Jinja render check: empty → MAERSK, unset → MAERSK, "MSC" → MSC.

### To confirm on the server
`grep JSONCARGO /etc/encar/backend.env` — the line must read `JSONCARGO_SHIPPING_LINE=MAERSK`.
The key itself is fine: plan MARINER, 983 of 1000 requests left.

## 2026-06-08 (later still) — the production diagnosis, and making the failure visible

### What production actually answered
`GET https://encareurope.com/api/tracking?ref=271191199&by=bol` →
`{"configured": false, "reference": "271191199", "by": "bol"}`.
That is `tracking.track()`'s last line: no EDI events, `_cargo()` gave nothing, Maersk's public
read is off, no manual shipment, no Maersk consumer key. The JSONCargo quota counter stayed at
17-18 (this pod's own calls), so the DEPLOYED backend has never successfully called the provider.

The owner's own `curl` from back1 returned real data for B/L 271191199 → container MRSU5757040,
which rules out three theories at once: back1 has internet (NAT fine), the key works from their
network, and the key is NOT restricted by IP or domain — it also answers 200 from this pod on a
completely different address, and JSONCargo documents no allowlist.

`_cargo()` returns None both when there is no key AND when the provider errors, so the two
remaining causes are indistinguishable from outside: either `JSONCARGO_API_KEY` is empty in
`/etc/encar/backend.env`, or the deployed release is still the OLD code with the empty
`JSONCARGO_SHIPPING_LINE`. Both are fixed by the same deploy. `grep JSONCARGO
/etc/encar/backend.env` on the host settles which it was.

### THE POINT THAT COST FOUR ROUNDS
Fixes made in the Emergent workspace are NOT on the Hetzner host. Production runs whatever was
last deployed from GitHub. Say this out loud whenever a bug report is about the deployed site.

### Made visible, so this cannot happen silently again
- `jsoncargo._note()` / `last_error()` — the last provider failure (status + the provider's own
  wording + which path) kept in memory. Never shown to a buyer.
- `/api/admin/tracking-quota` now returns `last_error`, `shipping_line`, and, when there is no
  key, an explicit `hint` naming the missing variable.
- `AdminShipments.js` renders that line even when the provider is NOT connected — it used to be
  hidden behind `quota?.configured`, so a missing key produced an empty space in the admin and
  "nothing found" on the customer page, with nothing anywhere to contradict it. A live plan with
  a failing carrier now shows both facts.

VERIFIED: 20 passed / 2 skipped on the tracking suites; admin panel screenshot reads
"Provider plan MARINER: 983 of 1000 lookups left this month · carrier MAERSK".

## 2026-06-08 — "Стойност на щетите на трети лица" removed from every listing

The third-party CLAIM AMOUNT row is no longer rendered in the insurance panel on the car page
(`CarDetailPage.js`, the only place it appeared, so it is gone in all three languages at once).
That figure is what the car's insurer paid to SOMEBODY ELSE, so it says nothing about the
condition of the car on the page and read as if this car had that much damage.

- The third-party claim COUNT stays ("Щети на трети лица — 4 пъти"): that IS about this car.
- The own-damage amount ("Стойност на собствените щети") is untouched — the owner named only the
  third-party line.
- The backend still computes `insurance.other_accident_cost_eur`; only the display is dropped, so
  restoring the row is a four-line change. The `otherClaimAmount` i18n keys are kept in BG/RO/EN
  for the same reason.

VERIFIED on car 42341529, which really carries both figures (third-party 2793.75 EUR, own
4427.52 EUR): `insurance-other-claim-amount` renders 0 times, `insurance-own-claim-amount` once
(4428 EUR), and the panel text no longer contains "Стойност на щетите на трети лица".

## 2026-06-08 — "Add your Maersk keys": the message that sent the owner hunting for keys he does not need

### The logic bug
`tracking.is_configured()` returned `bool(MAERSK_CONSUMER_KEY)` and knew nothing about
JSONCargo. This deployment tracks through JSONCargo and has no Maersk enterprise arrangement, so
that check was permanently False. With `MAERSK_PUBLIC_TRACK=0` the tail of `track()` therefore
returned `{"configured": False}` for EVERY reference JSONCargo had no data for — and the page
rendered "Проследяването още не е свързано · Липсват ключовете за Maersk Track & Trace".

Two unrelated facts had been collapsed into one flag: "we cannot track at all" and "we tracked
and found nothing". A perfectly working JSONCargo still produced "not connected".

### Fixed
- `is_configured()` now means "can this deployment track with ANY provider" (Maersk key OR
  JSONCargo). New `maersk_private_configured()` keeps the separate question the private REST API
  actually needs, so `track()` still knows not to call it without a consumer key.
- When JSONCargo is connected but has nothing (or refused us), `track()` returns
  `configured: True, found: False, source: "jsoncargo"` — an answer about the lookup, not a
  missing integration.
- `_cargo()` takes a `problem` dict and records WHY it came back empty (`no_key` /
  `provider_error` + the provider's wording). A bare `None` had made three different situations
  indistinguishable.
- `track(..., admin=True)` adds `provider_error` to the payload for ADMINS ONLY;
  `GET /api/tracking` derives it from the session. Buyers never see provider internals; the
  operator is no longer left with a log on the server as the only trace.
- `trackNotReadyBody` in BG/RO/EN no longer names Maersk — it says a tracking provider key is
  missing from the server, which is what that state now means.

### Tests
`tests/test_tracking_not_connected.py` (5, offline — the metered plan must not be charged by the
suite): JSONCargo alone counts as configured, the private Maersk API is reported separately, a
Maersk key alone also counts, "nothing configured" is the ONLY not-connected case, and `_cargo`
reports `no_key` rather than a bare None.

### VERIFIED against the owner's real bill of lading 271191199
Preview: B/L → container MRSU5757040, INCHON → BERGEN OP ZOOM (HANJIN INCHON CONTAINER TERMINAL
→ BTT MULTIMODAL BERGEN OP ZOOM), 5 milestones, vessel GENOVA EXPRESS (IMO 9943906) on the map,
delivery 2026-08-12, status "Gate out for delivery". Full page renders, `track-not-connected`
count 0. An unknown reference now shows "Няма намерена пратка с този номер" instead of the Maersk
message, and `provider_error` is absent for an anonymous visitor.
Suites: 21 passed / 1 skipped on the tracking suites, 5 passed on the new one.

### Production is still on the OLD code, and its key never reached the process
`https://encareurope.com/api/tracking?ref=271191199&by=bol` → `{"configured": false}` for the
same B/L that renders fully on preview. Decisive: the JSONCargo counter sat at 21 requests, ALL
of them made from this pod, while the owner was loading the production tracking page — so the
deployed backend has never called the provider once. That means `JSONCARGO_API_KEY` is empty in
the running `/etc/encar/backend.env`, not merely that the carrier was blank. The owner's own
`curl` from back1 succeeded because he supplied the key by hand, which proves the network and
the key but says nothing about what the application reads.
Still outstanding from the owner: `grep JSONCARGO /etc/encar/backend.env`.

## 2026-06-08 — Live visitor bar (admin only) + a bill of lading tied to a car

### 1. Cookieless visitor counting
`backend/traffic.py`. What identifies a visit is `HMAC(daily_salt, ip|user-agent)` truncated to
20 hex chars. The salt is generated fresh each day in `traffic_salt` and expires after two days,
so once it is gone nobody — us included — can recompute yesterday's fingerprints or link them to
today. The raw IP is never stored. Nothing is written to the visitor's device, so ePrivacy's
consent rule for storage does not apply and the count is honest rather than "only those who
accepted a banner". Basis: legitimate interest, Art. 6(1)(f).
- `traffic_hits` keeps `{v, p, l, at}` only, TTL 40 days.
- `POST /api/traffic/ping` — public. Drops known bots by user agent AND drops an administrator's
  own browsing: an owner watching his own shop must not appear in his own "live now" figure.
  Wrapped so a counting failure can never break a page.
- `GET /api/admin/traffic` — live (5 min), what is being viewed right now (people per page, top
  6), and day / week / month as {visitors, views}. Unique counts use `$group` by visitor then
  count, never `$addToSet`, so a busy month cannot hit the 16MB document limit. 10-second cache
  because an open bar polls every 20s and every poll is an aggregation.
- `AdminTrafficBar.js` — thin dark strip, `sticky top-0`, collapsible. It sets `--admin-bar-h`
  on the document while mounted and `HeaderBar` now reads `top-[var(--admin-bar-h,0px)]` as its
  sticky offset, so the two stack instead of overlapping.
- `LangLayout` pings 1.2s after each route change: `useSeo` has set the title by then, and that
  title's first segment ("Hyundai Santa Fe DM") is the readable label. The delay also means a
  visitor bouncing through three pages in a second is not counted three times.
- Privacy policy: new section 2.10 in BG/RO/EN describing exactly this, and the stamp moves to
  v1.4 — section 17's own rule for a material change. THE OWNER'S LAWYER SHOULD SEE 2.10.

### 2. A bill of lading tied to a specific car
The gap was small and invisible: `/api/purchases` already joins shipments by `car_id`, and
`MyPurchasesPage` already renders a Track button per purchased car — but the admin form had no
car field, so `car_id` was always "" and the join never matched. The buyer therefore never saw
the reference and nothing anywhere said why.
- `GET /api/admin/customer-cars?email=` — that customer's reserved cars, newest first, with
  titles and `assigned_ref` so the operator can see a car is already on another B/L. An id typed
  from memory is an id typed wrong, and a mismatch here is silent.
- `AdminShipments.js` — a car picker that loads when a customer is chosen; the list shows the car
  by NAME instead of a bare id.
- `GET /api/admin/shipments` now resolves car titles in one lookup for the page.

### VERIFIED
- Traffic: `tests/test_traffic.py`, 9 tests — the digest is 20 hex chars and holds no address or
  user agent, the same visitor gets one digest within a day (else "people" and "views" would be
  the same number), the salt exists with a 2-day TTL, hits have a 40-day TTL, bots are refused,
  the numbers are 401 for a visitor, every window is present with views >= visitors, a fresh view
  appears as live, and windows widen rather than shrink.
- Live proof: four views from three browsers → `live: 3`, `day: {visitors: 3, views: 4}` (the
  browser that looked twice counted as ONE person), pages strip showed all three real labels.
  Bar screenshot confirms it renders above the header with `--admin-bar-h: 28px`, and the collapse
  toggle hides the windows while keeping the live count.
- Shipment→car end to end: seeded a held deposit → the car appeared in the picker → assigned B/L
  271191199 to it → the admin list showed "Hyundai Santa Fe DM (42341529)" → the picker flagged
  `assigned_ref: 271191199` → `GET /api/purchases` as the buyer returned `ref: '271191199'` on
  that car. Seed data removed afterwards.
- Suites: full run 219 passed / 2 skipped / 14 errors, where all 14 are the Stripe-hosted-checkout
  tests driven through Chromium; `test_deposit_refund_e2e.py` alone = 19 passed and
  `test_partial_refund_and_commission.py` alone = 9 passed. The errors are xdist contention on
  Stripe's page (`input#cardNumber` not visible inside 60s), not a regression.

### Environment note
`/pw-browsers` had lost its Chromium, which made 20 deposit tests ERROR with
"Executable doesn't exist". `python -m playwright install chromium` fixes it. Check this before
suspecting the payment code.

## 2026-06-08 — "are you sure the view count is working": it was, but only half-checked

The owner was right to push. Everything so far had been verified with `curl` and pytest, which
prove the SERVER counts. Nothing had proved that a real browser actually sends the ping — and
`ping()` ends in `.catch(() => {})`, so a 403 from the CSRF layer or a broken import would have
been swallowed in total silence and the bar would simply have read 0 forever.

Verified properly: an ANONYMOUS Chromium session (admins are not counted, so an admin session
proves nothing here) with an ordinary browser user agent set, listening on the network for
`/traffic/ping`. Five page loads → five requests, all `200 {"counted":true}`, five rows in
`traffic_hits`, ONE digest across all five (same person, five views), and the snapshot read
`live: 1, day: {visitors: 1, views: 5}`.

### A real defect the check exposed
The label came from `document.title.split(" · ")[0]`. Car pages set "{name} · Encar" so they
worked, but the home page title is "Автомобили от Корея с крайна цена до България | Encar" — a
pipe, not a middle dot — so the whole SEO headline became the label and would have swamped the
strip. Fixed with `labelFor()` in `lib/traffic.js`: fixed short names for every known route, and
the title only for a car page, because a car is the only page whose name cannot be known in
advance. Capped at 42 chars so several cars still fit on one line.
Now reads: `1× Начало · 1× Hyundai Santa Fe DM (2013-2016) · 1× Проследяване · 1× Как работи ·
1× Поверителност`.

Lesson recorded in agent_learnings.md: a fire-and-forget call that swallows its errors has to be
watched from the browser's network, not inferred from the endpoint working.

## 2026-06-08 — Traffic history: a Traffic tab in the admin panel

New `Traffic` tab (second, right after Overview) at `/{lang}/admin?tab=traffic`.
- `GET /api/admin/traffic/history?days=` in `traffic.py` — visitors and views PER DAY, oldest
  first, with quiet days filled in as zeros: a chart that silently skips empty days makes a flat
  week look like a busy one. `days` arrives from a query string so it is clamped to 1..40 rather
  than trusted.
- Unique visitors per day are counted by grouping on (day, visitor) then counting the groups —
  never `$addToSet` — so a busy month cannot approach the 16MB document limit.
- `components/admin/AdminTraffic.js` — four stat cards (live / 24h / 7d / 30d as
  visitors / views), a day-by-day bar chart with a hover tooltip per day, a 7-vs-30-day switch,
  and "being viewed right now". The solid part of each bar is the unique visitors, the pale part
  the total views.
- The chart is hand-drawn rather than charted with recharts. Recharts IS in package.json but was
  unused anywhere, so importing it would have added a few hundred KB to every visitor's bundle
  for one panel only an administrator opens.

### Tests
`tests/test_traffic.py` grew to 12: the history endpoint is admin-only (401), a fixed window
always returns exactly that many days with none missing or repeated and oldest first, quiet days
come back as zeros, visitors never exceed views on any day, and `days` is clamped (0 → 1,
-5 → 1, 9999 → 40).

### VERIFIED
Seeded 923 views over 30 days with two deliberately quiet days, then read the panel as an admin:
30 bars drawn, the quiet days render as zeros, the 7-day switch redraws 7 bars, cards read
14/29 (24h), 83/218 (7d), 366/923 (30d), and "най-силен ден 1.08 с 57". Live reads 0 because the
only visitor was the admin, who is deliberately not counted. Seed data removed afterwards.
Suites: 38 passed / 1 skipped across traffic, tracking, jsoncargo and password-reset.

## 2026-06 — Hetzner NAT redesigned: WireGuard tunnel instead of a default route via front1
Owner report: `ip route replace default via 10.0.0.2` on back1 fails with "Nexthop has invalid
gateway", and with `onlink` it is accepted but `ip neigh` shows `10.0.0.2 ... FAILED` and no
traffic flows. ROOT CAUSE: Hetzner's private network hands out /32 addresses, so back1's only
directly connected neighbour is Hetzner's router 10.0.0.1. front1's private address can never
be an L2 next hop. DO NOT retry `onlink` or hardcode 10.0.0.2 as a gateway.
`deploy/hetzner/ansible/playbooks/deploy_nat.yml` was refactored (nothing unrelated touched):
* WireGuard point-to-point over the private network (which works fine as transport):
  front1 wg0 10.99.0.1, back1 wg0 10.99.0.2, endpoint {frontend_private_ip}:51820. The port is
  opened ONLY from backend_private_ip to frontend_private_ip — never publicly.
* back1 uses POLICY ROUTING, never the main default route (`Table = off`): mangle OUTPUT marks
  packets owned by `backend_service_user` (www-data, matches the unit file) 0x1, `ip rule fwmark
  0x1 lookup 100`, and table 100's default is `via 10.99.0.1 dev wg0`. `throw` routes in table
  100 for private_cidr, 169.254.0.0/16 (metadata), 172.16.0.0/12 and 192.168.0.0/16 fall back to
  the main table. So SSH/Ansible/apt/private traffic keep Hetzner's own route and a dead tunnel
  cannot lock anyone out.
* rp_filter must be 2 (loose) — replies arrive on wg0 while the route to their source is the main
  default. Written to /etc/sysctl.d/99-<app>-nat.conf and applied per-interface in PostUp.
* front1 MASQUERADEs 10.99.0.2/32 ONLY (the old 10.0.0.0/16 rule is gone, same blockinfile
  marker), still in /etc/ufw/before.rules because ufw rewrites the nat table on reload.
* The obsolete /etc/netplan/99-<app>-nat.yaml is DELETED by the playbook — it restored the
  invalid `via 10.0.0.2` route on every reboot.
* Private keys are generated on each host (`wg genkey`) and applied by
  `PostUp = wg set %i private-key /etc/wireguard/wg0.key`; only public halves pass through
  Ansible, so wg0.conf carries no secret.
* Built-in verification: handshake present, main default route asserted NOT to point at front1,
  `curl ifconfig.me` as www-data asserted to equal front1's public IP, the unmarked path printed
  for comparison, and HEAD to Stripe/Anthropic/Resend/Encar through the tunnel.
* New group_vars: wg_port, wg_front_ip, wg_back_ip, wg_mtu (1370 — private network is MTU 1450),
  backend_service_user, nat_table (100), nat_mark, nat_rule_priority.
NOT TESTABLE FROM THE EMERGENT POD (no Hetzner network): verified only by
`ansible-playbook --syntax-check` and offline Jinja rendering of both wg0 templates. The real
proof is the owner's own run.

### Two real bugs found while the owner ran it (2026-06, both fixed, both CONFIRMED on the boxes)
1. `wg-quick` runs each hook with `set -e`, so a PostUp line starting
   `ip rule del ... 2>/dev/null;` ABORTED the whole hook on the first run (nothing to delete)
   and wg-quick tore the interface down again (`ip link delete dev wg0`). It needs
   `... || true;`. Proven on the box: the hook log stopped exactly on that line.
2. For LOCALLY generated packets the route is chosen BEFORE mangle OUTPUT, so the fwmark
   reroutes the packet onto wg0 but its source address stays the host's private one
   (10.0.0.3). front1's cryptokey routing only accepts 10.99.0.2 from that peer, so the
   packets were dropped SILENTLY — the symptom was `wg show` on back1 reading
   "632 B received, 17.41 KiB sent" (handshake only) and curl failing on DNS first
   ("Resolving timed out"), which looks like a resolver problem and is not one.
   Fix: `iptables -t nat -A POSTROUTING -o wg0 -j SNAT --to-source 10.99.0.2` in PostUp.
   Verified live: `runuser -u www-data -- curl ifconfig.me` -> 178.105.37.1.
DIAGNOSTIC THAT SETTLED IT (keep for next time): on back1 `ip rule show`,
`ip route get 1.1.1.1 mark 0x1` (must read `dev wg0 src 10.99.0.2`),
`iptables -t mangle -S OUTPUT`, `iptables -t nat -S POSTROUTING`, `wg show` (compare
received vs sent), and a DNS-free reachability test to an IP so a resolver failure cannot be
mistaken for a routing failure.

### nginx http2 syntax broke the nginx deploy (2026-06, fixed)
front1's nginx is older than 1.25.1, where `http2 on;` does not exist — `nginx -t` failed with
`[emerg] unknown directive "http2"` and `deploy_nginx.yml` stopped at "Configuration is valid".
`deploy_nginx.yml` now reads `nginx -v` into `nginx_version` (regex on the `nginx/X.Y.Z`
string, stderr) and `nginx-encar.conf.j2` renders `listen 443 ssl http2;` below 1.25.1 and
`listen 443 ssl;` + `http2 on;` at or above it. Verified by rendering the template through
Ansible for 1.24.0 and 1.27.3 — the right form each time.
The `protocol options redefined for 0.0.0.0:443` and `duplicate MIME type "text/html"` lines
are WARNINGS from the other site on that host (sites-enabled/autoandbid), not our config.

### A deploy was WIPING ENCAREUROPE_API_TOKEN off the server (2026-06, fixed)
`templates/backend.env.j2` had no `ENCAREUROPE_API_TOKEN` line, and `deploy_backend.yml`
REWRITES /etc/encar/backend.env from that template on every deploy — so the mobile.bg bot's
token vanished after each run and `/api/post-queue` answered 503
("ENCAREUROPE_API_TOKEN is not configured"). The value was never gone from group_vars; the
template was the hole. Line restored, `encareurope_api_token` documented as REQUIRED in
group_vars/all.yml.example.
Guard so it cannot happen again to any other secret:
`backend/tests/test_deploy_env_complete.py` asserts the template writes every key the app
cannot work without (24 of them). Tuning knobs with in-code defaults are deliberately not
listed. Run it before a deploy, like test_requirements_portable.py.
Checked at the same time: the only other keys in the pod's .env missing from the template are
EMERGENT_LLM_KEY and PLAYWRIGHT_BROWSERS_PATH, both platform-only and correctly absent.

## 2026-06 — Cars under contract on Encar are neither shown nor depositable
Owner's report: fem.encar.com/cars/detail/42482867 was still in our catalogue and reservable
even though Encar has a pending sale on it. The fact lives in TWO places and both are now used:
`SalesStatus` on the search row and `advertisement.salesStatus` on the per-car detail
(verified live on that car: "CONTRACT").
* `encar.under_contract(detail)` / `encar.sales_status(detail)` read the detail payload; None
  and a missing `advertisement` block answer False rather than raising.
* `sync.contracted(row)` + `sync.retire_contracted(db, ids)`: `skip_row` already refused to
  IMPORT them, but a car indexed while it was on sale used to stay visible until the
  end-of-sweep retire pass — hours away on a full crawl and never on a partial one. Both import
  paths now retire the ids they skip for contract straight away.
* `car_detail`: a live fetch that comes back CONTRACT goes to `_gone(..., contract=True)`, which
  sets `active: False, sold: True, under_contract: True` (what `build_query` already filters on)
  and answers 410 with the sold screen plus 12 similar cars.
* Details are cached forever because they are immutable — the STATUS is not, so
  `_recheck_contract` re-asks Encar in the BACKGROUND when the cached snapshot is older than
  CONTRACT_RECHECK_HOURS (6). One upstream request per car per 6h, never in the visitor's path.
* `deposits`: `_under_contract(car_id)` asks Encar LIVE before a checkout session is created
  (money path, no cache), falling back to the cached snapshot if upstream is unreachable so an
  outage cannot block every reservation. Refused with 409 `{"code": "car_contracted"}`, and the
  car is retired on the spot. `deposit_quote` carries `contracted` from what we already know, so
  the button is dead before anyone clicks it.
* Frontend: `ReserveCar` shows "Продаден по договор в Корея" / "Vândut prin contract în Coreea" /
  "Sold under contract in Korea" (new key `depositContracted`) instead of the reserve button, and
  handles the `car_contracted` code on checkout.
MISTAKE TO LEARN FROM (cost a 500 on EVERY cached car page): Mongo hands datetimes back NAIVE,
so `datetime.now(timezone.utc) - cached["status_at"]` raised
"can't subtract offset-naive and offset-aware datetimes". Always coerce with
`.replace(tzinfo=timezone.utc)` when a stored datetime is compared. Also: `server.py` imports
`encar` as the CLIENT INSTANCE (`from encar import encar, ...`), so module-level helpers must be
imported by name — `encar.under_contract(...)` is an AttributeError there.
Verified: 42482867 -> 410 with `contract: true` and 12 similar cars, listing flagged
`active:false, under_contract:true`, 0 contracted rows left active in the index, quote reports
`contracted: true`, checkout answers 409 `car_contracted`, a normal car still produces a Stripe
session (happy path intact), the BG car page renders the sold screen with no reserve button, and
237 backend tests pass. New suite: `tests/test_contract_status.py` (5 tests).

## 2026-06 — Shop-window floor, footer identity removed, per-language meta in the static HTML

### The landing view never shows a car under EUR 18 000
Owner: "on the home page never show cars below 18 thousand euro", and the taste shelf too.
`server.HOME_MIN_EUR` (env `HOME_MIN_EUR`, default 18000) with two helpers: `unfiltered(p)`
(true only when NOTHING narrows the search - q, makes, models, badges, badge_details, fuels,
regions, transmissions, year/mileage/price bounds, the three only_* flags) and
`apply_home_floor(query)` which RAISES an existing `sale_eur.$gte` but never lowers it.
Applied in `/search` when `unfiltered(p)`, in `_popular_shelf` and in the taste branch of
`/recommendations` (the shelf only exists on the landing view). The floor is deliberately NOT
a filter chip - it is our curation, not the visitor's choice - and it disappears the moment
someone searches or filters. A cheap-car taste profile whose window sits entirely below the
floor now falls back to the popular shelf, which is floored too; that is the owner's call.
Verified: unfiltered + price_asc -> cheapest 18 099 (total 63 517); the same search with
price_min 5000 -> cheapest 6 099 (total 146 253); shelf (popular) min 19 099; shelf (taste)
min 48 999; zero items under 18 000 in any of them.

### Company identity removed from the footer
Owner pasted the block and said remove: `SiteFooter` no longer renders name / EIK / VAT /
address / phone (the `facts` array is gone), and the copyright line now reads the BRAND
("Encar Europe") instead of `co.name`, which printed "Auto&Bid LTD". The email link stays.
`content/company.js` is UNCHANGED, so every legal document still carries the full
identification - that is where the obligation is met. Verified in the browser: the footer
contains none of "Auto&Bid", "208833206", "Бяла река", "671 7074", and still shows the email.

### /bg and /ro now carry translated meta in the RAW HTML
Owner: the meta title and description must be translated on /bg and /ro. Root cause: this is a
CRA bundle, so every route is served the same `index.html` and `lib/seo.js` only rewrites the
tags AFTER React boots - `curl https://…/bg` returned the English title and description.
* `scripts/seo-landing.json` - one source for the per-language landing title/description
  (same copy as `seoHomeTitle`/`seoHomeDesc` in `src/i18n_extra.js`).
* `scripts/gen-lang-html.js`, wired as `postbuild` in package.json, does two things:
  writes `build/{bg,ro,en}/index.html` with the translated `<title>`, `description` and
  `<html lang>` baked in, and injects a tiny script after `</title>` in the root
  `build/index.html` that patches those three from the URL's first segment before the bundle
  loads (that is what covers DEEP routes like /bg/car/123).
* nginx template: `try_files $uri $uri/index.html /index.html` - the `$uri/index.html` step is
  what serves the per-language copies, with no redirect and no change to the canonical URL.
* GOTCHA THAT COST A BUILD: CRA MINIFIES index.html and strips HTML comments, so a
  `<!--LANG-SEO-->` placeholder never reaches build/. The script anchors on `</title>`
  instead, and is idempotent (`/*gen-lang-html*/` marker).
Verified: build/bg/index.html and build/ro/index.html carry the right lang/title/description;
the root shell keeps the English default plus the patch script exactly once after two runs; the
injected code was executed against a stub DOM for /bg, /bg/car/…, /ro/track, /en, / and /xx
(the last two correctly leave the English default alone); and in the browser /bg, /ro and /en
each report their own title, description, `<html lang>` and canonical.
KNOWN LIMITS, deliberate: a CMS seo override (Admin -> Pages, per language - /ro and /en
currently have one) wins at RUNTIME but is not baked into the static copies, and a deep route
read WITHOUT JS still shows the English default. Both need SSR or a build-time API call; not
worth it while Googlebot renders JS.

## 2026-06 — Bargain hunters, the real counter, price diversity, and a hidden car title

### A visitor sorting by cheapest first is not fenced in by the shop-window floor
`floored = unfiltered(p) and body.sort != "price_asc"`. Someone asking for the cheapest cars is
hunting a bargain; pushing EUR 18 000 cars at them is the opposite of helpful. Verified:
unfiltered default sort -> total 63 517, cheapest 18 499; `sort=price_asc` -> total 146 253,
cheapest 6 099.

### The counter advertises the whole library, not the floored slice
`/search` returns `total_all` (the real catalogue count, cached 5 min in `_catalogue_total()`)
next to `total`, which stays the FLOORED count so paging never offers empty pages. The frontend
reads `result.total_all ?? result.total` for the count label, the floating filters bar and the
"show results" button. On a filtered search the two are identical.

### Why the landing view was a wall of EUR 23 000 cars, and the fix
The home page sorts by `relevant`, which is either the popular list (most opened of the
fortnight) or the visitor's taste ranking scored on PRICE PROXIMITY to their own browsing
centre. Both pull towards a single number, and the diversity caps in `_spread` only ever
looked at model and make — never price. The new EUR 18 000 floor then cut off the bottom and
compressed what was left into an even narrower band.
* `_band(doc)` buckets by `sale_eur` at 22k/28k/35k/45k/60k/90k.
* `_spread(..., per_band=)` caps a bracket like it caps a model or a make; passed as
  `max(3, size // 4)` (6 of 24) and ONLY on the shop-window view, so a visitor's own price
  filter is never second-guessed.
* `_space` breaks up price-bracket RUNS as a SECOND preference, after make, so the ranking
  survives.
* The popular branch had no diversity at all and now gets the same treatment, with everything
  the caps reject queued behind so paging stays complete.
Verified on page 1: popular branch 7 brackets, max 6 in one (19k...419k); taste branch
7 brackets, max 6 in one, with the visitor's own bracket still holding the most.

### The car title was hidden behind the menu (admin only, which is why the owner saw it)
`DetailStickyBar` was `fixed top-16` — a hardcoded 64px that assumes the header starts at 0.
`HeaderBar` sits at `top-[var(--admin-bar-h,0px)]`, so the admin traffic bar (28px, admins
only) pushed the header down over the car bar. Now
`top-[calc(var(--admin-bar-h,0px)_+_4rem_+_1px)]`, and `CarDetailPage`'s mobile padding plus
the SearchPage mobile filter bar got the same treatment.
TWO GOTCHAS, both cost a round trip: CSS `calc()` REQUIRES whitespace around `+`, and Tailwind
arbitrary values cannot contain spaces — so it must be written with UNDERSCORES
(`calc(var(--x)_+_4rem)`). Without them the declaration is invalid and silently dropped.
Verified as a signed-in admin: header 28-93px, car bar starts at 93, title at 105 - fully
visible.

### Test suite
`tests/test_home_floor.py` (5 tests) covers `unfiltered()`, the raise-never-lower floor and the
narrowing fields. `test_relevant_sort.py` gained a shop-window test, and its old "filtered"
assertion was fixed: it passed `manufacturer`, which is NOT a search field, so it was really
comparing two landing views. 249 backend tests pass.

## 2026-06 — Hero rebuilt, trust strip removed, hidden h1

The owner rejected TWO attempts before this one. What they rejected, so nobody rebuilds it:
* the original pale pink gradient wash (`hero-bg` linear-gradient + `hero-grain` noise dots);
* a CENTRED hero on a blueprint grid with a radial red glow and a pulsing "radar" dot next to
  the catalogue counter. Their words: "this looks like every vibecoded ai slop project I have
  ever seen", "don't use the glowing radar red dot", "I really don't like the background".
DO NOT reintroduce: centred hero copy, gradient/gradient-wash backgrounds, the grid overlay,
noise textures, glowing or pulsing dots, pastel pink tinted icon tiles.

What it is now (`components/Hero.js`, `.hero-bg` / `.hero-panel` in index.css):
* Left-aligned, two columns on desktop (`minmax(0,1fr) 320px`, bottom-aligned), one column on
  a phone. A SOLID surface, no gradient, no texture: paper `hsl(220 16% 96%)` in light mode,
  `hsl(222 18% 7%)` in dark. Depth comes from the panel and hairlines only.
* Right: a specification panel — the three Encar guarantees as label + what it contains
  (`heroChip1Note`/`2Note`/`3Note`, new keys in all three languages), hairline-divided, red
  lucide icons. It replaced the pill chips, which orphaned the third pill on its own row and
  left the desktop column empty.
* CTA: red, 10px radius, an arrow that nudges on hover; the counter beside it is plain tabular
  text with NO indicator dot.
* Entrance: `.animate-rise` (a 10px rise + fade) staggered 0/60/120/180ms via inline
  `animation-delay`, disabled under `prefers-reduced-motion`. No library.
* Padding cut twice at the owner's request; now `py-6 sm:py-8 lg:py-9` (hero is 311px tall on
  a 1440 desktop, down from 351).
* The kicker line ("ДИРЕКТЕН ВНОС ОТ ЮЖНА КОРЕЯ") was added and then REMOVED on request; the
  `heroKicker` key was deleted from all three languages.

`TrustStrip` (Крайна цена / Документи / Бързо търсене) was DELETED on request — the component
file is gone and the usage is out of SearchPage. The `trust1Title`…`trust3Body` i18n keys were
left in place, harmless, in case the owner wants the block back.

Hidden h1: the landing view renders `<h1 className="sr-only">Encar Europe</h1>` as the FIRST
heading, and the hero's own headline became an `<h2>` with identical classes — so the page has
exactly ONE h1 and it is the brand. `sr-only`, deliberately NOT `display: none`, which search
engines discount. Verified: one h1 on the page, text "Encar Europe", box 1x1px.

The hero CTA now scrolls to the MAKE/MODEL/SUBMODEL dropdowns (`taxRef`), not to the results
list, offsetting the sticky header AND `--admin-bar-h` by hand because `scrollIntoView` puts
the target under the header. Verified: after the click the МАРКА label sits at y=92 with the
header ending at 65.

### Hero panel type size and MOBILE-ONLY vertical tightening (2026-06)
* The specification panel's rows went up a step at the owner's request: label 13px -> 14px
  (`text-sm`), note 11.5px -> 13px, icon 16 -> 17px.
* Then vertical space was cut on the PHONE ONLY — the owner was explicit that the desktop
  spacing must stay. Every cut is a base utility with an `sm:` restoring the old value:
  hero wrapper `py-4 sm:py-8 lg:py-9`, hero grid `gap-5 sm:gap-8`, standfirst `mt-3 sm:mt-3.5`,
  CTA row `mt-5 sm:mt-7`, panel rows `py-3 sm:py-3.5`; Recommended wrapper
  `py-4 sm:py-7` and its card row `mt-3 sm:mt-4`.
* Measured after: desktop hero 311px and Recommended 418px (UNCHANGED); at 414px wide the hero
  is 499px with 16px padding top and bottom, Recommended 378px.

## 2026-06 — Mobile admin bar, drawer preference circles, How-it-works expanded

### The admin traffic bar showed only the live count on a phone (fixed)
The three windows were `hidden sm:flex` / `hidden md:block`, so a phone got the live number and
nothing else. Now the numbers wrap onto a SECOND ROW below 640px as
"24ч 3/90 · 7д 3/90 · 30д 3/90" (visitors/views), and the bar height is MEASURED with a
`ResizeObserver` and published as `--admin-bar-h` instead of the old 28px constant — otherwise
the taller bar would cover the header. Verified at 414px: bar 54px, header starts at exactly 54.

### Admin accounts are NOT counted — this was already true
The owner reported admins showing in the live count. `traffic_ping` already refuses to record a
request whose session belongs to an admin. PROVED with identical user agents: anonymous ->
`{"counted": true}`, admin -> `{"counted": false}`. Note when testing: `BOTS` in traffic.py
matches `curl`, so a plain curl ping always answers `counted: false` regardless of the session —
pass a browser `-A` string or you will chase a bug that is not there.
Remaining honest explanations for what the owner sees: browsing from a device/browser where they
are NOT signed in, or 24h/7d/30d windows still holding rows recorded before the exclusion
existed. Historic rows cannot be attributed retroactively — the digests are anonymous by design.

### The drawer's three preferences are one line of circles
ЕЗИК / ВАЛУТА / ТЕМА were three labelled rows of segmented controls in `NavDrawer` (the MOBILE
menu). Now three 44px circles on one line showing the current value. First attempt made them
CYCLE on press; the owner corrected that: a press must OPEN the full list. Language and currency
are `DropdownMenu`s with a check on the active option (`language-option-*` /
`currency-option-*` testids kept), theme stays a straight toggle (`theme-toggle`) because with
two states a menu is one tap too many.

### How it works: deposit, contract, tracking and an FAQ
Added below the existing four steps and the price breakdown, in all three languages
(`howDepositTitle/Body`, `howContractTitle/Body`, `howTrackTitle/Body`, `howFaqTitle`,
`howFaq1..4Q/A` in i18n_extra.js) plus a `Detail` panel and a `<dl>` FAQ in HowItWorksPage.
Every claim is checked against the code: 10% deposit (DEPOSIT_RATE), a card HOLD and not a
charge, expiring after 7 days (AUTH_DAYS), EUR 300 commission (COMMISSION_EUR) due only on a
real purchase, verified email required, QES contract, bill-of-lading/container tracking, and
cars under contract in Korea being unreservable. If those env values change, the copy must too.
CAUTION WHEN VERIFYING: the preview DB has a CMS stub page for how-it-works in BG and RO
("Стъпка едно / Стъпка две") which REPLACES the whole built-in page, so the new sections only
appear on /en there. Production has no such stub.

## 2026-06 — The first impression: a hand-picked shelf, and previews for pasted car links

### "Picked for you" for somebody we know nothing about
A visitor with no taste profile used to get `_popular_shelf` — whatever the crowd clicked.
Now `POST /api/recommendations` answers `source: "curated"` from the owner's own list first,
and only falls back to `"popular"` when the list is off or nothing in it is in stock. The
moment a visitor looks at anything, their own taste takes over exactly as before.

Picks are stored as ENCAR'S OWN values (Korean marque, Encar model code) plus an optional
`badge` SUBSTRING, so a pick can be one specific version of a model. The seven the app ships
with (`DEFAULT_PICKS` in server.py) are BMW M2 (G87), Ferrari 458, Hyundai Santa Fe (MX5),
Mercedes C-Class W205 + "C63", Hyundai Palisade, Mercedes GLE-Class W167 + "GLE400d",
BMW X3 (G01) + "M40i". Never store translated labels here — a pick that stopped matching
would fail silently.

Owner's list lives in `site_settings._id = "default_taste"` `{enabled, picks[]}`; no document
means the built-in seven. Admin tab "Picked for you" (`AdminRecommendations.js`,
`/api/admin/reco-defaults` GET/PUT + `/reset?stats=`) edits it and shows, per pick: cars in
stock, impressions, opens, CTR and DEPOSITS EARNED. Impressions are written when the shelf is
built (`_reco_seen`), opens by `POST /api/reco/click` which the shelf fires ONLY when
`source === "curated"`, and deposits are computed live by matching `deposits.car_id` against
the picks. Counters live in `reco_stats`, keyed `make|model|badge`.

### A car link pasted into Viber/Messenger/WhatsApp now previews as the car
`GET /api/share/car/{id}` already carried og:image = the ad's first photo at 1200x630, but
nothing linked to it, so a pasted `/{lang}/car/{id}` previewed as nothing (chat apps never
run our JS). nginx now sends SOCIAL CRAWLERS ONLY to that endpoint: a `map` on the
user-agent (`$encar_crawler`) plus a regex location for `^/(bg|ro|en)/car/([^/]+)/?$`.
A human still gets the app through `try_files`.
TRAP, cost an hour: nginx CLEARS the location's `$1`/`$2` inside an `if`, so the first version
proxied to `/api/share/car/?lang=` and answered 404. The captures are copied into
`$share_lang` / `$share_id` BEFORE the `if`. Verified end to end with a real nginx on the pod:
`facebookexternalhit` gets the share HTML with the car's photo, `Mozilla/5.0` gets the shell.
The owner wants nothing on the card but the car's own first photo — no branded overlay.

Tests: `backend/tests/test_default_shelf.py` (9 passing) — curated source for an anonymous
visitor, every car belongs to a pick, a real taste profile still wins, admin 401 without an
admin, a click counted against its pick, an unknown car ignored, switching the shelf off
falling back to popular, and the share page carrying og:image + summary_large_image.

NOTE seen while testing: the translation provider is answering 429 (quota) in this
environment, so newly seen Korean model names stay Korean until the key has balance again.

## 2026-06 — Saving needs an account, a call button with opening hours, "Капарирай"

### Saving a car or a search now requires an account
Both used to be written straight into `localStorage` for anybody, which is a promise we cannot
keep: it is gone on the next device and the price-drop / new-match emails have nowhere to go.
`components/SignInGate.js` is a provider mounted INSIDE `AuthProvider` (so it can see the
session) that exposes `requireAccount("car" | "search")`. It returns `true` when signed in,
`false` and opens a dialog offering Вход / Регистрация otherwise — the owner explicitly chose
a DIALOG over a redirect so the buyer does not lose the car or the filters they were on.
Gated at all five call sites: `CarCard`, `CarRow`, `QuickViewDialog`, `CarDetailPage` (both the
sticky-bar heart and the desktop one) and `SearchPage`'s save-search.
`LoginPage` now honours `location.state.from` (stored WITHOUT the language prefix, because
`go()` puts it back) so sign-in returns to the car. `logout()` clears the local favourites and
searches — otherwise one person's hearts stayed on a shared machine. `/saved` and `/searches`
show `SignInPrompt` instead of an empty list when nobody is signed in. The backend already
required auth on `/auth/favourites` and `/auth/saved-searches`; nothing changed there.

### "Обади се" beside the enquiry button, gated by the owner's opening hours
`GET /api/call-button` decides everything ON THE SERVER (`Europe/Sofia`, `CALL_TZ`): a phone's
clock and time zone cannot be trusted. Config in `site_settings._id = "call_button"`
`{enabled, phone, phone_label, hours{mon..sun:{open,close,closed}}}`; no document means the
built-in default (+359886717074, Mon–Fri 09–18, Sat 10–15, Sun closed). `_hhmm()` returns ""
for anything it cannot parse, and a window with no times in it is CLOSED whatever the flag
says. Admin card `AdminCallButton.js` at the top of the Enquiries tab (`GET/PUT
/api/admin/call-button`). Outside the hours the button still dials, but `CallButton.js` first
shows the week's hours and asks whether to continue.
LAYOUT, per the owner: the call button makes the enquiry button HALF AS WIDE — the row on the
car page is `sm:grid-cols-2` with a nested `grid-cols-2` holding EnquiryDialog + CallButton,
and the reserve button takes the other half.

### "Блокирай сумата" → "Капарирай", with the terms in a dialog
The checkbox + small print under the button are gone. The button opens
`deposit-terms-dialog`, which carries `depositTerms` and `depositBlurb`, and the single
`deposit-agree-continue` button ("Съгласен съм с условията, продължи към преавторизация") IS
the acknowledgement. `dark:text-white` on the button — the red-on-dark label was unreadable.

### Two mobile bugs found and fixed
1. CarDetailPage's container had `pt-[calc(var(--admin-bar-h,0px) + 72px)]`. The admin traffic
   bar sits in NORMAL FLOW, so the container already starts below it — counting it twice left
   an admin on a phone with ~78px of nothing between the car bar and the first photo. Now a
   flat `pt-[72px]`, which is exactly the fixed car bar (65px) plus a gap. Measured at 390px:
   bar bottom 130, photo top 154.
2. The deposit dialog ran off the side of a phone. Cause was NOT the height: `Button`'s base
   class carries `whitespace-nowrap`, and the whole-sentence label forced a min-content width
   wider than 390px, dragging the grid (and the dialog) with it. Fixed with
   `whitespace-normal h-auto min-h-12 py-3` on that button, plus
   `w-[calc(100vw-2rem)] max-h-[88svh] overflow-y-auto` on this dialog, the call dialog and the
   sign-in gate. Measured at 390x844: 16–374 wide, 197–647 tall.

Tests: `backend/tests/test_call_button.py` (6) + `test_default_shelf.py` (9) pass. Testing
agent iteration_38.json: 13/13 frontend scenarios passed, 0 defects.

## 2026-06 (later) — Call-backs, the shelf ranking itself, Cayenne's years, Sofia clocks

### "Leave a number and we will call you", outside hours only
`POST /api/callback` books a ring-back. The requested slot is RE-CHECKED on the server against
the owner's hours: a form is a suggestion, not a fact, and a call booked for a Sunday never
happens. Refused for a closed day, a time outside the window, a moment already past, a phone
with under 6 digits, or a bad email (the owner wanted BOTH phone and email). Stored in
`callbacks` `{when, when_label, phone, email, status: new|called|closed}`; the existing enquiry
letters carry it, with the requested time folded into the message, so no new templates.
Admin list `AdminCallbacks.js` under the Enquiries tab, soonest first, with new/called/closed.
BUG my own check caught before the owner did: `openDays()` offered TODAY whenever the schedule
said the day was open, so at 19:09 on a Saturday that shuts at 15:00 the day was listed with
ZERO remaining slots — empty time dropdown, form impossible to submit. `openDays` now builds
each day's slots and drops any day with none left.

### The shelf orders itself
`auto_rank` (on by default) sorts the picks by `deposits × 10 + CTR` — a reservation is proof, a
click is only interest. THE GUARD THAT MATTERS: below `min_impressions` (default 50, editable) a
pick is NOT JUDGED at all — score `null`, keeps its configured place, keeps collecting data.
Without it a pick with one impression and one click would sit at 100% CTR forever. Leftover
slots go to the front of the order (top picks get 2 cars, the rest 1), so nothing vanishes.
The 60s `_rank_cache` is fine for the shelf but the admin screen passes `fresh=True`: a cached
order beside freshly computed scores contradicted itself on the page (two tests caught it).

### A renamed model was silently losing its years
`curate.display()` returned the owner's manual label and went home, so `카이엔 (PO536)` renamed to
"Cayenne" showed NO production span while the other two generations showed theirs. A rename
replaces the NAME, not the years — level 2 now always routes through `model_label()`.
Live: Cayenne (2019-) / (2011-2018) / (2004-2010). Test: `tests/test_model_year_labels.py`.

### Admin clocks are Sofia, always
Every admin timestamp was `toLocaleString()` — the DEVICE's timezone — and AdminTraffic cut the
day at a UTC boundary. `stampSofia()` / `daySofia()` in `AdminBits.js` pin `Europe/Sofia`, used
by Enquiries, Catalogue sync, Pages and Traffic. The call-button logic was already correct
(server-side Sofia, verified: pod UTC 16:11 → 19:11 EEST).

### An outage I caused, and how to avoid repeating it
`search_replace` wrote `backend/server.py` from a STALE copy twice: once duplicating the tail
(caught by py_compile) and once EATING the middle of `tracking_lookup` plus the
`@api.get("/tracking/saved")` decorator — a SyntaxError that took the backend down and left the
site with no ads. Recovered from `git show HEAD:backend/server.py`. Lesson, worth the pain:
after any large edit to server.py run `python3 -m py_compile server.py` AND compare the
def/class/route signature list against HEAD — syntax alone passed while a whole block was gone.

Tests: 31 pass across recommendations, default shelf, call button, callbacks/ranking and model
year labels; 249 pass across the full suite. `test_recommendations.py` had asserted the OLD
contract (`source == "popular"` for an empty profile) and was updated to the curated shelf.
Pre-existing, NOT regressions: the Stripe checkout e2e modules error out because the Playwright
browser binary is missing in this pod (`playwright install`).

## 2026-08-09 — iMessage: "Range: bytes=0-" now answers 206, not 200
- LIVE VERIFIED FIRST: the deployed server already returned 206 for partial ranges
  (bytes=0-1023) and correct HEAD answers — the previous fix WAS deployed. The one remaining
  deviation: `Range: bytes=0-` (the OPEN range Apple's CFNetwork opens every fetch with)
  came back **200 + full body**, because `_binary` deliberately downgraded a range that spans
  the whole file (`ranged = start != 0 or end != len-1`). Apple reads a 200 answer to a Range
  request as "this server does not do ranges" and drops the image -> icon/logo fallback.
- FIX in server.py `_binary`: ANY syntactically valid Range header is now answered 206 with
  Content-Range, even one spanning the whole file. `bytes=-` (degenerate, no numbers) raises
  ValueError and falls back to a plain 200. Verified locally: bytes=0- -> 206 full
  Content-Range; bytes=0-1023 -> 206/1024; bytes=500-999 -> 206/500; no header -> 200;
  If-None-Match -> 304; bytes=999999999- -> 416.
- RULED OUT while investigating: meta refresh in the share HTML (TN3156: "Link previews do
  not follow meta redirects" — metadata is read from the linked page itself); Cloudflare HTML
  caching (cf-cache-status: DYNAMIC on both bot and human UA, so nginx UA-routing always runs);
  UA mismatch (iMessage sends "...facebookexternalhit/1.1 Facebot Twitterbot/1.0", matched by
  the nginx map — confirmed by fetching live with that exact UA).
- NEEDS DEPLOYMENT by the owner (Save to GitHub -> git pull -> ansible). After deploy verify:
  curl -s -o /dev/null -D - -H "Range: bytes=0-" 'https://encareurope.com/api/image-proxy?...'
  must show HTTP/2 206 + content-range. Then test iMessage with a car link NEVER shared before
  (iMessage caches previews per URL on the device).

## 2026-02-27 — Maybach taxonomy reverted (agent mistake cleanup)
- Reverted the 마이바흐-badge-promotion rule in `/app/backend/encar.py` (normalise_row).
  Rule was: `if badge.startswith("마이바흐"): manufacturer = "마이바흐"`. Removed.
- DB cleanup:
  - Moved 368 modern Mercedes-Maybach listings (S-클래스 W222/W223, GLS X167, EQS SUV X296)
    from `manufacturer=마이바흐` back to `manufacturer=벤츠`.
  - Stripped the stray `마이바흐 ` prefix from 3045 벤츠 badges (side-effect of an
    over-broad restore). Next crawl repopulates the correct Encar-supplied badges.
  - Rebuilt taxonomy.
- Final state: 마이바흐 make holds ONLY the 6 legacy listings (57 x2, 62 x3, 62s x1) —
  all currently `active=False` (upstream crawl hasn't seen them this cycle, separate
  issue that user confirmed is "working now").

## 2026-08-31 — PWA polish, server-only account lists, custom lightbox zoom

### PWA / Liquid Glass tab bar (`PwaTabBar.js`, `index.css`)
- Blur walked down on user request: 28px -> 12 -> 6 -> **3px**, saturation 190% -> **112%**,
  `brightness`/`contrast` dropped (they read as "washed out" at low blur).
- Tint: light `rgba(255,255,255,.48)`, dark `rgba(18,18,22,.48)` — see-through veil per user.
- Capsule sits lower: `bottom: max(8px, calc(env(safe-area-inset-bottom) - 14px))`. Earlier
  `- 24px` overlapped the iPhone home-indicator line (user caught it), `+ 2px` floated too high.
- Height 60 -> 66px, radius 33px (true capsule), icon 32 -> 26px, tab padding 4px/6px.
- REFRACTION (`.lg-refract`, new layer between blur and tint): a much stronger blur
  (22px/sat 240%) MASKED to the outer rim by two union-composited gradient masks (horizontal +
  vertical). Safari does NOT support SVG displacement maps in `backdrop-filter`, so real
  Apple-style refraction is impossible in a browser; an SVG filter there would have voided the
  whole `backdrop-filter` and killed the blur on iPhone.
- Chromatic aberration was added on request, then REMOVED entirely on request. Rim is neutral
  white on all four edges again.
- Active pill: was one `.lg-tab-pill` per tab (could only blink); now ONE `.lg-pill` for the
  bar, positioned by measuring the active tab. Covers icon AND label, `border-radius: 9999px`.
- Pill motion: position rides the CSS `translate` property (NOT `transform`) so `scale` can be
  animated independently. Page change = 460ms `cubic-bezier(.32,.72,0,1)` slide; finger down =
  `scale: 1.06 1.12` swell (220ms, slight overshoot); during a drag `translate` is written raw
  with no transition (easing there reads as lag).
- DRAG-TO-SCRUB: pointer capture on `.lg-tabs`, `touch-action: none`, free-form clamped x under
  the finger, nearest-tab resolution on release, `go(TAB_ROUTES[key])` to navigate, and a
  one-shot `suppressClick` so the anchor's retargeted click does not navigate twice. Plain taps
  still navigate natively.
- BUG FOUND+FIXED while testing: `go()` already applies the language prefix, so
  `go(path("/searches"))` produced `/bg/bg/searches`, which SearchPage parsed as make/model
  slugs (make=bg, model=searches).
- Long-press link preview killed: `-webkit-touch-callout: none` + `onContextMenu` prevented.

### Dynamic Island / sticky bar overlaps (the recurring one)
- ROOT CAUSE of the "car title bar follows the menu" / jitter complaints: the header carried a
  DYNAMIC `padding-top` (island inset minus whatever was above it), so its height changed on
  every scroll frame while a banner scrolled away, and every bar hanging off it chased the
  change. Second cause: those bars read a `--header-bottom` published from a rAF scroll
  listener, i.e. always one frame behind.
- FIX: the island inset is reserved ONCE on `body.pwa-standalone { padding-top: env(...) }`.
  Header height is constant, sticky at `calc(var(--admin-bar-h) + var(--safe-top))`, and
  publishes only `--header-h` (ResizeObserver, no scroll listener). Dependent bars position
  themselves in pure CSS from `--header-h`. `--header-bottom` and `--header-top` are gone.
- `DetailStickyBar` is now `sticky` on mobile / `fixed` on `lg`. It was `fixed` while the
  header is `sticky`: during iOS rubber-band overscroll a fixed bar is welded to the viewport
  while a sticky header travels with the content, so the two visibly came apart. Removed the
  matching `pt-[72px]` compensation on the detail container (the bar reserves its own height).
- Pop-down sheets (burger menu, filters drawer) reserve the inset as `padding-top` and offset
  their absolutely-positioned close button by `calc(.75rem + inset)`. First attempt moved the
  whole panel down with `top: env(...)` and exposed the dialog's BLACK overlay in the island
  strip (user reported "black above the menu").
- `body.pwa-standalone::before` paints the island strip in the card colour (z-index 44, below
  the tab bar, above the header) so nothing shows through once the header scrolls away.

### Notifications
- `NotificationsPrompt` recoloured to the install banner's red (`--primary` + white text).
- Signed-out visitors are NOT offered push. Copy switches to "sign in to get notifications" and
  the CTA goes to `/login`. Reason (user's call): every notification is about a saved search or
  saved car, both of which live on the account, so an anonymous device would subscribe to
  silence — and `searchwatch.py` only walks `db.users`.
- NEW `NotifyConsentDialog.js`: asks for push the moment a buyer signs in INSIDE the installed
  app. Fires on the signed-out -> signed-in transition only (gated on `loading` so a restored
  session on cold start is not mistaken for a login). Shares the 30-day dismissal key with the
  banner; "Not now" snoozes 7 days. New i18n keys in bg/ro/en/pl: `notifyPromptLoginTitle`,
  `notifyPromptLoginBody`, `notifyPromptLogin`, `notifyPromptLater`.

### Favourites + saved searches are now SERVER-ONLY (user: "Всичко трябва да е в сървъра")
- `AppContext`: both lists are in-memory only, hydrated from the account. All `localStorage`
  writes removed; a mount effect deletes the legacy `encar.favourites` / `encar.searches` keys.
  `authedRef` + `setAuthed` make every mutator a no-op when signed out (backstop behind the
  existing `requireAccount` UI gate).
- `AuthContext`: merge-on-login is gone (nothing local exists to merge) — `adopt(user)` takes
  `user.favourites` / `user.saved_searches` straight from `_public(user)`.
- SAFETY GUARD: `hydratedFor` ref. The two debounced (800ms) PUT syncs refuse to run until the
  in-memory lists belong to the signed-in user, otherwise an un-hydrated empty list could
  overwrite and erase the whole account list.
- GDPR: the cookie policy in `src/content/legal.js` (bg/ro/en) declared those two localStorage
  entries. Those bullets were removed — the policy no longer describes storage we do not do.

### Lightbox zoom is OURS, not the browser's (`Lightbox.jsx`)
- Single-photo viewer: native zoom disabled (`touch-action: none`) and replaced with pinch,
  double-tap (2.5x at the tapped point), one-finger pan while zoomed (swipe still navigates at
  1x), clamped to 1x–4x with translation limited so the photo's edge never enters the frame.
  Zoom-to-point maths: `t1 = p - (s1/s0)(p - t0)`.
- Desktop: double-click, wheel-to-zoom at the cursor, ctrl+wheel (trackpad pinch on
  Chrome/Firefox), macOS Safari trackpad pinch driven from `gesturechange`'s `e.scale` (Safari
  does not send ctrl+wheel — it was only being cancelled), `+` `−` `0` keys, and an on-screen
  −/%/+ control (`lightbox-zoom-out|reset|in`) that doubles as the "you are zoomed" cue.
- Multi-photo column (`detail-lightbox`): native zoom off entirely — `touch-action: pan-y` plus
  document-level `gesture*` prevention while open (Safari's pinch is only stoppable there).
  Zooming used to drag the sticky close button out of reach.
- BUG FOUND+FIXED by simulated-pinch testing: `zoomRef` was synced by an effect, so when
  `touchmove` and `touchend` land in the same task (a quick pinch) `touchend` read a stale 1x,
  concluded the photo was not zoomed and threw the gesture away. Gesture handlers now write
  `zoomRef` synchronously via `applyZoom()` and mirror into state for rendering.
- Touch/gesture/wheel listeners are attached by hand with `{passive: false}`: React registers
  touchstart/touchmove/wheel passively at the root, where `preventDefault()` is ignored.

### Notes
- Production domain (user): **encareurope.com** or **encareu.com**. Nothing is hardcoded —
  `PUBLIC_SITE_URL` (backend) and `REACT_APP_SITE_URL` (frontend) drive canonicals, sitemaps,
  OG tags and email links; they stay on the preview host in preview and are set at deploy.
  Two things would still point at the preview host in production:
  `frontend/public/robots.txt` (hardcoded Sitemap line) and the default in
  `src/content/company.js`. AWAITING USER DECISION: which domain is canonical, and whether to
  serve robots.txt dynamically from `PUBLIC_SITE_URL`.
- Testing agent iteration_43: 9/9 frontend scenarios pass, `retest_needed: false`. It left
  2 favourites (42341529, 41728299) and 1 saved search ("BMW") on the admin account.
- REMINDER: the preview host is `encar-multi-lang.preview.emergentagent.com`. `encar-eu...`
  from an older handoff is stale and returns "Preview Unavailable". Also: opening the app on
  `localhost:3000` shows "Network Error" because the frontend calls the external backend URL —
  always test against the preview host.

## 2026-08-31 (later) — My Encar tab, share buttons, canonical domain

### PWA tab bar: share slot became "My Encar"
- 5th tab is now the account (`UserRound`, `pwaTabAccount`): `/account` when signed in,
  `/login` when not. It is a real route tab, so the pill lands on it, and it stays lit on
  `/account`, `/login` and `/register`. Sharing moved to where the shared thing is.
- CRITICAL BUG FOUND BY TESTING: plain taps on tabs stopped navigating when drag-to-scrub
  introduced `setPointerCapture` — a captured pointer retargets the follow-up `click` to the
  capture container, so the NavLink's own click never fired. `onPointerUp` now performs the
  navigation for EVERY pointer interaction (tap included) and swallows the retargeted click.
  Releasing more than 60px above/below the bar cancels instead of navigating. Keyboard
  activation still reaches the anchor (a click with no pointer sequence).

### Share buttons (standalone only, `useShare` hook in `src/hooks/useShare.js`)
- `navigator.share` with a clipboard + toast fallback, one hook for all call sites.
- Car page: in `DetailStickyBar` (which IS the car's header row on mobile), immediately left of
  the favourite button, with byte-identical classes — verified 40x40 vs 40x40, same radius and
  border. FIRST ATTEMPT WAS WRONG: it went into the page title row, which is wrapped in
  `hidden ... lg:flex`, i.e. desktop-only, so nothing appeared on the phone (user caught it).
  That desktop copy was kept for the desktop PWA.
- Search page: beside the save-search button, matching `h-11 gap-2 rounded-[10px] px-4 text-sm`
  and the same `hidden sm:inline` label rule — verified 50x44 vs 50x44, same padding and font.
- New i18n key `pwaShareAria` ("Сподели" / "Partajează" / "Share" / "Udostępnij"); `pwaShare`
  and the `Share2` import are gone from the tab bar.

### Canonical domain: encareurope.com, with encareu.com redirecting (user's decision)
- `canonical_host_middleware` in `server.py`: 301s any alias host onto `CANONICAL_HOST`,
  preserving path and query. Registered after the CSRF middleware so it runs BEFORE it — an
  alias request should be redirected, not token-checked. Inert while the env vars are unset,
  which is how preview keeps working.
- DEPLOY STEP (not set in preview .env on purpose):
      CANONICAL_HOST=encareurope.com
      REDIRECT_HOSTS=encareu.com,www.encareu.com,www.encareurope.com
      PUBLIC_SITE_URL=https://encareurope.com      # canonicals, OG, sitemaps, email links
      REACT_APP_SITE_URL=https://encareurope.com
  Verified with a temporary env: `Host: encareu.com` on `/bg/car/41728299?make=bmw&page=2`
  returned `301 -> https://encareurope.com/bg/car/41728299?make=bmw&page=2`; the canonical host
  and the preview host returned 200. The temporary env was then removed and the inert
  behaviour re-verified.
- `GET /api/robots.txt` renders robots.txt with the `Sitemap:` line from `PUBLIC_SITE_URL`, so
  it can never go stale. Route `/robots.txt` to it in nginx the way `/sitemap.xml` already is.
  Until then the static `frontend/public/robots.txt` names `https://encareurope.com/sitemap.xml`.

### Share button polish (same session)
- Icon switched from lucide `Share2` (the three-node graph glyph) to `Share` — the iOS
  box-with-an-arrow-out-the-top the owner asked for, by screenshot. Applied in all three
  places: `DetailStickyBar`, `SearchPage`, `CarDetailPage` (desktop title row).
- "Border is different" report: measured, and the borders are BYTE-IDENTICAL
  (`1px solid rgb(223,226,231)`, same box-shadow, same background, same radius) whenever both
  buttons are enabled. The only real difference was state: on the unfiltered home page the
  save-search button is DISABLED and dims to `opacity: .6`, which reads as a lighter border.
  Added the matching `disabled:opacity-60` to the share button so the pair cannot drift apart
  in any state. If the owner still perceives a mismatch, it is that dimming, not the border.
- Dead `onShare` removed from `PwaTabBar` (it referenced `toast` after the import was dropped
  along with the share tab — a blocking lint error).

### Car photos in emails (2026-08-31)
- ROOT CAUSE, and it was worse than a wrong size: the price-drop email had NO photo at all.
  `send_price_drop` rendered the text-only `_row()`, and `pricewatch.py` never even fetched
  `photos` from Mongo. The one email whose entire job is "look at this car again" was the one
  that never showed the car.
- `mailer.car_thumb(photos)` + `CARD_W, CARD_H = 300, 169` is now the single source for every
  email thumbnail. It is the same CDN transform the website's card uses (`image_url(p, 570,
  320)` — same `impolicy`, same centre crop, same watermark), at half the size, which is also
  2x the 150x84 box for retina. VERIFIED: email src and site src differ only in the size
  numbers.
- `send_price_drop` now renders each car with `_digest_car` (photo + title + price/year/km),
  passing the cut as the red `note` line. `pricewatch.py` projection gained `photos`,
  `year_month`, `mileage`; rows now carry `image`, `price_eur`, `year`, `mileage` (`now_eur`
  became `price_eur` — it had exactly one reader). The push notification path is untouched: it
  only reads `title`, `cut_pct`, `car_id`.
- `_digest_car`'s photo box was 150x100 (3:2) while the file is 16:9 — email clients honour the
  width/height ATTRIBUTES, so that squashed every car. Now 150x84.
- `digest.py` uses `mailer.car_thumb()` in both places instead of its own `image_url(..., 300,
  200)`, so digest and price-drop can no longer drift to different crops. Its now-unused
  `image_url` import was removed.
- `send_new_matches` was left alone: it has no callers anywhere (dead code — new-match alerts go
  out as push, and the weekly digest carries the email).
- Verified by building the real email HTML against a live listing: `<img>` present, absolute
  https URL, 150x84 attrs, localised subject, cut note rendered, no `&nbsp;` placeholder.
  DELIVERY still cannot be verified — the Resend API key is invalid.

## 2026-09-01 — Description translation quality rewritten + full AI cost monitoring

### The description translation bug (P0, owner: "lowest quality I have seen in my life")
Root cause found and removed. `translate_description_segmented` split every dealer
description on line breaks, then split each LINE again on commas/dots/dashes/brackets
(`_fragment_split`), translated the fragments, and stitched them back. Worse: those
fragments went through `_llm_translate`, whose system prompt is the UI-LABEL one
("be concise: most of these are UI labels and spec values, not prose") — the dedicated
`DESC_SYSTEM`/`DESC_RULES` prompt was never used on the segmented path. The model never
saw a sentence, so the output was word-for-word rubbish with no grammar.

Now (`translate.translate_description`):
  1. whole-description cache (`type: "description"`) — a re-visit is one indexed read;
  2. line-level cache — a description whose every Korean line is already known is
     assembled without an LLM call (owner asked to keep this layer);
  3. otherwise ONE contextual call over the FULL text with `DESC_SYSTEM`, streamed to the
     browser token by token (Anthropic Haiku, Gemini as standby with one patient retry on
     a free-tier 429).
`_fragment_split`, `_harvest_fragments`, `_from_fragments` and `stream_description` are
deleted. 538 poisoned `description_fragment` / `description_line` rows were removed from
`db.translations` at the owner's instruction. Verified live: fluent Bulgarian prose, no
Hangul, numbers/model names/decorative bars preserved; second request served from cache in
~0.2s with no new LLM call.

### AI cost monitoring (owner: "log every api call, extract cost from the api key, daily report")
- `translate.meter()` writes ONE row per provider call into `db.ai_calls`: ts, Sofia day,
  provider, model, kind (description / labels / latin / spec / cms_page / warm-up field),
  lang, input+output tokens, cost by list price (`translate.PRICES`), duration, ok/error.
  Wired into every provider path, including `cms.py` page translation (both providers),
  which was previously unmeasured. 100-day TTL.
- `aicost.py`: `billed()` reads the REAL invoiced amount from the Anthropic Admin API
  (`/v1/organizations/cost_report`, day buckets, cached in `db.ai_billing`). Needs
  `ANTHROPIC_ADMIN_KEY` (sk-ant-admin…) — absent in preview, so the panel shows the
  estimate and says so. `daily_report()` rolls a day up into `db.ai_reports` and emails it;
  `check_budget()` fires one alert the moment a day crosses the ceiling; `scheduler()`
  reports at 21:00 Sofia and probes the budget every 30 min.
- `mailer.send_ai_cost_report()` — Bulgarian letter, normal and alert variants.
- API: `GET /api/admin/ai-usage?days=`, `PUT /api/admin/ai-budget`,
  `POST /api/admin/ai-report/send`.
- Admin panel tab "AI разходи" (`AdminAiUsage.js`): today/7d/30d/average cards, per-day cost
  chart with the invoiced figure in the tooltip, breakdown by purpose and by model, cache
  counters, budget editor, "изпрati отчет сега", report archive, breaker and error list.
- Default budget $5/day, editable in the panel.

Environment notes: the preview `ANTHROPIC_API_KEY` returns 401, so every fresh description
logs one anthropic failure and then succeeds through Gemini — that is what the failure rows
in the panel are. Production has a valid key. `ANTHROPIC_ADMIN_KEY` must be added to the
production env for the invoiced column to fill in.

## 2026-09-01 — Secret audit of the repository

Asked: "are there any keys in github". Scanned every tracked file and the whole git history.

CLEAN: no `.env` was ever committed (`git log --all --diff-filter=A -- '*.env'` is empty), and
no provider key of any kind is in the tree — no Anthropic, Gemini, Stripe, Resend, JSONCargo,
VAPID, TOTP or Mongo credential, no `*.pem`/`*.key`. `.gitignore` covers `.env`, `.env.*`,
`*.env`, `*.key`, `*.pem`, `credentials.json`, `memory/test_credentials.md`, and the real
`deploy/hetzner/ansible/inventory.ini` + `group_vars/all.yml`.

FOUND AND REMOVED — three real credentials WERE in tracked files:
* `ADMIN_TOKEN` (the admin master header token) hardcoded in
  `backend/tests/test_ai_usage_and_desc.py`, `test_google_auth_and_cms.py`,
  `test_owner_password_admin.py`;
* `ADMIN_SEED_PASSWORD` ("<the real ADMIN_SEED_PASSWORD value>") in six test files;
* `OWNER_PASSWORD` ("Nero") in `test_owner_password_admin.py` and in
  `deploy/hetzner/ansible/group_vars/all.yml.example` (together with the owner's real email);
* all three quoted inside ~30 `test_reports/iteration_*.json`.

Fix: every test now reads the value from the environment (`conftest.py` already loads
`backend/.env`), the Ansible example carries placeholders, and the reports were scrubbed
(`memory/secret_scrub.py` is the one-off that did it). `pytest backend/tests/test_owner_password_admin.py`
= 11/11 pass afterwards.

STILL REQUIRED FROM THE OWNER: the old values remain in git HISTORY, so they must be rotated —
new `ADMIN_TOKEN` (`openssl rand -base64 24`), new `ADMIN_SEED_PASSWORD`, and a new owner
password. Then `ansible-playbook ... deploy_backend.yml --tags config,service`.

## 2026-09-03 — One price per car (search / car page / saved list / deposit)

Reported: `/bg/kia/stinger` showed 12299 EUR, the ad page 13099 EUR, the saved list a third
figure. Proven on production with `GET /api/car/42207598?refresh=1` → **12299**, i.e. the
list was right and the car page was wrong.

Root cause: two different sources for the asking price.
* `listings.price_krw` — rewritten by every catalogue sync while the ad is in Encar's search
  results. Search, the saved list (`/listings/by-ids`) and every shelf use it through
  `publish_prices`.
* `car_details.detail.advertisement.price` — a snapshot written the FIRST time that car page
  was ever opened, then served from cache forever (the code comment claimed a re-fetch "every
  few hours"; there is none). The car page preferred THIS one.
  Measured: 125 of 388 cached details disagreed with the listing (32%), up to EUR 800 apart.
  For this Kia the dealer had cut ~1160 → 1050 manwon; only the list noticed.

Fix (`server.py`, the pricing block of `GET /api/car/{id}`): an ACTIVE listing's own
`price_krw` is now the authority. The cached advertisement price is used only when the car is
inactive/archived, where the stored value is frozen at the last sync and the dealer can still
have edited the ad — that branch is unchanged.

Also aligned the deposit: it was 10% of the raw stored `sale_eur` while the page could be
showing the higher live-FX quote. New `pricing.published_sale(car, rates, constants)` is the
single rule (stored `sale_eur`, unless the live quote is higher) and `deposits.py` uses it in
the quote, the checkout amount and the stored `car_price_eur`.

Verified on preview with a car whose cached detail (50.0M KRW) disagreed with the listing
(52.0M): car page 40099 = saved list 40099 = deposit 40099 (4009.90). `test_fx_haircut.py`
+ `test_security_deposit.py`: 7 passed, 1 skipped — `test_car_quote_uses_buffered_rate` now
skips when its fixture car has gone inactive (it was comparing against a frozen KRW price).

## 2026-09-04 — The outage that hid itself, and the watchdog that will not let it

Owner reported "mobile loading issues on the ad details page". Measured on production:

| request | result |
|---|---|
| `/bg/car/...` (nginx, static) | 200 in 0.21s |
| `/api/car/42207598` | **524 after 125 seconds** |
| `/api/car/.../more-from-model` | 200 in 0.54s |
| `/api/deposit/car/...` | 200 in 0.21s |
| `/api/health` (minutes later) | **502** |

Not a mobile problem and not a frontend one: the shell renders instantly and the car data
never arrives. `more-from-model` and `deposit` only read Mongo, so they were fine.
`/api/car/{id}` is the one endpoint that talks to Encar upstream on a cache miss — and back1
had no route out, because `deploy_nat.yml` never finished (ssh host key, then an apt lock).

Two fixes, both about time:

1. `encar.py get_json` — an interactive read (a human waiting on a car page) now gets 12s per
   request, 2 attempts, backoff capped at 2s: ~26s worst case. It used to use the bulk-sync
   settings for everything: 5 attempts x 30s + 15s of backoff = over two minutes, which is
   past Cloudflare's 100s limit, and with ONE uvicorn worker a handful of those requests
   takes the entire site down. The bulk sync keeps its patient pacing.

2. `watchdog.py` (new) — emergency notifications to EVERY administrator, as the owner asked.
   Four probes on a 60s loop, all of them invisible from outside the box:
     * `egress` — can the host reach the internet at all (the tunnel / NAT route)
     * `encar` — is Encar answering (checked only when egress is healthy, so one outage
       raises one alarm)
     * `mongo` — does the database answer a ping
     * `mail` — is the Resend key still valid (every 30 min), because a dead key silences
       every other alert
   A check must fail twice in a row before anything is sent. Then every `is_admin` account
   is reached by web push AND email (plus ADMIN_NOTIFY_EMAIL / OWNER_EMAIL), with a reminder
   every 30 minutes while it lasts and an all-clear when it recovers. Push carries no event
   name on purpose: an emergency cannot be muted by notification preferences. Incidents live
   in `db.incidents`; `GET /api/admin/incidents?run=1` probes on demand.
   Admin panel: a red strip at the top of Overview (`AdminIncidents.js`), or a one-line
   all-clear when everything passes.

Two real bugs were caught while testing this, both in the watchdog itself:
  * recovery depended on an in-memory failure streak, so an incident raised before a restart
    could never be closed — the panel would keep screaming about an ended outage. A passing
    probe now always asks Mongo whether something is open.
  * Mongo returns naive datetimes, so `_now() - doc["opened_at"]` raised — which killed both
    the 30-minute reminder and the all-clear. Everything read from a document now goes
    through `_aware()`.

Verified live on preview: the `encar` probe genuinely fails there (no egress to Encar), the
incident opened after the second failure, and all three admin addresses were attempted —
`admin@encarskin.com`, `martingtodorov@gmail.com`, `webmaster@encareurope.com` — each
rejected only because the preview Resend key is invalid. Recovery was tested with a planted
incident: closed and announced in under a second.

STILL FOR THE OWNER: finish `ansible-playbook playbooks/deploy_nat.yml` (the apt lock was
first-boot `unattended-upgrades`; a wait step was added to every playbook) and restart
`encar-backend`. Also `deploy/hetzner/ansible/tasks/wait_apt.yml` is new.

## 2026-09-04 (later) — Outage alerts made push-first

Owner: "искам да са push известия." Push was already the first channel, but three things
made it weak, and one of them made it silent:

* `sw.js` now honours `require_interaction`, `renotify` and `vibrate` from the payload. An
  outage card stays on screen until it is touched and buzzes again on every reminder;
  everything else keeps the quiet default.
* `notify.py` — `push_to_user` / `push_to_admins` take arbitrary payload extras plus `ttl`
  and `urgency`. Incident pushes use `Urgency: high` (wakes a sleeping phone instead of
  being batched), a 24h ttl (a phone that was off overnight still gets it) and one `tag`
  per check, so a reminder REPLACES the previous card instead of stacking twelve of them.
* Email is now the backstop, not a second channel: it only goes out when push reached ZERO
  devices. No more duplicate noise.
* `notify.admin_devices()` counts subscribed admin devices, returned by
  `GET /api/admin/incidents` as `push_devices`.

The thing that would have made all of this pointless: **there are no push subscriptions at
all** (`push_subscriptions` is empty for both admin accounts). A push channel with no devices
is silence, and silence looks exactly like "nothing is wrong". So the incident strip now
states the device count out loud and carries two buttons — "Включи на това устройство"
(`enablePush()`) and "Изпрати тестова авария" (`POST /api/admin/incidents/test`, a real
emergency-grade push, so the channel is provable before it matters).

Verified: endpoint returns `{"sent": 0, "devices": 0}` and the strip renders
"Нито едно устройство не получава push известия" with both buttons. The owner must tap
"Включи на това устройство" on each phone/laptop he wants woken.

## 2026-09-05 — The 407 that sold live cars: seven confirmed production bugs

### 3 (the serious one) — data corruption
`encar.get_json()` returned None for every unexpected status, and `car_detail()` read a
falsy detail as Encar retiring the ad: `_gone()` set `active: false, sold: true,
sold_at: now`. So during the CloudFront 407 window, every uncached car a visitor clicked was
removed from the catalogue while being perfectly live.

The client now speaks in two distinct answers:
* `None` — ONLY an authoritative 404. The single case allowed to retire a car.
* `EncarUnavailable` (new, subclasses RuntimeError so existing sync handlers still catch it)
  — transport error, 403/407/511 block, 429/5xx, an empty 200, or a 200 whose body is not
  JSON. Never touches the database.
An unexpected status is not retried at all (we do not know what it means) and never returns
None.

### 6 — bounded interactive calls + circuit breaker
Interactive reads (a human on a car page): 12s per request, 2 attempts, backoff capped at
2s ≈ 26s worst case. Bulk sync keeps its patient 5x30s. Circuit breaker: 4 consecutive
failures opens it for 60s; a 403/407/511 opens it immediately for 180s, because retrying a
shut door is a storm. `encar.breaker()` exposes the state.

### 5 — availability: index-only fallback
`_partial_detail()` builds a real page from `db.listings` when upstream is unavailable:
photos, make/model/trim, year, mileage, fuel, gearbox and the local price, with
`partial: true` and a reason. NOT written to `car_details` — a half-empty permanent record
would hide the real car forever. Cached cars are untouched; if only the SIDE documents
(record/inspection/diagnosis/choice) failed, the assembled detail is served but not cached,
so the missing history is fetched on the next visit instead of being frozen in.
Frontend: amber banner + retry on the car page, `partialData` string in bg/ro/en/pl.

Two regressions were caught by testing this and fixed:
* `option_dicts()` propagated `EncarUnavailable`, so a FULLY CACHED car page returned 500 the
  moment the breaker opened — a working page destroyed by a missing glossary. It now keeps
  whatever copy it has. Same for `record()`, where a failing `open` endpoint used to skip the
  perfectly available `summary`.
* the fallback stubbed `insurance/inspection/diagnosis` as `{"available": false}`, but the
  page decides whether to render those panels by whether the OBJECT exists — the truthy stub
  walked straight into `car.diagnosis.items.map` and crashed the page. They are `None` now.

### 4 — restoring the falsely-sold rows
`backend/restore_false_sold.py`: window by `sold_at`, dry-run by default. Skips cars under
contract and cars whose `last_seen` predates `sold_at` by more than `--stale-hours` (default
6). `--verify` confirms each candidate against Encar and leaves genuine 404s alone — use
that on production. Proven on three synthetic cases: restored the false one, skipped the
stale one and the contract one.

    python restore_false_sold.py --from 2026-09-04T20:00:00Z --to 2026-09-04T21:00:00Z \
        --verify --apply

### 1 — WireGuard policy routing, by UID instead of a mark
`wg0-back.conf.j2` now sets `default via {{ wg_front_ip }} dev %i src {{ wg_back_ip }}` in
table 100 and selects with `ip rule uidrange $(id -u www-data)-$(id -u www-data)`. The mark
design was tested and does not work: route selection happens BEFORE mangle OUTPUT, so the
packet already carried the host's private source when the mark moved it onto wg0 — inner
packets left enp7s0 with source 10.99.0.2 and front1's wg0 RX error counter climbed. A
uidrange rule is evaluated during the FIRST lookup, so the route's `src` is what source
selection sees. UID is read with `id -u` rather than hardcoded 33.
`deploy_nat.yml`: removes any leftover fwmark rule and mangle MARK, backs up the working
wg0.conf to `wg0.conf.ansible-backup` before overwriting, and verifies with
`ip route get 1.1.1.1 uid <uid>` asserting `dev wg0` AND `src 10.99.0.2`, plus a check that
no fwmark rule survives.

### 2 — the /etc/hosts pin is not the fix
`deploy_nat.yml` now REMOVES any pinned `api.encar.com` line: a hardcoded CloudFront edge
that gets retired takes the whole catalogue with it. DNS decides again, and the breaker plus
the fallback mean a 407 costs a section of one page instead of the site. The playbook also
probes Encar as www-data and reports the status without failing the run.

### 7 — verification (run on preview, where upstream genuinely 407s)
* uncached car during 407: **200 in 0.13–0.28s**, `partial: true`, real photos/price/mileage,
  across six different cars
* no mutation: active 6→6, sold 4050→4050, car_details 1062→1062, and no `car_details` row
  written for any of the six
* fully cached car: 200, full payload (31 photos, 21 insurance fields, 68 options), no
  `partial` flag
* search: 200 in 0.15s, unaffected
* browser: banner + retry render, gallery and spec panel intact, insurance panel degrades to
  "Няма налични данни"

STILL FOR THE OWNER (needs the boxes): `deploy_nat.yml` for the uidrange fix and to drop the
/etc/hosts pin, then `restore_false_sold.py --verify --apply` for the incident window.

## 2026-06 — Ansible: two deploy-time failures fixed (deploy_nat.yml + all apt tasks)
* Peer public keys are now read from the other host with `delegate_to` inside the play that
  needs them (`peer_pubkey`), so `--tags`, `--limit` and a re-run after a failure no longer
  lose the `wg_pubkey` fact from play 1. Templates use `peer_pubkey`.
* `lock_timeout: 300` on all 7 `ansible.builtin.apt` tasks — `wait_apt.yml` only proves the
  lock was free a moment ago; apt-daily/unattended-upgrades could re-take it in between.
