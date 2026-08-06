/**
 * Third-party statistics, loaded ONLY after the visitor has agreed to the statistics
 * category - and only when an id is actually configured.
 *
 * Nothing here runs today: `REACT_APP_GA_ID` is unset, so `mount()` returns immediately and
 * no Google script, cookie or request exists. The owner plans GA4, so the consent gate and
 * Google's own Consent Mode defaults (everything DENIED before a decision) are in place
 * first - switching it on must never mean shipping a tracker that fires before the banner.
 */
const GA_ID = process.env.REACT_APP_GA_ID || "";

let mounted = false;

function pushConsentState(granted) {
  window.dataLayer = window.dataLayer || [];
  // eslint-disable-next-line prefer-rest-params
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
  if (!GA_ID) return;
  if (!granted) {
    pushConsentState(false);
    return;
  }
  pushConsentState(true);
  if (mounted) return;
  mounted = true;
  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_ID)}`;
  document.head.appendChild(s);
  window.gtag("js", new Date());
  // IP anonymisation is the default in GA4; no cross-site signals, no ad features.
  window.gtag("config", GA_ID, { anonymize_ip: true, allow_google_signals: false });
}

export const analyticsConfigured = () => !!GA_ID;
