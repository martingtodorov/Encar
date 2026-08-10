/**
 * Who runs this site. One place, because it appears in the footer, in every legal
 * document and in the emails we send.
 *
 * `address` and `vat` are left empty on purpose: the owner must paste the exact
 * registered address (and VAT number, if the company is VAT-registered) here. Anything
 * blank is simply not rendered rather than shown as a guess.
 */
export const COMPANY = {
  name: "Auto&Bid LTD",
  eik: "208833206",
  email: "contact@encareurope.com",
  phone: "+359 88 671 7074",
  address: "гр. София 1766, район Витоша, ул. „Бяла река“ 12, бл. 10, ап. 3, България",
  vat: "",
  site: "encareurope.com",
  // Owner-editable in Admin -> Pages -> Company. Everything below is optional: blank
  // values are simply not rendered anywhere.
  //  * ga_id — a GA4 measurement id like "G-XXXXXX". When present, analytics.js loads
  //    Google's tag once the visitor accepts the statistics category.
  //  * response_hours — "24" or "2 business hours", printed in the footer as a promise.
  //  * geo_lat/geo_lng and google_maps_url — used by the AutoDealer JSON-LD on the home
  //    page so Google can attach a knowledge panel and a directions link.
  ga_id: "",
  response_hours: "",
  geo_lat: "",
  geo_lng: "",
  google_maps_url: "",
};

/** The owner can edit these in Admin -> Pages. The object is mutated in place (rather than
 *  replaced) because the legal and help documents read it while they build their copy. */
export function setCompany(overrides) {
  if (!overrides) return COMPANY;
  Object.keys(overrides).forEach((k) => {
    if (k in COMPANY && overrides[k]) COMPANY[k] = overrides[k];
  });
  return COMPANY;
}

export const LEGAL_LINKS = [
  { to: "/terms", key: "legalTerms" },
  { to: "/privacy", key: "legalPrivacy" },
  { to: "/cookies", key: "legalCookies" },
  { to: "/contact", key: "legalContact" },
];

/** The footer sitemap, three columns wide. Column titles are i18n keys like the links. */
export const FOOTER_COLUMNS = [
  {
    key: "footerExplore",
    links: [
      { to: "/", key: "navSearch" },
      { to: "/saved", key: "savedCars" },
      { to: "/searches", key: "savedSearches" },
      { to: "/track", key: "navTrack" },
    ],
  },
  {
    key: "footerHelp",
    links: [
      { to: "/how-it-works", key: "navHowItWorks" },
      { to: "/fees", key: "navFees" },
      { to: "/contact", key: "legalContact" },
      { to: "/sitemap", key: "navSitemap", langs: ["bg", "en"] },
    ],
  },
  {
    key: "footerAccountCol",
    links: [
      { to: "/login", key: "login" },
      { to: "/login?mode=register", key: "register" },
      { to: "/terms", key: "legalTerms" },
      { to: "/privacy", key: "legalPrivacy" },
      { to: "/cookies", key: "legalCookies" },
    ],
  },
];
