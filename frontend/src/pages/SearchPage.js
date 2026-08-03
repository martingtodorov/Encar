import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { TrustStrip } from "@/components/TrustStrip";
import { TaxonomySelects } from "@/components/TaxonomySelects";
import { FilterSidebar } from "@/components/FilterSidebar";
import { AppliedFiltersChips } from "@/components/AppliedFiltersChips";
import { SortControl, DEFAULT_SORT_BROWSE, DEFAULT_SORT_FILTERED } from "@/components/SortControl";
import { CarGrid } from "@/components/CarGrid";
import { ResultsPagination } from "@/components/ResultsPagination";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { getCatalogueSize, getFilters, resolveSlugs, searchCars } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { useScrollDirection } from "@/hooks/useScrollDirection";
import { useSeo } from "@/lib/seo";
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

// Make alone is still browsing, so newest first. Once a model (or a trim below it) narrows
// the list the visitor is comparing like with like, so cheapest first.
const autoSort = (tax) =>
  tax.model || tax.badge || tax.badgeDetail ? DEFAULT_SORT_FILTERED : DEFAULT_SORT_BROWSE;

export default function SearchPage() {
  const { t, lang, currency, rates, saveSearch, isSearchSaved } = useApp();
  const { go } = useLangNav();
  const [searchParams, setSearchParams] = useSearchParams();
  // Read the URL ONCE on mount; after that this component owns the state and writes
  // back. Re-reading on every param change would fight the effect below.
  const initial = useMemo(() => paramsToState(searchParams), []);

  const [filters, setFilters] = useState(initial.filters);
  const [tax, setTax] = useState(initial.tax);
  // Translated labels for the current taxonomy selection, published by TaxonomySelects
  // so the applied-filter chips never show raw Korean values.
  const [taxLabels, setTaxLabels] = useState(EMPTY_TAX);
  const [sort, setSort] = useState(initial.sort || DEFAULT_SORT_BROWSE);
  // Once the visitor picks a sort themselves we stop overriding it. A sort in the URL
  // counts as a deliberate choice, so returning via Back keeps it.
  // A sort in the URL only counts as a deliberate choice if it differs from the one the
  // rule above would have picked. Otherwise coming back from a car (or switching
  // language) would freeze the sort, and clearing back to a make-only search would keep
  // showing cheapest first instead of newest.
  const [sortTouched, setSortTouched] = useState(
    !!initial.sort && initial.sort !== autoSort(initial.tax)
  );
  const [page, setPage] = useState(initial.page);

  // value -> English slug, per dimension. Seeded from the URL on arrival and then kept
  // topped up by the facets and taxonomy responses, so the query string can always be
  // written in English even before every dropdown level has loaded.
  const [slugs, setSlugs] = useState({});
  // A URL carrying slugs cannot be searched until they are translated back.
  const [resolving, setResolving] = useState(() => hasResolvableTokens(searchParams));

  const [facets, setFacets] = useState(null);
  const [result, setResult] = useState({ items: [], total: 0, pages: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [catalogueSize, setCatalogueSize] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const headerHidden = useScrollDirection(140);

  useSeo({ lang, title: t("seoHomeTitle"), description: t("seoHomeDesc") });

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
    setLoading(true);
    setError(null);
    try {
      setResult(await searchCars(body));
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "request failed");
      setResult({ items: [], total: 0, pages: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  const payload = useMemo(
    () => buildPayload({ filters, tax, sort, page }, { lang, pageSize: PAGE_SIZE }),
    [filters, tax, sort, page, lang]
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
  }, []);

  // Newest first while browsing (including make-only); lowest price first once a model
  // or trim narrows the list. Skipped entirely once the visitor has chosen a sort.
  useEffect(() => {
    if (sortTouched) return;
    setSort(autoSort(tax));
    setPage(1);
  }, [tax.model, tax.badge, tax.badgeDetail, sortTouched]);

  // Mirror the live search into the query string. `replace` so we do not push a history
  // entry per keystroke - the entry that exists when a car is opened already carries
  // these params, which is exactly what Back needs to restore.
  useEffect(() => {
    if (resolving) return;
    setSearchParams(stateToParams({ filters, tax, sort, page }, slugFor), { replace: true });
  }, [filters, tax, sort, page, setSearchParams, slugFor, resolving]);

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

  const scrollToResults = useCallback(() => {
    resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const changePage = useCallback((p) => {
    setPage(p);
    resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // Carry the live search in the navigation state. The detail page's own "back to
  // results" button is not a browser Back, so without this it can only guess at "/"
  // and the visitor lands in an unfiltered catalogue.
  const openCar = useCallback(
    (car) =>
      go(`/car/${car.id}`, {
        state: { from: `?${stateToParams({ filters, tax, sort, page }, slugFor)}` },
      }),
    [go, filters, tax, sort, page, slugFor]
  );

  // A saved search is the current filters, nothing else: it always reopens on page 1
  // with the default sort, so it keeps working as the catalogue changes.
  const query = useMemo(() => savableQuery({ filters, tax }, slugFor), [filters, tax, slugFor]);
  const alreadySaved = isSearchSaved(query);

  const saveThis = useCallback(() => {
    const name = describeSearch({ filters, tax, taxLabels, facets, t, lang, currency, rates });
    saveSearch({ name, query, total: result.total });
    toast.success(t("searchSavedToast"), { description: name });
  }, [filters, tax, taxLabels, facets, t, lang, currency, rates, query, result.total, saveSearch]);

  const countLabel =
    result.total === 1
      ? t("resultsCountOne")
      : t("resultsCount", { n: formatNumber(result.total, lang) });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar hidden={headerHidden} />

      {/* Mobile: once the header collapses on scroll, keep the filter button reachable */}
      <div
        className={`fixed left-1/2 top-2 z-50 -translate-x-1/2 transition-all duration-300 lg:hidden ${
          headerHidden ? "pointer-events-auto opacity-100" : "pointer-events-none -translate-y-16 opacity-0"
        }`}
      >
        <Button
          data-testid="floating-filters-button"
          onClick={() => setSheetOpen(true)}
          className="h-11 gap-2 rounded-full border border-border bg-[hsl(var(--primary))] px-5 text-sm font-semibold text-primary-foreground shadow-md hover:brightness-110"
        >
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
          {t("filters")}
        </Button>
      </div>

      <Hero totalUpstream={catalogueSize} onStart={scrollToResults} />

      <TrustStrip />

      {/* Cascading Make -> Model -> Submodel -> Trim replaces the old search box */}
      <section className="bg-card">
        <div className="mx-auto max-w-[1280px] px-4 py-5 sm:px-6">
          <TaxonomySelects
            value={tax}
            onChange={changeTax}
            onLabels={setTaxLabels}
            onSlugs={learnSlugs}
            trailing={
              <Button
                data-testid="open-filters-button"
                variant="outline"
                onClick={() => setSheetOpen(true)}
                className="h-11 w-full gap-2 rounded-[10px] border border-input bg-card px-4 text-sm shadow-sm"
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
                      {t("showResults")} ({formatNumber(result.total, lang)})
                    </Button>
                  </div>
                </SheetContent>
              </Sheet>

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
                {countLabel}
              </div>

              <div className="ml-auto flex items-center gap-2">
                <Button
                  data-testid="save-search-button"
                  variant="outline"
                  disabled={!query || alreadySaved}
                  onClick={saveThis}
                  className="h-11 gap-2 rounded-[10px] border border-input bg-card px-4 text-sm shadow-sm disabled:opacity-60"
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

            <CarGrid
              items={result.items}
              loading={loading}
              error={error}
              onRetry={() => runSearch(payload)}
              onOpen={openCar}
              onClearFilters={resetAll}
              pageSize={PAGE_SIZE}
            />

            <ResultsPagination
              page={result.page || page}
              pages={result.pages}
              onChange={changePage}
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
