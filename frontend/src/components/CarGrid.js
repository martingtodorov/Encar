import { useEffect, useState } from "react";
import { SearchX, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CarCard } from "@/components/CarCard";
import { CarRow } from "@/components/CarRow";
import { useApp } from "@/context/AppContext";

const CarCardSkeleton = () => (
  <div className="overflow-hidden rounded-[18px] border border-border bg-card">
    <Skeleton className="aspect-[4/3] w-full rounded-none bg-muted" />
    <div className="space-y-2 p-3.5">
      <Skeleton className="h-4 w-3/4 bg-muted" />
      <Skeleton className="h-3 w-1/2 bg-muted" />
      <Skeleton className="h-3 w-2/3 bg-muted" />
      <Skeleton className="mt-4 h-7 w-1/2 bg-muted" />
    </div>
  </div>
);

const CarRowSkeleton = () => (
  <div className="flex items-stretch gap-4 rounded-[14px] border border-border bg-card p-3">
    <Skeleton className="aspect-video w-[236px] shrink-0 rounded-[10px] bg-muted" />
    <div className="flex flex-1 flex-col justify-center gap-2">
      <Skeleton className="h-4 w-1/3 bg-muted" />
      <Skeleton className="h-3 w-1/2 bg-muted" />
      <Skeleton className="h-3 w-2/5 bg-muted" />
    </div>
    <div className="flex w-[200px] shrink-0 flex-col items-end justify-center gap-2 border-l border-border pl-4">
      <Skeleton className="h-6 w-24 bg-muted" />
      <Skeleton className="h-9 w-full bg-muted" />
    </div>
  </div>
);

// Mobile/tablet: cards in a grid. Desktop: one full-width row per ad, so all 16
// listings line up on a single vertical axis and are easy to compare.
const GRID = "grid grid-cols-1 gap-5 sm:grid-cols-2 md:grid-cols-3 lg:hidden";
const ROWS = "hidden flex-col gap-3 lg:flex";

const LG = "(min-width: 1024px)";

/** Only the layout this viewport actually shows is rendered. Building both and letting CSS
 *  throw one away doubled the cost of mounting a page of results - which is exactly what a
 *  Back from a car has to pay before the visitor sees their list again. */
function useDesktopLayout() {
  const [desktop, setDesktop] = useState(() => window.matchMedia(LG).matches);
  useEffect(() => {
    const mq = window.matchMedia(LG);
    const onChange = (e) => setDesktop(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return desktop;
}

export const CarGrid = ({ items, loading, error, onRetry, onOpen, onClearFilters, pageSize = 24 }) => {
  const { t } = useApp();
  const desktop = useDesktopLayout();

  if (error) {
    return (
      <div
        data-testid="error-state"
        className="rounded-[14px] border border-destructive/40 bg-secondary p-6 text-center"
      >
        <AlertTriangle className="mx-auto h-8 w-8 text-destructive" aria-hidden="true" />
        <h3 className="mt-3 text-[15px] font-semibold text-foreground">{t("errorTitle")}</h3>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{String(error)}</p>
        <Button
          data-testid="error-retry-button"
          onClick={onRetry}
          className="mt-4 h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-primary-foreground hover:brightness-110"
        >
          {t("retry")}
        </Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div data-testid="loading-state">
        {!desktop && (
          <div className={GRID}>
            {Array.from({ length: Math.min(pageSize, 6) }).map((_, i) => (
              <CarCardSkeleton key={i} />
            ))}
          </div>
        )}
        {desktop && (
          <div className={ROWS}>
            {Array.from({ length: Math.min(pageSize, 8) }).map((_, i) => (
              <CarRowSkeleton key={i} />
            ))}
          </div>
        )}
      </div>
    );
  }

  if (!items?.length) {
    return (
      <div
        data-testid="empty-state"
        className="rounded-[14px] border border-border bg-card p-10 text-center"
      >
        <SearchX className="mx-auto h-9 w-9 text-muted-foreground" aria-hidden="true" />
        <h3 className="mt-3 text-[16px] font-semibold text-foreground">{t("emptyTitle")}</h3>
        <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">
          {t("emptyBody")}
        </p>
        <Button
          data-testid="empty-clear-filters"
          onClick={onClearFilters}
          variant="secondary"
          className="mt-4 h-10 rounded-[10px] bg-secondary px-5 text-[hsl(var(--primary))] hover:brightness-95"
        >
          {t("clearAll")}
        </Button>
      </div>
    );
  }

  return (
    <div data-testid="car-grid">
      {!desktop && (
        <div className={GRID}>
          {items.map((car, i) => (
            <CarCard key={car.id} car={car} onOpen={onOpen} eager={i === 0} />
          ))}
        </div>
      )}
      {desktop && (
        <div data-testid="car-rows" className={ROWS}>
          {items.map((car) => (
            <CarRow key={car.id} car={car} onOpen={onOpen} />
          ))}
        </div>
      )}
    </div>
  );
};

export default CarGrid;
