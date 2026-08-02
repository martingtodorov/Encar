import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { LANGS } from "@/i18n";
import { stripLang } from "@/lib/seo";

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

  if (!valid) return <LangRedirect />;
  return <Outlet />;
};

/** Sends a prefix-less or unknown-prefix URL to the same page in the visitor's language. */
export const LangRedirect = () => {
  const { lang } = useApp();
  const { pathname, search, hash } = useLocation();
  const rest = stripLang(pathname);
  return <Navigate to={`/${lang}${rest}${search}${hash}`} replace />;
};

export default LangLayout;
