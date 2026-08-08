/**
 * One phone format for the whole site.
 *
 * A number nobody can dial is a lost sale, and every form used to accept anything at all: a
 * local "0888..." with no country code, a number typed with the letter O, a five-digit stub.
 * Everything is normalised to E.164 (+359881234567) before it is sent or stored, and the page
 * language supplies the country code when the buyer types a national number starting with 0.
 */
const HOME_CODE = { bg: "359", ro: "40", en: "" };

/** Digits, plus a single leading +. Nothing else survives. */
export function normalisePhone(raw, lang = "bg") {
  let value = String(raw || "").trim();
  if (!value) return "";
  const plus = value.startsWith("+") || value.startsWith("00");
  value = value.replace(/^00/, "").replace(/[^\d]/g, "");
  if (!value) return "";
  if (plus) return `+${value}`;
  // A national number: 0888 123 456 in Bulgaria is +359 888 123 456.
  const code = HOME_CODE[lang] || "";
  if (value.startsWith("0") && code) return `+${code}${value.replace(/^0+/, "")}`;
  return `+${value}`;
}

/** E.164: a country code that cannot start with 0, then 7 to 14 more digits. */
export function isValidPhone(raw, lang = "bg") {
  return /^\+[1-9]\d{7,14}$/.test(normalisePhone(raw, lang));
}

/** "" when the field is fine, otherwise the translation key of the reason. */
export function phoneProblem(raw, lang = "bg", required = false) {
  const value = String(raw || "").trim();
  if (!value) return required ? "phoneRequired" : "";
  return isValidPhone(value, lang) ? "" : "phoneInvalid";
}
