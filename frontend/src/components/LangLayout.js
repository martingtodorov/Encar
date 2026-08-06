import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { CookieBar } from "@/components/CookieBar";
import { ScrollToTop } from "@/components/ScrollToTop";
import { SiteFooter } from "@/components/SiteFooter";
import { LANGS } from "@/i18n";
import { stripLang } from "@/lib/seo";
import { allows, onConsentChange } from "@/lib/consent";
import { syncAnalytics } from "@/lib/analytics";

const CODES = LANGS.map((l) => l.code);

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
  const valid = CODES.includes(urlLang);

  useEffect(() => {
    if (valid && urlLang !== lang) setLang(urlLang);
  }, [valid, urlLang, lang, setLang]);

  // Third-party statistics follow the decision, in both directions: nothing loads before a
  // yes, and a withdrawal switches the consent signal back to denied.
  useEffect(() => {
    syncAnalytics(allows("statistics"));
    return onConsentChange(() => syncAnalytics(allows("statistics")));
  }, []);

  if (!valid) return <LangRedirect />;
  return (
    <>
      <ScrollToTop />
      <Outlet />
      <SiteFooter />
      <CookieBar />
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
