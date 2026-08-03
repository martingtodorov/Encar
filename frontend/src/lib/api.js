import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// withCredentials so the HttpOnly session cookie travels with every call.
const http = axios.create({ baseURL: API, timeout: 60000, withCredentials: true });

export async function searchCars(body) {
  const { data } = await http.post("/search", body);
  return data;
}

export async function getFilters(lang) {
  const { data } = await http.get("/meta/filters", { params: { lang } });
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
export async function getCatalogueSync() {
  const { data } = await http.get("/admin/catalogue-sync");
  return data;
}

export async function startCatalogueSync() {
  const { data } = await http.post("/admin/catalogue-sync/run");
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

export async function getQuote(priceKrw) {
  const { data } = await http.get("/pricing/quote", { params: { price_krw: priceKrw } });
  return data;
}

// ── accounts ────────────────────────────────────────────────────────────────
export async function apiMe() {
  const { data } = await http.get("/auth/me");
  return data;
}

export async function apiRegister(body) {
  const { data } = await http.post("/auth/register", body);
  return data;
}

export async function apiLogin(body) {
  const { data } = await http.post("/auth/login", body);
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
