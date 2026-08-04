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
