import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { SlidersHorizontal, Loader2, RotateCcw, Bookmark, BookmarkCheck } from "lucide-react";
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
import { TrustStrip } from "@/components/TrustStrip";
import { TaxonomySelects } from "@/components/TaxonomySelects";
import { FilterSidebar } from "@/components/FilterSidebar";
import { AppliedFiltersChips } from "@/components/AppliedFiltersChips";
import { SortControl, DEFAULT_SORT_BROWSE } from "@/components/SortControl";
import { CarGrid } from "@/components/CarGrid";
import { ResultsPagination } from "@/components/ResultsPagination";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { cachedSearch, getCatalogueSize, getFilters, prefetchSearch, resolveSlugs, searchCars } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { noteSearch, getTaste } from "@/lib/taste";
import { takeBackScroll } from "@/lib/backScroll";
import { useScrollDirection } from "@/hooks/useScrollDirection";
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
const PAGE_SIZE = 16;

// Scroll offset handed back by a car page, read on the next mount of this one.
let pendingRestore = null;

// Relevance is ranked against the visitor's taste profile, which grows every time they
// open a car. Re-reading it when this page remounts after Back would reshuffle the very
// list they were looking at a minute ago, so the profile is snapshotted per query and
// reused until the query itself changes. Module level on purpose: it has to outlive the
// component, exactly like `pendingRestore`.
let tasteSnapshot = { key: null, taste: null };

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
  const { go } = useLangNav();
  const [searchParams, setSearchParams] = useSearchParams();
  // Read the URL ONCE on mount; after that this component owns the state and writes
  // back. Re-reading on every param change would fight the effect below.
  const initial = useMemo(() => paramsToState(searchParams), []);
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
    () => !restored && hasResolvableTokens(searchParams)
  );

  const [facets, setFacets] = useState(null);
  const [result, setResult] = useState(
    restored?.result || { items: [], total: 0, pages: 0 }
  );
  const [loading, setLoading] = useState(!restored);
  const [error, setError] = useState(null);
  const [catalogueSize, setCatalogueSize] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const headerHidden = useScrollDirection(140);

  const seoHome = cms?.seo?.home || {};
  useSeo({
    lang,
    title: seoHome.title || t("seoHomeTitle"),
    description: seoHome.description || t("seoHomeDesc"),
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
        setTax({
          make: r.make || "",
          model: r.model || "",
          badge: r.badge || "",
          badgeDetail: r.badge_detail || "",
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

  // Mirror the live search into the query string. `replace` so we do not push a history
  // entry per keystroke - the entry that exists when a car is opened already carries
  // these params, which is exactly what Back needs to restore.
  useEffect(() => {
    if (resolving) return;
    setSearchParams(stateToParams({ filters, tax, sort, page }, slugFor), { replace: true });
  }, [filters, tax, sort, page, setSearchParams, slugFor, resolving]);

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

  const scrollToResults = useCallback(() => {
    resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

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
    saveSearch({ name: searchName, query, total: result.total });
    toast.success(t("searchSavedToast"), { description: searchName });
  }, [searchName, query, result.total, saveSearch, t]);

  // Any narrowing at all earns the red dot on the floating bar - and hides the hero.
  const anyFilterActive = !!query;
  const isHome = !anyFilterActive && page <= 1;

  // The site itself, plus its search entry point: this is what lets Google offer a search
  // box for the site and attribute pages to the company running it.
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
          ],
        }
      : null,
    "site-jsonld"
  );
  const barVisible = triggerOffscreen;

  // The landing view advertises the whole library: `total_all` is the catalogue count, while
  // `total` stays the floored one that paging is built from.
  const shownTotal = result.total_all ?? result.total;
  const countLabel =
    shownTotal === 1
      ? t("resultsCountOne")
      : t("resultsCount", { n: formatNumber(shownTotal, lang) });

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
        className={`fixed inset-x-0 z-30 -mt-px transition-all duration-300 lg:hidden ${
          headerHidden
            ? "top-[var(--admin-bar-h,0px)]"
            : "top-[calc(var(--admin-bar-h,0px)_+_4rem)]"
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

      {/* The pitch belongs on the landing view only: once someone has filtered, they are
          shopping and the hero is just something to scroll past. Sorting alone still counts
          as the home view. */}
      {isHome && <Hero totalUpstream={catalogueSize} onStart={scrollToResults} />}

      {isHome && <TrustStrip />}

      {isHome && <Recommended onOpen={openCar} />}

      {/* Cascading Make -> Model -> Submodel -> Trim replaces the old search box */}
      <section className="bg-background">
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
                facets={facets}
                onReset={resetAll}
              />
            </div>
          </aside>

          <section className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                <SheetContent side="left" className="flex w-[92vw] max-w-sm flex-col gap-0 bg-card p-0">
                  <SheetHeader className="border-b border-border px-4 py-3 text-left">
                    <SheetTitle className="text-[15px] font-semibold">{t("filters")}</SheetTitle>
                    <SheetDescription className="sr-only">{t("filters")}</SheetDescription>
                  </SheetHeader>
                  <FilterSidebar
                    filters={filters}
                    setFilter={setFilter}
                    toggleInArray={toggleInArray}
                    facets={facets}
                    onReset={resetAll}
                    inSheet
                    tax={tax}
                    onTaxChange={changeTax}
                    onTaxLabels={setTaxLabels}
                    onTaxSlugs={learnSlugs}
                  />
                  <div className="flex gap-2 border-t border-border bg-card px-4 py-3">
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
                <Button
                  data-testid="save-search-button"
                  variant="outline"
                  disabled={!query || alreadySaved}
                  onClick={saveThis}
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
                facets={facets}
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
