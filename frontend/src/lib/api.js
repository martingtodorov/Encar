import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// withCredentials so the HttpOnly session cookie travels with every call.
const http = axios.create({ baseURL: API, timeout: 60000, withCredentials: true });

/**
 * CSRF: every unsafe call carries a token another site cannot learn.
 *
 * A cross-origin page can make your browser POST to us with your session cookie attached, but
 * it can neither read our JSON nor set a custom header - so the token in `X-CSRF-Token` is the
 * thing it cannot produce. Held in memory only, per tab: localStorage would hand it to any
 * script that manages to run on the page.
 */
const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE = new Set(["post", "put", "patch", "delete"]);
let csrfToken = null;
let csrfInFlight = null;

async function freshToken() {
  // One request even if ten calls discover the missing token at the same moment.
  if (!csrfInFlight) {
    csrfInFlight = http
      .get("/csrf", { headers: { "Cache-Control": "no-store" } })
      .then(({ data }) => {
        csrfToken = data.token;
        return csrfToken;
      })
      .finally(() => {
        csrfInFlight = null;
      });
  }
  return csrfInFlight;
}

/** Signing in or out replaces the session, so the token bound to the old one is worthless. */
export function forgetCsrf() {
  csrfToken = null;
}

http.interceptors.request.use(async (config) => {
  const method = (config.method || "get").toLowerCase();
  if (!UNSAFE.has(method)) return config;
  if (!csrfToken) await freshToken();
  config.headers[CSRF_HEADER] = csrfToken;
  return config;
});

http.interceptors.response.use(
  (res) => {
    // A new session means a new token; drop ours rather than waiting to be refused.
    if (/\/auth\/(login|register|logout|google\/session)/.test(res.config?.url || "")) {
      forgetCsrf();
    }
    return res;
  },
  async (error) => {
    const { response, config } = error;
    const stale = response?.status === 403 &&
      /csrf/i.test(response?.data?.detail || "") && config && !config._csrfRetried;
    if (!stale) return Promise.reject(error);
    // Exactly one retry: the token rotated under us (another tab signed in, or the session
    // was replaced). Looping here would turn a real 403 into a storm.
    config._csrfRetried = true;
    csrfToken = null;
    await freshToken();
    config.headers[CSRF_HEADER] = csrfToken;
    return http(config);
  }
);

// Pages the visitor is ABOUT to ask for: they hovered a page button, or the pagination row
// scrolled into view on a phone. A head start, not a cache layer — a handful of entries,
// handed over to the first real request that matches and then forgotten.
const PREFETCH_MAX = 8;
const prefetched = new Map();

const searchKey = (body) => JSON.stringify(body);

/** Fire a search the visitor has not asked for yet. Silent: failures are the real
 *  request's problem, and it will make its own. */
export function prefetchSearch(body) {
  const key = searchKey(body);
  if (prefetched.has(key)) return;
  if (prefetched.size >= PREFETCH_MAX) {
    prefetched.delete(prefetched.keys().next().value);
  }
  prefetched.set(
    key,
    http
      .post("/search", body)
      .then((r) => r.data)
      .catch(() => {
        prefetched.delete(key);
        return null;
      })
  );
}

/** Kept between visits so coming back from a car is instant. Small: the last few searches. */
const RESULT_MAX = 6;
const results = new Map();

export function cachedSearch(body) {
  return results.get(searchKey(body)) || null;
}

function remember(key, data) {
  if (results.size >= RESULT_MAX) results.delete(results.keys().next().value);
  results.set(key, data);
}

export async function searchCars(body) {
  const key = searchKey(body);
  const early = prefetched.get(key);
  if (early) {
    // Spent once: the next visit to this page should see fresh counts.
    prefetched.delete(key);
    const data = await early;
    if (data) {
      remember(key, data);
      return data;
    }
  }
  const { data } = await http.post("/search", body);
  remember(key, data);
  return data;
}

export async function getFilters(lang) {
  const { data } = await http.get("/meta/filters", { params: { lang } });
  return data;
}

/** Every make + its models, for the HTML sitemap page. bg and en only. */
export async function getSitemapIndex(lang) {
  const { data } = await http.get("/sitemap/index", { params: { lang } });
  return data;
}

/** Same-make + same-model shelf on the car detail page. */
export async function getMoreFromModel(carId, lang, limit = 12) {
  const { data } = await http.get(`/car/${carId}/more-from-model`, {
    params: { lang, limit },
  });
  return data;
}

/** Fuel + transmission counts scoped to the current search body. */
export async function getFacetCounts(body) {
  const { data } = await http.post("/meta/facet-counts", body);
  return data;
}

