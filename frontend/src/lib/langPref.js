/**
 * Where the language decision comes from.
 *
 * Order of authority: the account (server) → the visitor's OWN pick (remembered here,
 * forever, until they pick another one) → the IP country (`/api/geo/lang`).
 *
 * The URL prefix is NOT a preference. It used to be written to `encar.lang` on the first
 * render of every visit, which meant the very first address a shopper happened to land on
 * — including a link shared from someone else's phone in another language — froze their
 * language for good and switched the IP rule off. Only `switchLang` writes here now.
 */
const LS_LANG = "encar.lang";
const LS_EXPLICIT = "encar.lang.explicit";
const LS_GEO = "encar.geolang";

// The country behind an IP does not change while someone browses. Cached so a shopper
// walking twenty pages costs one lookup, not twenty.
const GEO_TTL = 6 * 60 * 60 * 1000;

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;              // private mode: nothing was ever stored
  }
}

/**
 * The language the visitor picked themselves, or null.
 *
 * Also migrates away the old writes: a stored language with no `explicit` marker next to
 * it was put there by the URL sync, not by a person, so it is dropped and the IP rule
 * takes over again.
 */
export function readLangPref() {
  const stored = read(LS_LANG);
  if (!stored) return null;
  if (read(LS_EXPLICIT) === "1") return stored;
  try {
    localStorage.removeItem(LS_LANG);
  } catch { /* nothing to clean */ }
  return null;
}

/** Remembers an explicit pick from the switcher. No expiry: it is their choice. */
export function saveLangPref(code) {
  try {
    localStorage.setItem(LS_LANG, code);
    localStorage.setItem(LS_EXPLICIT, "1");
  } catch { /* private mode: the pick lasts for this tab only */ }
}

/** The last IP answer, if it is still fresh. */
export function cachedGeoLang() {
  try {
    const raw = read(LS_GEO);
    if (!raw) return null;
    const { lang, at } = JSON.parse(raw);
    if (!at || Date.now() - at > GEO_TTL) return null;
    return lang || null;
  } catch {
    return null;
  }
}

export function rememberGeoLang(lang) {
  try {
    localStorage.setItem(LS_GEO, JSON.stringify({ lang: lang || "", at: Date.now() }));
  } catch { /* private mode */ }
}
