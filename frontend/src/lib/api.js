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

export async function getCatalogueSize() {
  const { data } = await http.get("/catalogue/size");
  return data;
}

export async function getHealth() {
  const { data } = await http.get("/health");
  return data;
}

// ── admin ──────────────────────────────────────────────────────────────────
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
