#!/usr/bin/env node
/**
 * Writes public/robots.txt and public/sitemap.xml.
 *
 * The sitemap needs absolute URLs, and static files in public/ cannot read env vars at
 * runtime, so they are generated. Re-run after pointing SITE_URL at the real domain:
 *   node scripts/gen-seo.js
 */
const fs = require("fs");
const path = require("path");

require("dotenv").config({ path: path.join(__dirname, "..", ".env") });

const site = (process.env.REACT_APP_SITE_URL || process.env.REACT_APP_BACKEND_URL || "")
  .trim()
  .replace(/\/$/, "");

if (!site) {
  console.error("gen-seo: no REACT_APP_SITE_URL or REACT_APP_BACKEND_URL set");
  process.exit(1);
}

const LANGS = ["bg", "ro", "en"];
// Only pages worth indexing: account, login and admin are private.
const PAGES = [
  { path: "", priority: "1.0", changefreq: "hourly" },
  { path: "/how-it-works", priority: "0.6", changefreq: "monthly" },
];

const today = new Date().toISOString().slice(0, 10);

const urls = PAGES.flatMap((page) =>
  LANGS.map((lang) => {
    const loc = `${site}/${lang}${page.path}`;
    const alts = LANGS.map(
      (l) => `    <xhtml:link rel="alternate" hreflang="${l}" href="${site}/${l}${page.path}"/>`
    ).join("\n");
    return `  <url>
    <loc>${loc}</loc>
${alts}
    <lastmod>${today}</lastmod>
    <changefreq>${page.changefreq}</changefreq>
    <priority>${page.priority}</priority>
  </url>`;
  })
);

const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls.join("\n")}
</urlset>
`;

const robots = `User-agent: *
Allow: /
Disallow: /*/login
Disallow: /*/account
Disallow: /*/admin
Disallow: /*/saved
Disallow: /*/searches

Sitemap: ${site}/sitemap.xml
`;

const out = path.join(__dirname, "..", "public");
fs.writeFileSync(path.join(out, "sitemap.xml"), sitemap);
fs.writeFileSync(path.join(out, "robots.txt"), robots);
console.log(`gen-seo: wrote robots.txt and sitemap.xml for ${site}`);
