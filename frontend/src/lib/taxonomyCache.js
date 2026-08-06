/**
 * The dropdown lists, remembered for the length of the visit.
 *
 * Coming back from a car, `TaxonomySelects` remounts with empty lists, and the applied-filter
 * chips fall back to the RAW Korean value until `/meta/taxonomy` answers — a second or two of
 * Korean model names on every Back. Seeding the state from here means the labels are correct
 * in the FIRST render and the request that follows only confirms them.
 *
 * In memory on purpose: a Back inside the app is a client-side navigation, so the module
 * survives it, and a full reload should ask the server again anyway.
 */
const mem = new Map();

const keyOf = ({ level, lang, make = "", model = "", badge = "" }) =>
  `${level}|${lang}|${make}|${model}|${badge}`;

export function cachedTaxonomy(query) {
  return mem.get(keyOf(query)) || null;
}

export function rememberTaxonomy(query, items) {
  mem.set(keyOf(query), items);
}
