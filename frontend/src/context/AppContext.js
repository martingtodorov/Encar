import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getCmsSite, getFx } from "@/lib/api";
import { setCompany } from "@/content/company";
import { EMPTY_SITE, cachedSite, rememberSite } from "@/lib/cmsCache";
import { noteFavourite } from "@/lib/taste";
import { configureAnalytics } from "@/lib/analytics";
import { t as translate, CURRENCIES } from "@/i18n";

/** A currency we retired (e.g. BGN) can still be sitting in a returning visitor's
 *  localStorage, which would format prices in a currency we no longer convert. */
function validCurrency(code) {
  return CURRENCIES.some((c) => c.code === code) ? code : null;
}

const AppContext = createContext(null);

const LS_LANG = "encar.lang";
const LS_CUR = "encar.currency";
const LS_FAV = "encar.favourites";
const LS_SEARCHES = "encar.searches";
const LS_THEME = "encar.theme";

function detectLang() {
  const stored = localStorage.getItem(LS_LANG);
  if (stored) return stored;
  const nav = (navigator.language || "").toLowerCase();
  if (nav.startsWith("ro")) return "ro";
  if (nav.startsWith("en")) return "en";
  return "bg";
}

function detectTheme() {
  const stored = localStorage.getItem(LS_THEME);
  if (stored) return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function AppProvider({ children }) {
  const [lang, setLangState] = useState(detectLang);
  const [currency, setCurrencyState] = useState(() => {
    const saved = validCurrency(localStorage.getItem(LS_CUR));
    if (saved) return saved;
    // Prime the market's home currency on the first visit. Overridden the moment the
    // buyer picks something else from the header menu.
    const l = detectLang();
    return l === "ro" ? "RON" : l === "pl" ? "PLN" : "EUR";
  });
  const [theme, setThemeState] = useState(detectTheme);
  const [rates, setRates] = useState(null);
  // The owner's own SEO titles, hero copy and company details. Seeded from the last visit's
  // cache so a refresh never flashes the built-in headline before the API answers.
  const [cms, setCms] = useState(() => {
    const hit = cachedSite(detectLang());
    if (hit) {
      setCompany(hit.company);
      configureAnalytics(hit.company?.ga_id);
    }
    return hit || EMPTY_SITE;
  });
  const [favourites, setFavourites] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(LS_FAV) || "[]");
    } catch (e) {
      return [];
    }
  });
  const [searches, setSearches] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(LS_SEARCHES) || "[]");
    } catch (e) {
      return [];
    }
  });

  useEffect(() => {
    getFx()
      .then(setRates)
      .catch(() => setRates(null));
  }, []);

  // Editable copy is per language, so it is re-read when the visitor switches.
  useEffect(() => {
    let alive = true;
    // Show whatever this language had last time straight away, then confirm it.
    const hit = cachedSite(lang);
    if (hit) {
      setCompany(hit.company);
      configureAnalytics(hit.company?.ga_id);
      setCms(hit);
    }
    getCmsSite(lang)
      .then((data) => {
        if (!alive) return;
        setCompany(data.company);
        configureAnalytics(data.company?.ga_id);
        setCms({ company: data.company || {}, seo: data.seo || {}, hero: data.hero || {} });
        rememberSite(lang, data);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [lang]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  // Switching language switches the market, so it switches the currency with it:
  // Polish buyers price in PLN, Romanian buyers in RON, everyone else in EUR.
  const setLang = useCallback((l) => {
    setLangState(l);
    localStorage.setItem(LS_LANG, l);
    const cur = l === "ro" ? "RON" : l === "pl" ? "PLN" : "EUR";
    setCurrencyState(cur);
    localStorage.setItem(LS_CUR, cur);
  }, []);

  const setCurrency = useCallback((c) => {
    setCurrencyState(c);
    localStorage.setItem(LS_CUR, c);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((p) => (p === "dark" ? "light" : "dark"));
  }, []);

  const toggleFavourite = useCallback((id, car = null) => {
    setFavourites((prev) => {
      const adding = !prev.includes(id);
      const next = adding ? [...prev, id] : prev.filter((x) => x !== id);
      localStorage.setItem(LS_FAV, JSON.stringify(next));
      // Favouriting is the strongest taste signal there is, so it feeds the profile that
      // drives the landing recommendations.
      if (adding && car) noteFavourite(car);
      return next;
    });
  }, []);

  // Used when signing in: the account's list becomes the source of truth locally.
  const replaceFavourites = useCallback((ids) => {
    const next = Array.from(new Set(ids || []));
    localStorage.setItem(LS_FAV, JSON.stringify(next));
    setFavourites(next);
  }, []);

  // ── saved searches: a stored query string plus a name ──────────────────────
  const writeSearches = useCallback((next) => {
    localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
    setSearches(next);
    return next;
  }, []);

  const saveSearch = useCallback(
    ({ name, query, total }) => {
      const item = {
        id: `s_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name,
        query,
        seen_total: total ?? null,
        alerts: false,   // opt-in: "email me when a new car matches this search"
        lang,            // the alert email speaks the language the search was saved in
        created_at: new Date().toISOString(),
      };
      setSearches((prev) => {
        const next = [item, ...prev.filter((s) => s.query !== query)].slice(0, 60);
        localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
        return next;
      });
      return item;
    },
    [lang]
  );

  // "Email me when a new car matches this search". The backend keeps its own baseline per
  // search, so turning it on never mails out cars that were already in the index.
  const toggleSearchAlerts = useCallback((id) => {
    setSearches((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, alerts: !s.alerts } : s));
      localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
      return next;
    });
  }, []);

  const renameSearch = useCallback((id, name) => {
    setSearches((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, name } : s));
      localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
      return next;
    });
  }, []);

  const removeSearch = useCallback((id) => {
    setSearches((prev) => {
      const next = prev.filter((s) => s.id !== id);
      localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
      return next;
    });
  }, []);

  const markSearchSeen = useCallback((id, total) => {
    setSearches((prev) => {
      const item = prev.find((s) => s.id === id);
      if (!item || item.seen_total === total) return prev;
      const next = prev.map((s) => (s.id === id ? { ...s, seen_total: total } : s));
      localStorage.setItem(LS_SEARCHES, JSON.stringify(next));
      return next;
    });
  }, []);

  const replaceSearches = useCallback((items) => {
    const seen = new Set();
    const next = (items || []).filter((s) => s?.id && !seen.has(s.id) && seen.add(s.id));
    return writeSearches(next);
  }, [writeSearches]);

  const isSearchSaved = useCallback(
    (query) => searches.some((s) => s.query === query),
    [searches]
  );

  const value = useMemo(
    () => ({
      lang,
      setLang,
      currency,
      setCurrency,
      theme,
      toggleTheme,
      rates,
      cms,
      favourites,
      toggleFavourite,
      replaceFavourites,
      isFavourite: (id) => favourites.includes(id),
      searches,
      saveSearch,
      toggleSearchAlerts,
      renameSearch,
      removeSearch,
      markSearchSeen,
      replaceSearches,
      isSearchSaved,
      t: (key, vars) => translate(lang, key, vars),
    }),
    [lang, setLang, currency, setCurrency, theme, toggleTheme, rates, cms, favourites,
     toggleFavourite, replaceFavourites, searches, saveSearch, renameSearch,
     removeSearch, markSearchSeen, replaceSearches, isSearchSaved, toggleSearchAlerts]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
