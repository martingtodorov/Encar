/**
 * Link previews on a host we do not own the web server of.
 *
 * Messenger, Viber, WhatsApp and Facebook never run our JavaScript, so a car link can only
 * preview with the ad's own photo if the SERVER answers that URL with og:* tags. On our own
 * box nginx does that (`$encar_crawler` -> /api/share/car/{id}); on the Emergent preview host
 * only /api reaches the backend, so /bg/car/123 was always the plain CRA shell and every
 * preview fell back to the logo.
 *
 * The dev server can do the same job: a crawler asking for a car or the Track page is sent to
 * the backend's share page, which carries the picture and the title. A human is never touched.
 */
const CRAWLER = /facebookexternalhit|facebookcatalog|Facebot|Twitterbot|Slackbot|WhatsApp|Viber|TelegramBot|LinkedInBot|Discordbot|Pinterest|SkypeUriPreview|redditbot|vkShare|Applebot|Iframely|embedly|Snapchat|Instagram|Mastodon|Bluesky|Google-InspectionTool/i;

module.exports = function setupPreviewShareLinks(app) {
  const api = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  if (!api) return;

  // Sitemaps live under /api/ on the preview host (only /api/* reaches the backend),
  // but Google fetches the paths listed in robots.txt without the /api prefix. In
  // production nginx rewrites those, so mirror that in the dev server.
  app.get(/^\/sitemap(?:-[a-z]+(?:-\d+)?)?\.xml$/, (req, res) => {
    res.redirect(301, `${api}/api${req.url}`);
  });

  app.get(/^\/(bg|ro|pl|en)\/car\/([^/]+)\/?$/, (req, res, next) => {
    if (!CRAWLER.test(req.headers["user-agent"] || "")) return next();
    const [, lang, id] = req.url.split("?")[0].match(/^\/(bg|ro|pl|en)\/car\/([^/]+)\/?$/);
    res.redirect(302, `${api}/api/share/car/${encodeURIComponent(id)}?lang=${lang}`);
  });

  app.get(/^\/(bg|ro|pl|en)\/track\/?$/, (req, res, next) => {
    if (!CRAWLER.test(req.headers["user-agent"] || "")) return next();
    const [, lang] = req.url.split("?")[0].match(/^\/(bg|ro|pl|en)\/track\/?$/);
    const query = req.url.includes("?") ? `&${req.url.split("?")[1]}` : "";
    res.redirect(302, `${api}/api/share/track?lang=${lang}${query}`);
  });
};