/** First-visit language hint from IP geolocation. Returns `{lang: 'bg'|'ro'|'en'|''}`. */
export async function getGeoLang() {
  const { data } = await http.get("/geo/lang");
  return data;
}

/** Cascading Make -> Model -> Submodel -> Trim. Served from a precomputed tree. */
/** English slugs from the URL -> the Korean values the search endpoint speaks. */
export async function resolveSlugs(params) {
  const { data } = await http.get("/meta/resolve", { params });
  return data;
}

export async function getTaxonomy({ level, make = "", model = "", badge = "", lang }) {
  const { data } = await http.get("/meta/taxonomy", {
    params: { level, make, model, badge, lang },
  });
  return data;
}

export async function getCar(id, lang) {
  const { data } = await http.get(`/car/${id}`, { params: { lang } });
  return data;
}

/**
 * Car payloads warmed while the visitor hovers a row, so opening the car is instant.
 * Keyed by language because the payload is translated. Entries hold the PROMISE, so a
 * hover and the click that follows share one request instead of racing.
 */
const carCache = new Map();
const CAR_TTL = 5 * 60 * 1000;
const CAR_CACHE_MAX = 60;

const carKey = (id, lang) => `${lang}:${id}`;

/** A car opened from the hand-picked landing shelf. Fire and forget, like countView. */
export function countRecoClick(id) {
  http.post("/reco/click", { id: String(id) }).catch(() => {});
}

export function countView(id) {
  // Fire and forget: a failed count must never interrupt reading the ad.
  http.post(`/car/${encodeURIComponent(id)}/view`).catch(() => {});
}

export function warmCar(id, lang) {
  const key = carKey(id, lang);
  const hit = carCache.get(key);
  if (hit && Date.now() - hit.at < CAR_TTL) return hit.p;
  if (carCache.size >= CAR_CACHE_MAX) carCache.clear();
  const p = getCar(id, lang)
    .then((d) => {
      // Also pull the first full-size photo into the browser cache, so the hero image is
      // already there when the page opens instead of fading in after it.
      const first = d?.photos?.[0]?.full;
      if (first) {
        const im = new Image();
        im.src = first;
      }
      return d;
    })
    .catch((e) => {
      carCache.delete(key);
      throw e;
    });
  carCache.set(key, { at: Date.now(), p });
  return p;
}

export function forgetCar(id, lang) {
  carCache.delete(carKey(id, lang));
}

export async function getFx() {
  const { data } = await http.get("/fx");
  return data;
}

export async function translateDescription(id, lang) {
  const { data } = await http.post(`/car/${id}/translate-description`, null, {
    params: { lang },
  });
  return data;
}

/**
 * Streamed description translation. Generation takes 10-20s because output length is the
 * bottleneck, so `onChunk` is called as text arrives instead of after it is finished.
 * Resolves with the full text. Throws so the caller can fall back to the POST route.
 */
export async function streamDescription(id, lang, onChunk) {
  const res = await fetch(
    `${API}/car/${id}/translate-description/stream?lang=${encodeURIComponent(lang)}`,
    { credentials: "include" }
  );
  if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; keep any partial frame in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const msg = JSON.parse(line.slice(5).trim());
      if (msg.error) throw new Error(msg.error);
      if (msg.chunk) {
        full += msg.chunk;
        onChunk?.(full);
      }
    }
  }
  return full;
}

export async function getListingsByIds(ids, lang) {
  const { data } = await http.post("/listings/by-ids", { ids }, { params: { lang } });
  return data;
}

export async function getCatalogueSize() {
  const { data } = await http.get("/catalogue/size");
  return data;
}

export async function getHealth() {
  const { data } = await http.get("/health");
  return data;
}

// ── admin ──────────────────────────────────────────────────────────────────
export async function getConsentLog() {
  const { data } = await http.get("/admin/consent");
  return data;
}

export async function getAuditLog() {
  const { data } = await http.get("/admin/audit");
  return data.items;
}

export async function deleteEnquiry(id) {
  const { data } = await http.delete(`/admin/enquiries/${encodeURIComponent(id)}`);
  return data;
}

export async function deleteCustomer(email) {
  const { data } = await http.delete(`/admin/users/${encodeURIComponent(email)}`);
  return data;
}

export async function getRawTaxonomy({ level, make = "", model = "" }) {
  const { data } = await http.get("/meta/taxonomy", {
    params: { level, make, model, lang: "en", raw: true },
  });
  return data;
}

