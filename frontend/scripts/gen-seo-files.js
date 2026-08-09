/* Writes robots.txt with an ABSOLUTE Sitemap: URL for whichever host this build is for.
 *
 * The sitemap itself is served DYNAMICALLY by the FastAPI backend (see server.py's
 * /sitemap.xml, /sitemap-static.xml, /sitemap-models.xml and /sitemap-listings-N.xml).
 * A static build-time file could never keep up with 146k listings and would go stale
 * within an hour of the next Encar sync.
 *
 * robots.txt still lives here because the sitemap protocol needs an absolute URL in the
 * Sitemap: directive and static files in public/ cannot read env vars at request time.
 *
 * Set REACT_APP_SITE_URL to the public domain; it falls back to REACT_APP_BACKEND_URL, which
 * is the origin that serves the app in the preview environment.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PUBLIC = path.join(ROOT, "public");

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

// A stale static sitemap.xml from an older build shadows the backend's dynamic one on
// disk (nginx proxies /sitemap*.xml, but a lingering file in public/ is confusing).
const stale = path.join(PUBLIC, "sitemap.xml");
if (fs.existsSync(stale)) fs.unlinkSync(stale);

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

console.log(`gen-seo-files: wrote robots.txt for ${origin} (sitemap.xml is served by the backend)`);
