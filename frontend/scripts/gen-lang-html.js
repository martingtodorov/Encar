#!/usr/bin/env node
/**
 * Postbuild: make /bg and /ro serve their own translated <title> and description.
 *
 * The app is a CRA bundle, so every route is served the SAME index.html and the per-page tags
 * are written by lib/seo.js AFTER React boots. A browser and Googlebot see the translation;
 * anything that reads the raw HTML without running JS (Bing, chat previews, SEO auditors) saw
 * the English default on /bg and /ro. Two things fix that:
 *
 * 1. `build/<lang>/index.html` — a copy with the language's own title, description and
 *    <html lang>, served directly by nginx (`try_files $uri $uri/index.html /index.html`).
 *    That covers the language landing pages, which are the URLs in the sitemap.
 * 2. A tiny inline script injected into `build/index.html`, which patches the title,
 *    description and <html lang> from the URL's first segment before the bundle loads. That
 *    covers every DEEPER route (/bg/car/123, /ro/track) for anything that runs JS.
 *
 * Copy lives in scripts/seo-landing.json — one source for both.
 */
const fs = require("fs");
const path = require("path");

const build = path.join(__dirname, "..", "build");
const shell = path.join(build, "index.html");
const MAP = require("./seo-landing.json");
const LANGS = ["bg", "ro", "pl", "en"];

// The absolute site URL, because an og:image must not be relative. CRA only loads .env for the
// bundle, so this postbuild script reads it itself.
function siteUrl() {
  if (process.env.REACT_APP_SITE_URL) return process.env.REACT_APP_SITE_URL.replace(/\/$/, "");
  try {
    const env = fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8");
    const hit = env.match(/^REACT_APP_SITE_URL=(.*)$/m);
    if (hit) return hit[1].trim().replace(/^["']|["']$/g, "").replace(/\/$/, "");
  } catch (e) {
    /* no .env in this build environment */
  }
  return "";
}

const SITE = siteUrl();

// Copy for the pages that are worth their own preview. The route map is rendered by the
// backend from OpenStreetMap tiles (backend/mapshot.py); everything else previews with the logo.
const ROUTES = {
  track: {
    image: "/api/map/track.png",
    bg: ["Проследи автомобила си · Encar Europe",
         "Виж къде е контейнерът с колата ти — от терминала в Корея до доставката."],
    ro: ["Urmărește mașina ta · Encar Europe",
         "Vezi unde este containerul mașinii tale — din terminalul din Coreea până la livrare."],
    pl: ["Śledź swój samochód · Encar Europe",
         "Sprawdź, gdzie jest kontener z Twoim samochodem — od terminalu w Korei do dostawy."],
    en: ["Track my vehicle · Encar Europe",
         "See where your car's container is — from the terminal in Korea to delivery."],
  },
};

if (!fs.existsSync(shell)) {
  console.error("gen-lang-html: build/index.html is missing - run the build first");
  process.exit(1);
}

/**
 * CRA leaves `%REACT_APP_SITE_URL%` in index.html VERBATIM when the variable is not defined at
 * build time, and that is exactly what shipped to encareurope.com once: every og:image pointed
 * at "%REACT_APP_SITE_URL%/og.png", so Facebook could not fetch a picture for any page. The
 * placeholder is resolved here as well as by CRA, and if there is genuinely no site URL to use
 * the tags are REMOVED — a missing preview picture is recoverable, a malformed one is not.
 */
function resolve(source) {
  if (!source.includes("%REACT_APP_SITE_URL%")) return source;
  if (SITE) return source.split("%REACT_APP_SITE_URL%").join(SITE);
  console.warn(
    "gen-lang-html: REACT_APP_SITE_URL is not set, so og:image tags are being dropped." +
      " Set it in the build environment (deploy_frontend.yml passes it) to get link previews."
  );
  return source.replace(
    /\s*<meta (?:property|name)="(?:og:image[a-z:_]*|twitter:image)" content="[^"]*%REACT_APP_SITE_URL%[^"]*"\s*\/?>/g,
    ""
  );
}

const html = resolve(fs.readFileSync(shell, "utf8"));

function retag(source, { lang, title, description }) {
  return source
    .replace(/<html lang="[^"]*"/, `<html lang="${lang}"`)
    .replace(/<title>[\s\S]*?<\/title>/, `<title>${title}</title>`)
    .replace(
      /<meta name="description" content="[^"]*"\s*\/?>/,
      `<meta name="description" content="${description}" />`
    )
    .replace(
      /<meta property="og:title" content="[^"]*"\s*\/?>/,
      `<meta property="og:title" content="${title}" />`
    )
    .replace(
      /<meta property="og:description" content="[^"]*"\s*\/?>/,
      `<meta property="og:description" content="${description}" />`
    )
    .replace(
      /<meta name="twitter:title" content="[^"]*"\s*\/?>/,
      `<meta name="twitter:title" content="${title}" />`
    )
    .replace(
      /<meta name="twitter:description" content="[^"]*"\s*\/?>/,
      `<meta name="twitter:description" content="${description}" />`
    );
}

// A page whose preview picture is NOT the logo: every og:image/twitter:image is repointed.
function repoint(source, image) {
  return source.replace(
    /content="[^"]*\/og\.png"/g,
    `content="${image}"`
  );
}

LANGS.forEach((lang) => {
  const dir = path.join(build, lang);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), retag(html, MAP[lang]));

  // /bg/track and friends get their own file, so a link pasted into a chat previews with the
  // route map instead of the site's logo. nginx serves it through `try_files $uri/index.html`.
  Object.entries(ROUTES).forEach(([route, copy]) => {
    const [title, description] = copy[lang];
    const page = repoint(retag(html, { lang, title, description }), `${SITE}${copy.image}`);
    const sub = path.join(dir, route);
    fs.mkdirSync(sub, { recursive: true });
    fs.writeFileSync(path.join(sub, "index.html"), page);
  });
});

const runtime = `<script>/*gen-lang-html*/(function(){var M=${JSON.stringify(
  Object.fromEntries(LANGS.map((l) => [l, [MAP[l].title, MAP[l].description]]))
)};var l=(location.pathname.split("/")[1]||"").toLowerCase();var m=M[l];if(!m)return;document.documentElement.lang=l;document.title=m[0];var d=document.querySelector('meta[name="description"]');if(d)d.setAttribute("content",m[1]);})();</script>`;

// Injected after </title> rather than at a comment marker: the build MINIFIES index.html and
// strips HTML comments, so a placeholder never survives to build/.
if (!/<\/title>/.test(html)) {
  console.error("gen-lang-html: build/index.html has no <title> to anchor to");
  process.exit(1);
}
// Idempotent: a second run on an already patched shell must not inject the script twice — but
// the shell is written EITHER WAY, so a resolved %REACT_APP_SITE_URL% always lands on disk.
fs.writeFileSync(
  shell,
  html.includes("gen-lang-html") ? html : html.replace("</title>", `</title>${runtime}`)
);

console.log(`gen-lang-html: wrote ${LANGS.map((l) => `build/${l}/index.html`).join(", ")}`);
