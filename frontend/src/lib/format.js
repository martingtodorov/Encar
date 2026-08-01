// Locale-correct money and number formatting.
// Prices are computed in EUR by the backend; BGN/RON are display conversions.

const LOCALE = { bg: "bg-BG", ro: "ro-RO", en: "en-GB" };

export function convert(eur, currency, rates) {
  if (!Number.isFinite(eur)) return null;
  if (currency === "BGN") return eur * (rates?.eur_bgn ?? 1.95583);
  if (currency === "RON") return eur * (rates?.eur_ron ?? 4.977);
  return eur;
}

export function formatMoney(eur, currency, lang, rates, opts = {}) {
  const v = convert(eur, currency, rates);
  if (v === null) return "\u2014";
  try {
    return new Intl.NumberFormat(LOCALE[lang] || "bg-BG", {
      style: "currency",
      currency,
      maximumFractionDigits: opts.decimals ?? 0,
      minimumFractionDigits: opts.decimals ?? 0,
    }).format(v);
  } catch (e) {
    return `${Math.round(v)} ${currency}`;
  }
}

export function formatNumber(n, lang) {
  if (!Number.isFinite(n)) return "\u2014";
  try {
    return new Intl.NumberFormat(LOCALE[lang] || "bg-BG").format(n);
  } catch (e) {
    return String(n);
  }
}

export function formatMileage(km, lang, unit = "km") {
  if (!Number.isFinite(km)) return "\u2014";
  return `${formatNumber(km, lang)} ${unit}`;
}

// Encar stores registration as YYYYMM (e.g. 201912)
export function formatYearMonth(ym, formYear) {
  if (!ym) return formYear ? String(formYear) : "\u2014";
  const y = Math.floor(ym / 100);
  const m = ym % 100;
  return m >= 1 && m <= 12 ? `${String(m).padStart(2, "0")}/${y}` : String(y);
}

export function carTitle(car) {
  const parts = [
    car.manufacturer_t || car.manufacturer,
    car.model_t || car.model,
  ].filter(Boolean);
  return parts.join(" ");
}

export function carSubtitle(car) {
  return car.badge_t || car.badge || "";
}
