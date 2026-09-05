import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SlidersHorizontal, Loader2, RotateCcw, Bookmark, BookmarkCheck, Share } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { HeaderBar } from "@/components/HeaderBar";
import { Hero } from "@/components/Hero";
import { Recommended } from "@/components/Recommended";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import NotFoundPage from "@/pages/NotFoundPage";
import { TaxonomySelects } from "@/components/TaxonomySelects";
import { FilterSidebar } from "@/components/FilterSidebar";
import { AppliedFiltersChips } from "@/components/AppliedFiltersChips";
import { SortControl, DEFAULT_SORT_BROWSE } from "@/components/SortControl";
import { CarGrid } from "@/components/CarGrid";
import { ResultsPagination } from "@/components/ResultsPagination";
import { useApp } from "@/context/AppContext";
import { useGate } from "@/components/SignInGate";
import { useLangNav } from "@/hooks/useLangNav";
import { cachedSearch, getCatalogueSize, getFacetCounts, getFilters, prefetchSearch, resolveSlugs, searchCars } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { noteSearch, getTaste } from "@/lib/taste";
import { takeBackScroll } from "@/lib/backScroll";
import { useScrollDirection } from "@/hooks/useScrollDirection";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { useShare } from "@/hooks/useShare";
import { useSeo, useJsonLd } from "@/lib/seo";
import {
  EMPTY,
  EMPTY_TAX,
  buildPayload,
  hasResolvableTokens,
  paramsToState,
  savableQuery,
  stateToParams,
} from "@/lib/searchQuery";
import { describeSearch } from "@/lib/describeSearch";

// 16 ads per page on every viewport: mobile shows them as cards, desktop as rows.
// Model and make landings are the site's main category layer and its best shot at
// "BMW from Korea" style queries. "Обяви BMW" / "BMW listings" was inverted, carried no
// intent and is not a phrase anybody writes, so the template names the make, where the car
// comes from and what the price covers. The server-rendered HTML (backend/prerender.py)
// says the same thing, with a price range added.
const LANDING = {
  bg: {
    title: (s) => `${s} от Корея — крайна цена до България | Encar Europe`,
    h1: (s) => `Автомобили ${s} от Корея`,
    desc: (s, n) =>
      `${n} обяви за ${s} от Корея. Крайна цена до България с включени мито, ДДС, морски транспорт и доставка.`,
  },
  ro: {
    title: (s) => `${s} din Coreea — preț final livrat | Encar Europe`,
    h1: (s) => `Mașini ${s} din Coreea`,
    desc: (s, n) =>
      `${n} anunțuri ${s} din Coreea. Preț final livrat, cu taxe vamale, TVA, transport maritim și livrare incluse.`,
  },
  pl: {
    title: (s) => `${s} z Korei — cena końcowa z dostawą | Encar Europe`,
    h1: (s) => `Samochody ${s} z Korei`,
    desc: (s, n) =>
      `${n} ofert ${s} z Korei. Cena końcowa zawiera cło, VAT, transport morski i dostawę pod wskazany adres.`,
  },
  en: {
    title: (s) => `${s} from Korea — final landed price | Encar Europe`,
    h1: (s) => `${s} cars from Korea`,
    desc: (s, n) =>
      `${n} ${s} cars from Korea. The final landed price includes customs duty, VAT, sea freight and delivery.`,
  },
};

const PAGE_SIZE = 16;

// Query keys that turn this page into one of thousands of near-identical filter URLs.
// Google picked up a great many of them (`?make=hyundai&badge=…`), most showing "0 cars",
// which is a crawl trap and a quality signal against the whole domain. Any URL carrying one
// of these is `noindex, follow` with its canonical pointing at the clean landing page; the
// server-rendered HTML says exactly the same thing (backend/prerender.py).
const FILTER_PARAMS = ["make", "model", "badge", "badgeDetail", "fuels", "regions",
                       "transmissions", "year_min", "year_max", "mileage_min",
                       "mileage_max", "price_min", "price_max", "only_inspection",
                       "only_record", "only_diagnosed", "q"];

// Scroll offset handed back by a car page, read on the next mount of this one.
let pendingRestore = null;

// Relevance is ranked against the visitor's taste profile, which grows every time they
// open a car. Re-reading it when this page remounts after Back would reshuffle the very
// list they were looking at a minute ago, so the profile is snapshotted per query and
// reused until the query itself changes. Module level on purpose: it has to outlive the
// component, exactly like `pendingRestore`.
let tasteSnapshot = { key: null, taste: null };

// Whether the mobile filter drawer was open on the previous mount. Picking Make or Model
// changes the URL path, App.js keys SearchPage on the pathname, and the whole page
// remounts - which would otherwise slam the drawer shut mid-selection. Kept at module
// scope so it survives the remount but not a full reload.
let persistedSheetOpen = false;

// The state last painted for a given URL. A Back from a car remounts this page, and until the
// English slugs in the query string have been translated back the page cannot search at all —
// which is why Back used to paint a grid of skeletons and empty dropdowns for a few hundred
// milliseconds. Hydrating from here means the FIRST render already carries the cars, the
// upstream values and the labels; the quiet refresh that follows only confirms them.
// In memory, like `pendingRestore`: a Back is a client-side navigation so the module survives
// it, while a real reload should ask the server again.
const VISITS_MAX = 6;
const visits = new Map();

// The language lives in the PATH, not the query string, so both are part of the key -
// otherwise a Back after a language switch would hydrate the previous language's labels.
const visitKey = () => `${window.location.pathname}${window.location.search}`;

