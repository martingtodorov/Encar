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

  // The SLUG is part of the shared address: the car page canonicalises /bg/car/42328978 to
  // /bg/car/42328978/mercedes-benz-c-class-w205, so that longer form is what a buyer copies
  // out of the address bar or hands to the Share sheet. Without the optional segment here it
  // fell through to the plain CRA shell and every chat preview showed the site logo and the
  // generic homepage title instead of the car.
  const CAR = /^\/(bg|ro|pl|en)\/car\/([^/?]+)(?:\/([^/?]+))?\/?$/;
  app.get(CAR, (req, res, next) => {
    if (!CRAWLER.test(req.headers["user-agent"] || "")) return next();
    const [, lang, id, slug] = req.url.split("?")[0].match(CAR);
    // The slug travels with it so og:url and canonical name the EXACT address that was
    // shared — Apple's fetcher re-checks that they agree before it draws the rich card.
    const tail = slug ? `&slug=${encodeURIComponent(slug)}` : "";
    res.redirect(302, `${api}/api/share/car/${encodeURIComponent(id)}?lang=${lang}${tail}`);
  });

  app.get(/^\/(bg|ro|pl|en)\/track\/?$/, (req, res, next) => {
    if (!CRAWLER.test(req.headers["user-agent"] || "")) return next();
    const [, lang] = req.url.split("?")[0].match(/^\/(bg|ro|pl|en)\/track\/?$/);
    const query = req.url.includes("?") ? `&${req.url.split("?")[1]}` : "";
    res.redirect(302, `${api}/api/share/track?lang=${lang}${query}`);
  });
};
