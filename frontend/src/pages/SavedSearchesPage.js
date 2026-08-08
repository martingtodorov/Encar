import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookmarkX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { SavedSearchCard } from "@/components/SavedSearchCard";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { SignInPrompt } from "@/components/SignInPrompt";
import { useLangNav } from "@/hooks/useLangNav";
import { resolveSlugs, searchCars } from "@/lib/api";
import { buildPayload, hasResolvableTokens, paramsToState } from "@/lib/searchQuery";
import { useSeo } from "@/lib/seo";

/** Slugs in a stored query -> the Korean values /api/search understands. */
async function resolveState(params) {
  const state = paramsToState(params);
  if (!hasResolvableTokens(params)) return state;
  try {
    const r = await resolveSlugs({
      make: state.tax.make,
      model: state.tax.model,
      badge: state.tax.badge,
      badge_detail: state.tax.badgeDetail,
      fuels: (state.filters.fuels || []).join("~"),
      regions: (state.filters.regions || []).join("~"),
    });
    return {
      ...state,
      tax: {
        make: r.make || "",
        model: r.model || "",
        badge: r.badge || "",
        badgeDetail: r.badge_detail || "",
      },
      filters: { ...state.filters, fuels: r.fuels || [], regions: r.regions || [] },
    };
  } catch (e) {
    return state;
  }
}

/**
 * Saved searches, each resolved live: the point of coming back is to see what has
 * arrived since, so the stored query is re-run on every visit rather than cached.
 */
export default function SavedSearchesPage() {
  const { t, lang, searches, renameSearch, removeSearch, markSearchSeen,
          toggleSearchAlerts } = useApp();
  const { user, loading: authLoading } = useAuth();
  const { path, go } = useLangNav();
  const [states, setStates] = useState({});

  useSeo({ lang, title: `${t("savedSearches")} · Encar`,
           description: t("seoSearchesDesc"), noindex: true });

  useEffect(() => {
    let cancelled = false;
    searches.forEach((s) => {
      // Stored queries hold English slugs, and the search endpoint speaks the upstream
      // Korean values, so they have to be translated back before counting matches.
      resolveState(new URLSearchParams(s.query))
        .then((state) =>
          searchCars(buildPayload({ ...state, sort: "newest", page: 1 }, { lang, pageSize: 1 }))
        )
        .then((d) => {
          if (cancelled) return;
          const car = (d.items || [])[0];
          setStates((p) => ({
            ...p,
            [s.id]: { total: d.total || 0, thumb: car?.images?.[0] || car?.image || null },
          }));
        })
        .catch(() => !cancelled && setStates((p) => ({ ...p, [s.id]: { total: 0, thumb: null } })));
    });
    return () => {
      cancelled = true;
    };
  }, [searches, lang]);

  // Opening a saved search means you have seen what is in it: the "new since" badge
  // resets to the count you just looked at.
  const open = useCallback(
    (item) => {
      const total = states[item.id]?.total;
      if (total != null) markSearchSeen(item.id, total);
      go(`/?${item.query}`);
    },
    [states, markSearchSeen, go]
  );

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[900px] px-4 py-6 sm:px-6">
        <h1 className="mb-5 text-2xl font-semibold text-foreground">{t("savedSearches")}</h1>

        {searches.length === 0 && !user && !authLoading ? (
          <SignInPrompt
            testId="searches-signin-prompt"
            icon={BookmarkX}
            title={t("gateSearchTitle")}
            body={t("gateSearchBody")}
          />
        ) : searches.length === 0 ? (
          <div
            data-testid="searches-empty-state"
            className="rounded-[16px] border border-border bg-card p-10 text-center"
          >
            <BookmarkX className="mx-auto h-9 w-9 text-muted-foreground" aria-hidden="true" />
            <h2 className="mt-3 text-[16px] font-semibold text-foreground">
              {t("noSearchesTitle")}
            </h2>
            <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground">
              {t("noSearchesBody")}
            </p>
            <Link to={path("/")}>
              <Button className="mt-4 h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-primary-foreground hover:brightness-110">
                {t("navSearch")}
              </Button>
            </Link>
          </div>
        ) : (
          <div data-testid="saved-searches-list" className="flex flex-col gap-3">
            {searches.map((s) => (
              <SavedSearchCard
                key={s.id}
                item={s}
                state={states[s.id]}
                onOpen={open}
                onRename={renameSearch}
                onRemove={removeSearch}
                onToggleAlerts={toggleSearchAlerts}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
