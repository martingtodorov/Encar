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
const LANGS = ["bg", "ro", "en"];

if (!fs.existsSync(shell)) {
  console.error("gen-lang-html: build/index.html is missing - run the build first");
  process.exit(1);
}

const html = fs.readFileSync(shell, "utf8");

function retag(source, { lang, title, description }) {
  return source
    .replace(/<html lang="[^"]*"/, `<html lang="${lang}"`)
    .replace(/<title>[\s\S]*?<\/title>/, `<title>${title}</title>`)
    .replace(
      /<meta name="description" content="[^"]*"\s*\/?>/,
      `<meta name="description" content="${description}" />`
    );
}

LANGS.forEach((lang) => {
  const dir = path.join(build, lang);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), retag(html, MAP[lang]));
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
// Idempotent: a second run on an already patched shell must not inject the script twice.
if (!html.includes("gen-lang-html")) {
  fs.writeFileSync(shell, html.replace("</title>", `</title>${runtime}`));
}

console.log(`gen-lang-html: wrote ${LANGS.map((l) => `build/${l}/index.html`).join(", ")}`);