export async function getTaxonomyOverrides() {
  const { data } = await http.get("/admin/taxonomy/overrides");
  return data.items;
}

export async function saveTaxonomyOverride(body) {
  const { data } = await http.post("/admin/taxonomy/overrides", body);
  return data;
}

export async function deleteTaxonomyOverride(id) {
  const { data } = await http.delete(`/admin/taxonomy/overrides/${encodeURIComponent(id)}`);
  return data;
}

export async function getCatalogueSync() {
  const { data } = await http.get("/admin/catalogue-sync");
  return data;
}

export async function startCatalogueSync({ fresh = false } = {}) {
  const { data } = await http.post(`/admin/catalogue-sync/run${fresh ? "?fresh=true" : ""}`);
  return data;
}

export async function getAdminDeposits() {
  const { data } = await http.get("/admin/deposits");
  return data;
}

export async function queueForMobileBg(carId) {
  const { data } = await http.post(`/admin/post-queue/${encodeURIComponent(carId)}`);
  return data.item;
}

export async function getMobileBgStatus(carId) {
  const { data } = await http.get(`/admin/post-queue/${encodeURIComponent(carId)}`);
  return data.item;
}

export async function refundDeposit(sessionId) {
  const { data } = await http.post(`/admin/deposits/${encodeURIComponent(sessionId)}/refund`);
  return data;
}

export async function captureDeposit(sessionId, amountEur) {
  const { data } = await http.post(
    `/admin/deposits/${encodeURIComponent(sessionId)}/capture`, { amount_eur: amountEur });
  return data;
}

export async function releaseDeposit(sessionId) {
  const { data } = await http.post(`/admin/deposits/${encodeURIComponent(sessionId)}/release`);
  return data;
}

export async function putSyncSchedule(body) {
  const { data } = await http.put("/admin/catalogue-sync/schedule", body);
  return data;
}

export async function getAdminOverview() {
  const { data } = await http.get("/admin/overview");
  return data;
}

export async function getAdminCoverage() {
  const { data } = await http.get("/admin/coverage");
  return data;
}

export async function refreshAdminCoverage() {
  const { data } = await http.post("/admin/coverage/refresh");
  return data;
}

export async function getAdminEnquiries(params) {
  const { data } = await http.get("/admin/enquiries", { params });
  return data;
}

export async function setEnquiryStatus(id, status) {
  const { data } = await http.patch(`/admin/enquiries/${id}`, { status });
  return data;
}

export async function getQuote(priceKrw, fuel = "") {
  const { data } = await http.get("/pricing/quote", { params: { price_krw: priceKrw, fuel } });
  return data;
}

export async function getPricingSettings() {
  const { data } = await http.get("/settings");
  return data;
}

export async function putPricingSettings(constants, { reprice = false } = {}) {
  const { data } = await http.put("/settings", { constants, reprice });
  return data;
}

// ── accounts ────────────────────────────────────────────────────────────────
export async function apiMe() {
  const { data } = await http.get("/auth/me");
  return data;
}

export async function saveBilling(billing) {
  const { data } = await http.put("/auth/billing", billing);
  return data.user;
}

/** Persist the buyer's preferred skin language on the account. */
export async function saveAccountLang(lang) {
  const { data } = await http.post("/auth/lang", { lang });
  return data;
}

export async function apiRegister(body) {
  const { data } = await http.post("/auth/register", body);
  return data;
}

export async function apiVerifyEmail(code) {
  const { data } = await http.post("/auth/verify-email", { code });
  return data;
}

export async function apiResendCode(lang = "") {
  const { data } = await http.post(
    `/auth/resend-code${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`, {});
  return data;
}

/** Ask for a reset link. The answer never says whether the address exists. */
/** Visitors and views per day, oldest first. Admin only. */
export async function getTrafficHistory(days = 30) {
  const { data } = await http.get("/admin/traffic/history", { params: { days } });
  return data.items || [];
}

/** Token spend per day, per purpose and per model. Admin only. */
export async function getAiUsage(days = 30) {
  const { data } = await http.get("/admin/ai-usage", { params: { days } });
  return data;
}

/** Fire a real emergency push to every admin device, to prove the channel works. */
export async function testIncidentPush() {
  const { data } = await http.post("/admin/incidents/test");
  return data;
}

/** Open outages and incident history from the server-side watchdog. Admin only. */
export async function getIncidents(run = false) {
  const { data } = await http.get("/admin/incidents", { params: run ? { run: 1 } : {} });
  return data;
}

/** The daily ceiling that triggers an alert email. Admin only. */
export async function setAiBudget(dailyUsd) {
  const { data } = await http.put("/admin/ai-budget", { daily_usd: Number(dailyUsd) });
  return data;
}

