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
  (filters.colors || []).forEach((c) => parts.push(t(`colour_${c}`) || c));
  (filters.regions || []).forEach((r) => parts.push(label(facets?.regions, r)));

  // The filter inputs hand us STRINGS, and Number.isFinite("40000") is false, so the
  // formatters answered with a dash: the heading read "≤ — км · ≤ —" instead of the range
  // the visitor had just typed. Every bound is coerced before it is formatted.
  const num = (v) => (v === 0 || (v && String(v).trim() !== "") ? Number(v) : null);
  const span = (lo, hi, fmt, unit = "") => {
    const a = num(lo) === null || Number.isNaN(num(lo)) ? "" : fmt(num(lo));
    const b = num(hi) === null || Number.isNaN(num(hi)) ? "" : fmt(num(hi));
    if (!a && !b) return "";
    const core = a && b ? `${a}\u2013${b}` : a ? `${a}+` : `\u2264 ${b}`;
    return unit ? `${core} ${unit}` : core;
  };
  const push = (text) => text && parts.push(text);

  push(span(filters.year_min, filters.year_max, (n) => String(n)));
  push(span(filters.price_min, filters.price_max,
            (n) => formatMoney(n, currency, lang, rates)));
  push(span(filters.mileage_min, filters.mileage_max,
            (n) => formatNumber(n, lang), t("km")));

  if (filters.only_inspection) parts.push(t("onlyInspection"));
  if (filters.only_record) parts.push(t("onlyRecord"));
  if (filters.only_diagnosed) parts.push(t("onlyDiagnosed"));

  return parts.length ? parts.join(" \u00b7 ") : t("allCars");
}

export default describeSearch;
