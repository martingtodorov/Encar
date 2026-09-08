import { useEffect, useRef } from "react";
import {
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
  useNavigationType,
  useParams,
} from "react-router-dom";
import { noteNav } from "@/lib/navDepth";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { CookieBar } from "@/components/CookieBar";
import { ScrollToTop } from "@/components/ScrollToTop";
import { SiteFooter } from "@/components/SiteFooter";
import { AdminTrafficBar } from "@/components/AdminTrafficBar";
import { InstallBanner } from "@/components/InstallBanner";
import { NotificationsPrompt } from "@/components/NotificationsPrompt";
import { NotifyConsentDialog } from "@/components/NotifyConsentDialog";
import { PwaTabBar } from "@/components/PwaTabBar";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { LANGS } from "@/i18n";
import { stripLang } from "@/lib/seo";
import { allows, onConsentChange } from "@/lib/consent";
import { syncAnalytics } from "@/lib/analytics";
import { ping, labelFor } from "@/lib/traffic";
import { getGeoLang } from "@/lib/api";
import { cachedGeoLang, readLangPref, rememberGeoLang } from "@/lib/langPref";

const CODES = LANGS.map((l) => l.code);

/**
 * Language lives in the URL, not in the browser's preference.
 *
 * Every page sits under /bg, /ro, /pl or /en so each translation has its own indexable
 * address. This layout is the single place that reads the prefix and pushes it into app
 * state; an unknown prefix (or none at all) is redirected to the visitor's language with
 * the rest of the path and the query string kept intact.
 *
 * Which language that is comes from, in order: the signed-in account, the visitor's own
 * pick from the switcher (remembered for good), then the country behind their IP.
 */
export const LangLayout = () => {
  const { lang: urlLang } = useParams();
  const { lang, setLang } = useApp();
  const { user } = useAuth();
  const { pathname, search, hash, key } = useLocation();
  const navigate = useNavigate();
  const navType = useNavigationType();
  const valid = CODES.includes(urlLang);

  // Count the steps back that are OURS to spend — see `lib/navDepth`. A language redirect
  // is a REPLACE and must not look like history the visitor can be sent back into.
  useEffect(() => {
    noteNav(navType);
  }, [navType, key]);
  const timer = useRef(null);
  const geoLookupFired = useRef(false);
  const accountLangApplied = useRef(false);

  useEffect(() => {
    if (valid && urlLang !== lang) setLang(urlLang);
  }, [valid, urlLang, lang, setLang]);

  // Account language wins over both localStorage and IP geolocation. A Bulgarian on
  // holiday abroad sees the Bulgarian skin the moment they sign in, even from a
  // browser with no prior visit history. Only applied once per session so a shopper
  // can still switch languages manually mid-session without being snapped back.
  useEffect(() => {
    if (!valid || !user || accountLangApplied.current) return;
    const preferred = (user.lang || "").toLowerCase();
    if (!preferred || !CODES.includes(preferred)) return;
    accountLangApplied.current = true;
    if (preferred === urlLang) return;
    const rest = stripLang(pathname);
    setLang(preferred);
    navigate(`/${preferred}${rest}${search}${hash}`, { replace: true });
  }, [valid, user, urlLang, pathname, search, hash, navigate, setLang]);

  // Language decision for anyone who is not signed in, on EVERY visit: their own pick if
  // they have one, otherwise the country behind their IP. That is what makes a shared
  // listing behave — a link sent as /en/car/123 opens in Bulgarian for a shopper in
  // Bulgaria, on the same car, with the path and query string carried over.
  useEffect(() => {
    if (!valid) return;
    if (user?.lang) return;                          // account preference wins, see above
    const apply = (next) => {
      if (!next || !CODES.includes(next) || next === urlLang) return;
      const rest = stripLang(pathname);
      // Push the language into state IN THE SAME TICK as the redirect. The search page
      // mirrors its filters back into the URL, so a navigate() on its own could be
      // overwritten by that mirror one render later — the redirect looked like it never
      // happened.
      setLang(next);
      navigate(`/${next}${rest}${search}${hash}`, { replace: true });
    };
    const picked = readLangPref();
    if (picked) {
      apply(picked);
      return;
    }
    const cached = cachedGeoLang();
    if (cached) {
      apply(cached);
      return;
    }
    if (geoLookupFired.current) return;              // one lookup per page load, at most
    geoLookupFired.current = true;
    getGeoLang()
      .then((res) => {
        rememberGeoLang(res?.lang || "");
        apply(res?.lang);
      })
      .catch(() => {});
  }, [valid, user, urlLang, pathname, search, hash, navigate, setLang]);

  // Third-party statistics follow the decision, in both directions: nothing loads before a
  // yes, and a withdrawal switches the consent signal back to denied.
  useEffect(() => {
    syncAnalytics(allows("statistics"));
    return onConsentChange(() => syncAnalytics(allows("statistics")));
  }, []);

  // One count per page. Deliberately delayed: on a car page `useSeo` only sets the title once
  // the car has loaded, and that title is where the car's name comes from. Waiting also means a
  // visitor bouncing through three pages in a second is not counted three times over.
  useEffect(() => {
    if (!valid) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const path = stripLang(pathname) || "/";
      ping(path, labelFor(path, document.title || ""));
    }, 1200);
    return () => clearTimeout(timer.current);
  }, [pathname, valid]);

  // Standalone (homescreen PWA) needs extra bottom padding on <body> so the floating
  // Liquid Glass tab bar does not cover the last row of content. The class flips
  // reactively if the OS toggles display-mode mid-session (rare on desktop, real on
  // Chrome/Edge multi-window PWAs).
  const standalone = useDisplayMode();
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    document.body.classList.toggle("pwa-standalone", standalone);
    return () => document.body.classList.remove("pwa-standalone");
  }, [standalone]);

  if (!valid) return <LangRedirect />;
  return (
    <>
      <AdminTrafficBar />
      {/* Install nag shown in a browser tab; enable-push nag shown once installed.
          Only one of them can ever be visible because they gate on opposite states
          of `display-mode: standalone`. */}
      {standalone ? <NotificationsPrompt /> : <InstallBanner />}
      {/* Asks for push the instant a buyer signs in inside the installed app. Renders
          nothing until that transition happens. */}
      {standalone ? <NotifyConsentDialog /> : null}
      <ScrollToTop />
      <Outlet />
      <SiteFooter />
      <CookieBar />
      {/* Floating Liquid Glass bottom bar — only in standalone. Rendered after the
          footer so it stacks above every fixed layer while never appearing in a
          plain browser tab (that already has Safari/Chrome's own toolbar). */}
      <PwaTabBar />
    </>
  );
};

/** Sends a prefix-less or unknown-prefix URL to the same page in the visitor's language. */
export const LangRedirect = () => {
  const { lang } = useApp();
  const { pathname, search, hash } = useLocation();
  const rest = stripLang(pathname);
  return <Navigate to={`/${lang}${rest}${search}${hash}`} replace />;
};

export default LangLayout;