/** Build and email the cost report for a day now, without waiting for 21:00. */
export async function sendAiReport(day = "") {
  const { data } = await http.post("/admin/ai-report/send", null, { params: { day } });
  return data;
}

/** Live/day/week/month traffic. Admin only — the endpoint refuses anyone else. */
export async function getTraffic() {
  const { data } = await http.get("/admin/traffic");
  return data;
}

/** The cars this customer has reserved, so a B/L can be tied to one of them by name. */
export async function getCustomerCars(email) {
  const { data } = await http.get("/admin/customer-cars", { params: { email } });
  return data.items || [];
}

export async function apiForgotPassword(email, lang = "en") {
  const { data } = await http.post("/auth/forgot-password", { email, lang });
  return data;
}

export async function apiResetValid(token) {
  const { data } = await http.get("/auth/reset-valid", { params: { token } });
  return data;
}

export async function apiResetPassword(token, password) {
  const { data } = await http.post("/auth/reset-password", { token, password });
  return data;
}

export async function apiLogin(body) {
  const { data } = await http.post("/auth/login", body);
  return data;
}

/** Hand the one-time `session_id` from the Google redirect to our backend, which exchanges
 *  it for an identity and sets our own session cookie. */
export async function apiGoogleSession(sessionId, termsVersion = "") {
  const { data } = await http.post("/auth/google/session", {
    session_id: sessionId,
    terms_version: termsVersion,
  });
  return data;
}

export async function changePassword(current, next) {
  const { data } = await http.post("/auth/password", { current, new: next });
  return data;
}

export async function setUserAdmin(email, isAdmin) {
  const { data } = await http.put(`/admin/users/${encodeURIComponent(email)}/admin`, {
    is_admin: isAdmin,
  });
  return data;
}

export async function apiLogout() {
  const { data } = await http.post("/auth/logout");
  return data;
}

export async function apiMergeFavourites(ids) {
  const { data } = await http.post("/auth/favourites/merge", { ids });
  return data;
}

export async function apiPutFavourites(ids) {
  const { data } = await http.put("/auth/favourites", { ids });
  return data;
}

export async function apiMergeSearches(items) {
  const { data } = await http.post("/auth/saved-searches/merge", { items });
  return data;
}

export async function apiPutSearches(items) {
  const { data } = await http.put("/auth/saved-searches", { items });
  return data;
}

export async function apiPasskeyRegisterOptions() {
  const { data } = await http.post("/auth/passkey/register/options", {});
  return data;
}

export async function apiPasskeyRegisterVerify(body) {
  const { data } = await http.post("/auth/passkey/register/verify", body);
  return data;
}

export async function apiPasskeyLoginOptions() {
  const { data } = await http.post("/auth/passkey/login/options", {});
  return data;
}

export async function apiPasskeyLoginVerify(body) {
  const { data } = await http.post("/auth/passkey/login/verify", body);
  return data;
}

export default http;

// ── shipment tracking ---------------------------------------------------------
export async function trackShipment(ref, by = "container") {
  const { data } = await http.get("/tracking", { params: { ref, by } });
  return data;
}

export async function getTrackedShipments() {
  const { data } = await http.get("/tracking/saved");
  return data.items || [];
}

export async function saveTrackedShipment(body) {
  const { data } = await http.post("/tracking/saved", body);
  return data.items || [];
}

export async function removeTrackedShipment(ref) {
  const { data } = await http.delete(`/tracking/saved/${encodeURIComponent(ref)}`);
  return data.items || [];
}

export async function getAdminShipments() {
  const { data } = await http.get("/admin/shipments");
  return data.items || [];
}

export async function assignShipment(body) {
  const { data } = await http.post("/admin/shipments", body);
  return data;
}

export async function refreshShipment(ref, by = "container") {
  const { data } = await http.post(
    `/admin/shipments/${encodeURIComponent(ref)}/refresh`, null, { params: { by } });
  return data;
}

export async function getRecommendations(profile) {
  const { data } = await http.post("/recommendations", profile);
  return data;
}

export async function getBuyers() {
  const { data } = await http.get("/admin/buyers");
  return data.items || [];
}

export async function getTrackingQuota() {
  const { data } = await http.get("/admin/tracking-quota");
  return data;
}

export async function deleteShipment(ref) {
  const { data } = await http.delete(`/admin/shipments/${encodeURIComponent(ref)}`);
  return data;
}

