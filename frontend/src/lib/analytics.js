/**
 * Third-party statistics, loaded ONLY after the visitor has agreed to the statistics
 * category - and only when an id is actually configured.
 *
 * The GA4 measurement id is owner-editable in Admin -> Pages -> Company (`ga_id`) and
 * arrives through the CMS `/cms/site` response, so switching analytics on no longer
 * requires a rebuild. `REACT_APP_GA_ID` is honoured as a fallback for local dev.
 * The consent gate and Google's own Consent Mode defaults (everything DENIED before a
 * decision) are in place first — switching it on must never mean shipping a tracker
 * that fires before the banner.
 */
let gaId = process.env.REACT_APP_GA_ID || "";
let mounted = false;
let lastGranted = null;

/** AppContext calls this the moment the CMS company details load or change. */
export function configureAnalytics(nextId) {
  const clean = String(nextId || "").trim();
  if (clean === gaId) return;
  gaId = clean;
  // Re-emit the current consent state now that we know an id exists (or has changed).
  if (lastGranted !== null) syncAnalytics(lastGranted);
}

function pushConsentState(granted) {
  window.dataLayer = window.dataLayer || [];
  function gtag() {
    window.dataLayer.push(arguments);
  }
  window.gtag = window.gtag || gtag;
  window.gtag("consent", "update", {
    analytics_storage: granted ? "granted" : "denied",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
  });
}

/** Called whenever the decision changes. `granted` is the statistics category. */
export function syncAnalytics(granted) {
  lastGranted = granted;
  if (!gaId) return;
  if (!granted) {
    pushConsentState(false);
    return;
  }
  pushConsentState(true);
  if (mounted) return;
  mounted = true;
  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(gaId)}`;
  document.head.appendChild(s);
  window.gtag("js", new Date());
  // IP anonymisation is the default in GA4; no cross-site signals, no ad features.
  window.gtag("config", gaId, { anonymize_ip: true, allow_google_signals: false });
}

export const analyticsConfigured = () => !!gaId;
