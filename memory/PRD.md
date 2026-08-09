# Encar Localised Skin — PRD

<!-- 2026-08-08: FACEBOOK "og:image processed asynchronously" WARNING. The dimensions were
already declared on every page, so the real cause was the RACE the notice describes: the crawler
reads the HTML, then fetches the picture, and our proxy was going all the way to Encar's CDN in
Korea for it — too slow, so Facebook queued it and the first share had no image. Now
`_encar_image()` keeps every proxied photo under `MEDIA_ROOT/imgcache` (name = sha256 of the
source URL, suffix = the real image type) and `share_car` WARMS it in a background task while it
answers the HTML, so the crawler's fetch is local: measured 0.155s against a cold CDN round trip.
Added the missing `og:image:type` — `image/jpeg` for a car photo, `image/png` for the route map
and the logo plate. Chat apps and Facebook cache previews hard, so an already-shared URL keeps
the old blank preview until "Scrape Again" in the Sharing Debugger. -->

<!-- 2026-08-08: TERMS AT GOOGLE SIGN-UP + COUNTRY DROPDOWN.
GOOGLE. `POST /auth/google/session` no longer creates an account on trust: when the identity has
NO account yet and the body carries no `terms_version`, it answers **409 `terms_required`** and
writes nothing. Google proving who somebody is does not accept our terms for them. Signing in to
an EXISTING account never asks again. The tick made on the sign-up form survives the redirect in
`sessionStorage` under `TERMS_HANDOFF` (`encar:terms-accepted`, set in `LoginPage.googleSignIn`,
read and cleared in `AuthCallback`); when it is absent — somebody who pressed "sign in" but turns
out to be new — `AuthCallback` renders the checkbox itself and retries with `TERMS_VERSION`, so
the account is still created in the same visit. `terms: {version, at}` is stored either way.
NOT VERIFIED END TO END: this path needs a real Google account, so it is code-reviewed only. Test
it by signing in with a Google address that has never been used here.
COUNTRY IS A DROPDOWN. `BillingFields` had a two-letter free-text box, which produced "bg", "BGR"
and "Бг" in the same column. It is now a select of all 222 countries from `/api/geo`, preselected
from the visitor's IP, and an address saved under the old field is matched forward ("bg", "BGR" or
"Bulgaria" -> BG) so an existing account does not open blank. Label lost its "(BG, RO…)" hint in
all three languages. The phone field spans the full width (it was sharing a row and the number
box was ~30px wide).
Verified in the browser: 223 options, preselect from IP, picking BG sticks, phone prefix
"Bulgaria +359", number field 226px, submit still gated by the terms tick. Backend: 45 tests pass
across the registration suites (`tests/conftest.py` completes `terms_version` for the older
files). -->