// ── contract ────────────────────────────────────────────────────────────────
export async function getContract(sessionId, lang) {
  const { data } = await http.get(`/contract/${encodeURIComponent(sessionId)}`, {
    params: { lang },
  });
  return data;
}

export async function saveContract(sessionId, lang, buyer) {
  const { data } = await http.put(`/contract/${encodeURIComponent(sessionId)}`, buyer, {
    params: { lang },
  });
  return data;
}

/** A Word file, so it can be printed or handed to a notary as it is. */
export async function downloadContractDocx(sessionId, lang) {
  const res = await http.get(`/contract/${encodeURIComponent(sessionId)}/docx`, {
    params: { lang },
    responseType: "blob",
  });
  const name = (res.headers["content-disposition"] || "").match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name ? name[1] : "contract.docx";
  a.click();
  URL.revokeObjectURL(url);
}

export async function getContractTemplate() {
  const { data } = await http.get("/admin/contract-template");
  return data;
}

export async function saveContractTemplate(body) {
  const { data } = await http.put("/admin/contract-template", body);
  return data;
}

export async function resetContractTemplate(lang) {
  const { data } = await http.post("/admin/contract-template/reset", null, { params: { lang } });
  return data;
}

// ── owner-editable pages (SEO, bodies, company details) ─────────────────────
export async function getCmsSite(lang) {
  const { data } = await http.get("/cms/site", { params: { lang } });
  return data;
}

export async function getCmsPage(slug, lang) {
  const { data } = await http.get(`/cms/page/${slug}`, { params: { lang } });
  return data;
}

export async function adminCmsPages() {
  const { data } = await http.get("/admin/cms/pages");
  return data.items;
}

export async function adminCmsPage(slug, lang) {
  const { data } = await http.get(`/admin/cms/page/${slug}/${lang}`);
  return data;
}

export async function adminSaveCmsPage(slug, lang, body) {
  const { data } = await http.put(`/admin/cms/page/${slug}/${lang}`, body);
  return data;
}

export async function adminResetCmsPage(slug, lang) {
  const { data } = await http.delete(`/admin/cms/page/${slug}/${lang}`);
  return data;
}

export async function adminTranslateCmsPage(slug, source = "bg") {
  const { data } = await http.post(`/admin/cms/page/${slug}/translate`, null, {
    params: { source },
  });
  return data;
}

export async function getCallButton() {
  const { data } = await http.get("/call-button");
  return data;
}

export async function requestCallback(body) {
  const { data } = await http.post("/callback", body);
  return data;
}

export async function adminCallbacks(params) {
  const { data } = await http.get("/admin/callbacks", { params });
  return data;
}

export async function adminSetCallbackStatus(id, status) {
  const { data } = await http.patch(`/admin/callbacks/${id}`, { status });
  return data;
}

export async function adminDeleteCallback(id) {
  const { data } = await http.delete(`/admin/callbacks/${id}`);
  return data;
}

export async function adminCallButton() {
  const { data } = await http.get("/admin/call-button");
  return data;
}

export async function adminSaveCallButton(body) {
  const { data } = await http.put("/admin/call-button", body);
  return data;
}

export async function adminRecoDefaults() {
  const { data } = await http.get("/admin/reco-defaults");
  return data;
}

export async function adminSaveRecoDefaults(body) {
  const { data } = await http.put("/admin/reco-defaults", body);
  return data;
}

export async function adminResetRecoDefaults(stats = false) {
  const { data } = await http.post("/admin/reco-defaults/reset", null, { params: { stats } });
  return data;
}

export async function adminGetCompany() {
  const { data } = await http.get("/admin/cms/company");
  return data;
}

export async function adminSaveCompany(body) {
  const { data } = await http.put("/admin/cms/company", body);
  return data;
}


// ── Self-learning translation dictionary ────────────────────────────────────
// Every make, model, badge, spec value, fuel and dealer boilerplate line the site
// has ever translated lives in `db.translations` with a `type` tag. These helpers
// power the admin browser + inline edits that push corrections back to the cache.
export async function adminDictionaryStats() {
  const { data } = await http.get("/admin/dictionary/stats");
  return data;
}

export async function adminDictionaryBrowse({ type = "", lang = "",
                                              q = "", limit = 50, offset = 0 } = {}) {
  const { data } = await http.get("/admin/dictionary", {
    params: { type, lang, q, limit, offset },
  });
  return data;
}

export async function adminDictionaryEdit(lang, sourceHash, target) {
  const { data } = await http.put(
    `/admin/dictionary/${encodeURIComponent(lang)}/${encodeURIComponent(sourceHash)}`,
    { target }
  );
  return data;
}
