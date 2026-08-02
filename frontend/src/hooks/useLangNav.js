import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { stripLang } from "@/lib/seo";

/**
 * Every internal link carries the language prefix, so building paths by hand would mean
 * remembering it in a dozen places. `path()` prefixes, `go()` navigates, and
 * `switchLang()` swaps the prefix while staying on the same page with the same filters.
 */
export function useLangNav() {
  const { lang } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  const path = useCallback(
    (to) => {
      const clean = !to || to === "/" ? "" : to.startsWith("/") ? to : `/${to}`;
      return `/${lang}${clean}`;
    },
    [lang]
  );

  const go = useCallback((to, opts) => navigate(path(to), opts), [navigate, path]);

  const switchLang = useCallback(
    (code) => {
      const rest = stripLang(location.pathname);
      navigate(`/${code}${rest}${location.search}${location.hash}`);
    },
    [navigate, location.pathname, location.search, location.hash]
  );

  return { lang, path, go, switchLang };
}

export default useLangNav;
