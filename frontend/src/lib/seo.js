import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { LANGS } from "@/i18n";

/**
 * Per-page SEO head, written straight into the document.
 *
 * Each language has its own address (/bg, /ro, /en), so every page needs a canonical
 * URL and hreflang alternates pointing at its siblings - that is what lets Google index
 * all three versions instead of treating two of them as duplicates.
 *
 * Nothing public is ever blocked from crawling. Private pages (an account, a payment
 * receipt) carry a `noindex` META tag instead of a robots.txt rule: a Disallow stops a
 * crawler from even LOOKING, which also stops it from seeing the noindex, and it leaks the
 * URL shape to anyone who reads robots.txt.
 */

const SITE_NAME = "Encar Europe";
const OG_LOCALE = { bg: "bg_BG", ro: "ro_RO", en: "en_GB" };

function upsert(selector, make) {
  let el = document.head.querySelector(selector);
  if (!el) {
    el = make();
    document.head.appendChild(el);
  }
  return el;
}

function meta(name, content) {
  const el = upsert(`meta[name="${name}"]`, () => {
    const m = document.createElement("meta");
    m.setAttribute("name", name);
    return m;
  });
  el.setAttribute("content", content);
}

function property(prop, content) {
  const el = upsert(`meta[property="${prop}"]`, () => {
    const m = document.createElement("meta");
    m.setAttribute("property", prop);
    return m;
  });
  el.setAttribute("content", content);
}

function link(rel, hreflang, href) {
  const sel = hreflang ? `link[rel="${rel}"][hreflang="${hreflang}"]` : `link[rel="${rel}"]`;
  const el = upsert(sel, () => {
    const l = document.createElement("link");
    l.setAttribute("rel", rel);
    if (hreflang) l.setAttribute("hreflang", hreflang);
    return l;
  });
  el.setAttribute("href", href);
}

/** Strip the language prefix so the same page can be addressed in every language.
 *  A two-letter first segment that is not one of ours (e.g. /xx/saved) is a mistyped
 *  language, not a page, so it is dropped rather than carried into the redirect. */
export function stripLang(pathname) {
  const codes = LANGS.map((l) => l.code);
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length && (codes.includes(parts[0]) || /^[a-z]{2}$/i.test(parts[0]))) parts.shift();
  return parts.length ? `/${parts.join("/")}` : "";
}

export function useSeo({ lang, title, description, image, noindex = false }) {
  const { pathname } = useLocation();

  useEffect(() => {
    if (title) document.title = title;
    if (description) meta("description", description);

    const origin = window.location.origin;
    const rest = stripLang(pathname);
    const self = `${origin}/${lang}${rest}`;
    // og.png is our logo on the brand plate at 1200x630 — a square app icon previews as a
    // cropped blob in a chat list. A page with a picture of its own (a car, the route map)
    // passes it in.
    const picture = image || `${origin}/og.png`;

    // Private pages are kept out of the index, but never out of a crawler's reach.
    meta("robots", noindex ? "noindex, nofollow" : "index, follow, max-image-preview:large");

    link("canonical", null, self);
    LANGS.forEach((l) => link("alternate", l.code, `${origin}/${l.code}${rest}`));
    link("alternate", "x-default", `${origin}/en${rest}`);

    property("og:site_name", SITE_NAME);
    property("og:title", title || document.title);
    property("og:url", self);
    property("og:type", "website");
    property("og:image", picture);
    property("og:image:width", "1200");
    property("og:image:height", "630");
    property("og:locale", OG_LOCALE[lang] || OG_LOCALE.en);
    if (description) property("og:description", description);

    meta("twitter:card", "summary_large_image");
    meta("twitter:title", title || document.title);
    meta("twitter:image", picture);
    if (description) meta("twitter:description", description);
  }, [lang, title, description, image, noindex, pathname]);
}

/**
 * Structured data. Google reads this to show a car as a rich result with its price and
 * mileage, which a plain page cannot earn on its own.
 */
export function useJsonLd(data, id = "page-jsonld") {
  useEffect(() => {
    const existing = document.getElementById(id);
    if (!data) {
      if (existing) existing.remove();
      return undefined;
    }
    const script = existing || document.createElement("script");
    script.id = id;
    script.type = "application/ld+json";
    script.textContent = JSON.stringify(data);
    if (!existing) document.head.appendChild(script);
    return () => {
      const node = document.getElementById(id);
      if (node) node.remove();
    };
  }, [JSON.stringify(data || null), id]);
}
