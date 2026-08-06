/**
 * A copy of the owner's editable copy, kept in localStorage.
 *
 * The API answer cannot arrive before the first paint, so without this the built-in
 * headline (or the built-in legal text) is what a returning visitor sees for a split second
 * on every refresh. Seeding React's state from this cache means the owner's own words are
 * in the very first render; the fetch that follows only corrects them if they changed.
 */
const LS_SITE = "encar.cms.site";
const LS_PAGES = "encar.cms.pages";

const read = (key) => {
  try {
    return JSON.parse(localStorage.getItem(key) || "{}");
  } catch (e) {
    return {};
  }
};

const write = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    /* a full or blocked storage is not worth failing a page render over */
  }
};

export const EMPTY_SITE = { company: {}, seo: {}, hero: {} };

export function cachedSite(lang) {
  const hit = read(LS_SITE)[lang];
  return hit ? { ...EMPTY_SITE, ...hit } : null;
}

export function rememberSite(lang, data) {
  const all = read(LS_SITE);
  all[lang] = {
    company: data.company || {},
    seo: data.seo || {},
    hero: data.hero || {},
  };
  write(LS_SITE, all);
}

export function cachedPageHtml(slug, lang) {
  const hit = read(LS_PAGES)[`${slug}|${lang}`];
  return typeof hit === "string" ? hit : "";
}

export function rememberPageHtml(slug, lang, html) {
  const all = read(LS_PAGES);
  all[`${slug}|${lang}`] = html || "";
  write(LS_PAGES, all);
}
