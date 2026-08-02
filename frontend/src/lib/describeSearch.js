import { formatMoney, formatNumber } from "@/lib/format";

/**
 * Human name for a set of filters, used as the default title of a saved search.
 * Built from the TRANSLATED taxonomy labels, never the raw Korean values.
 */
export function describeSearch({ filters, tax, taxLabels, facets, t, lang, currency, rates }) {
  const parts = [];
  const label = (list, value) => (list || []).find((x) => x.value === value)?.label || value;

  const car = [
    taxLabels?.make || tax.make,
    taxLabels?.model || tax.model,
    taxLabels?.badge || tax.badge,
    taxLabels?.badgeDetail || tax.badgeDetail,
  ].filter(Boolean);
  if (car.length) parts.push(car.join(" "));

  (filters.fuels || []).forEach((f) => parts.push(label(facets?.fuels, f)));
  (filters.transmissions || []).forEach((tr) => parts.push(t(tr === "manual" ? "manual" : "auto")));
  (filters.regions || []).forEach((r) => parts.push(label(facets?.regions, r)));

  if (filters.year_min && filters.year_max) parts.push(`${filters.year_min}\u2013${filters.year_max}`);
  else if (filters.year_min) parts.push(`${filters.year_min}+`);
  else if (filters.year_max) parts.push(`\u2264 ${filters.year_max}`);

  const money = (v) => formatMoney(v, currency, lang, rates);
  if (filters.price_min && filters.price_max)
    parts.push(`${money(filters.price_min)}\u2013${money(filters.price_max)}`);
  else if (filters.price_max) parts.push(`\u2264 ${money(filters.price_max)}`);
  else if (filters.price_min) parts.push(`\u2265 ${money(filters.price_min)}`);

  if (filters.mileage_max)
    parts.push(`\u2264 ${formatNumber(filters.mileage_max, lang)} ${t("km")}`);

  if (filters.only_inspection) parts.push(t("onlyInspection"));
  if (filters.only_record) parts.push(t("onlyRecord"));
  if (filters.only_diagnosed) parts.push(t("onlyDiagnosed"));

  return parts.length ? parts.join(" \u00b7 ") : t("allCars");
}

export default describeSearch;
