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
  email: "office@autoandbid.bg",
  phone: "",
  address: "",
  vat: "",
  site: "autoandbid.bg",
};

export const LEGAL_LINKS = [
  { to: "/terms", key: "legalTerms" },
  { to: "/privacy", key: "legalPrivacy" },
  { to: "/cookies", key: "legalCookies" },
  { to: "/contact", key: "legalContact" },
];
