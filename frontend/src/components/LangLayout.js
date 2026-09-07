import { useEffect, useRef } from "react";
import { Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
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

const CODES = LANGS.map((l) => l.code);
const GEO_LANG_DONE = "encar.geolang.done";

/**
 * Language lives in the URL, not in the browser's preference.
 *
 * Every page sits under /bg, /ro or /en so each translation has its own indexable
 * address. This layout is the single place that reads the prefix and pushes it into app
 * state; an unknown prefix (or none at all) is redirected to the visitor's language with
 * the rest of the path and the query string kept intact.
 */
export const LangLayout = () => {
  const { lang: urlLang } = useParams();
  const { lang, setLang } = useApp();
  const { user } = useAuth();
  const { pathname, search, hash } = useLocation();
  const navigate = useNavigate();
  const valid = CODES.includes(urlLang);
  const timer = useRef(null);
  // Snapshot at mount whether the visitor had ever explicitly picked a language.
  // The URL-sync effect below writes `encar.lang` on the very first render, so
  // reading storage later would always look "explicit" and the geo hint would be
  // silently skipped. Ref captured once so the geo effect can trust it.
  const hadStoredLang = useRef(Boolean(localStorage.getItem("encar.lang")));
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
    navigate(`/${preferred}${rest}${search}${hash}`, { replace: true });
  }, [valid, user, urlLang, pathname, search, hash, navigate]);

  // First-visit geolocation: a Romanian visitor who lands on the BG homepage (because
  // Bulgarian is the fallback locale) should be reshown the same page in Romanian
  // without having to hunt for a switcher. `useNavigate` returns a new function on
  // every render, so we guard against re-entry with a ref rather than an effect dep.
  useEffect(() => {
    if (!valid) return;
    if (hadStoredLang.current) return;
    if (user?.lang) return;                          // account preference will win below
    if (geoLookupFired.current) return;
    if (sessionStorage.getItem(GEO_LANG_DONE)) {
      geoLookupFired.current = true;
      return;
    }
    geoLookupFired.current = true;
    getGeoLang()
      .then((res) => {
        sessionStorage.setItem(GEO_LANG_DONE, "1");
        const next = res?.lang;
        if (!next || !CODES.includes(next) || next === urlLang) return;
        // Rewrite the URL to the detected language, keeping the rest of the path so a
        // deep link (e.g. /bg/bmw/3-series-g20) survives the redirect. The URL-sync
        // effect above will pick the new prefix up and store it, so no explicit
        // setLang is needed here (a double write would race with the redirect).
        const rest = stripLang(pathname);
        navigate(`/${next}${rest}${search}${hash}`, { replace: true });
      })
      .catch(() => {
        sessionStorage.setItem(GEO_LANG_DONE, "1");
      });
  }, [valid, urlLang, pathname, search, hash, navigate, setLang]);

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
