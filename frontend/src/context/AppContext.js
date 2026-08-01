import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getFx } from "@/lib/api";
import { t as translate } from "@/i18n";

const AppContext = createContext(null);

const LS_LANG = "encar.lang";
const LS_CUR = "encar.currency";
const LS_FAV = "encar.favourites";
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
  const [currency, setCurrencyState] = useState(
    () => localStorage.getItem(LS_CUR) || (detectLang() === "ro" ? "RON" : "EUR")
  );
  const [theme, setThemeState] = useState(detectTheme);
  const [rates, setRates] = useState(null);
  const [favourites, setFavourites] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(LS_FAV) || "[]");
    } catch (e) {
      return [];
    }
  });

  useEffect(() => {
    getFx()
      .then(setRates)
      .catch(() => setRates(null));
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  const setLang = useCallback((l) => {
    setLangState(l);
    localStorage.setItem(LS_LANG, l);
  }, []);

  const setCurrency = useCallback((c) => {
    setCurrencyState(c);
    localStorage.setItem(LS_CUR, c);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((p) => (p === "dark" ? "light" : "dark"));
  }, []);

  const toggleFavourite = useCallback((id) => {
    setFavourites((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem(LS_FAV, JSON.stringify(next));
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      lang,
      setLang,
      currency,
      setCurrency,
      theme,
      toggleTheme,
      rates,
      favourites,
      toggleFavourite,
      isFavourite: (id) => favourites.includes(id),
      t: (key, vars) => translate(lang, key, vars),
    }),
    [lang, setLang, currency, setCurrency, theme, toggleTheme, rates, favourites, toggleFavourite]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
