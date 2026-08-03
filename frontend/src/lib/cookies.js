/**
 * Cookie helpers.
 *
 * Interest signals and tracking history live in cookies, not localStorage, because the
 * owner wants them to survive for a fixed 90 days and to be readable on any entry point.
 * Values are URI-encoded, so JSON is safe to store.
 */
const DEFAULT_DAYS = 90;

export function readCookie(name) {
  const hit = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  if (!hit) return "";
  try {
    return decodeURIComponent(hit.slice(name.length + 1));
  } catch (e) {
    return "";
  }
}

export function writeCookie(name, value, days = DEFAULT_DAYS) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString();
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie =
    `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax${secure}`;
}

export function dropCookie(name) {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

export function readJsonCookie(name, fallback) {
  const raw = readCookie(name);
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch (e) {
    return fallback;
  }
}

export function writeJsonCookie(name, value, days = DEFAULT_DAYS) {
  // A cookie has ~4KB to spend and every request carries it, so callers must keep the
  // payload small; this only guards against a runaway profile.
  const text = JSON.stringify(value);
  if (text.length > 3000) return false;
  writeCookie(name, text, days);
  return true;
}
