# Changelog

Newest first. Verified = confirmed by the testing agent, report referenced.

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
