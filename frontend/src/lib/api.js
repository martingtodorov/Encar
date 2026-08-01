import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const http = axios.create({ baseURL: API, timeout: 60000 });

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

export async function getHealth() {
  const { data } = await http.get("/health");
  return data;
}

export async function getQuote(priceKrw) {
  const { data } = await http.get("/pricing/quote", { params: { price_krw: priceKrw } });
  return data;
}

export default http;
