import { SearchX, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CarCard } from "@/components/CarCard";
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

const GRID =
  "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

export const CarGrid = ({ items, loading, error, onRetry, onOpen, onClearFilters, pageSize = 24 }) => {
  const { t } = useApp();

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
      <div data-testid="loading-state" className={GRID}>
        {Array.from({ length: Math.min(pageSize, 12) }).map((_, i) => (
          <CarCardSkeleton key={i} />
        ))}
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
    <div data-testid="car-grid" className={GRID}>
      {items.map((car) => (
        <CarCard key={car.id} car={car} onOpen={onOpen} />
      ))}
    </div>
  );
};

export default CarGrid;
