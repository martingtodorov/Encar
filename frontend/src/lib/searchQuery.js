// The whole search lives in the query string, which makes any result set a shareable
// link, survives Back, and lets a saved search be nothing more than a stored URL.

export const LIST_SEP = "~";

export const EMPTY = {
  fuels: [],
  regions: [],
  transmissions: [],
  year_min: "",
  year_max: "",
  mileage_min: "",
  mileage_max: "",
  price_min: "",
  price_max: "",
  only_inspection: false,
  only_record: false,
  only_diagnosed: false,
};

export const EMPTY_TAX = { make: "", model: "", badge: "", badgeDetail: "" };

// Which slug dimension each query key belongs to. Anything not listed is a plain
// number or flag and needs no translation.
const DIM = { make: "make", model: "model", badge: "badge", badgeDetail: "badge_detail",
              fuels: "fuel", regions: "region" };

/**
 * `slugFor(dim, value)` turns an upstream Korean value into its English slug. Without it
 * (or for a value we have no slug for) the raw value is written, which still works.
 */
export function stateToParams({ filters, tax, sort, page }, slugFor) {
  const slug = (key, v) => (slugFor && DIM[key] ? slugFor(DIM[key], v) || v : v);
  const p = new URLSearchParams();
  Object.entries(tax).forEach(([k, v]) => {
    if (v) p.set(k, slug(k, v));
  });
  Object.entries(filters).forEach(([k, v]) => {
    if (Array.isArray(v)) {
      if (v.length) p.set(k, v.map((x) => slug(k, x)).join(LIST_SEP));
    } else if (typeof v === "boolean") {
      if (v) p.set(k, "1");
    } else if (v !== "" && v !== null && v !== undefined) {
      p.set(k, String(v));
    }
  });
  if (sort) p.set("sort", sort);
  if (page > 1) p.set("page", String(page));
  return p;
}

export function paramsToState(p) {
  const tax = { ...EMPTY_TAX };
  Object.keys(EMPTY_TAX).forEach((k) => {
    if (p.get(k)) tax[k] = p.get(k);
  });

  const filters = { ...EMPTY };
  Object.entries(EMPTY).forEach(([k, fallback]) => {
    const raw = p.get(k);
    if (raw === null) return;
    if (Array.isArray(fallback)) filters[k] = raw.split(LIST_SEP).filter(Boolean);
    else if (typeof fallback === "boolean") filters[k] = raw === "1";
    else filters[k] = raw;
  });

  return {
    filters,
    tax,
    sort: p.get("sort") || "",
    page: Math.max(1, parseInt(p.get("page") || "1", 10) || 1),
  };
}

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

/** Search-endpoint body for a piece of search state. */
export function buildPayload({ filters, tax, sort, page }, { lang, pageSize }) {
  return {
    makes: tax.make ? [tax.make] : [],
    models: tax.model ? [tax.model] : [],
    badges: tax.badge ? [tax.badge] : [],
    badge_details: tax.badgeDetail ? [tax.badgeDetail] : [],
    fuels: filters.fuels,
    regions: filters.regions,
    transmissions: filters.transmissions,
    year_min: num(filters.year_min),
    year_max: num(filters.year_max),
    mileage_min: num(filters.mileage_min),
    mileage_max: num(filters.mileage_max),
    price_min: num(filters.price_min),
    price_max: num(filters.price_max),
    only_inspection: filters.only_inspection,
    only_record: filters.only_record,
    only_diagnosed: filters.only_diagnosed,
    sort,
    page,
    page_size: pageSize,
    lang,
  };
}

/** Sort and page are deliberately dropped: a saved search reopens on page 1. */
export function savableQuery({ filters, tax }, slugFor) {
  return stateToParams({ filters, tax, sort: "", page: 1 }, slugFor).toString();
}

/** Does this URL carry anything that might be a slug needing resolution? */
export function hasResolvableTokens(p) {
  return ["make", "model", "badge", "badgeDetail", "fuels", "regions"].some((k) => !!p.get(k));
}

export function isEmptySearch(query) {
  return !String(query || "").length;
}
