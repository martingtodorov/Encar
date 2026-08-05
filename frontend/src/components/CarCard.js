import { Heart, Gauge, Calendar, Fuel, MapPin } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PhotoSwiper } from "@/components/PhotoSwiper";
import { useApp } from "@/context/AppContext";
import { useCarWarm } from "@/hooks/useCarWarm";
import {
  carSubtitle,
  carTitle,
  formatMileage,
  formatMoney,
  formatYearMonth,
} from "@/lib/format";

// The Korean city is never shown: it is the one fact that cannot help a buyer in Europe
// decide. `showRegion` is kept as a no-op prop so the callers need no change.
export const CarCard = ({ car, onOpen, showRegion = true }) => {
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();
  const saved = isFavourite(car.id);
  const [warm, warmNow] = useCarWarm(car.id);

  // Three steps of the site's own palette instead of yellow/blue/green: darker grey for the
  // diagnosis, brand red for the inspection, light grey for the insurance history.
  const badges = [];
  if (car.diagnosed)
    badges.push({
      label: t("diagnosed"),
      cls: "bg-foreground/10 text-foreground",
    });
  if (car.has_inspection)
    badges.push({
      label: t("inspected"),
      cls: "bg-secondary text-[hsl(var(--primary))]",
    });
  if (car.has_record)
    badges.push({
      label: t("insured"),
      cls: "bg-muted text-muted-foreground",
    });

  const subtitle = [carSubtitle(car), car.badge_detail_t || car.badge_detail]
    .filter(Boolean)
    .join(" \u00b7 ");

  return (
    <article
      data-testid="car-card"
      data-car-id={car.id}
      data-under-contract={car.under_contract ? "true" : "false"}
      {...warm}
      role="button"
      tabIndex={0}
      aria-label={`${carTitle(car)} \u2014 ${t("viewDetails")}`}
      onClick={() => onOpen?.(car)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen?.(car);
        }
      }}
      className="group relative flex cursor-pointer flex-col overflow-hidden rounded-[14px] border border-border bg-card shadow-sm transition-shadow duration-200 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {car.under_contract && (
        <span data-testid="car-card-contract-ribbon" className="ribbon">
          {t("underContract")}
        </span>
      )}

      <div className="relative">
        {/* Swipe through the photos without leaving the list; a tap anywhere opens the car. */}
        <div data-testid="car-card-open" className="aspect-video w-full">
          <PhotoSwiper
            images={car.images?.length ? car.images : [car.image]}
            alt={carTitle(car)}
            testId="car-card-swiper"
            ctaLabel={t("viewListing")}
            ctaHint={t("tapToOpen")}
            onCtaReached={warmNow}
            // Swiping to the second photo is intent: nobody flicks past the cover shot of a
            // car they are not considering. The ad is fetched in the background from there
            // on (warmCar dedupes, so the extra calls cost nothing) and the tap is instant.
            onIndexChange={(n) => {
              if (n >= 1) warmNow();
            }}
          />
        </div>

        <button
          type="button"
          data-testid="car-card-save-button"
          onClick={(e) => {
            e.stopPropagation();
            toggleFavourite(car.id, car);
          }}
          aria-label={saved ? t("saved") : t("save")}
          aria-pressed={saved}
          className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card shadow-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Heart
            className={`h-4 w-4 ${
              saved
                ? "fill-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                : "text-muted-foreground"
            }`}
            aria-hidden="true"
          />
        </button>

      </div>

      {/* compact body: tight spacing, no filler gaps */}
      <div className="flex flex-col gap-1.5 p-2.5">
        <h3
          data-testid="car-card-title"
          className="line-clamp-1 text-[14px] font-semibold leading-tight text-foreground"
        >
          {carTitle(car)}
        </h3>

        {subtitle && (
          <p
            className="line-clamp-1 text-[11px] leading-tight text-muted-foreground"
            title={subtitle}
          >
            {subtitle}
          </p>
        )}

        <div className="flex flex-wrap gap-x-2.5 gap-y-0.5 text-[11px] leading-tight text-muted-foreground">
          <span className="tnum inline-flex items-center gap-1">
            <Calendar className="h-3 w-3" aria-hidden="true" />
            {formatYearMonth(car.year_month, car.form_year)}
          </span>
          <span className="tnum inline-flex items-center gap-1" data-testid="car-card-mileage">
            <Gauge className="h-3 w-3" aria-hidden="true" />
            {formatMileage(car.mileage, lang, t("km"))}
          </span>
          {(car.fuel_type_t || car.fuel_type) && (
            <span className="inline-flex items-center gap-1">
              <Fuel className="h-3 w-3" aria-hidden="true" />
              {car.fuel_type_t || car.fuel_type}
            </span>
          )}
        </div>

        {badges.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {badges.slice(0, 3).map((b) => (
              <Badge
                key={b.label}
                className={`rounded-full border-0 px-1.5 py-0 text-[10px] font-medium leading-[16px] ${b.cls}`}
              >
                {b.label}
              </Badge>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between gap-2 pt-0.5">
          <div className="leading-none">
            <div
              data-testid="car-card-price"
              className="tnum text-[19px] font-semibold tracking-tight text-foreground"
            >
              {formatMoney(car.sale_eur, currency, lang, rates)}
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{t("finalPrice")}</div>
          </div>
          <Button
            data-testid="car-card-details-button"
            onClick={(e) => {
              e.stopPropagation();
              onOpen?.(car);
            }}
            className="h-8 shrink-0 rounded-[8px] bg-[hsl(var(--primary))] px-2.5 text-[12px] font-medium text-primary-foreground transition-all hover:brightness-110"
          >
            {t("viewDetails")}
          </Button>
        </div>
      </div>
    </article>
  );
};

export default CarCard;
