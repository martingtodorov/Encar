// Locale-correct money and number formatting.
// Prices are computed in EUR by the backend; RON and PLN are display conversions.

const LOCALE = { bg: "bg-BG", ro: "ro-RO", pl: "pl-PL", en: "en-GB" };

export function convert(eur, currency, rates) {
  if (!Number.isFinite(eur)) return null;
  if (currency === "RON") return eur * (rates?.eur_ron ?? 4.977);
  if (currency === "PLN") return eur * (rates?.eur_pln ?? 4.35);
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

/**
 * Encar spells a generation into the model name — "Santa Fe DM (2013-2016)". That range is
 * the model's identity upstream, so it stays in filters, slugs and the taxonomy; it is only
 * dropped where the car itself is being named, because the car has one year, not a range.
 */
/**
 * A model name as a TITLE should read it: no brackets, no marketing prefix.
 *
 * The catalogue carries the production years and the factory's generation code in brackets
 * ("Cayenne (2019-)", "Cayenne (PO536)", "5 Series (F10)"), and Korean marketing prefixes a
 * facelift with "올 뉴", which the English cache renders as "All New Sorento" / "The All-New
 * Niro". None of that means anything to somebody reading a search result or a chat preview, and
 * all of it crowds out the trim in a title that gets truncated. The page's own H1 keeps the
 * years — only titles are cleaned.
 */
export function titleModel(text) {
  return String(text || "")
    .replace(/\s*[(（][^)）]*[)）]/g, "")
    .replace(/^\s*(the\s+)?all[\s-]*new\s+/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function stripGenerationYears(text) {
  return String(text || "")
    .replace(/[(（]\s*\d{4}\s*[-–~]\s*\d{0,4}\s*[)）]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
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
