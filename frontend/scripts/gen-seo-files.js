/* Writes robots.txt and sitemap.xml with ABSOLUTE URLs for whichever host this build is for.
 *
 * The sitemap protocol does not accept a relative Sitemap: directive or relative <loc>
 * entries, and the preview host is not the production host — so these two files cannot be
 * checked in as static text. Run before every build (see the prebuild script).
 *
 * Set REACT_APP_SITE_URL to the public domain; it falls back to REACT_APP_BACKEND_URL, which
 * is the origin that serves the app in the preview environment.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PUBLIC = path.join(ROOT, "public");
const LANGS = ["bg", "ro", "en"];

// Public pages only. The account, admin, saved-list, purchases and payment pages are private:
// they carry a noindex meta tag and have no business in a sitemap.
const PAGES = [
  { at: "", changefreq: "hourly", priority: "1.0" },
  { at: "/how-it-works", changefreq: "monthly", priority: "0.8" },
  { at: "/faq", changefreq: "monthly", priority: "0.7" },
  { at: "/fees", changefreq: "monthly", priority: "0.7" },
  { at: "/track", changefreq: "weekly", priority: "0.6" },
  { at: "/contact", changefreq: "yearly", priority: "0.5" },
  { at: "/terms", changefreq: "yearly", priority: "0.3" },
  { at: "/privacy", changefreq: "yearly", priority: "0.3" },
  { at: "/cookies", changefreq: "yearly", priority: "0.3" },
];

function env(key) {
  const file = path.join(ROOT, ".env");
  if (!fs.existsSync(file)) return "";
  const line = fs
    .readFileSync(file, "utf8")
    .split("\n")
    .find((l) => l.startsWith(`${key}=`));
  return line ? line.slice(key.length + 1).trim() : "";
}

const origin = (
  process.env.REACT_APP_SITE_URL ||
  env("REACT_APP_SITE_URL") ||
  process.env.REACT_APP_BACKEND_URL ||
  env("REACT_APP_BACKEND_URL")
).replace(/\/+$/, "");

if (!origin) {
  console.error("gen-seo-files: no REACT_APP_SITE_URL or REACT_APP_BACKEND_URL, skipping");
  process.exit(0);
}

const today = new Date().toISOString().slice(0, 10);

const urls = PAGES.flatMap(({ at, changefreq, priority }) =>
  LANGS.map((lang) => {
    const alternates = LANGS.map(
      (l) => `    <xhtml:link rel="alternate" hreflang="${l}" href="${origin}/${l}${at}"/>`
    ).join("\n");
    return [
      "  <url>",
      `    <loc>${origin}/${lang}${at}</loc>`,
      alternates,
      `    <xhtml:link rel="alternate" hreflang="x-default" href="${origin}/en${at}"/>`,
      `    <lastmod>${today}</lastmod>`,
      `    <changefreq>${changefreq}</changefreq>`,
      `    <priority>${priority}</priority>`,
      "  </url>",
    ].join("\n");
  })
);

fs.writeFileSync(
  path.join(PUBLIC, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls.join("\n")}
</urlset>
`
);

fs.writeFileSync(
  path.join(PUBLIC, "robots.txt"),
  `User-agent: *
Allow: /

# Nothing public is blocked. The account, admin and payment pages carry a noindex meta tag
# instead of a Disallow: a crawler that is not allowed to fetch a page can never see the
# noindex on it, and a robots.txt full of private paths is a map of them.

Sitemap: ${origin}/sitemap.xml
`
);

console.log(`gen-seo-files: wrote sitemap.xml (${urls.length} urls) and robots.txt for ${origin}`);