<!-- 2026-08-08: CONSENT, TERMS AND PHONE NUMBERS (one session, owner-driven).
COOKIE CONSENT IS NOW BLOCKING. It was a bar along the bottom and buyers scrolled straight past
it, so for them nothing outside the strictly necessary category could ever be written — the
owner's "some users have not been asked" was real. `CookieBar` is a modal over everything
(`z-[200]`, `cookie-overlay` testid): body scroll locked, Tab trapped inside the panel, Escape
and backdrop clicks ignored WHILE the choice is outstanding, no close button. Reopened from the
footer afterwards it behaves as an ordinary closable dialog. Refusing stays as easy and as
prominent as accepting (three equal buttons), toggles start OFF. Verified: overlay present on
/bg/login?mode=register, body overflow hidden, a click on the form underneath does not reach it,
and after a choice the overlay goes and overflow returns.
Also FIXED a compliance bug in `taste.setConsent`: adopting the decision recorded on the ACCOUNT
called `save()`, which re-stamps it with the CURRENT policy version — a policy change would then
never ask again. New `consent.adopt()` keeps the original `v` and `ts`, so `hasDecision()` is
false when the policy has moved on.
TERMS ACCEPTANCE AT SIGN-UP. Mandatory unticked checkbox ("Прочетох и приемам Общи условия и
Поверителност", links open in a new tab); the Sign Up button is disabled until it is ticked.
`auth.register` REFUSES an account with no `terms_version` and stores
`terms: {version, at}`, returned by `_public`. The version the buyer was shown lives in
`frontend/src/lib/legal.js` (`TERMS_VERSION`) — bump it when either document changes.
While wiring this up: the billing address typed on the SIGN-UP form was being collected and then
DROPPED — `AuthContext.register` never passed it to `apiRegister`. It is sent now.
NOTE THE GAP: a Google sign-up does not pass through this checkbox.
PHONE NUMBERS. `lib/phone.js` + `backend/phones.py` normalise everything to E.164 and reject what
cannot be dialled, checked in the browser AND at the API (`/enquiry`, `/callback`,
`PUT /notifications/phone`). `PhoneInput` (`components/PhoneInput.jsx`) is a dial-code dropdown
plus a number field, used by the enquiry dialog, the call-back form, the billing fields
(sign-up + account) and the account phone panel. The prefix is PRESELECTED from the visitor's IP:
`GET /api/geo` answers from a CDN header (`cf-ipcountry`) or a cached IP lookup
(`backend/geoip.py`, keyed by a HASH of the address, 30-day TTL, never the address itself) and
also serves the full list (`backend/dialcodes.py`, 222 entries). Shared codes resolve by COUNTRY,
not alphabet, so +1 shows "United States" to a New Yorker rather than "Canada". Verified: a
national "0881234567" posted to /enquiry is stored as "+359881234567", "88" is refused with 400.
TESTS: `tests/test_terms_acceptance.py` (3 passing) covers the refusal, the stored version/date
and the sign-up address. `tests/conftest.py` completes `terms_version` for the twelve older
suites that register throwaway buyers — the gate itself is tested for real in the new file. -->

<!-- 2026-08-08: CONTACT FORMS PREFILL THE PHONE. The enquiry dialog and the out-of-hours
"call me back" form filled in name and email from the account but NOT the number, and the
account's number was not even exposed: `auth._public` returned `billing` only, while a number
kept for notifications lives at `users.phone`. Now `_public` returns one `phone` field
(`users.phone` first, then `billing.phone`) and both forms read it. A number typed by a
signed-in buyer is REMEMBERED (`server._remember_phone`, called after the enquiry and the
callback are stored) but never overwrites one the account already has. Verified end to end:
login -> phone "" -> enquiry with a number -> `/api/auth/me` returns it -> both dialogs open
with phone, name and email already filled. -->

<!-- 2026-08-08: SUB-MODELS WERE BEING LOCALISED ON THE CAR PAGE ONLY — root cause found. The
detail payload ends with a LEFTOVER-KOREAN pass (`collect_korean` + `apply_translations`) that
walks the whole payload and replaces any Hangul string with the PAGE language. `badge` and
`badge_detail` still held Korean there (the `_t` fields are in-memory only, never stored), so the
page printed "Дизел 2.0 2WD Noblesse" / "Топ клас" / "(Без подкатегория)" while the rows and the
filters said English. `grade` was worse: it went through `T()` on purpose. Fixed three ways:
(1) `NO_TRANSLATE_KEYS` now contains `badge`, `badge_detail`, `grade` — the leftover pass can
never touch a trim again; (2) `car_detail` resolves all four trim strings from the ENGLISH cache
(`translate_cached_only(..., "en")` via the new `L()`), and schedules the English translation of
anything still Korean so the next view is right; (3) `grade` prefers OUR cached English trim
before Encar's `gradeEnglishName`, so the page, the rows and the dropdown spell it identically
("4-Door 43 4MATIC+", not Encar's "4Door 43 4MATIC+").
SEO TITLE now carries the trim: `CarDetailPage` builds `seoTitle` = title + grade + badge_detail
(years stripped, parts never repeated), so 42174617 reads
"Mercedes-Benz AMG GT 4-Door 43 4MATIC+ · Encar" in the tab, in og:title and in search results,
while the H1 stays "Mercedes-Benz AMG GT". Verified in the browser and through
`/api/share/car/42174617`. -->

<!-- 2026-08-08: LINK PREVIEWS (og:image) — FOUND: nothing was ever blocking bots. The ONLY
user-agent logic anywhere is the nginx `$encar_crawler` map, which ROUTES chat-app crawlers to
`/api/share/car/{id}` so a preview HAS a picture, and it lives ONLY in
`deploy/hetzner/ansible/templates/nginx-encar.conf.j2` — i.e. on the owner's own server. THAT is
why nothing previews on the PREVIEW URL: this pod's ingress sends only `/api` to the backend, so
`/bg/car/123` is always answered by the CRA shell, and `public/index.html` carried NO og tags at
all. Fixed:
* `public/og.png` (1200x630) is the owner's own logo on the #141414 brand plate, built from
  `public/logo.png`. Full og:/twitter: tags now sit STATICALLY in `public/index.html` with an
  absolute image URL via `%REACT_APP_SITE_URL%` (new key in frontend/.env, CRA substitutes it at
  build AND in dev). So every shared URL previews with the logo and the site's title.
* `lib/seo.js` default picture moved from the square `icons/icon-512.png` to `/og.png` and now
  emits og:image:width/height.
* TRACK PAGE PREVIEW IS A REAL MAP: `backend/mapshot.py` renders the shipment's route on
  OpenStreetMap tiles server side (1200x630 PNG) — tiles cached forever under
  `MEDIA_ROOT/tiles`, composed pictures for 6h under `MEDIA_ROOT/mapshots`, real User-Agent per
  OSM policy, so one preview costs zero upstream calls after the first. Endpoints:
  `GET /api/map/track.png?ref=&by=` and `GET /api/share/track?ref=&by=&lang=`. With no reference
  it draws Incheon -> Singapore -> Rotterdam. `TrackPage` passes the same URL to `useSeo`, and
  `scripts/gen-lang-html.js` writes `build/<lang>/track/index.html` with the map as og:image.
* nginx template gained the same crawler route for `^/(bg|ro|en)/track/?$` (passes `$args`).
* `share_car` title now carries the TRIM (`badge_detail` or `badge`): "BMW 5 Series (F10) 520d",
  "Mercedes-Benz S-Class W223 S580L 4MATIC". It was make + model only.
STILL TRUE AND WORTH REMEMBERING: a per-CAR photo preview needs the request to reach a server
rule. On the preview host that is now `frontend/src/setupProxy.js` — the CRA dev server sends a
crawler UA on `/{lang}/car/{id}` and `/{lang}/track` to the matching `/api/share/...` page with a
302, and a human falls through to the app untouched. Production uses the nginx `$encar_crawler`
rule instead (car was already there, track added). Verified on the preview host with a
`facebookexternalhit` UA: car link -> the ad's own photo + "BMW 5 Series (F10) 520d", track link
-> the OSM route map, home -> the logo plate, human UA -> the normal app.
SHARE TITLES: `_share_title` builds make + model + trim + sub-trim from the ENGLISH cache and
(a) strips generation years — the owner does not want "(2018-2023)" in a preview, and
`CarDetailPage` now passes `stripGenerationYears(car.title)` to `useSeo` for the same reason,
(b) drops anything still in Hangul, (c) drops a purely parenthetical sub-trim, because Encar's
"(세부등급 없음)" translates to "(No detailed trim)" and is filler, (d) never repeats a part.
`PUBLIC_SITE_URL` and `REACT_APP_SITE_URL` must both be changed at go-live. The DOMAIN IS
**encareurope.com** and the deploy config already carries it (`group_vars/all.yml.example`
`site_domains`, `backend.env.j2` -> `PUBLIC_SITE_URL`); `deploy_frontend.yml` was missing
`REACT_APP_SITE_URL` in the `yarn build` environment, which would have made every og:image
RELATIVE in production — it is passed now. -->

<!-- 2026-08-08: TRAFFIC COUNTERS ARE CALENDAR PERIODS, NOT ROLLING WINDOWS. `traffic._day_start`
returns midnight in `ADMIN_TZ` (Europe/Sofia) N calendar days ago, converted to UTC, and
`snapshot()` uses it for all three cards: today from 00:00, the last 7 calendar days (today
included, so `_day_start(6)`) and the last 30 (`_day_start(29)`). `history()` starts on the same
boundary and groups with `$dateToString(..., timezone="Europe/Sofia")`, so a hit at 01:00 Sofia is
counted on the day the owner would call it. Before this, "24h" at 07:10 still carried half of
yesterday evening. Labels updated: "Днес (от 00:00)", "Последните 7/30 дни (с днешния)".
Verified: today 7 visitors / 194 views since 2026-08-07T21:00Z (= 00:00 Sofia), 7 days 207 views,
history grouped per Sofia day. -->

<!-- 2026-08-08: PICKED-FOR-YOU RANKING BUG — the shelf was being won by a deposit that no
longer existed. `_reco_deposits` counted EVERY document in `deposits`, so an abandoned checkout
(`pending`), a timed-out one (`expired`) and a refunded one (`released`) all scored as retention
(x10 in `_pick_score`). It now counts only money actually held:
`payment_status in deposits.HELD_STATES` (authorised / captured / paid). Measured before and
after on the real data: the C63 pick showed 1 deposit from a RELEASED authorisation and ranked
first at score 13.4; it now shows 0 and ranks first on CTR alone at 3.4, M2 (G87) second at 1.52
(both had dep 0 for the M2 all along - the number the owner saw was this stale count).
`/admin/reco-defaults` also now ranks with `fresh=True`, as its own docstring always intended,
so the order can no longer be up to a minute behind the scores printed beside it. -->

<!-- 2026-08-08: TRACKING TENSE — a milestone that has not happened is no longer worded in the
past ("Пристигна" under a date a week away). `TrackPage.FUTURE` holds future-tense copy per
event code in BG/RO/EN and `label(lang, code, estimated)` prefers it; a milestone counts as
future when the carrier marks it estimated OR its date is still ahead of now (`ahead()`),
because JSONCargo sometimes flags a PLANNED arrival as actual. Applied to the timeline, the
ETA line, "last event" and the map popups (`VesselMap` now passes `e.estimated` to
`labelFor`). Verified on B/L 271191199 in BG and EN: "Отплава / Пристигна / Ще бъде доставен",
"Vessel departed / Vessel arrived / To be delivered". The +4d customs / +7d delivery tail from
`tracking._last_leg` is confirmed working.
LAST LEG, final rule (owner, 2026-08-08, THIRD and current revision): ONE step only — delivery =
official arrival + 7 days (`DELIVERY_LEAD_DAYS`). Our invented "Customs cleared" forecast was
REMOVED at the owner's request (`CUSTOMS_LEAD_DAYS` and `view["customs"]` are gone; a CU event the
CARRIER reports is still shown). EVERY bill of lading must carry the step, so the anchor falls
back in this order: real discharge `UV` -> actual arrival at the destination JSONCargo names
(`route.to`) -> the FORECAST arrival there -> the last forecast arrival of any kind. A booking
still at sea therefore has a delivery date too (272520178: ETA Rotterdam 10.09 -> delivery 17.09).
The delivery step carries the buyer's
billing COUNTRY CODE only (never the street); with no buyer attached it falls back to
`DEFAULT_DELIVERY_COUNTRY` (BG). `TrackPage.COUNTRIES` + `countryName()`/`place()` print it in the
page language, so BG reads "България" and EN "Bulgaria". Verified on B/L 271191199 (arrival 06.08
Bergen Op Zoom -> "Ще бъде доставен" 13.08, България) and 272520178 (forecast arrival Rotterdam
10.09 -> delivery 17.09). Tests updated to the new rule: test_iter24, test_iter25,
test_review_iter23, test_tracking_destination. -->

<!-- 2026-06 (later): Outside working hours a buyer can LEAVE A NUMBER AND A TIME and we
ring them back (admin list under Enquiries; the slot is re-checked server-side against the
owner's Sofia hours). The hand-picked shelf now ORDERS ITSELF by deposits x 10 + CTR, with a
minimum-impressions guard so a lucky click cannot win. A renamed model keeps its production
years (Cayenne). All admin timestamps are pinned to Europe/Sofia. See CHANGELOG.md. -->
<!-- 2026-06: SAVING NOW REQUIRES AN ACCOUNT — the heart and "save this search" open a
Вход/Регистрация dialog (components/SignInGate.js) for a signed-out visitor, and logging out
clears the local lists. A red "Обади се" button sits beside "Прати запитване" (half its old
width each); its number and opening hours live in the admin Enquiries tab and outside those
hours the visitor is warned before dialling. The reserve button reads "Капарирай" and puts the
terms in a dialog. See CHANGELOG.md. -->
<!-- 2026-06: a brand-new visitor now meets the OWNER'S hand-picked shelf ("Picked for you",
source "curated") instead of the crowd's most-opened ads; the list, its stock counts and its
impressions/opens/CTR/deposits live in the admin tab "Picked for you". A car link pasted into a
chat app previews with the ad's own first photo, because nginx routes social crawlers to
/api/share/car/{id}. See CHANGELOG.md. -->
<!-- 2026-06-04: "подходящи" (relevant) is now the DEFAULT SORT on every search — the old
auto-switch rules (make -> newest, model -> cheapest) were removed; a sort the visitor
picks themselves is respected for the session. Catalogue sync is checkpointed per slice
and resumes after any number of server restarts. Bill-of-lading customer assignment is
finished (the picker was breaking because it sat inside a <label>). The deposit -> archive
-> My Purchases pipeline is now verified end to end in a browser through real Stripe test
checkout (iteration_27.json, 0 defects). Admins can refund a deposit in one click from the
new Deposits tab, which also releases the car for other buyers (iteration_28.json). The
deposit is a PURCHASE, not a holding fee: non-refundable on withdrawal, returned less a
EUR 300 commission once the buyer wires the balance (iteration_29.json, 0 defects). Car
pages carry a body-damage diagram and a mechanical-checks card built from Encar's
inspection sheet. Price-drop alerts for saved cars and a deposit-returned email are built
but CANNOT DELIVER: SENDER_EMAIL is still Resend's shared sender and ADMIN_NOTIFY_EMAIL is
unset, which also silently drops enquiry notifications. See CHANGELOG.md.
2026-06: the owner's "Europe Encar" logo replaced the text wordmark everywhere
(`public/logo.png` + `logo-220.png`, header, footer, favicon.ico/png, PWA icons 180/192/512
on a #141414 plate). SECURITY: `ADMIN_TOKEN` no longer has the "encar-admin" default — it is
read from backend/.env with NO fallback, compared with `secrets.compare_digest`, and an unset
value refuses header-token admin access outright (verified: old token 401, new token 200, no
token 401). Owner's decision on price-drop alerts: notify on ANY drop, no user threshold.
2026-06 (same session): every email now opens with the logo (`mailer._logo_html` uses
`PUBLIC_SITE_URL` + `/logo-220.png`, falling back to a text wordmark if the env var is
unset). BUG FOUND AND FIXED: `acknowledge_enquiry` never sent anything — its `_send` call
had been orphaned to the bottom of the file below `send_deposit_returned`'s `return`, so
buyers got no acknowledgement at all.
Share previews: `GET /api/share/car/{id}?lang=` returns a tiny HTML page carrying og:/twitter
tags with the ad's LEAD PHOTO at 1200x630 (make/model resolved through the English cache) and
forwards a human to `/{lang}/car/{id}` — chat apps never run our JS, so the runtime og tags
on the car page are invisible to them. The owner explicitly does NOT want a Share button in
the UI, so nothing links to it; the endpoint exists for links pasted by hand.
Equipment panel: `Panel` now takes a `className`, and the options block carries
`lg:col-span-2` with its categories in a `sm:grid-cols-2 lg:grid-cols-3` grid — full page
width on desktop, height down from ~1100px to 583px.
2026-06 — BACK NAVIGATION / DROPDOWN BUG (Opera report), root causes were TWO, both fixed:
(1) `TaxonomySelects.load` had no stale-response guard. Arriving on a slug URL fires the
level 2/3/4 lookups TWICE — once with the English slugs (always empty) and again with the
Korean values resolved by `/api/meta/resolve` — and the empty answer often landed LAST,
wiping the model and submodel lists. Every load now carries an `alive()` token, and
`SearchPage` passes `EMPTY_TAX` to the selects while `resolving`, so the slug round never
fires. (2) "Подходящи" re-read the taste profile on every mount, and the profile had just
grown from the car the visitor opened, so Back silently RESHUFFLED the same 14 results.
`tasteFor(key)` snapshots the profile per query (module level, like `pendingRestore`) and
reuses it until the query changes. Verified: identical id order and intact dropdowns after
in-app back, browser back and a direct slug URL.
Note: "+" is stripped by `slugs.slugify` ("E53 AMG 4MATIC+" -> `e53-amg-4matic`). Only ONE
real collision exists in the whole tree (Spark LS+/LS) and resolution is scoped, so this was
NOT the cause — do not "fix" the slugs chasing this bug.
Desktop result rows: the photo arrows now appear on hover of the WHOLE card
(`group/card` on the row root + `group-hover/card:opacity-100` in `PhotoSwiper.ARROW`).
The "Region in Korea" filter section was REMOVED from `FilterSidebar` at the owner's
request — where in Korea a car sits means nothing to a European buyer. The `regions` field
still travels in the payload, URL and saved searches, so old links keep working, and the
region is still shown on the card and in quick view.
Follow-up: the Korean region was then removed from the UI ENTIRELY — the spec chip on the
desktop row, the chip on the mobile card and the row in QuickViewDialog (the car page never
had one). `showRegion` on `CarCard` is now a no-op kept only so callers need no change; the
backend still returns and filters on `region`.
Wording overrides: `translate.OVERRIDES` is the place for copy the owner has fixed by hand —
it beats the cache and is never sent to the LLM, so a cache rebuild cannot undo it. First
entry: "가솔린+전기" reads "Хибрид" / "Hibrid" / "Hybrid" instead of "Бензин + Електричество".
Applied in BOTH `translate_many` and `translate_cached_only`, so filters, rows and car pages
all agree. "디젤+전기" and "LPG+전기" followed as "Дизелов хибрид" / "Газов хибрид" (and the
RO/EN equivalents).
Keyboard photo flicking: `PhotoSwiper` listens for ArrowLeft/ArrowRight on `window` ONLY
while the pointer is on that deck (`hovering` state), so 16 rows on a page never fight each
other or the page's own scrolling; the key is swallowed so the page cannot scroll sideways,
and typing in an input/textarea/select is ignored. Verified on a result row (1/4 -> 3/4 ->
2/4, scrollY stays 0, nothing happens once the pointer leaves) and on the car page gallery
(1/18 -> 2/18 -> 1/18).
Body diagram: the schematic is no longer a rounded rectangle. `BodyDiagram.BODY` is our own
top-down sports-coupe outline (narrow nose, pinched waist, rear haunches WIDER than the
front) with wheels drawn under the body, a windscreen and rear-glass band and mirrors;
`SHAPES` entries are now `{d, cx, cy}` paths that follow the flanks instead of `{x,y,w,h}`
rects. It is a generic silhouette drawn by us — deliberately NOT a copy of any
manufacturer's design. viewBox 0 0 320 460, rendered at h-[320px]. REVERTED at the owner's
request — the plain rounded-block version is back, and the owner is drawing the silhouette
by hand; the agreed hand-off is ONE svg, front at the top, one `<path id="...">` per panel
using the existing slugs (hood, roof, trunk_lid, front_fender_left/right,
front_door_left/right, rear_door_left/right, quarter_panel_left/right), no fill/stroke on the
panels, a viewBox and no fixed width/height.
Admin buyer interests (`GET /admin/buyers`): makes, models and fuels were showing the raw
Korean, and the same make appeared TWICE when a profile had both "아우디" and "Audi". Keys are
now resolved through the English cache (`translate_cached_only`, never the LLM), counts are
merged under the English name and only then is the top 3 / top 2 taken. It also now carries
the buyer's PHONE (billing.phone, a tel: link in the table) and their LAST SEARCH:
`_remember_search` stores `users.last_search` on every page-1 search by a signed-in buyer,
and the admin endpoint renders it as one line ("E-Class W213 · €30 000–80 000 · 2019+ · up
to 90 000 km · Petrol"). NOTE: `users.billing` is only ever written at REGISTER time — there
is no `PUT /auth/billing` despite the comment in auth.py claiming otherwise.
DIAGNOSIS COMMENT staying Korean — root cause and fix: Encar's comment is boilerplate plus
whatever the dealer pasted after it (credit-union account for the warranty premium, insurer
hotline, ♣ markers), which made the WHOLE paragraph a unique string that could never be a
cache hit; the buyer got Korean and the frontend gave up after 2 retries (12s). Now
`_diag_comment_parts` splits it into sentences, drops the payment/contact noise and caches
per sentence, so the boilerplate is already translated on the FIRST view of a car (verified:
a second car sharing the boilerplate came back in Bulgarian immediately), and the car page
retries up to 4 times (4s/7s/11s/16s) for whatever tail is genuinely new.
DROPPED FEATURE (owner's decision, 2026-06): "3rd and 4th card photo must be interior" is
NOT being built. Encar's search feed returns only 4 photos per car and all of them are
exterior; interior shots exist only in the per-car detail (587 of ~215k cached), so it would
cost one upstream detail request per car. The owner chose to skip it entirely — do not
re-propose it.
Tracking forecast: the "Customs cleared" and "Delivery" estimates used to hang off the
BERTHING/arrival event, so a barge leg onward to Bergen op Zoom pushed customs to 12.08 when
the box had been on the quay in Rotterdam since 01.08. `_last_leg` now bases both on the
DISCHARGE event (code `UV`, falling back to arrival), and `CUSTOMS_LEAD_DAYS` is 4 by the
owner's rule — customs = discharge + 4 days, delivery = customs + 7. Verified: discharge
01.08 19:04 Rotterdam -> customs 05.08, delivery 12.08.
Mobile cards: swiping to the SECOND photo now warms the ad in the background —
`CarCard` passes `onIndexChange` to `PhotoSwiper` and calls `warmNow()` from slide 2 onward
(`warmCar` dedupes, so later slides cost nothing). Verified in isolation: scrolling the deck
with JS only, pointer nowhere near the card, produced exactly ONE `/api/car/{id}` request.
2026-06 — CURATION + polish batch:
* `curate.py` (new) holds the owner's taxonomy curation. `taxonomy_overrides` docs
  (`_id = "{level}|{value}"`) either RENAME a value or MERGE it into another; dropdowns are
  collapsed (counts summed onto the survivor) in `/meta/taxonomy` and `build_query` expands a
  filter on the survivor to every value folded into it, so the single entry really returns all
  the cars. `raw=1` on `/meta/taxonomy` skips the collapse — that is what the admin screen
  reads. Admin API: GET/POST `/admin/taxonomy/overrides`, DELETE `.../{id}`. UI:
  `AdminTaxonomy.js`, tab "Models & trims". Nothing touches `listings`, so every change is
  undoable and a re-crawl cannot overwrite it. Applied for the owner: M2 Coupe M Performance
  Steering Wheel Edition + M2 Black Shadow -> M2 Coupe (16 cars), M2 Competition Final
  Edition -> M2 Competition (16 cars); Chevrolet (GM Daewoo) -> Chevrolet (one entry, 6 897
  cars, 70 models from both, slug `chevrolet`). Merging at LEVEL 1 also needed the scope of
  `/meta/taxonomy` itself to expand (`q["make"] = {"$in": curate.expand(1, [make])}`, same for
  model/badge) plus a de-dupe pass, so the survivor lists the children of everything folded
  into it; `build_query` expands `makes` too. Verified end to end.
* Model names: `curate.model_label` strips "The New / All New / New" and "5th Generation" and
  appends the production span read from our own catalogue (`curate.ensure_years`, one grouped
  pass over `form_year`, cached a week in `model_years`). Open span while still on sale:
  "더 뉴 스포티지 5세대" -> "Sportage (2024-)", "올 뉴 쏘렌토" -> "Sorento (2015-2017)". Applied in
  the model dropdown, `listing_out.model_t` and the car page title.
* Trims are Latin everywhere now: `translate.LATIN_FIELDS` gained `badge` and `badge_detail`,
  and `/meta/taxonomy` uses `label_lang = "en"` at every level, so "M2 Купе" is gone — the
  dropdown, the cards and the car page all read "M2 Coupe", "E220d 4MATIC AMG Line". A card
  still shows the car's OWN trim (e.g. "M2 Black Shadow"); only the filter option is merged.
* Filter pill bug: the inputs hand over STRINGS, so `Number.isFinite("60000")` was false and
  the mileage pill read "Пробег: –— км". `AppliedFiltersChips` now coerces every bound and
  words one-sided ranges as "≤ 60 000 км" / "≥ …" (same fix for price and year).
* Mobile: `index.css` forces 16px form text on touch devices, so iOS no longer zooms in when
  a field is focused (pinch-zoom still works).
* Login: "Нямате профил?" is now 16px with a real Регистрация button (`auth-switch-mode`).
* MISTAKE TO LEARN FROM: two of my own edits took the site down (a `search_replace` that
  joined two lines in server.py -> SyntaxError -> 502, and a new component importing api
  helpers that had not landed). ALWAYS `python3 -c "import ast; ast.parse(...)"` the backend
  and check `/var/log/supervisor/frontend.out.log` for "compiled" before moving on.
* Prefetch 410: `useCarWarm` fire-and-forgot `warmCar` with no `.catch`, so hovering or
  swiping a card whose ad the dealer had just pulled surfaced "Request failed with status
  code 410" to the visitor. Prefetch errors are swallowed now; the car PAGE still shows the
  friendly sold screen with similar cars (verified on 42439184: no page errors).

## Hetzner NAT: /32 private network, so back1's egress goes through a WireGuard tunnel
`deploy/hetzner/ansible/playbooks/deploy_nat.yml` no longer points back1's default route at
front1 — on Hetzner's /32 private network that is an invalid next hop ("Nexthop has invalid
gateway"; with `onlink` the neighbour resolves FAILED). WireGuard point-to-point over the
private network instead (front1 10.99.0.1 / back1 10.99.0.2), and only the backend user's
outbound traffic is policy-routed into it (fwmark 0x1 -> table 100). Hetzner's own
`default via 10.0.0.1` stays in the main table, so SSH/apt/private traffic is untouched.
Details and the full list of what was measured: CHANGELOG.md, 2026-06. Cannot be tested from
this pod — the owner runs the playbook.

## Landing view: floor, real counter, price diversity (2026-06)
* `sort=price_asc` LIFTS the EUR 18 000 floor — a bargain hunter is never fenced in.
* `/search` returns `total_all` (whole catalogue, cached) for the counter; `total` stays the
  floored count so paging never offers empty pages.
* Price diversity: `_band()` + `_spread(per_band=)` cap one price bracket at 6 of 24 on the shop
  window, because `relevant` (popular list AND taste proximity) collapsed onto ~EUR 23 000.
* `DetailStickyBar` no longer hides under the menu when the admin traffic bar is up. Tailwind
  arbitrary `calc()` needs UNDERSCORES around `+`. Details: CHANGELOG.md.

## Landing view floor + footer + per-language static meta (2026-06)
* The home (unfiltered) view and the taste shelf never show a car under **EUR 18 000**
  (`server.HOME_MIN_EUR`, env `HOME_MIN_EUR`). It is silent — never a filter chip — and it
  disappears as soon as the visitor searches or filters.
* The footer no longer prints the company name, EIK, address or phone (owner's request); the
  legal pages still carry the full identification.
* `/bg` and `/ro` now serve translated `<title>`/`description`/`<html lang>` in the RAW HTML via
  `scripts/gen-lang-html.js` (postbuild) + `try_files $uri $uri/index.html /index.html`.
  Details: CHANGELOG.md.

## Cars under contract on Encar (2026-06)
Encar marks a pending sale as `SalesStatus` / `advertisement.salesStatus == "CONTRACT"`. Such a
car is effectively sold: it must never appear in search and never be depositable. Enforced in
four places — the crawl (retired the moment a row is skipped for contract), the car page (live
detail check -> 410 sold screen), a background re-check every 6h for cars whose detail is already
cached, and a LIVE check inside `deposit_checkout` (409 `car_contracted`). Details: CHANGELOG.md.

## Self-hosting on Hetzner — checklist (asked 2026-06)
Static scan passed: no hardcoded secrets or URLs in code, env usage correct, `yarn build`
succeeds (294 kB gzip), backend imports clean. What the owner must still do on their own box:
1. Code out via "Save to GitHub"; `.env` files are NOT included — recreate every key.
2. `REACT_APP_BACKEND_URL` is baked in at BUILD time by CRA — rebuild for the new domain.
3. `PUBLIC_SITE_URL` in backend/.env still points at the preview URL; it is what email logos
   and share links use, so it MUST change.
4. Own MongoDB (`MONGO_URL`, `DB_NAME`). A fresh DB is EMPTY — either run the catalogue sync
   and taxonomy build, or `mongodump/restore`. Worth carrying over: `translations` (already
   paid for), `taxonomy_overrides` (the owner's merges), `users`, `purchases`, `shipments`.
5. `MEDIA_ROOT` needs a PERSISTENT volume: archived photos of purchased cars live there and
   are served from `/api/media`.
6. nginx: `/api` -> uvicorn:8001, everything else -> the static `build/`. HTTPS is required —
   sessions and passkeys are Secure-cookie only. Passkey RP id is derived from the request
   origin (auth.py `_rp`), so nothing to configure there.
7. ONE backend process: `syncjob` and `pricewatch` schedule in-process, so multiple uvicorn
   workers would double-run the crawl and the price emails.
8. Translations already use the owner's own `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` directly; the
   Emergent universal key is only a FALLBACK and stops working off-platform, which is fine.
9. Deploy package lives in `/app/deploy`: `ansible/deploy.yml` (installs docker, ufw, checks
   out the repo, templates `.env` from `group_vars`, builds and starts the stack, waits on
   `/api/health`, installs a nightly mongodump kept a fortnight), `Dockerfile.backend`
   (one uvicorn worker on purpose), `Dockerfile.frontend` (CRA build served by nginx with
   `REACT_APP_BACKEND_URL=""` so the app talks to /api on its own origin), `nginx.conf`,
   `docker-compose.yml`, `Caddyfile` (automatic TLS), `.env.example` and `README.md`.
   `export_data.py` / `import_data.py` move the collections worth keeping as gzipped JSON —
   round-trip verified here on 29 816 docs (1.5 MB).

## Admin deletions (2026-06)
`DELETE /admin/enquiries/{id}` refuses while the status is still `new` (that is an unanswered
lead) and works once it is contacted or closed. `DELETE /admin/users/{email}` erases the
account, its sessions, passkeys, 2FA secret and challenges, but REFUSES while the customer has
an unrefunded deposit — money that moved has to stay traceable, so refund it first. Purchase
rows are deliberately kept. UI: trash button per row in `AdminBuyers`, "Delete" on contacted
or closed cards in `AdminEnquiries`, both behind a confirm. Verified end to end. -->



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
Guarded by `_require_admin` — admin session OR `x-admin-token` header (`ADMIN_TOKEN` from
backend/.env, NO default: unset means the header path is refused). Three tabs: **Overview** (index size, crawl progress, translation
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

### EDI ingest (the owner's actual Maersk setup)
The zip the owner supplied is NOT the REST API: it is the Maersk implementation guide pair
for **X12 315** and **EDIFACT IFTSTA D99B** (v1.3), i.e. Maersk PUSHES container status
messages to the customer over AS2/SFTP/VAN. So tracking is a feed, not a poll — no keys, no
quota, no polling.
- `backend/edi.py` parses both formats into the same canonical event shape used by the REST
  path. Element positions vary between senders and profiles, so fields are recognised BY
  SHAPE, not by counting: in X12 `B4` the 1-2 letter status code, the 8-digit date with an
  optional time after it, the 4-letter equipment initial + container number, and the place
  name between them; in `TDT` the longest alphabetic component is the vessel name (shorter
  ones are carrier codes like MAEU) and any 7-digit component is the IMO. Estimated vs
  actual comes from the DTM qualifier (X12 139/140, IFTSTA 132 vs 133/334). IFTSTA status
  codes are mapped onto the X12 vocabulary so the UI has ONE label map.
  Timestamps are stored exactly as sent (carriers quote local time without an offset;
  inventing UTC would shift events by hours).
- `POST /api/tracking/edi` takes the raw message, authenticated by `EDI_INGEST_TOKEN`
  (in backend/.env) or an admin session. Idempotent: upsert on (ref, code, when) with a
  unique index, so a redelivered message cannot duplicate a timeline. Events live in
  `shipment_events`, indexed on container and bol.
- `tracking.track()` prefers the EDI feed (`source: "edi"`) and falls back to the REST
  client only for references the feed has not covered.
- Verified: X12 315 and IFTSTA samples both parse (container, B/L, codes, est/act, ports,
  vessel, voyage), ingest returns `{stored: 5}`, lookup works by container AND by B/L,
  redelivery keeps 5 milestones, a wrong token is rejected, garbage is rejected with a clear
  message, and the BG page renders the full timeline. Test events were then deleted.
- STILL NEEDED: how the messages reach us (their EDI provider/VAN forwarding to the webhook,
  or an SFTP drop we would need to poll), plus the MarineTraffic/Kpler key for live vessel
  positions (the vessel card says so honestly until then).

### Vessel map + car link (2026-06)
- `backend/ports.py`: UN/LOCODE -> coordinates for the ~50 ports these shipments actually
  call at (Korea, Asian transhipment, Suez, Med/Adriatic, Black Sea, North Europe). A
  geocoder would be another dependency and another key for data that never changes; unknown
  ports simply get no marker and the timeline still names them. `edi.py` now captures the
  UN/LOCODE (X12 `R4` when qualifier is UN, IFTSTA `LOC` first component), the REST path
  reads `UNLocationCode`, and `tracking._view` attaches lat/lon to each milestone.
- `frontend/src/components/VesselMap.js` (react-leaflet 5 + leaflet 1.9, OpenStreetMap
  tiles, no key): solid red polyline for the legs already sailed, dashed grey for what is
  ahead, filled markers for ports passed and hollow for ports still to come, consecutive
  events in one port collapsed into a single stop, and a blue ship marker at the AIS
  position when a key is configured. Circle markers, NOT Leaflet's default pin — the
  default icon loads from an asset path webpack rewrites, which is the classic
  "markers vanish in production" bug.
- Car link: `tracked_shipments[i].car_id` (POST body accepts `car_id`). The Track page shows
  a "Your car" panel with photo, title, year, mileage, EUR price, a link to the ad and an
  unlink action; when nothing is linked it offers a picker built from the buyer's saved cars
  plus any car already attached to a shipment.
- Verified signed in: car panel rendered the linked Hyundai Santa Fe with its EUR price, the
  map drew 12 tiles and 5 vectors (Busan -> Singapore solid, dashed on to Piraeus), zero
  console errors. Test events, saved shipments and the test favourite were then removed.
- NOTE: `getListingsByIds` returns `{items}`, not an array — that mistake cost one render
  crash ("cars.find is not a function").

### Admin shipment assignment + Maersk PUBLIC track (2026-06, this session)
The owner said API access is not coming, so tracking now has a third source: Maersk's own
public track page, read with a real browser, plus an operator screen to attach a reference
to a customer.
- `backend/maersk_public.py`: Chromium (Playwright) loads
  `https://www.maersk.com/tracking/<ref>`. MEASURED FIRST, do not redo this work:
  a plain httpx/curl call to the page OR to the data endpoint returns **403 Access Denied**
  from Akamai, while a real browser session loads it with status 200. The page itself calls
  `https://api.maersk.com/synergy/tracking/<ref>?operator=MAEU` — no key, no quota — so the
  response is captured on the way past; if the edge resets that call mid-flight it is
  repeated from inside the page, where the session cookies already are. The JSON shape is
  undocumented and third-party descriptions disagree, so milestones are recognised BY SHAPE
  (a dict carrying a date and a description ≤ 90 chars), exactly like `edi.py` does with
  segments, and the English prose is mapped onto the SAME event-code vocabulary the EDI feed
  uses so the UI keeps one label map. `text` is kept alongside `code` and the timeline falls
  back to it when a phrase maps to nothing.
- Cost control: one page at a time (`asyncio.Lock`), a cap of `MAERSK_PUBLIC_MAX_PER_MIN`
  (10) reads a minute, and a 30 min cache per reference in `tracking_cache` (`pub:<ref>`,
  raw payload kept next to the normalised events). A BUYER NEVER WAITS FOR A READ: a cache
  miss schedules the read as a background task and answers in ~0.2s with `checking: true`;
  `TrackPage` then re-polls at most 3 times, 12s apart. Only the operator's refresh runs
  inline. New copy `trackChecking` in BG/RO/EN.
- Source order in `tracking.track()`: EDI feed → public page → admin assignment → private
  REST (only if a consumer key ever appears). "The carrier has nothing public for this
  reference" is now reported as `found: false`, NOT as `configured: false` — a real answer
  is not a missing integration.
- Admin → **Shipments** tab (`components/admin/AdminShipments.js`): assign a reference to a
  customer email with optional car id, vessel name/IMO/MMSI, ETA and a note; list of
  assignments with "Read carrier" (forces a fresh browser read and prints the last 8
  milestones) and remove. The shipment endpoints moved from session-only auth to
  `_require_admin`, so `x-admin-token` works for scripts like the rest of the admin surface.
- MarineTraffic moved to the OFFICIAL AIS API per the spec the owner supplied:
  `GET {base}/exportvessel/{key}?v=5&imo=…|mmsi=…&timespan=1440&msgtype=extended&protocol=jsono`,
  redirects followed, `SPEED` divided by 10, rows read defensively (array or `DATA`), cached
  30 min. Env: `MARINETRAFFIC_API_KEY`, `MARINETRAFFIC_BASE_URL`,
  `MARINETRAFFIC_EXPORTVESSEL_VERSION`.
  **Scraping MarineTraffic was tried and rejected**: even in a real browser their Cloudflare
  hard-blocks this datacenter IP ("Sorry, you have been blocked"), and vesselfinder.com
  times out. Live vessel positions therefore need the paid key; until it is set the vessel
  card says so honestly.
- Verified (testing agent iteration_21, 13/13 checks + 6/6 pytest in
  `backend/tests/test_shipments_tracking.py`): assign / duplicate / unknown-email 404 /
  delete, the ~0.2s `checking` answer followed by an honest not-found, the seeded payload
  rendering 6 milestones with a Busan→Singapore solid leg and a dashed leg to Piraeus, and
  BG/RO copy. Test assignments and cached test refs were deleted afterwards;
  `backend/seed_track_test.py` re-seeds a synthetic payload for UI work (`--clear` removes).
### Reading Maersk's public track from this server is NOT POSSIBLE — measured, do not retry
`MAERSK_PUBLIC_TRACK` is therefore **0 (off)** in `backend/.env`. The reader stays in the
tree because it works instantly if the app is ever hosted behind an egress IP Akamai
accepts, but it must not be switched on here: every attempt costs ~30s and a Chromium and
always ends in "no results".
What was tried, in order, and what happened:
1. `curl`/httpx to `api.maersk.com/synergy/tracking/<ref>?operator=MAEU` → **403 Access
   Denied** (Akamai edge), with and without browser-like headers.
2. Headless Chromium loading `maersk.com/tracking/<ref>` → the PAGE loads 200, but its own
   data call dies with `ERR_HTTP2_PROTOCOL_ERROR` and the app prints "No results found".
3. The tracking bundle (`/tracking/assets/track-*.js`) shows why: the ocean call is sent
   with `Consumer-Key`, an `Authorization` constant AND
   `Akamai-BM-Telemetry: window.bmak.get_telemetry()`. Without valid telemetry the edge
   refuses it. Forging that header is not something we will build.
4. A GENUINE, HEADED Chrome build (full `chromium-1234`, real X display via Xvfb, real
   locale/timezone/viewport) → the page renders fully and STILL gets a plain **403 Access
   Denied** on the data call. So this is the datacenter IP being refused, not
   headless detection and not a bad reference.
Conclusion: `271191199` showing "No results found" is our request being blocked, NOT proof
that the reference is wrong. Live carrier milestones need one of: the EDI 315/IFTSTA feed
Maersk pushes (already built and idempotent — ask the Maersk rep or their EDI provider to
forward to `POST /api/tracking/edi`), or a paid aggregator with a real carrier contract
(Vizion, Terminal49, ShipsGo, Safecube…), or Maersk's own Track & Trace Plus key. Until one
exists, the admin assignment IS the data and the page shows it honestly.

### Customer shipments on the account page (2026-06)
- `frontend/src/components/AccountShipments.js`, rendered by `AccountPage`: every reference
  attached to the account with its status, ETA, vessel, the linked car (title links to the
  ad) and a Track button. Empty state explains that a number appears once the car sails.
  New copy `accountShipments`, `accountNoShipments` (BG/RO/EN).
- `TrackPage` now accepts a deep link `/{lang}/track?ref=…&by=container|bol` and looks it up
  on mount, which is what the account button uses.
- The Journey card is hidden when a shipment has no milestones yet (an assignment-only
  shipment used to render an empty card), the operator's note is shown to the buyer
  (`data-testid="track-note"`), and a date-only ETA no longer pretends to be 00:00.
- STILL NEEDED FROM THE OWNER: a live milestone source (see above) and the MarineTraffic API
  key for the vessel position.
- NOTE: `271191199` is currently assigned to the TEST admin account
  (admin@encarskin.com) as a demo row — delete it in Admin → Shipments when it is no longer
  wanted.

## Fixed 2026-06 (relevance, photos, tracking tail, sold ads)
- **Duplicate photos (an 18-photo ad showed 24).** Encar's detail payload repeats some
  pictures as a second row with `type: "THUMBNAIL"` and the SAME `path`. `car_detail` now
  sorts by `(code, type == "THUMBNAIL")` and drops a `path` it has already emitted, so the
  THUMBNAIL copy loses and the deck matches the real ad. Listing rows were already clean —
  the bug was only on the detail page. Verified: `/api/car/42259236` returns exactly 18.
- **"Relevant" no longer floods the page with one badge.** Owner was getting a page of
  nothing but Mercedes. `_spread` now caps per MODEL (2) and per MAKE (a quarter of a page),
  and `_interleave` was replaced by `_space(gap=2)` which keeps the ranking but never lets a
  brand sit within two places of itself. A strict round-robin across makes was tried first
  and rejected — it handed out exactly ONE car per brand and buried the preference.
  Measured with a Mercedes-heavy profile: 6 of 24, none adjacent. Empty profile still falls
  back to `popular_ids()` (most opened ads of the last 14 days).
- **Estimated last leg.** `tracking._last_leg` hangs both dates off the DESTINATION-PORT
  arrival (codes AV/VA/ARRI) rather than whatever event is last, so an inland move after
  berthing cannot push customs back: "Customs cleared" = arrival + 3 days, "Delivery" =
  customs + 7 days. The delivery step carries the buyer's billing COUNTRY only — never the
  street or city, because a shared tracking link would print it. Both render with the dashed
  marker and a localised "est." badge.
- **The container number is gone from the Track page.** It is our lookup key (and the
  JSONCargo cache key), not something the buyer needs; only the bill of lading is shown.
- **JSONCargo is capped at one call per container per day** (`CARGO_TTL_CONTAINER=86400`,
  errors cached too). Verified: two back-to-back lookups left the quota `used` unchanged.
- **Desktop header balance.** Language, theme and the account actions are now one right-hand
  group (the language block carries `ml-auto`, the auth block no longer does); before, the
  right side held only sign-in/register and the bar read lopsided.
- **Car page gallery**: main image `lg:w-[calc(100%-286px)]`, thumbnail column 276px,
  mobile thumbs 112x76 — a smaller hero and bigger thumbnails, per the owner.
- **A retired ad is no longer a dead end.** When Encar answers nothing for a listing we still
  hold (e.g. 42389436, a sold Rolls-Royce Ghost), `car_detail` retires it from the index
  (`active: false, sold: true, sold_at`) and returns **410 Gone** with the make, model and up
  to 12 live cars of the same make+model (falling back to the make alone when fewer than 4
  are left). `CarDetailPage` renders "Uh oh, this car has been sold" plus that grid
  (`data-testid="detail-sold"`), in BG/RO/EN.
- NOTE: `CarDetailPage.js` was corrupted once by editing it while the testing agent held it —
  the tail was duplicated from line 771. Do not edit files while a testing agent runs.

## Next: account page, phase 2 (owner approved, not started)
Modelled on the owner's Auto&Bid account page, minus everything auction-specific (bids,
reserve price, listing approval). Agreed scope:
- Web Push (VAPID, keys generated by us) + iOS "Add to Home Screen" instructions + a
  "send test" button; email notification toggles per event.
- Events that apply here: a new car matches a saved search, the landed price of a saved car
  drops, an enquiry is answered, a shipment status changes.
- Contact phone (alongside billing), TOTP 2FA with recovery codes, active-session list with
  "sign out everywhere", GDPR account deletion behind typing ИЗТРИЙ.
- Saved card via Stripe for a **deposit / reservation** on a car (test key already in the
  pod env — never ask the owner for one).
- Email delivery is still limited to the Resend account owner: no verified domain yet.

## Back to the results page: no reload, no flash (2026-06, VERIFIED iteration_33)
Two owner reports, one mechanism. A Back from a car remounts `SearchPage`, and because the URL
carries ENGLISH SLUGS (`?make=audi`) the page could not search at all until `/meta/resolve`
translated them back — so it painted a grid of skeletons (~250-400ms) and the make/model
dropdowns showed the "Всички марки" placeholder for a frame.
- `SearchPage` now keeps a module-level `visits` Map (max 6, LRU) of the state it last painted
  for a URL: `{filters, tax, slugs, taxLabels, result}`. The key is
  `pathname + search` — the language lives in the PATH, so keying on the query alone would
  hydrate a Back after a language switch with the previous language's labels.
- `restored = visits.get(visitKey())` is read ONCE on mount and seeds every one of those
  `useState` calls, starts `loading` at **false** and makes `resolving` false, so the FIRST
  painted frame already has the right cars, the upstream Korean values and the Latin labels.
  The debounced search that follows hits `api.cachedSearch` and refreshes quietly.
- The snapshot is written by an effect declared AFTER the URL-mirror effect, so
  `window.location.search` is already the URL those results answer.
- In memory on purpose (owner agreed): a Back is a client-side navigation so the module
  survives it, while a real reload should ask the server again. No sessionStorage.
- Verified frame-accurately at 1920x1080 and 390x844: at +16/30/100/250/500ms after Back,
  0 skeletons, 16 cards with IDENTICAL ids and order, make trigger "Audi (3244)", chip
  "Марка: Audi", 0 Hangul characters. Direct load of a slug URL still resolves normally.
- Known LOW finding, not fixed: the car page's own "Назад към резултатите" button waits
  ~200ms before it pushes history, so the car page stays on screen a moment longer than a
  browser Back. Results page itself hydrates instantly once it fires.

## "Назад към резултатите" as fast as the browser's own Back (2026-06, VERIFIED iteration_34)
MEASURED FIRST, before changing anything: the button was NOT waiting to fire — the URL changed
~40ms after the click. Both paths then spent the rest of the time in ONE React render of the
results page (click -> list in the DOM: 383ms for the button, 307ms for the browser Back). Two
changes closed the gap:
1. `CarDetailPage.goBack` now does a REAL history POP (`navigate(-1)`) whenever the page was
   opened from inside the app (`location.key !== "default"`), instead of pushing a second copy
   of the list onto the stack. Pushing `{pathname, search: from}` is kept only for a cold-opened
   shared link. The scroll offset can no longer travel in navigation state (the entry we pop to
   was written before the visitor scrolled), so it goes through `lib/backScroll.js` — a one-shot
   module handoff, read by `SearchPage` via `takeBackScroll()` when
   `location.state.restoreScroll` is absent. Verified: `history.length` no longer grows.
2. `CarGrid` renders ONLY the layout the viewport shows. It used to build the 16 mobile cards
   AND the 16 desktop rows on every search and let CSS (`lg:hidden` / `hidden lg:flex`) throw one
   away — double the mount cost of the very render a Back is waiting on. `useDesktopLayout()`
   reads `matchMedia("(min-width: 1024px)")` synchronously for the first render and listens for
   `change`, so a resize across the breakpoint still swaps the layout live.
Result: button 383 -> **271ms**, browser Back 307 -> **227ms** (~30% faster for BOTH, and the
button is now within ~50ms of the browser's own). Verified by the testing agent: 16 `car-card`
and 0 `car-row` at 390x844, 16 `car-row` and 0 `car-card` at 1920x1080, live resize swaps, cold
open still lands on the search page, no console errors, no skeletons and no Hangul on Back.
NOTE for future tests: on DESKTOP the listing element is `[data-testid="car-row"]`;
`[data-testid="car-card"]` is the MOBILE layout and no longer exists in the desktop DOM at all.


## Pagination prefetch (2026-06, VERIFIED)
`ResultsPagination` takes `onPrefetch` (wired to `SearchPage.prefetchPage` -> `api.prefetchSearch`,
an in-memory promise map of max 8 that `searchCars` consumes for a matching body):
hover/keyboard focus on prev, any page button or next warms exactly that page; on a phone an
IntersectionObserver on the nav root (`rootMargin: 200px`) warms page+1 the first time the row
scrolls into view. A `warmed` ref set holds the page numbers already warmed, because the effect
is re-created whenever the parent's callback identity changes and a scroll up-and-down again was
re-firing it. Verified: one POST /api/search on hover/scroll-into-view, ZERO extra POSTs on the
click that follows.


## ePrivacy prior consent + GDPR policies (2026-06, VERIFIED iteration_35, 0 defects)
Owner's requirement: nothing beyond the strictly necessary may touch the visitor's device before
explicit consent, plus a thorough GDPR privacy policy.
BIGGEST FINDING: the platform's inline **PostHog snippet with session recording** sat in
`frontend/public/index.html` and fired on EVERY page load, before the banner existed. It was
REMOVED (a comment in its place explains why). Do not paste it back — any tracker must be loaded
from `lib/analytics.js` after consent. Also closed: `ab_track` (recent tracking references) and the
listing view counter were firing without consent.
* `lib/consent.js` is the SINGLE gate. `POLICY_VERSION = "2026-06-08"`, categories
  `personalisation` (ab_taste, ab_vid, ab_track) and `statistics` (view counter, future GA4).
  No marketing category — no ad networks, no pixels. The decision is stored as a RECORD
  (`{v, ts, cats}`) in `ab_consent` for 365 days, not a flag, so we can show what was agreed and
  when; `allows()` answers false for everything until a decision exists against the CURRENT
  version, so bumping the version re-asks. Refusing/withdrawing DELETES the cookies of that
  category. `ab_consent` itself is strictly necessary: it stores a refusal too.
* `CookieBar` — three equally sized buttons (Reject all / Settings / Accept all), optional toggles
  default OFF, links to both policies, `openCookieSettings()` custom event so
  `SiteFooter` ("Cookie settings", on every page) can reopen it to change or withdraw.
* Gates: `taste.record()` -> `allows("personalisation")`; `TrackPage` ab_track writes;
  `CarDetailPage` `countView` -> `allows("statistics")`.
* `lib/analytics.js` is the GA4 loader the owner asked to prepare: nothing loads unless
  `REACT_APP_GA_ID` is set AND statistics consent is given, Google Consent Mode defaults are
  DENIED, `allow_google_signals: false`. Wired to consent changes in `LangLayout` in BOTH
  directions, so a withdrawal flips the signal back to denied.
* Backend: `TasteIn.consent_record` is stored on the user with a server-side `recorded_at` (a
  client cannot backdate it) and returned by `_public`, so a signed-in buyer is asked once, not
  once per device (`AuthContext` adopts it).
* Company facts from the owner, now in `content/company.js`: address "гр. София, район Витоша,
  ул. „Бяла река“ 12, бл. 10, ап. 3", phone +359 88 671 7074, NOT VAT registered, GDPR contact
  contact@encareurope.com, hosting Hetzner Germany. NOTE: no post code was supplied — do not
  invent one.
* `content/legal.js`: privacy and cookie policies rewritten in BG/RO/EN (`UPDATED 2026-06-08`) —
  controller, data map, purpose-by-purpose legal bases (Art. 6(1)(a)-(f)), every processor named
  (Hetzner, Resend, Stripe, Anthropic, Google, carrier/tracking, forwarders, advisers), third
  country transfers with adequacy/SCC Art. 46(2)(c), retention per record type, rights Art. 15-22
  + withdrawal, complaint to КЗЛД and ANSPDCP, "no Art. 22 automated decisions", children,
  security, breach notification, and a cookie-by-cookie table. Editable in Admin -> Pages.
* Verified independently: fresh visit carries ONLY Cloudflare cookies, zero tracker requests while
  browsing cars/searching/tracking with no decision, toggles default unchecked, Reject keeps it
  clean and the site fully working, Accept writes ab_taste/ab_vid, withdrawal deletes them, banner
  does not return after a decision, `/api/auth/me` carries the record, policy pages render in all
  three languages with the real company facts, and the service worker/push still only register on
  an explicit gesture.


## Permanent per-set label cache for the taxonomy dropdowns (2026-06, self-verified)
Owner: "Wait on model and submodel translation from the llm. Cache all models of a brand
permanently once translated once to English. Permanently cache all brand translations. And the
trim models too."
Before: `_labels()` looked labels up value by value, gave the provider a 2.5s budget and then
served the raw Korean while a background job filled in — so a cold set showed Hangul to everyone
until the job landed, and every request re-checked.
* `translate.cached_label_set(db, set_id, values, lang, wait=90)` — the whole dropdown is ONE
  document in the new `label_sets` collection (`{labels, complete, n, lang, at}`), read back in a
  single indexed lookup. A brand's model list is a closed set, so once complete there is no
  provider call and no per-value query, ever. Only a genuinely new value (Encar added a model)
  costs anything, and only that value.
* It WAITS for the provider instead of serving Korean: the wait is paid once per set for the life
  of the site, whereas the Hangul would be seen by everyone until the background fill landed.
* All FOUR levels go through it — makes (1), models (2), trims (3), sub-trims (4) — keyed
  `tax:en:{level}:{make}|{model}|{badge}`, plus `tax:en:1:|||filters` for the make list in
  `/api/meta/filters`.
* `_looks_translated()` guards the permanent write: `translate_many` falls back to the SOURCE
  string when a provider fails, and freezing that into a permanent cache would nail Korean into
  the site forever. Anything containing Hangul is rejected as an answer.
  IMPORTANT SUBTLETY (cost a bug): a value already in Latin script ("BMW", "GMC") IS its own
  label, so identity is correct there. Rejecting it left every set containing a western marque
  permanently `complete: false` and re-asked the provider on every single request. Those values
  are now filled from the shared cache first (so curation overrides still win), then identity.
* `db.translations` has no TTL and never did — it was already permanent; the missing piece was
  the per-set completeness marker.
Verified by curl and in the browser: all 4 levels return 0 Hangul; a deliberately wiped cold set
(Lotus models) waited 2.39s, came back fully in English and was stored `complete: true`; the same
call then took 0.25s; all 5 sets read `complete: true`; the UI cascade Make -> Model -> Trim shows
Latin labels only.


## Owner's own privacy policy + weekly saved-search digest (2026-06, self-verified)

### Privacy policy replaced with the owner's document
The owner uploaded their settled policy (`politika-poveritelnost-encar.1`, a .docx — unzip and
strip `word/document.xml` to read it) and asked for it to be used. BG is now their text as
supplied; RO and EN are faithful translations of the SAME 14-section document.
* `doc()` in `content/legal.js` takes an optional 4th argument, and the privacy documents carry
  `PRIVACY_STAMP` ("Версия 1.1 · Актуализирана на 6 август 2026 г.") instead of the shared
  `UPDATED`, so editing another page cannot silently restamp the policy.
* New sections vs my draft: 3. where the data comes from, 4. whether providing it is obligatory,
  Art. 28 processor-contract wording, Art. 21(2)-(3) marketing objection, and the accounting
  retention counted from 1 January of the following year.
* Sections are numbered 1-14 in the headings, which is how the owner's lawyer refers to them —
  keep the numbers if sections are ever added.

### Weekly saved-search digest with photos (`digest.py`)
Owner's choices, verbatim: ONE email a week, all saved searches in it, up to 12 cars per search
with 1 photo each, **Saturday 15:00 Sofia**, and NOTHING sent when there is no news.
* `digest.run(db)` walks users with saved searches + `notify.wants(user, "email",
  "saved_search")`, queries `first_seen > digest_at` per search, and sends ONE
  `mailer.send_search_digest` per buyer. The window advances only for searches that were
  actually checked, so a car arriving mid-send lands in the NEXT digest instead of vanishing.
* The window is `search_watch.digest_at`, DELIBERATELY separate from `at`: `at` moves on every
  catalogue sync for the instant push, so sharing it would leave the digest seeing only hours.
  A brand-new search looks back `FIRST_WINDOW` = 7 days, never the whole catalogue.
* `searchwatch.py` is now push-ONLY (its docstring says so). The instant email is gone — a daily
  sync meant an email a day about two cars. It returns `"emails": 0` and gates on the push
  preference; `mailer.send_new_matches` is left in place, unused by the app.
* `mailer.send_search_digest` / `_digest_car`: two-cell tables and inline dimensions only (the
  one layout Outlook and Gmail both honour), photo from `encar.image_url(photos[0], 300, 200)` —
  an absolute CDN URL, because a mail client has no site to resolve against.
* `digest.scheduler(db)` is started in `server.on_startup` and guards itself with
  `settings/search_digest.last_run_date`, the same shape as `syncjob.scheduler`.
  `POST /api/admin/digest/run` (admin-only) sends it now and reports `next_run_at`.
* GOTCHA that cost a test: the stored preferences key is `user["notify"]`, NOT `notify_prefs`
  (see `notify.prefs_of`). Writing `notify_prefs` silently falls back to the defaults, where
  email is enabled — so an "email off" case appears to work when it is not being read at all.
* Verified: real run produced 1 email, 2 search groups, 24 car photos, 21.7 KB, prices/mileage,
  correct BG copy; every photo URL returns 200 and 0 images broken when rendered in a browser;
  an immediate second run sent nothing; `next_run_at` = 2026-08-08T12:00Z = Saturday 15:00 EEST.
  Tests: `tests/test_search_digest.py` (6) + reworked `tests/test_search_watch.py` (5) all pass,
  plus notifications/saved-search/GDPR suites (32 tests) green.
  NOTE for future test authors: a digest run sweeps EVERY account, so a fixture must filter
  captured mail to its own buyer or a parallel suite's letter shows up in the assertions.


## Owner's cookie policy v1.1 (2026-06, self-verified)
The owner uploaded their settled cookie policy (`politika-biskvitki-v1.1`, a .docx — unzip and
strip `word/document.xml` to read it) and asked for it to be used. BG is their text; RO and EN
are faithful translations of the same 13-section document. All three carry `PRIVACY_STAMP`
(version 1.1, 6 August 2026), same as the privacy policy.
TWO FACTUAL CORRECTIONS were needed before it could go live — a cookie table that names storage
we do not set is exactly what an inspector checks:
1. The document listed `ab_lang / ab_currency / ab_theme` and `ab_saved / ab_searches`. The real
   localStorage keys are `encar.lang`, `encar.currency`, `encar.theme`, `encar.favourites`,
   `encar.searches` (see `context/AppContext.js`), plus `encar.cms.*` for the text cache. The
   real names are in the published table.
2. It had a row for a one-off CSRF token cookie. There is NO CSRF token anywhere in the backend;
   the actual defence is the session cookie being HttpOnly + Secure + **SameSite=Lax**
   (`auth.py` ~line 170). The row now says that instead of describing a cookie we never set.
   If a real CSRF token is ever added, the row can be reinstated.
The document also documents the ePrivacy legal basis (Art. 5(3) of Directive 2002/58/EC via the
Bulgarian Electronic Communications Act), third-party cookies at Stripe/Google sign-in only,
per-browser deletion instructions, and that DNT/GPC signals have no legal effect in the EU.
GOTCHA that broke the page mid-work: `content/legal.js` is `const BG = {...}; const RO = {...};
const EN = {...}`, and the per-language blocks are only separated by `};\n\nconst XX = {`.
Slicing a language's last document out by searching for the NEXT `terms: doc(` swallows that
boundary and the page dies with "RO is not defined". Bound replacements by the block, not by the
next key.
Verified: all 9 legal pages (privacy/cookies/terms/contact x bg/ro/en) render with 0 missing
strings, no `${` or `undefined` leftovers, 14 sections in the cookie policy and 15 in the privacy
policy, and the consent banner still works on top of them.


## Real CSRF protection (2026-06, self-verified) — `backend/csrf.py`
Owner asked for a real token so the cookie policy row is true. Built per the integration
playbook: a SYNCHRONISER token, not a double-submit cookie — only its SHA-256 is stored, so a
database leak hands over nothing usable.
* `GET /api/csrf` issues a token. Signed in → stored as `csrf_hash` on the session document.
  Not signed in → a PRE-AUTH record in `csrf_pre` (TTL index, 60 min) keyed by an HttpOnly
  `encar_pre` cookie, so **login and registration are protected too** (login CSRF is real: an
  attacker logs you into THEIR account and watches what you do next).
* Per SESSION, not per request: consuming a token on every call breaks two tabs, a retry and an
  upload, which is how CSRF protection ends up switched off. An existing `encar_pre` cookie is
  reused on re-issue so a second tab does not invalidate the first.
* Enforced by ONE `@app.middleware("http")` in `server.py` (`csrf_middleware`), not a dependency
  on ~150 routes — a route added tomorrow is protected without anyone remembering to.
  `csrf.exempt()` covers: safe methods, non-/api paths, `/api/csrf`, `/api/stripe/webhook`
  (Stripe signs the raw body) and any request carrying `X-Admin-Token` (a cross-origin page
  cannot set custom headers, and this is how the deploy/seed scripts call us).
  DELIBERATELY NOT exempt: a request with no cookies at all.
* `frontend/src/lib/api.js`: request interceptor adds `X-CSRF-Token` to every POST/PUT/PATCH/
  DELETE, fetching a token on demand with a single in-flight promise; response interceptor
  retries ONCE on a 403 whose detail matches /csrf/ and forgets the token after
  login/register/logout/google-session. Token lives in memory only — localStorage would hand it
  to any script that manages to run on the page. Nothing in the frontend bypasses `http`.
* `POLICY_VERSION` in `consent.js` was NOT bumped: the new `encar_pre` cookie is strictly
  necessary, so nobody has to consent again. The cookie policy has its own `COOKIE_STAMP`
  (version 1.2) and now documents the token and `encar_pre` in all three languages; the privacy
  policy stays at 1.1.
* `backend/tests/conftest.py` is NEW: it wraps `requests.sessions.Session.request` so every
  unsafe test call fetches a token through the SAME session first (inheriting that test's
  cookies). This took the suite from 79 failed/46 errors back to green WITHOUT relaxing anything
  in the app. If a new test 403s, it is missing this fixture, not a broken app.
* Verified by curl: POST without a token → 403; with a pre-auth token → login 200; the old
  token on the new session → 403; refreshed → 200 (`scope: session`); `X-Admin-Token` path →
  200; Stripe webhook → 400 invalid signature (never 403); GETs untouched.
  Verified in the browser: consent save, login, favourite, GDPR export — 14 unsafe calls, all
  200, zero 403s, one token fetch per page load.
* NOT verified end to end: the Google sign-in POST (`/api/auth/google/session`) — it goes
  through the same axios client, but there are no Google credentials in this environment.
* PRE-EXISTING test failures, unrelated to CSRF (all on GETs or missing config): `tests/
  test_admin_features.py` hardcodes a stale `x-admin-token: "encar-admin"`; `test_recommendations`
  reads an unset BASE_URL; tracking tests need the JsonCargo key; CMS translate needs a valid
  ANTHROPIC_API_KEY; `test_deposit_refund_e2e` needs Playwright fixtures.


## Backlog
### P0 (blocked on the owner)
- **A real Maersk reference** to finish validating the public reader against live data, and
  the **MarineTraffic API key** for live vessel positions on the map.
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

## Admin audit log (2026-06, VERIFIED)
`audit_log` collection, written by `server._audit(request, actor, action, target, detail)`;
read by `GET /api/admin/audit` (newest first, limit ≤ 500) and rendered in Admin → **Activity**
(`components/admin/AdminAudit.js`, `data-testid="admin-audit"`). Actor is the signed-in admin's
email or `"master token"` when `x-admin-token` was used; the client IP is stored too.
Audited: taxonomy merge / rename, merge-rename undone, enquiry deleted, **customer deleted**,
**deposit refunded** (the last two were missing and were added). Verified end to end with the
master token (3 rows written) and in the browser as `admin@encarskin.com`; the probe rows were
deleted afterwards, so the collection is empty on purpose.
FIXED SAME SESSION: the tail of `server.py` was corrupt from the previous session's botched
edit (a stray `_public.close()` plus a duplicated `on_shutdown` body) — it would have taken the
backend down on the next restart. Always `python3 -c "import ast; ast.parse(...)"` after editing.

## Tracking timeline order (2026-06)
Milestones are now sorted CHRONOLOGICALLY in `tracking._view` (`_when_key`, stable, undated
events last, tz dropped so naive and offset-carrying timestamps can be compared). Our two
estimated steps hang off the DISCHARGE date, so simply appending them printed "Customs cleared
05.08" BELOW a carrier arrival on 09.08 — the owner's report. Verified live on B/L 271191199:
departure 07.06 → discharge Rotterdam 01.08 → ready 01.08 → customs 05.08 → arrival Bergen op
Zoom 09.08 → delivery 12.08. The frontend renders payload order, so nothing changed there.

## New-match alerts for saved searches (2026-06, VERIFIED — delivery still blocked)
`backend/searchwatch.py`. A saved search is a standing order, so its stored query string
(English slugs) is resolved back to upstream values (`slugs.resolve_taxonomy` +
`facet_slugs`, mirroring `/meta/resolve`), turned into `server.build_query` params and re-run
after every catalogue sync, filtered on `first_seen > baseline`. `first_seen` is the marker,
NOT `last_seen` or the crawl id: a re-crawled car is not news. Baseline per (person, search)
in `search_watch` (`_id = "{user_id}:{search_id}"`), set WITHOUT alerting on the first pass,
and rebased from scratch when the search's `query` changes (different question). Up to 6 cars
per email plus an "and N more" tail; `mailer.send_new_matches` (BG/RO/EN) links each title to
the ad through `PUBLIC_SITE_URL`. Push goes out too when the buyer opted in
(`notify.wants(user, "push"|"email", "saved_search")`).
Scheduling: `searchwatch.run_later(db)` next to `pricewatch` at the end of a catalogue sync;
manual trigger `POST /api/admin/search-watch/run?first_seen=0|1`.
UI: per-search bell in `SavedSearchCard` ("Известия" / "Известия вкл.",
`data-testid="saved-search-alerts-{id}"`), `AppContext.toggleSearchAlerts`, disabled for
guests with a "sign in" tooltip. `alerts` was already carried through `auth._clean_searches`
and the existing debounced PUT syncs it to the account; `lang` was ADDED to `_SEARCH_KEYS`
and is stored on save, so the alert speaks the language the search was made in (searches
saved before this change fall back to English).
Verified: 6/6 in `backend/tests/test_search_watch.py` (baseline-only first pass, real matches
and exactly one email on the second, silence on the third, alerts-off never checked, rebasing
on a filter change, slug resolution, and the rendered HTML carrying titles/prices/links), plus
the toggle flipped in the browser and read back from `GET /auth/saved-searches` as
`alerts=true`. NOTE: no pytest-asyncio in this pod — tests drive their own loop with
`asyncio.run`, like the deposit tests.
EMAIL DELIVERY IS STILL BLOCKED for this and every other message: `ADMIN_NOTIFY_EMAIL` is
unset and `SENDER_EMAIL` is Resend's shared sender, so `mailer._send` drops everything.

## Merged trims cleared on Back — root cause and fix (2026-06)
The owner's report: after filtering on the merged "S63 AMG 4MATIC+ Coupe" and opening an ad,
Back cleared the submodel select and the merge "stopped working". REPRODUCED, one root cause:
`slugs.ensure_taxonomy_slugs` scoped slug uniqueness by `(level, make, model, badge)`, but a
level-3 document carries `badge` equal to its OWN value (and a level-2 document `model`), so
every trim sat in a scope of its own. "S63 AMG 4MATIC" and "S63 AMG 4MATIC+" both slugify to
`s63-amg-4matic` (slugify drops "+") and BOTH kept it; `resolve_taxonomy` then returned
whichever Mongo found first — the value the owner had merged AWAY — which is not in the
collapsed dropdown, so the select cleared. 17 real collisions existed (16 at level 3, 1 at
level 2: LS/LS+, 솔/솔+, 뉴SM5/뉴SM5(신형)…). Note this CONTRADICTS the earlier PRD claim that
"only ONE real collision exists" — merging creates new ones, so do not trust that line.
Fixes, both in `slugs.py`:
1. Uniqueness is scoped by the PARENTS only — level 1 `()`, 2 `(make)`, 3 `(make, model)`,
   4 `(make, model, badge)` — and documents are numbered survivors-first (`curate.root`), so a
   folded value can never steal the plain slug from the value that survives.
2. `resolve_taxonomy` maps whatever it finds through `curate.root`, so even an old link
   carrying a folded value's slug (`s63-amg-4matic-coupe-2`) lands on the survivor. Parent
   constraints use `curate.expand`, because the children of a merged make/model still carry
   the folded parent.
Slugs were rewritten once with `ensure_taxonomy_slugs(db, force=True)`: 0 collisions left,
0 empty slugs. Verified in a browser: load the slug URL, open an ad, Back — trim still reads
"S63 AMG 4MATIC+ Coupe (15)" and the 15 results (both the "+" and non-"+" cars) are intact.
Regression test: `TestMergedValuesResolve` in `backend/tests/test_english_slugs.py` walks every
level-3 merge and asserts the survivor's slug never resolves to a folded value.
The stale `test_level1_62_unique_makes_and_slugs` assertion was made merge-aware (62 marques
minus the owner's merges) instead of the hardcoded 62.

## Untranslated submodels — cause and fix (2026-06)
35 taxonomy values (34 trims, 1 sub-trim) had NO English cache entry, so they rendered as
Hangul ("A200 CDI 나이트", "럭셔리 블랙"). Warming already covers every distinct badge, but the
cache had drifted behind the crawl. All four levels are now 100% English (level 1: 62,
level 2: 1 252, level 3: 4 215, level 4: 520 — 0 missing, 0 still Hangul) and the newly
translated values got proper slugs in the same rebuild. `warm_translations` no longer warms
LATIN_FIELDS (make/model/badge/badge_detail) in bg/ro — they are read from the English cache in
every language, so those calls were paying for translations nothing renders.
CLAUDE IS THE ONLY TRANSLATOR IN USE (owner's instruction): `translate._llm_translate` picks
Anthropic whenever `ANTHROPIC_API_KEY` is set (`ANTHROPIC_MODEL=claude-sonnet-5`), and the
dealer-description stream uses `ANTHROPIC_FAST_MODEL`. Gemini and the Emergent key are dormant
`elif` fallbacks that only fire if the Anthropic key disappears.

## Deploy: Hetzner, systemd, no Docker (2026-06) — matches the owner's Auto&Bid pattern
The owner deploys their other app with plain Ansible playbooks per component, systemd units and
a venv — NO Docker — so `/app/deploy/hetzner/ansible/` now mirrors that exactly and the old
Docker/Caddy tree moved to `/app/deploy/legacy-docker/` (do not extend it).
Two hosts: `front1` public (nginx + the static build, root over ssh) and `back1` private-only
(`deploy@10.0.0.3`, reached through front1 as a jump host).
- `playbooks/deploy_backend.yml` — apt base, MongoDB 7 native (jammy pool, Noble has none)
  bound to 127.0.0.1, git checkout per release into `/opt/encar/releases/<ref>-<stamp>`, venv at
  `/opt/encar/venv`, env file `/etc/encar/backend.env` (0640 root:www-data) from `group_vars`,
  systemd unit `encar-backend.service` (User=www-data, 0.0.0.0:8001, **--workers 1**,
  ProtectSystem=strict with `ReadWritePaths` for the media dir, TimeoutStopSec=45 so the
  shutdown hook can record an interrupted crawl), `current`/`previous` symlink swap,
  `/api/health` gate, prune to 5 releases, ufw (ssh from anywhere, 8001+27017 from
  `10.0.0.0/16` only, outbound allow), nightly mongodump kept 14 days.
- `playbooks/deploy_frontend.yml` — Node 20 + yarn via corepack, `yarn install --frozen-lockfile`,
  build with `CI=false` and **`REACT_APP_BACKEND_URL=""`** (same origin, so ONE build serves every
  brand domain), `gen-seo.js` with the real domain, atomic `build` symlink swap +
  `build.previous`, prune to 5.
- `playbooks/deploy_nginx.yml` — nginx, `/etc/ssl/encar` created but NEVER written (Cloudflare
  Origin cert is dropped by hand; the playbook asserts both files exist and says where to get
  them), `/etc/hosts` entry `encar-back1`, site config, `nginx -t`, ufw.
- `templates/nginx-site.conf.j2` — Cloudflare `set_real_ip_from` list + `CF-Connecting-IP`,
  80 → 301, `www.*` → apex per TLD, one server block for all domains, SPA `try_files`,
  immutable `/static/`, `no-store` on `service-worker.js`, `/api/` proxy with
  **`proxy_buffering off`** (the description translation is SSE), long-cached `/api/media/`.
- `playbooks/site.yml` runs backend → frontend → nginx. `-e ref=main` selects branch/tag/commit.
- Verified here: `ansible-playbook --syntax-check` passes on all three (with
  `community.general` + `ansible.posix` installed) and all three Jinja templates render from
  `group_vars/all.yml.example`. `inventory.ini` and `group_vars/all.yml` are gitignored.
- SSH: nothing in the tree touches sshd, keys or `authorized_keys`. The only lockout risk is
  ufw, so `ssh_port` is a variable (default 22) and the private CIDR is trusted on both hosts.
- **Known gap to watch**: back1 has no public IPv4, so `deploy_nat.yml` makes front1 its way
  out. Without it every integration fails.

## Deploy: NAT gateway (2026-06)
`playbooks/deploy_nat.yml`, first in `site.yml`. front1 masquerades `10.0.0.0/16` out its
public interface; back1 gets a default route via `frontend_private_ip` (10.0.0.2). The
MASQUERADE rule lives in `/etc/ufw/before.rules` ON PURPOSE — ufw rewrites the nat table on
every `ufw reload`, so an iptables-persistent rule silently disappears. Plus
`net/ipv4/ip_forward=1` in `/etc/ufw/sysctl.conf` and `DEFAULT_FORWARD_POLICY="ACCEPT"` in
`/etc/default/ufw` (ufw's FORWARD chain defaults to DROP, which would break NAT even with the
nat rule in place). On back1 the route is applied live with `ip route replace` and persisted in
a netplan drop-in, WITHOUT `netplan apply` (that bounces the interface Ansible is connected
over). The play then proves egress: `curl https://ifconfig.me` (must print front1's public
address) plus HEAD requests to Stripe, Anthropic, Resend and Encar. Must run BEFORE
`deploy_backend.yml` on a fresh box or apt and pip have no way out.

## Price note, recommendation shelf, clean title (2026-06)
Prices are won amounts converted at the day's rate, so they really do move overnight and the
owner wanted that said out loud.
- `components/PriceNote.js` — an ⓘ beside the price (detail header `detail-price-note` and the
  sticky bar `sticky-price-note`), plus the same sentence in the footer (`footer-fx-note`).
  i18n: `fxNote`, `fxNoteLabel` in bg/ro/en.
  DO NOT rebuild this on Radix. The tooltip never opens on touch, and the popover hands focus
  to its panel and hands it BACK on close, which re-fired the trigger's focus handler and
  reopened the note the moment the mouse left — it looked stuck open permanently (the owner
  reported exactly that). It is now a plain absolutely-positioned panel closed by mouseleave,
  Escape and outside `pointerdown`.
  Hover handlers are bound ONLY when `matchMedia("(hover: hover) and (pointer: fine)")` says the
  device hovers. Without that guard iOS fires mouseenter on the first tap and then click, so the
  note opened and shut in one gesture and needed a SECOND tap — the owner's second report.
  Verified: desktop hover opens and closes; with CDP `Emulation.setEmulatedMedia`
  (hover:none/pointer:coarse) + touch emulation ONE tap opens, a second closes, outside closes.
- `components/YouMightLike.js` — "You might also like" carousel under the dealer description
  (`you-might-like`, arrows on desktop, free-scrolling strip on mobile, 12 cards verified). It
  POSTs `/api/recommendations` with the DEVICE taste profile plus the car in front of the buyer
  weighted at 4 (heavier than a favourite), excluding the current id. Raw upstream values
  (`manufacturer`/`model`/`fuel_type`) because that is what the recommender matches; it hides
  itself below 2 results and the backend still falls back to the fortnight's most-opened ads.
- `format.stripGenerationYears()` drops "(2013-2016)" from the DISPLAYED car name on the detail
  page and the sticky bar only. Encar spells the generation into the model name, and that range
  is the model's identity upstream, so filters, slugs and the taxonomy keep it.

## Contract on the payment page (2026-06, stage 1 done, КЕП pending)
`backend/contracts.py` + `components/ContractPanel.js` + `components/admin/AdminContract.js`.
The template lives in `settings._id="contract_template"` as `{seller, bodies: {bg, ro, en}}`,
seeded from the owner's own paper contract (АТЛАНТИК ДРАЙВ ЕООД, ЕИК 208414795) and editable in
Admin → **Contract** per language, with a Reset per language and a placeholder cheatsheet.
NOTE: the seed only runs when the settings doc does not exist, so changing `DEFAULT_BODIES`
in code does NOT reach an install that has already seeded — delete the doc or use Reset.
- Buyer fills 7 fields (name, ЕГН/CNP, ID card no, issue date, issuer, address, phone). They are
  stored on the USER (`users.contract`), so a second purchase arrives pre-filled.
- Placeholders render as the dotted blank `……` when unknown, never as an empty gap or a guess.
- **Encar publishes NO VIN** — checked the ad, the cached detail and the archive: `vin` is always
  null and only the Korean plate (`detail.vehicleNo`, e.g. "11조1431") exists. So `{{plate}}` is
  filled from the archive and `{{vin}}` stays blank until someone types it on the deposit record.
  Do not "fix" this by inventing a VIN.
- Contract number is `{car_id}/{ddmmyyyy}`, not the Stripe session id.
- `.docx` is built with python-docx (added to requirements) — no LibreOffice on the box.
  Printing uses a print stylesheet on `#contract-print` in `index.css` (a popup window gets
  eaten by blockers).
- Endpoints: `GET/PUT /api/contract/{session_id}`, `GET /api/contract/{session_id}/docx`,
  `GET/PUT /api/admin/contract-template`, `POST /api/admin/contract-template/reset`.
  Ownership is enforced: another buyer gets 404, an anonymous caller 401.
- Verified: 8/8 in `backend/tests/test_contract.py` plus the browser flow (fill 7 fields → save →
  every value appears in the document, "7 fields left" note disappears).
- STAGE 2, BLOCKED: signing with КЕП through **Eurosign** (owner's choice,
  app.eurosign.com/docs/api). Needs the owner's Eurosign API credentials; nothing is implemented
  yet and the panel says so in all three languages (`contractKepNote`).
- Two bugs found and fixed during the browser check: `key.replace("_","-")` only replaced the
  FIRST underscore so half the test ids were wrong, and the contract number was unreadable.

## Deploy blocker: requirements.txt was not installable off-platform (2026-06, FIXED)
The owner's first Hetzner run died on `No matching distribution found for
emergentintegrations==0.2.0`. Cause: `pip freeze` inside the Emergent pod captures
`emergentintegrations` (private index only) and a `litellm` wheel pinned to an
emergentagent.com URL. Neither is imported by the app — `translate._emergent_call` is a
last-resort fallback that is only selected when there is NO `ANTHROPIC_API_KEY`, its import is
function-local and the caller already catches every exception. Both lines removed.
Also removed `ansible-core` + `resolvelib`, which my own `pip freeze` leaked in after I
installed Ansible here to syntax-check the playbooks (confirmed by diffing the two commits).
The same freeze legitimately ADDED PyOTP, qrcode, pywebpush, py-vapid, http_ece, lxml and
python-docx, which were installed in the pod but missing from the file — a fresh server would
have installed cleanly and then crashed at import. Keep them.
Verified: `pip install --dry-run --ignore-installed -r requirements.txt` resolves all 143 lines
from PyPI, every runtime import still loads, backend healthy.
GUARD: `backend/tests/test_requirements_portable.py` (5 tests) fails on any URL/file pin,
unpinned line, platform-only package or agent tooling, and checks the packages the app imports

## 2026-06 — Cayenne rename + email sender on the owner's own domain
- Taxonomy: `카이엔 (PO536)` (525 cars) now READS "Cayenne" in the model dropdown. The owner
  chose a RENAME ONLY — no merge — so `뉴 카이엔` ("Cayenne (2011-2018)") and `카이엔`
  ("Cayenne (2004-2010)") stay separate entries and the slug is still `cayenne-po536`
  (renaming does not touch slugs, so old links keep working). Applied through
  `POST /api/admin/taxonomy/overrides` with `label`, no `target`; verified in
  `/api/meta/taxonomy?level=2&make=포르쉐` (`renamed: true`).
  NOTE: a manual label SKIPS `curate.model_label`, so a renamed model carries no year span —
  that is why this one entry reads plain "Cayenne" next to the two dated ones.
- Email: `SENDER_EMAIL` and `ADMIN_NOTIFY_EMAIL` are both `contact@encareurope.com`
  (backend/.env and `deploy/hetzner/ansible/group_vars/all.yml.example`). Since the sender is
  no longer Resend's shared address, `mailer._send` no longer redirects buyer mail to the
  owner — enquiry acknowledgements, price-drop and saved-search alerts now address the buyer
  directly.
- STILL BLOCKED, ONE RECORD: `encareurope.com` is added to Resend but its status is
  **pending** — SPF (MX + TXT on `send`) verified, **DKIM not**. A live send fails with
  "The encareurope.com domain is not verified". The owner must add at their DNS host:
  TXT `resend._domainkey` = `p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDFpQiE9HAWm4b0ibiXAZbPk79Nq2KM4XugBXvDPBeVd4KyxIVbEbMe1ShJFOm6Nop1w9aiTDxGzV4+nGGdun4P0WooQHvyKZ/6ccpOwn5GyAa19oLfU4oHgrOtJUS23SdvsOv10DsDnLnifCop7b8qz5qI/s7YePqJg0uVhwVMwQIDAQAB`
  (if Cloudflare, the record must be DNS-only/grey cloud). Check with
  `curl -s https://api.resend.com/domains -H "Authorization: Bearer $RESEND_API_KEY"` — no
  code change is needed once it flips to `verified`.
- Deferred by the owner this session: Eurosign contract E2E browser pass, and the Hetzner
  deploy failure (they will send the Ansible output / `journalctl -u encar-backend` later).

are actually listed. NEVER run a bare `pip freeze > requirements.txt` in this pod again without
running that test.

## Reference
- Test credentials: `/app/memory/test_credentials.md`
- Implementation log: `/app/memory/CHANGELOG.md`
- Test reports: `/app/test_reports/iteration_1.json` … `iteration_12.json`

## 2026-06 — Google sign-in, the page/SEO editor, headings, tracking inference
### Google sign-in (Emergent-managed OAuth)
`auth.google_session` (`POST /api/auth/google/session`). The button on the login page sends the
buyer to `https://auth.emergentagent.com/?redirect=<window.location.origin + /{lang}>` — the
redirect is built from the BROWSER's own origin, never hardcoded and with no fallback, so the
same build works on the preview domain and on encareurope.com. The one-time `session_id` comes
back in the URL FRAGMENT; `App.AppRouter` checks `useLocation().hash` DURING RENDER (not in an
effect) and hands over to `pages/AuthCallback.js`, which spends the id once (a `useRef` guard,
not state) and navigates away, which is also what drops the fragment — `history.replaceState`
would not re-render the router. `AuthContext` skips its `/auth/me` probe while a `session_id`
hash is present, otherwise it races the exchange and 401s.
The exchange with `demobackend.emergentagent.com/auth/v1/env/oauth/session-data` happens SERVER
side, so the provider token never reaches the browser, and the account is then given one of OUR
OWN sessions (`_start_session`): same HttpOnly cookie, same active-devices list, same instant
revocation. An existing email is LINKED (no second account); a new one is created with no
password_hash and `google_id`/`picture`. TOTP is still enforced — the endpoint answers
`mfa_required` + `pending_id` and the callback navigates to the login page with the ticket in
navigation state, where the existing 2FA form picks it up.
### Owner-editable pages, SEO and company details (`backend/cms.py`, `admin/AdminPages.js`)
Admin -> **Pages & SEO**. Everything is an OVERRIDE: `site_pages` (`_id = "{slug}|{lang}"`) and
`site_settings._id = "company"`; an empty field falls back to the copy that ships in the
frontend, and `DELETE /admin/cms/page/{slug}/{lang}` puts the built-in text back. Eight slugs
(home, how-it-works, faq, fees, contact, terms, privacy, cookies) x bg/ro/en carry
`seo_title` + `seo_description`; the seven content pages also carry a RAW HTML body (the owner's
explicit choice) and `home` carries the hero headline/sub-headline instead.
* Public: `GET /cms/site?lang=` (company + every SEO override + hero, 15s in-process cache) and
  `GET /cms/page/{slug}?lang=`. Admin: GET/PUT/DELETE per page, `POST .../translate?source=bg`,
  GET/PUT `/admin/cms/company`.
* `cms.sanitise` strips `<script|style|iframe|object|embed|form|link|meta>`, every `on*=`
  handler and `javascript:` URLs on save AND on read. The author is the owner, so this is not a
  defence against a hostile author — it stops a pasted tracking snippet reaching visitors.
* The editor carries a Google SERP preview and 60/155 counters that turn red, a "Load the
  built-in text" button that serialises the existing structured copy to HTML (built in the
  FRONTEND, where that content lives, so nothing is duplicated on the server), and a preview
  toggle rendering `.cms-html`.
* `.cms-html` in `index.css` gives h1/h2/h3/p/ul/table/img their typography, because raw tags
  cannot carry Tailwind classes.
* `content/legal.js` and `content/help.js` now build their documents in a `build()` called
  through a cache keyed on `JSON.stringify(COMPANY)`, instead of at import time — the company
  details are editable at runtime and those documents quote them. `content/company.setCompany`
  mutates the object in place; `AppContext` calls it with whatever `/cms/site` returns.
* Translation: the owner writes Bulgarian and `POST /admin/cms/page/{slug}/translate` writes RO
  and EN. The prompt keeps every tag, attribute and URL and translates only the text between
  them. **Claude first, Gemini as the standby** — see the next section.
* MISTAKE TO LEARN FROM: `translate._extract_json` ALREADY returns a parsed dict. Wrapping it in
  `json.loads` again cost one debugging round ("the translation came back in an unexpected
  shape"). Also: I overwrote the owner's own home/bg record while verifying, and had to
  reconstruct it from their RO/EN translations. NEVER PUT to a CMS slug the owner may have
  edited — write to a throwaway slug or read the record first.
### THE OWNER'S ANTHROPIC KEY IS INVALID (2026-06)
`ANTHROPIC_API_KEY` in backend/.env answers **401 "API key is invalid"**. Every Claude path is
therefore dead right now: taxonomy warming, the dealer-description stream and (before the
fallback) the CMS translation. `GEMINI_API_KEY` works and was verified. `cms._translate_doc`
tries Claude, logs, then falls back to Gemini with `responseMimeType: application/json`.
`translate.py` was NOT changed — its Gemini branch is an `elif` that only fires when the
Anthropic key is ABSENT, so an invalid-but-present key still breaks it. If the owner cannot
replace the key, that `elif` has to become a real fallback.
### The editable copy no longer flashes (`lib/cmsCache.js`)
The owner's report: on refresh the built-in headline showed for a split second before theirs
loaded. An API answer cannot arrive before the first paint, so the payload is now mirrored in
localStorage (`encar.cms.site` per language, `encar.cms.pages` per slug|lang) and React's state
is SEEDED from it, with the fetch only correcting it afterwards. Verified: on a refresh the very
first paint already carries the owner's h1. A brand-new visitor with an empty cache still sees
the built-in text for that one paint — the only real cure for that is server-side rendering.
### Heading hierarchy (owner asked, all three approved and done)
* Filtered result pages had **no h1 at all** (the hero, and with it the only h1, is home-only).
  `SearchPage` now renders `data-testid="results-heading"` — `{describeSearch()} от Корея —
  {count}` (new i18n keys `listH1`, `resultsHeading`) — ABOVE the grid, so it is the first
  heading in the document, before Radix's own accordion `h3`s in the filter sidebar.
* The car page's h1 lived in a `hidden lg:flex` block, so the MOBILE dom had no h1 at all and
  Google crawls mobile-first. The title is now in the DOM at every width, `sr-only` below `lg`
  (the visible mobile title is the sticky bar's), and only the price/save block is hidden.
  Verified: exactly ONE h1 at 414px.
* h1 -> h3 skips closed: `TrustStrip` cards are h2 (directly under the hero h1) and the results
  list carries an h2 ("Резултати"); the count label is `sr-only` on filtered pages because the
  h1 already prints it. Outline now reads H1 -> H2 -> H2 -> H2 -> H3 on home.
### Tracking: a confirmed event proves the earlier ones (owner's report)
"Предаден за доставка 06.08" (actual) was printing ABOVE "Готов за доставка 01.08 ПРОГНОЗА" and
"Освободен от митницата 05.08 ПРОГНОЗА" — a box out for delivery has obviously cleared customs.
`tracking._view` now takes the LATEST confirmed event and clears the `estimated` flag on every
milestone dated before it, reported or derived by us. Only genuinely future steps keep the
forecast badge and the dashed marker. Verified with a synthetic timeline and in the browser on
B/L 271191199: four solid steps, "Доставка 12.08" the only forecast left.
### Leaflet sat on top of the header
Leaflet gives its panes and controls z-index 400-1000, the site header is z-40, so the map
covered the nav on scroll. The map wrapper in `VesselMap` is now `relative isolate z-0`: one
stacking context of our own, Leaflet's internal ordering untouched. Verified with
`elementFromPoint` at y=30 — the header link wins.
### Domain cleanup
Leftover Auto&Bid references that a visitor or Google could see are gone: `content/company.js`
(email `contact@encareurope.com`, site `encareurope.com`), `lib/seo.SITE_NAME` and the home
JSON-LD Organization/WebSite name are "Encar Europe", and the service worker's push title/tag.
The registered company name and ЕИК are unchanged (that is the real legal entity), and
`~/.ssh/autoandbid_root` in the deploy notes is the owner's own key file name.
### Taxonomy: Cayenne
`카이엔 (PO536)` (525 cars) READS "Cayenne" — a RENAME ONLY at the owner's choice, so
`뉴 카이엔` ("Cayenne (2011-2018)") and `카이엔` ("Cayenne (2004-2010)") remain separate and the
slug stays `cayenne-po536`. A manual label skips `curate.model_label`, which is why this entry
alone carries no year span.
### Email
`SENDER_EMAIL` and `ADMIN_NOTIFY_EMAIL` are both `contact@encareurope.com`, so `mailer._send`
no longer redirects buyer mail to the owner. STILL BLOCKED ON ONE DNS RECORD: the Resend domain
is `pending` — SPF verified, **DKIM not**. The owner must add TXT `resend._domainkey` (value in
the earlier section of this file / readable from `GET https://api.resend.com/domains`), DNS-only
if it is on Cloudflare. No code change is needed once it flips.
### Test report
`/app/test_reports/iteration_30.json` — 14/14 backend checks plus the Playwright pass on the
Google button/callback and the whole CMS editor. `retest_needed: false`.


## 2026-06 — Owner's account, password change, admin rights, gallery arrows, production data
### The owner's own account (`auth.ensure_owner`, called from on_startup)
`OWNER_EMAIL` / `OWNER_PASSWORD` in backend/.env (and `owner_email` / `owner_password` in the
Ansible group_vars + `backend.env.j2`). Currently `martingtodorov@gmail.com` / `Nero` — FOUR
characters, at the owner's explicit instruction. The seed re-applies `is_admin` on every boot
but writes the password ONLY when the account has none, so a password changed in the profile
survives a restart. Because that account already HAD a password (registered 02.08), the seed
would not have touched it, so the hash was set once by hand.
* THE TRAP THIS EXPOSED: the login form enforced `MIN_PASSWORD` (8) via `minLength` AND a
  client-side check, so "Nero" could not be submitted — the form silently refused, no request,
  no error. A minimum length is a rule for CHOOSING a password, never for typing one that
  already exists. `LoginPage` now applies it only when `mode === "register"`.
### Change your own password
`POST /api/auth/password` ({current, new}) + `components/PasswordPanel.js` on the account page.
Requires the current password, unless the account has none because it only ever signed in with
Google — then the same card reads "set a password" and the signed-in session is the proof.
Drops every OTHER session afterwards and keeps the one that made the change, and reports how
many were signed out. Verified: wrong current -> 401, short -> 400, same -> 400, and a second
cookie jar for the same user goes dead while the acting one still passes /auth/me.
### Making other people administrators
`PUT /api/admin/users/{email}/admin` ({is_admin}) + an Admin column in
`components/admin/AdminBuyers.js`. Two rails: nobody changes their OWN flag, and the last
administrator cannot be demoted. Audited. The buyers table now lists EVERY account, not only
the ones with browsing history, otherwise a fresh account could never be promoted.
### The header shows the first name
`ProfileMenu` shows `user.name`'s first word (falling back to the email local part) instead of
"Моят профил". Test id `header-profile-name`.
### Gallery arrows
The owner asked for no left arrow on the first photo and no right arrow on the last. They were
already `disabled` with `disabled:opacity-0`, but the hover rule that makes them appear at all
was winning over it, so a dead arrow still showed. `PhotoSwiper` now RENDERS them conditionally
(`active > 0`, `active < count - 1`). The testing agent then caught the real reason the owner
saw nothing change on result cards: `CarCard` never passed `arrows` at all and PhotoSwiper's
default is `false`, so grid cards had no arrows in the first place. Fixed. NOTE `Lightbox` is
deliberately left cycling (modulo), so its arrows always work.
### Production (encareurope.com) had no dropdowns, no merges, no year spans
All three are DATA, not code. `taxonomy`, `model_years`, `facets` and `option_dicts` are derived
from `listings` and self-heal on the first `/meta/taxonomy` read; `taxonomy_overrides`,
`site_pages`, `site_settings`, `settings` and `translations` are the owner's own work and cannot
be rebuilt anywhere.
* **`backend/seed_curation.py` + `backend/seed/curation.json`** — the merges/renames and the
  year spans now TRAVEL IN THE REPOSITORY and are applied at startup, INSERT-IF-MISSING by
  `_id`, so every deploy carries them and a live edit is never clobbered by the next restart.
  Regenerate after curating: `cd /app/backend && python3 seed_curation.py --dump`
  (9 overrides + 1,252 year spans, 93 KB). Verified against a scratch database: a fresh server
  gets everything, a restart adds nothing, and an edit made on the server survives.
* **`deploy/doctor.py`** — run on the box, prints every collection with a count and what breaks
  when it is empty, then checks the three symptoms properly (taxonomy per level + how many have
  slugs, `sync_state.taxonomy.built_at`, span count, the overrides listed one by one, admin
  count, pricing settings), then which integration keys are BLANK, then the remedy. It already
  found 2 of 1,261 level-2 models with no slug.
* **`deploy/export_data.py` collection list was stale and lost money**: it asked for
  "purchases", which does not exist — the real names are `deposits` and `purchased_listings`, so
  every paid reservation deposit was silently left behind. Also added `site_pages`,
  `site_settings`, `shipment_events`, `price_watch`, `search_watch`, `push_subscriptions`,
  `audit_log`.
* A full verified `mongodump --gzip --archive` of everything lives in `/app/db_export/`
  (31 collections, 251,635 documents, 60 indexes, 19.6 MB) plus a curation-only pair of
  `.jsonl.gz` files in `/app/db_export/curation/`. NOTE: the mongodump in this image is old and
  does NOT accept `--nsInclude`; use `--collection` or the jsonl route.
### Facts established while answering the owner's questions
* **Catalogue coverage**: 62 makes (all of them), 1,261 models, 5,988 submodels, 3,339 trims =
  10,650 precomputed nodes. But the index holds 145,451 of Encar's 210,046 exportable cars =
  **69.2%**, and every single brand sits at 68-74%. A uniform shortfall like that is a
  systematic cap in the partitioned crawl, not brand-specific failures — worth investigating
  (`sync._crawl_node`, `LEAF_MAX = 500`, and the `min(count, 20_000)` window on unsplittable
  buckets).
* **JsonCargo works**: `x-api-key` (NOT `Authorization: Bearer` — an early test of mine used the
  wrong header and produced a misleading 401). `GET /api_key/stats` answers 200: plan MARINER,
  15 of 1,000 requests used. So "Проследяването още не е свързано" on production means
  `jsoncargo_api_key` is EMPTY in the owner's group_vars, not a broken integration.
* I cannot create or push to a GitHub repository. That is the "Save to Github" button.
### Still open
* Pre-warming the taxonomy translations after a sync so the FIRST search is not slow. Today
  `/meta/taxonomy` calls `translate_many` inline, and with the dead Anthropic key each miss
  burns the retry ladder before falling back. The fix has two halves: warm all four levels for
  all three languages after `build_taxonomy`, and make the dropdown path use
  `translate_cached_only` + `schedule_translation` so it can never block on an LLM.
* The ~31% of the catalogue that is not indexed.
* `/app/test_reports/iteration_31.json` — everything else passed.


## 2026-06 — "the first search is very slow": four separate causes, all fixed
The owner asked for the makes and models to be warmed after a sync. Measuring it turned up
four things, three of which were the actual cause.

### 1. The nightly crawl warmed nothing (the real one)
`warm_translations` was only called at the end of `run_full_sync`, but the crawl actually in
use is `crawl_partitioned` (`sync_state.catalogue_partition`), which built no taxonomy, filled
no slugs, computed no year spans and warmed nothing. Extracted `sync.post_crawl(db)` —
build_taxonomy -> ensure_taxonomy_slugs(force) -> curate.ensure_years(force) ->
warm_translations, each guarded so one failure cannot abort the rest — and called it at the end
of BOTH crawls. `curate.ensure_years` gained a `force` argument for exactly this.
Measured: 12.3s for the whole pass. 10,650 nodes, 10,648 slugs written, 1,253 year spans, and
the 19 cold labels translated. It also fixed the 2 slugless models `doctor.py` had found —
`taxonomy` now has ZERO nodes without a slug.

### 2. The dropdown request itself blocked on the LLM
`/meta/taxonomy`, `/meta/filters` and `/meta/models` called `translate_many`, which translates
cache misses INLINE. All three now use `translate_cached_only` + `schedule_translation`, so a
request can never wait on a provider: a value that is not warm yet renders as its upstream name
for one view and is filled in the background. With the cache 99.9% warm this is invisible.
Measured: `/meta/taxonomy` 24-28ms at every level.

### 3. A present-but-invalid key took the whole translator down
`_llm_translate` picked ONE provider by which key existed and gave up there, so the owner's
expired Anthropic key meant a working Gemini key right next to it was never reached. It is now
a CHAIN (`_providers()`): on a credential or budget failure it falls through to the next
provider instead of tripping the breaker. `FATAL_MARKERS` also missed Anthropic's actual
wording — "API key is invalid." and `authentication_error` — so a dead key burned the full
retry ladder on every call before giving up; both added.
Measured: Anthropic 401 -> Gemini -> three model names translated in 1.7s, breaker still shut.

### 4. Every ten minutes, one visitor paid for the facet aggregation
`/meta/filters` recomputed its 220k-document aggregation in the request whenever the 10-minute
TTL had expired — 1,284ms for whoever arrived first. Split into `_compute_filters` (single
flight, a global `_filters_refreshing` flag so a burst starts ONE aggregation not twenty) and
`_filters_aggregate`, and the endpoint now serves the stale document and refreshes BEHIND the
visitor. Ten-minute-old counts are fine; a slow sidebar is not.
Measured: forced the cache two hours stale — 20ms, 20ms, 20ms, and the document was rewritten
in the background a second later. Was 1,284ms.

### Verified end to end
`/bg` first paint of results 1.2s, marque dropdown all Latin, ZERO Hangul characters on the
page, the owner's own headline in place.

### Note for whoever comes next
The Anthropic key is still invalid — everything above works because Gemini now picks it up.
Replacing the key restores the preferred provider with no code change.


## 2026-06-08 — Status update

### Delivered this session
- Reservations (`POST /api/deposit/checkout`) require a CONFIRMED email; the reserve button is
  shown disabled with a link to `/{lang}/verify-email`. Pre-rollout accounts stay trusted.
- Full password reset flow built from scratch (it did not exist): enumeration-safe request,
  one-shot 30-minute hashed token, new password, all sessions dropped. Available only to
  accounts with a confirmed email. Pages at `/{lang}/forgot-password` and `/{lang}/reset-password`.
- Privacy policy v1.3 translated into Romanian and English (all three stamps now read 1.3).
- Verified: backend suite 211 passed / 2 skipped; testing agent iteration_37 clean.

### Backlog
- P1: Custom 911-style SVG silhouette for the body-damage diagram — BLOCKED on the owner
  supplying the file.
- P1: Owner to review the RO/EN privacy v1.3 translations (machine-translated from their own
  Bulgarian v1.3, same 18 sections, same stamp).
- P2: Row comparison tool for the desktop list view — tick several rows, compare specs and
  prices side by side.
- P2: `server.py` is large and declares many routes; split by area when it next needs work.
- P3: `backend/backend_test.py` still holds a preview URL. Stale standalone script, not part of
  the pytest suite; delete or repoint it.

### 2026-06-08 (later) — production tracking fix
Container tracking was dead on the Hetzner host because `jsoncargo_shipping_line` was deployed
empty and an empty env var beats a code default. Fixed in the config reader, both group_vars
examples and all three env templates; config-caused failures are no longer cached. 219 backend
tests pass. Owner should confirm `JSONCARGO_SHIPPING_LINE=MAERSK` in `/etc/encar/backend.env`
after the next deploy.

### 2026-06-08 (later) — live visitor bar + shipment tied to a car
- Admin-only traffic bar above the header on every page: live now (5 min), what is being viewed
  right now, and day/week/month as visitors + views. Counted first-party and cookieless via a
  daily-rotating salted HMAC of IP+user-agent; raw IP never stored, nothing written to the
  device, admins and bots excluded. Privacy policy gained section 2.10 and moved to v1.4.
- A bill of lading can now be tied to one of the customer's reserved cars from the admin panel,
  which is what puts the Track button on that car in the buyer's Purchases page. The join
  already existed; the car field did not, so car_id was always empty.
- P1: owner's lawyer should review privacy section 2.10 (new processing described).
- P2: 14 Stripe-checkout tests error under parallel xdist workers (Stripe's page is slow to
  render `input#cardNumber`); they pass when the file runs alone. Consider marking them serial.

### 2026-06-08 — view counting confirmed from a real browser
Owner challenged the verification and was right: only the server side had been proven. Confirmed
end to end with an anonymous browser session (5 loads → 5 counted pings → 5 rows → 1 visitor,
5 views). The check exposed a wrong label separator on non-car pages, now fixed with fixed short
route names in `lib/traffic.js::labelFor`.

### 2026-06-08 — Traffic tab
Admin panel gained a Traffic tab: live/24h/7d/30d cards, a day-by-day visitors-vs-views bar
chart with a 7/30-day switch, and what is being viewed right now. Backed by
`GET /api/admin/traffic/history`. Chart hand-drawn on purpose (recharts unused elsewhere; not
worth the bundle for one admin panel).
Remaining backlog unchanged: lawyer review of privacy 2.10 (P1), most-viewed-cars report (P2),
integrations health screen (P2), row comparison tool (P2), custom body SVG (blocked on owner).
