import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { stripLang } from "@/lib/seo";
import { saveAccountLang } from "@/lib/api";
import { saveLangPref } from "@/lib/langPref";

/**
 * Every internal link carries the language prefix, so building paths by hand would mean
 * remembering it in a dozen places. `path()` prefixes, `go()` navigates, and
 * `switchLang()` swaps the prefix while staying on the same page with the same filters.
 */
export function useLangNav() {
  const { lang } = useApp();
  const { user } = useAuth();
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
      // A pick from the switcher is the one thing we remember: from here on the IP rule
      // stays out of the way on this device, on every visit, until they pick again.
      saveLangPref(code);
      navigate(`/${code}${rest}${location.search}${location.hash}`);
      // Explicit picks by a signed-in buyer follow them across devices. Fire-and-forget
      // so a slow network never blocks the visual switch; a stale value on failure is
      // fixed next time they open the switcher.
      if (user) {
        saveAccountLang(code).catch(() => {});
      }
    },
    [navigate, location.pathname, location.search, location.hash, user]
  );

  return { lang, path, go, switchLang };
}

export default useLangNav;