function rememberVisit(search, snap) {
  if (!visits.has(search) && visits.size >= VISITS_MAX) {
    visits.delete(visits.keys().next().value);
  }
  visits.set(search, snap);
}

function tasteFor(key) {
  if (tasteSnapshot.key !== key) tasteSnapshot = { key, taste: getTaste() };
  return tasteSnapshot.taste;
}

// "Relevant" is the sort for every search - browsing or narrowed down to a trim. The
// visitor can pick another one from the dropdown and that choice is then respected for
// the rest of the session, including while they change make/model.

export default function SearchPage() {
  const { t, lang, currency, rates, cms, saveSearch, isSearchSaved } = useApp();
  const { requireAccount } = useGate();
  const standalone = useDisplayMode();
  const share = useShare();
  const { go } = useLangNav();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  // Pretty search paths: /bg/bmw/m2-g87. The path segments are the same English slugs the
  // query string used to carry, so they feed the same resolver.
  const { makeSlug, modelSlug } = useParams();
  // Read the URL ONCE on mount; after that this component owns the state and writes
  // back. Re-reading on every param change would fight the effect below.
  const initial = useMemo(() => {
    const st = paramsToState(searchParams);
    if (makeSlug && !st.tax.make) st.tax.make = makeSlug;
    if (modelSlug && !st.tax.model) st.tax.model = modelSlug;
    return st;
  }, []);
  // Everything this page painted the last time it stood on this exact URL, if it is still
  // in memory (i.e. the visitor came back rather than reloading).
  const restored = useMemo(() => visits.get(visitKey()) || null, []);

  const [filters, setFilters] = useState(restored?.filters || initial.filters);
  const [tax, setTax] = useState(restored?.tax || initial.tax);
  // Translated labels for the current taxonomy selection, published by TaxonomySelects
  // so the applied-filter chips never show raw Korean values.
  const [taxLabels, setTaxLabels] = useState(restored?.taxLabels || EMPTY_TAX);
  const [sort, setSort] = useState(initial.sort || DEFAULT_SORT_BROWSE);
  // A non-default sort in the URL is a deliberate choice, so returning via Back or
  // sharing a link keeps it.
  const [sortTouched, setSortTouched] = useState(
    !!initial.sort && initial.sort !== DEFAULT_SORT_BROWSE
  );
  const [page, setPage] = useState(initial.page);

  // value -> English slug, per dimension. Seeded from the URL on arrival and then kept
  // topped up by the facets and taxonomy responses, so the query string can always be
  // written in English even before every dropdown level has loaded.
  const [slugs, setSlugs] = useState(restored?.slugs || {});
  // A URL carrying slugs cannot be searched until they are translated back — unless we
  // already know the answer from the visit we are coming back to.
  const [resolving, setResolving] = useState(
    () => !restored && (hasResolvableTokens(searchParams) || !!makeSlug)
  );

  const [facets, setFacets] = useState(null);
  // Dynamic fuel + transmission counts, scoped to the current search. The static
  // `facets` above holds labels, slugs and the whole-catalogue counts; a merge at
  // render time swaps in these live numbers so a shopper who ticked "BMW" no longer
  // sees the global 80k Petrol count next to it.
  const [dynamicCounts, setDynamicCounts] = useState(null);
  // A URL like `/bg/junk-make` isn't a real make: the resolver echoes it back. When that
  // happens we render NotFoundPage instead of silently redirecting to home, so an old
  // shared link tells the visitor the make is gone rather than dumping them elsewhere.
  const [notFound, setNotFound] = useState(false);
  const [result, setResult] = useState(
    restored?.result || { items: [], total: 0, pages: 0 }
  );
  const [loading, setLoading] = useState(!restored);
  const [error, setError] = useState(null);
  const [catalogueSize, setCatalogueSize] = useState(null);
  // Picking Make or Model changes the URL path (`/bg` -> `/bg/bmw` -> `/bg/bmw/m2-g87`),
  // which flips App.js's `searchKey` and remounts SearchPage from scratch. That would
  // reset a plain useState back to `false` mid-selection and slam the drawer shut, so
  // we keep the last value in a module-level flag and seed useState from it. Submodel
  // stays in the query string, so it never hit this bug — this fixes the make/model
  // path only. Cleared to false on unmount so a real navigation (Back, follow a link)
  // does not resurrect the sheet on the next visit.
  const [sheetOpen, setSheetOpenRaw] = useState(persistedSheetOpen);
  const setSheetOpen = useCallback((next) => {
    setSheetOpenRaw((prev) => {
      const v = typeof next === "function" ? next(prev) : next;
      persistedSheetOpen = v;
      return v;
    });
  }, []);
  // The sheet ALSO plays its slide-in-from-left animation on every remount, because
  // Radix marks a fresh SheetContent as `data-state=open` from tick zero and the
  // CSS entrance fires. The visitor sees the drawer whip back in every time they
  // pick a make or model. Suppress it only for the one render that follows the
  // remount: a body class disables Radix animations. The class is added
  // synchronously during the useState initializer so it lands on the DOM BEFORE
  // the Portal commits its Content and Overlay, and it STAYS on until the user
  // closes the sheet. Toggling it off earlier would restart the entrance
  // animation, because the browser treats an `animation-name` change from
  // `none` back to a real keyframes value as a fresh animation trigger. When the
  // user actually closes the drawer (`sheetOpen` -> false), the class comes off
  // and the very next open animates normally, remount or not.
  const [suppressSheetAnim, setSuppressSheetAnim] = useState(() => {
    if (typeof document !== "undefined" && persistedSheetOpen) {
      document.body.classList.add("suppress-sheet-anim");
      return true;
    }
    return false;
  });
  useEffect(() => {
    if (suppressSheetAnim && !sheetOpen) {
      setSuppressSheetAnim(false);
      document.body.classList.remove("suppress-sheet-anim");
    }
  }, [sheetOpen, suppressSheetAnim]);
  useEffect(
    () => () => {
      // Only strip on a real unmount (visitor left the page WITH the sheet
      // still open — a click on a car card, say). During a Make/Model remount
      // the module-scope `persistedSheetOpen` is still true, so we leave the
      // class in place and let the fresh mount's initializer keep it on. The
      // React 18 strict-mode simulated unmount also hits this cleanup, but at
      // that point the fresh mount has already re-added the class, so the
      // guard is what prevents strict mode from stripping it under us.
      if (!persistedSheetOpen) {
        document.body.classList.remove("suppress-sheet-anim");
      }
    },
    []
  );

  const headerHidden = useScrollDirection(140);

  const seoHome = cms?.seo?.home || {};
  // A make/model page is a landing page in its own right: "Обяви BMW M2 (G87) (2024-)"
  // in the tab and the snippet instead of the generic home line. Labels come translated
  // from TaxonomySelects; until they land the raw URL value stands in.
  const selName = [taxLabels.make || tax.make, taxLabels.model || tax.model]
    .filter(Boolean)
    .join(" ");
  const landing = selName ? LANDING[lang] || LANDING.en : null;
  useSeo({
    lang,
    title: notFound
      ? `${t("notFoundTitle")} · Encar`
      : landing
        ? landing.title(selName)
        : seoHome.title || t("seoHomeTitle"),
    description: notFound
      ? t("notFoundLead")
      : landing
        ? landing.desc(selName, formatNumber(result.total || 0, lang))
        : seoHome.description || t("seoHomeDesc"),
    // A pretty-URL slug we could not resolve is a 404 wearing a 200: keep it out of the
    // index even though SearchPage is still the mounted component underneath NotFoundPage.
    // Same treatment for a filter URL, for a search that matched nothing and for a page
    // that failed to load — Google has indexed several of the last two ("0 cars",
    // "Could not load results"), and those pages hurt every other page on the domain.
    noindex:
      notFound ||
      !!error ||
      FILTER_PARAMS.some((k) => searchParams.get(k)) ||
      (initial.page || 1) > 1 ||
      (!loading && !error && (result.total || 0) === 0),
    follow: true,
  });


  // The floating bar exists only to replace the in-page Filters button once that button
  // has scrolled off the top of the screen - so watch the button itself rather than
  // guessing from the header.
  // Coming back from a car: scroll to where the visitor was, but only once the results
  // that make the page that tall have rendered.
  // Kept OUTSIDE the component: this page rewrites its own URL with replace: true, which
  // drops the navigation state, so a remount would find nothing left to restore.
  const location = useLocation();
  if (location.state?.restoreScroll != null) pendingRestore = location.state.restoreScroll;
  else {
    // A pop lands on an entry written before the visitor scrolled, so the offset comes
    // through the module handoff the car page filled in instead.
    const handed = takeBackScroll();
    if (handed != null) pendingRestore = handed;
  }

  useEffect(() => {
    const target = pendingRestore;
    if (target == null) return undefined;
    pendingRestore = null;
    // Waiting for the results to arrive made the jump feel like a second page load, so
    // instead poll the layout and move the moment the document is tall enough - the
    // loading skeletons alone are usually enough.
    let frame = 0;
    const started = Date.now();
    const tick = () => {
      if (document.documentElement.scrollHeight >= target + window.innerHeight * 0.5) {
        window.scrollTo(0, target);
        if (Date.now() - started > 900) return;   // settled: stop re-asserting
      }
      if (Date.now() - started < 2500) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => frame && cancelAnimationFrame(frame);
    // Keyed on the navigation, not on mount: the render that carries the offset is not
    // always the mounting one, and a mount-only effect simply missed it.
  }, [location.key]);

  const filterTriggerRef = useRef(null);
  const [triggerOffscreen, setTriggerOffscreen] = useState(false);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = filterTriggerRef.current;
      // Measured rather than observed: an IntersectionObserver set up while the button is
      // still display:none (desktop layout) reports a zero rect and never recovers.
      setTriggerOffscreen(!!el && el.offsetParent !== null && el.getBoundingClientRect().bottom < 0);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [resolving]);

  const resultsRef = useRef(null);
  const taxRef = useRef(null);
  const debounce = useRef(null);

  const learnSlugs = useCallback((entries) => {
    if (!entries?.length) return;
    setSlugs((prev) => {
      const next = { ...prev };
      let changed = false;
      entries.forEach(([dim, value, slug]) => {
        if (!value || !slug) return;
        const key = `${dim}:${value}`;
        if (next[key] !== slug) {
          next[key] = slug;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, []);

  const slugFor = useCallback((dim, value) => slugs[`${dim}:${value}`] || "", [slugs]);

  useEffect(() => {
    if (!resolving) return;
    const q = {
      make: initial.tax.make,
      model: initial.tax.model,
      badge: initial.tax.badge,
      badge_detail: initial.tax.badgeDetail,
      fuels: (initial.filters.fuels || []).join("~"),
      regions: (initial.filters.regions || []).join("~"),
    };
    resolveSlugs(q)
      .then((r) => {
        const learned = [
          ["make", r.make, initial.tax.make],
          ["model", r.model, initial.tax.model],
          ["badge", r.badge, initial.tax.badge],
          ["badge_detail", r.badge_detail, initial.tax.badgeDetail],
          ...(r.fuels || []).map((v, i) => ["fuel", v, (initial.filters.fuels || [])[i]]),
          ...(r.regions || []).map((v, i) => ["region", v, (initial.filters.regions || [])[i]]),
        ].filter(([, value, slug]) => value && slug && value !== slug);
        learnSlugs(learned);
        // The resolver echoes unknown tokens back so PRE-SLUG links with raw values keep
        // working — but a PATH segment is always a slug, so one echoed back unchanged is a
        // junk URL (/bg/some-junk-make). This is a real 404: show it instead of home so an
        // old shared link surfaces the fact that the make (or model) is gone.
        let make = r.make || "";
        let model = r.model || "";
        let dead = false;
        if (makeSlug && initial.tax.make === makeSlug && make === makeSlug) {
          make = "";
          model = "";
          dead = true;
        }
        if (modelSlug && initial.tax.model === modelSlug && model === modelSlug) {
          model = "";
          dead = true;
        }
        if (dead) setNotFound(true);
        setTax({
          make,
          model,
          badge: make ? r.badge || "" : "",
          badgeDetail: make ? r.badge_detail || "" : "",
        });
        setFilters((f) => ({
          ...f,
          fuels: r.fuels || [],
          regions: r.regions || [],
        }));
      })
      .catch(() => {})
      .finally(() => setResolving(false));
  }, [resolving, initial, learnSlugs]);

  useEffect(() => {
    getFilters(lang)
      .then((d) => {
        setFacets(d);
        learnSlugs([
          ...(d.makes || []).map((m) => ["make", m.value, m.slug]),
          ...(d.fuels || []).map((m) => ["fuel", m.value, m.slug]),
          ...(d.regions || []).map((m) => ["region", m.value, m.slug]),
        ]);
      })
      .catch(() => setFacets(null));
  }, [lang, learnSlugs]);

  useEffect(() => {
    getCatalogueSize()
      .then((d) => setCatalogueSize(d?.unique_cars || null))
      .catch(() => {});
  }, []);

  const runSearch = useCallback(async (body) => {
    // Coming back from a car: show the results we already have, with no spinner, and
    // refresh them quietly behind the visitor.
    const early = cachedSearch(body);
    if (early) setResult(early);
    setLoading(!early);
    setError(null);
    try {
      setResult(await searchCars(body));
      // A filtered search is the clearest thing a visitor ever tells us about their taste.
      noteSearch(body);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "request failed");
      if (!early) setResult({ items: [], total: 0, pages: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  const payload = useMemo(
    () => {
      const body = buildPayload({ filters, tax, sort, page }, { lang, pageSize: PAGE_SIZE });
      // "Relevant" is ranked against this visitor's own profile, which lives on their
      // machine, so it has to travel with the request. Signed-in buyers also have it on
      // their account, and the backend prefers whichever is present.
      return sort === "relevant"
        ? { ...body, taste: tasteFor(JSON.stringify({ filters, tax, sort, lang })) }
        : body;
    },
    [filters, tax, sort, page, lang]
  );

  /** The visitor is hovering a page button, or the pagination just scrolled into view on a
   *  phone. Fetch that page now so the click lands on something already loaded. */
  const prefetchPage = useCallback(
    (n) => {
      if (!n || n < 1 || n === page) return;
      if (result.pages && n > result.pages) return;
      prefetchSearch({ ...payload, page: n });
    },
    [payload, page, result.pages]
  );


  useEffect(() => {
    if (resolving) return undefined;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => runSearch(payload), 280);
    return () => debounce.current && clearTimeout(debounce.current);
  }, [payload, runSearch, resolving]);

  // Fetch dynamic fuel/transmission counts for the current payload, so the sidebar
  // stops advertising whole-catalogue numbers next to a narrowed result set. The
  // request piggybacks the SAME debounce window as the main search, and null-out
  // while in flight so a partially applied filter never renders stale counts.
  useEffect(() => {
    if (resolving) return undefined;
    let alive = true;
    const t = setTimeout(() => {
      getFacetCounts(payload)
        .then((d) => alive && setDynamicCounts(d))
        .catch(() => alive && setDynamicCounts(null));
    }, 280);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [payload, resolving]);

  // Static `facets` keeps labels, slugs and (whole-catalogue) counts. Dynamic
  // counts overlay only the ones that changed. Any static value the dynamic count
  // dropped to zero is filtered out - a "Diesel (0)" chip is worse than no chip.
  const facetsForSidebar = useMemo(() => {
    if (!facets) return facets;
    if (!dynamicCounts) return facets;
    const byValue = (list) => Object.fromEntries((list || []).map((r) => [r.value, r.count]));
    const fuelCount = byValue(dynamicCounts.fuels);
    const transCount = byValue(dynamicCounts.transmissions);
    return {
      ...facets,
      fuels: (facets.fuels || [])
        .map((f) => ({ ...f, count: fuelCount[f.value] ?? 0 }))
        .filter((f) => f.count > 0),
      transmissions: (facets.transmissions || [])
        .map((tr) => ({ ...tr, count: transCount[tr.value] ?? 0 })),
    };
  }, [facets, dynamicCounts]);

  const setFilter = useCallback((key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  }, []);

  const toggleInArray = useCallback((key, value) => {
    setFilters((prev) => {
      const list = prev[key] || [];
      return {
        ...prev,
        [key]: list.includes(value) ? list.filter((x) => x !== value) : [...list, value],
      };
    });
    setPage(1);
  }, []);

  const changeTax = useCallback((next) => {
    setTax(next);
    setPage(1);
    // Choosing a make or a model collapses the hero, the trust strip and the picked-for-you
    // shelf, so the page shortens underneath the visitor. Going back to the top leaves them
    // looking at the results instead of stranded in the middle of a page that just changed
    // height. Instant, not smooth: the layout shifts as those sections unmount, which a
    // smooth scroll would chase.
    window.scrollTo(0, 0);
  }, []);

  // Mirror the live search into the URL. Make and model live in the PATH when their
  // English slugs are known — /bg/bmw/m2-g87 outranks /bg?make=bmw&model=m2-g87 in a
  // search result — and fall back to query params until a slug is learned. `replace` so
  // we do not push a history entry per keystroke - the entry that exists when a car is
  // opened already carries this URL, which is exactly what Back needs to restore.
  useEffect(() => {
    if (resolving) return;
    // A junk path segment (/bg/no-such-make) resolved to nothing, so the mirror below would
    // write `/bg` — and that rewrite REMOUNTS this page (App.js keys it on the path), which
    // reset `notFound` and quietly landed the visitor on the home page with an indexable
    // 200. That is the soft 404 the SEO audit found. Leaving the URL alone keeps the 404
    // page on screen and keeps it out of the index.
    if (notFound) return;
    const p = stateToParams({ filters, tax, sort, page }, slugFor);
    let path = `/${lang}`;
    const makeSeg = tax.make ? slugFor("make", tax.make) : "";
    if (makeSeg) {
      p.delete("make");
      path += `/${encodeURIComponent(makeSeg)}`;
      const modelSeg = tax.model ? slugFor("model", tax.model) : "";
      if (modelSeg) {
        p.delete("model");
        path += `/${encodeURIComponent(modelSeg)}`;
      }
    }
    const q = p.toString();
    const next = q ? `${path}?${q}` : path;
    if (`${window.location.pathname}${window.location.search}` !== next) {
      navigate(next, { replace: true });
    }
  }, [filters, tax, sort, page, navigate, lang, slugFor, resolving, notFound]);

  // Snapshot the painted state against the URL it belongs to, so a Back to it hydrates
  // instantly. Declared AFTER the URL mirror above so `window.location.search` is already
  // the URL these results answer.
  useEffect(() => {
    if (loading || error || !result.items?.length) return;
    rememberVisit(visitKey(), { filters, tax, slugs, taxLabels, result });
  }, [loading, error, result, filters, tax, slugs, taxLabels, searchParams]);

  const changeSort = useCallback((v) => {
    setSort(v);
    setSortTouched(true);
    setPage(1);
  }, []);

  const removeChip = useCallback(
    (key) => {
      if (["make", "model", "badge", "badgeDetail"].includes(key)) {
        setTax((p) => {
          if (key === "make") return EMPTY_TAX;
          if (key === "model") return { ...p, model: "", badge: "", badgeDetail: "" };
          if (key === "badge") return { ...p, badge: "", badgeDetail: "" };
          return { ...p, badgeDetail: "" };
        });
        setPage(1);
        return;
      }
      if (["year", "price", "mileage"].includes(key)) {
        setFilters((p) => ({ ...p, [`${key}_min`]: "", [`${key}_max`]: "" }));
        setPage(1);
        return;
      }
      if (key.includes(":")) {
        const [field, value] = key.split(":");
        toggleInArray(field, value);
        return;
      }
      setFilter(key, false);
    },
    [setFilter, toggleInArray]
  );

  const resetAll = useCallback(() => {
    setFilters(EMPTY);
    setTax(EMPTY_TAX);
    setPage(1);
    setSort(DEFAULT_SORT_BROWSE);
    setSortTouched(false);
  }, []);

  // Tapping the logo starts over: clear every filter and go back to the top.
  const homeSignal = location.state?.home;
  useEffect(() => {
    if (!homeSignal) return;
    resetAll();
    window.scrollTo(0, 0);
  }, [homeSignal, resetAll]);

  // The hero's button lands on the make/model dropdowns, not on the list: the visitor asked to
  // start searching, and the first thing they need is the first dropdown. The sticky header
  // (and the admin bar above it, when present) would cover them, so it is offset by hand
  // instead of using scrollIntoView.
  const scrollToSearch = useCallback(() => {
    const node = taxRef.current;
    if (!node) return;
    const bar = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue("--admin-bar-h") || "0",
      10,
    ) || 0;
    const top = node.getBoundingClientRect().top + window.scrollY - bar - 64 - 8;
    window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }, []);

  // The header's "Search cars" link carries a `#search` fragment: clicking it from any
  // page (or clicking it again from home) drops the visitor at the make/model dropdowns
  // rather than the top of the hero, mirroring the hero CTA. Runs after the taxonomy
  // node exists AND the initial data has arrived so the target does not jump.
  useEffect(() => {
    if (location.hash !== "#search") return;
    // Two frames: the first paints, the second measures once the layout is stable.
    const raf1 = requestAnimationFrame(() => {
      requestAnimationFrame(() => scrollToSearch());
    });
    return () => cancelAnimationFrame(raf1);
  }, [location.hash, scrollToSearch]);

  // A new page starts at the top of the page, not at the pagination the visitor just
  // clicked. Measuring the list instead was unreliable: the hero disappears from page two
  // onwards, so the layout shifts out from under the target mid-scroll.
  const jumpedToPage = useRef(false);
  const changePage = useCallback((p) => {
    setPage(p);
    jumpedToPage.current = true;
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    if (!jumpedToPage.current || loading) return;
    jumpedToPage.current = false;
    window.scrollTo(0, 0);
  }, [loading, result.page]);

  // Carry the live search in the navigation state. The detail page's own "back to
  // results" button is not a browser Back, so without this it can only guess at "/"
  // and the visitor lands in an unfiltered catalogue.
  const openCar = useCallback(
    (car) =>
      go(`/car/${car.id}`, {
        state: {
          from: `?${stateToParams({ filters, tax, sort, page }, slugFor)}`,
          scrollY: window.scrollY,
        },
      }),
    [go, filters, tax, sort, page, slugFor]
  );

  // A saved search is the current filters, nothing else: it always reopens on page 1
  // with the default sort, so it keeps working as the catalogue changes.
  const query = useMemo(() => savableQuery({ filters, tax }, slugFor), [filters, tax, slugFor]);
  const alreadySaved = isSearchSaved(query);

  // The same human name a saved search would get. On a filtered page it is also the h1,
  // because the hero (and with it the only other h1) is not rendered there.
  const searchName = useMemo(
    () => describeSearch({ filters, tax, taxLabels, facets, t, lang, currency, rates }),
    [filters, tax, taxLabels, facets, t, lang, currency, rates]
  );

  const saveThis = useCallback(() => {
    if (!requireAccount("search")) return;
    saveSearch({ name: searchName, query, total: result.total });
    toast.success(t("searchSavedToast"), { description: searchName });
  }, [searchName, query, result.total, saveSearch, t, requireAccount]);

  // Any narrowing at all earns the red dot on the floating bar - and hides the hero.
  const anyFilterActive = !!query;
  const isHome = !anyFilterActive && page <= 1;

  // The site itself, plus its search entry point: this is what lets Google offer a search
  // box for the site and attribute pages to the company running it. When the owner has
  // filled in office details in Admin -> Company, we also emit AutoDealer with the address
  // and phone so Google can attach a knowledge panel and a directions button.
  const co = cms?.company || {};
  const autoDealer = (() => {
    if (!co.address && !co.phone && !co.email) return null;
    const node = {
      "@type": ["AutoDealer", "LocalBusiness"],
      name: co.name || "Encar Europe",
      url: `${window.location.origin}/${lang}`,
      ...(co.email ? { email: co.email } : {}),
      ...(co.phone ? { telephone: co.phone } : {}),
      ...(co.address
        ? {
            address: { "@type": "PostalAddress", streetAddress: co.address },
          }
        : {}),
      ...(co.geo_lat && co.geo_lng
        ? {
            geo: {
              "@type": "GeoCoordinates",
              latitude: Number(co.geo_lat),
              longitude: Number(co.geo_lng),
            },
          }
        : {}),
      ...(co.google_maps_url ? { hasMap: co.google_maps_url } : {}),
    };
    return node;
  })();

  useJsonLd(
    isHome
      ? {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "Organization",
              name: "Encar Europe",
              url: `${window.location.origin}/${lang}`,
              logo: `${window.location.origin}/icons/icon-512.png`,
            },
            {
              "@type": "WebSite",
              name: "Encar Europe",
              url: `${window.location.origin}/${lang}`,
              inLanguage: lang,
              potentialAction: {
                "@type": "SearchAction",
                target: `${window.location.origin}/${lang}?q={search_term_string}`,
                "query-input": "required name=search_term_string",
              },
            },
            ...(autoDealer ? [autoDealer] : []),
          ],
        }
      : null,
    "site-jsonld"
  );

  // Make/model landings and the plain search page get an ItemList entry so Google
  // can render a rich carousel next to the listing card. The @id points at the car
  // detail URL - Google follows those to the Vehicle schema already on each page.
  useJsonLd(
    !isHome && result.items?.length
      ? {
          "@context": "https://schema.org",
          "@type": "ItemList",
          numberOfItems: Math.min(result.items.length, 20),
          itemListElement: result.items.slice(0, 20).map((it, i) => ({
            "@type": "ListItem",
            position: i + 1,
            url: `${window.location.origin}/${lang}/car/${it.id}`,
          })),
        }
      : null,
    "results-itemlist-jsonld"
  );
  const barVisible = triggerOffscreen;

  // The landing view advertises the whole library: `total_all` is the catalogue count, while
  // `total` stays the floored one that paging is built from.
  const shownTotal = result.total_all ?? result.total;
  const countLabel =
    shownTotal === 1
      ? t("resultsCountOne")
      : t("resultsCount", { n: formatNumber(shownTotal, lang) });

  // A pretty-URL segment that didn't resolve to a real make/model is a genuine 404.
  // Rendering the shared NotFoundPage keeps the header, footer, noindex meta and BG copy
  // consistent with an unknown route like /bg/no-such-page.
  if (notFound) return <NotFoundPage />;

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar hidden={headerHidden} flush={barVisible} />

      {/* Mobile: once the header collapses on scroll, keep the filters reachable as a
          full-width bar carrying the live result count. */}
      <div
        // Flush against the header (or the top edge once the header collapses) and edge
        // to edge, so there is no gap and nothing of the menu is ever covered. z-30 keeps
        // it under the header's z-40. Both offsets add `--admin-bar-h`, because the admin
        // traffic bar is pinned above everything and pushes the header down with it.
        data-testid="floating-filters-bar"
        // Pure CSS, no JS scroll tracking (that lagged a frame behind the header).
        // The two offsets are transitioned with the SAME 300ms as the header's own
        // hide transform, so the bar rides up with it instead of jumping ahead.
        className={`fixed inset-x-0 z-30 -mt-px transition-[top,opacity,transform] duration-300 lg:hidden ${
          headerHidden
            ? "top-[calc(var(--admin-bar-h,0px)_+_var(--safe-top,0px))]"
            : "top-[calc(var(--admin-bar-h,0px)_+_var(--safe-top,0px)_+_var(--header-h,4rem))]"
        } ${
          triggerOffscreen
            ? "pointer-events-auto opacity-100"
            : "pointer-events-none -translate-y-16 opacity-0"
        }`}
      >
        <button
          type="button"
          data-testid="floating-filters-button"
          onClick={() => setSheetOpen(true)}
          className="relative flex h-11 w-full items-center gap-2.5 border-b border-border bg-card px-4 text-left shadow-[0_3px_8px_rgba(18,20,23,0.08)] active:bg-muted"
        >
          <SlidersHorizontal className="h-[18px] w-[18px] shrink-0 text-foreground" aria-hidden="true" />
          <span className="truncate text-[14px] font-semibold text-foreground">
            {t("changeFilters")}
          </span>
          <span className="tnum ml-auto shrink-0 text-[14px] text-muted-foreground">
            {formatNumber(shownTotal, lang)}
          </span>
          {anyFilterActive && (
            <span
              data-testid="floating-filters-dot"
              className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[hsl(var(--primary))]"
              aria-hidden="true"
            />
          )}
        </button>
      </div>

      {/* Breadcrumbs on non-home views only: on the home page the hero already anchors
          the visitor. When a make or model is picked, the trail runs Home > Make > Model. */}
      {!isHome && (
        <Breadcrumbs
          testId="search-breadcrumbs"
          items={[
            { label: t("breadcrumbHome"), to: `/${lang}` },
            ...(taxLabels?.make
              ? [{
                  label: taxLabels.make,
                  to: tax?.model
                    ? `/${lang}/${encodeURIComponent(slugFor("make", tax.make) || tax.make)}`
                    : undefined,
                }]
              : []),
            ...(taxLabels?.model ? [{ label: taxLabels.model }] : []),
            ...((!taxLabels?.make && !taxLabels?.model)
              ? [{ label: searchName || t("breadcrumbSearch") }]
              : []),
          ]}
        />
      )}

      {/* The site name as the landing page's h1, for crawlers. `sr-only` and not
          `display: none`: hidden text is discounted, a screen-reader-only heading is not. The
          hero's own headline is an h2 below it, so the page keeps exactly ONE h1. */}
      {isHome && <h1 className="sr-only">Encar Europe</h1>}

      {/* The pitch belongs on the landing view only: once someone has filtered, they are
          shopping and the hero is just something to scroll past. Sorting alone still counts
          as the home view. */}
      {isHome && <Hero totalUpstream={catalogueSize} onStart={scrollToSearch} />}

      {isHome && <Recommended onOpen={openCar} />}

      {/* Cascading Make -> Model -> Submodel -> Trim replaces the old search box */}
      <section ref={taxRef} className="bg-background">
        <div className="mx-auto max-w-[1280px] px-4 py-5 sm:px-6">
          <TaxonomySelects
            // While the URL's English slugs are still being translated back, `tax` holds
            // slugs — feeding those to the dropdowns fires level 2/3/4 lookups that can
            // only come back empty, and the empty answer used to land AFTER the good one.
            value={resolving ? EMPTY_TAX : tax}
            onChange={changeTax}
            onLabels={setTaxLabels}
            onSlugs={learnSlugs}
            trailing={
              <Button
                ref={filterTriggerRef}
                data-testid="open-filters-button"
                variant="outline"
                onClick={() => setSheetOpen(true)}
                className="h-11 w-full gap-2 rounded-[10px] border border-input bg-background px-4 text-sm shadow-sm"
              >
                <SlidersHorizontal
                  className="h-4 w-4 text-[hsl(var(--primary))]"
                  aria-hidden="true"
                />
                {t("filters")}
              </Button>
            }
          />
        </div>
      </section>

      <main ref={resultsRef} className="mx-auto max-w-[1280px] px-4 pb-12 sm:px-6">
        {/* A filtered page has no hero, so this is its h1: what the visitor is looking at,
            in words, plus how many there are. It sits ABOVE the grid so it is the first
            heading in the document, before the filter widgets in the sidebar. */}
        {!isHome && (
          <h1
            data-testid="results-heading"
            className="mb-3 text-2xl font-semibold leading-tight tracking-tight text-foreground sm:text-3xl"
          >
            {`${t("listH1", { what: searchName })} \u2014 ${countLabel}`}
          </h1>
        )}
        <div className="lg:grid lg:grid-cols-[320px_1fr] lg:gap-6">
          <aside className="hidden lg:block">
            <div className="sticky top-[80px] pb-4">
              <FilterSidebar
                filters={filters}
                setFilter={setFilter}
                toggleInArray={toggleInArray}
                facets={facetsForSidebar}
                onReset={resetAll}
              />
            </div>
          </aside>

          <section className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                <SheetContent
                  side="left"
                  data-testid="filters-sheet-panel"
                  className={`flex w-[92vw] max-w-sm flex-col gap-0 bg-card p-0 ${
                    suppressSheetAnim ? "!animate-none !duration-0" : ""
                  }`}
                >
                  <SheetHeader className="shrink-0 border-b border-border px-4 py-3 text-left">
                    <SheetTitle className="text-[15px] font-semibold">{t("filters")}</SheetTitle>
                    <SheetDescription className="sr-only">{t("filters")}</SheetDescription>
                  </SheetHeader>
                  {/* Middle band takes whatever is left over between the header and the sticky
                      button row; `min-h-0` lets the flex child actually shrink (flex items
                      default to `min-height:auto`, which was why a filter list taller than the
                      phone viewport pushed Clear/Show past the bottom of the screen). */}
                  <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                    <FilterSidebar
                      filters={filters}
                      setFilter={setFilter}
                      toggleInArray={toggleInArray}
                      facets={facetsForSidebar}
                      onReset={resetAll}
                      inSheet
                      tax={tax}
                      onTaxChange={changeTax}
                      onTaxLabels={setTaxLabels}
                      onTaxSlugs={learnSlugs}
                    />
                  </div>
                  {/* `shrink-0` + `pb-[env(safe-area-inset-bottom)]`: Clear and Show stay pinned
                      to the bottom of the viewport on iOS, clear of the home-indicator swipe
                      bar, however long the filter list gets. */}
                  <div
                    className="flex shrink-0 gap-2 border-t border-border bg-card px-4 py-3"
                    style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
                  >
                    <Button
                      data-testid="sheet-reset-button"
                      variant="outline"
                      onClick={resetAll}
                      className="h-11 flex-1 gap-1.5 border-border bg-card text-sm"
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                      {t("clearAll")}
                    </Button>
                    <Button
                      data-testid="sheet-apply-button"
                      onClick={() => setSheetOpen(false)}
                      className="tnum h-11 flex-[1.4] rounded-[10px] bg-[hsl(var(--primary))] text-sm text-primary-foreground hover:brightness-110"
                    >
                      {t("showResults")} ({formatNumber(shownTotal, lang)})
                    </Button>
                  </div>
                </SheetContent>
              </Sheet>

              <h2
                data-testid="results-section-heading"
                className="text-base font-semibold text-foreground md:text-lg"
              >
                {t("resultsHeading")}
              </h2>

              <div
                data-testid="result-count"
                aria-live="polite"
                className="tnum flex items-center gap-2 text-sm font-medium text-foreground"
              >
                {loading && (
                  <Loader2
                    className="h-4 w-4 animate-spin text-[hsl(var(--primary))]"
                    aria-hidden="true"
                  />
                )}
                {/* The count is already in the h1 on a filtered page, so it is kept for
                    screen readers and the live region rather than printed twice. */}
                <span className={isHome ? "" : "sr-only"}>{countLabel}</span>
              </div>

              <div className="ml-auto flex items-center gap-2">
                {/* Homescreen app only: no browser share button exists there, and a filtered
                    search is exactly the thing buyers send to whoever is paying. */}
                {standalone && (
                  <Button
                    data-testid="search-share-button"
                    variant="outline"
                    onClick={() => share({ title: document.title })}
                    aria-label={t("pwaShareAria")}
                    // Same box as the save-search button beside it: same height, radius,
                    // border, padding, text size, label-hiding breakpoint AND the same
                    // disabled dimming, so the pair never drifts apart in any state.
                    className="h-11 gap-2 rounded-[10px] border border-input bg-background px-4 text-sm shadow-sm disabled:opacity-60"
                  >
                    <Share className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                    <span className="hidden sm:inline">{t("pwaShareAria")}</span>
                  </Button>
                )}
                <Button
                  data-testid="save-search-button"
                  variant="outline"
                  disabled={!query || alreadySaved}
                  onClick={saveThis}
                  aria-label={alreadySaved ? t("searchSaved") : t("saveThisSearch")}
                  className="h-11 gap-2 rounded-[10px] border border-input bg-background px-4 text-sm shadow-sm disabled:opacity-60"
                >
                  {alreadySaved ? (
                    <BookmarkCheck className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                  ) : (
                    <Bookmark className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                  )}
                  <span className="hidden sm:inline">
                    {alreadySaved ? t("searchSaved") : t("saveThisSearch")}
                  </span>
                </Button>
                <SortControl value={sort} onChange={changeSort} />
              </div>
            </div>

            <div className="mb-4">
              <AppliedFiltersChips
                filters={filters}
                tax={tax}
                taxLabels={taxLabels}
                facets={facetsForSidebar}
                onRemove={removeChip}
                onClearAll={resetAll}
              />
            </div>

            <div>
              <CarGrid
                items={result.items}
                loading={loading}
                error={error}
                onRetry={() => runSearch(payload)}
                onOpen={openCar}
                onClearFilters={resetAll}
                pageSize={PAGE_SIZE}
              />
            </div>

            <ResultsPagination
              page={result.page || page}
              pages={result.pages}
              onChange={changePage}
              onPrefetch={prefetchPage}
            />
          </section>
        </div>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            {t("trust1Body")} {t("trust2Body")}
          </p>
        </div>
      </footer>
    </div>
  );
}
