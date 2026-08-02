import { Heart, Gauge, Calendar, Fuel, MapPin, Camera } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { useApp } from "@/context/AppContext";
import {
  carSubtitle,
  carTitle,
  formatMileage,
  formatMoney,
  formatYearMonth,
} from "@/lib/format";

/**
 * Desktop-only listing row.
 *
 * The desktop viewport is wide enough that a card grid wastes horizontal space and
 * makes cars hard to compare: the eye has to jump around a 2D layout. A single
 * column of full-width rows puts every car's specs and price on the same vertical
 * axis, so scanning 16 listings is one straight read down the page.
 *
 * Mobile keeps the card grid (see CarCard) - rows do not fit a narrow viewport.
 */
export const CarRow = ({ car, onOpen }) => {
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();
  const saved = isFavourite(car.id);

  const badges = [];
  if (car.diagnosed)
    badges.push({
      label: t("diagnosed"),
      cls: "bg-[hsl(var(--warning-soft))] text-[hsl(var(--warning))]",
    });
  if (car.has_inspection)
    badges.push({
      label: t("inspected"),
      cls: "bg-[hsl(var(--info-soft))] text-[hsl(var(--info))]",
    });
  if (car.has_record)
    badges.push({
      label: t("insured"),
      cls: "bg-[hsl(var(--success-soft))] text-[hsl(var(--success))]",
    });

  const subtitle = [carSubtitle(car), car.badge_detail_t || car.badge_detail]
    .filter(Boolean)
    .join(" \u00b7 ");

  const specs = [
    {
      key: "year",
      icon: Calendar,
      text: formatYearMonth(car.year_month, car.form_year),
      testId: "car-row-year",
    },
    {
      key: "mileage",
      icon: Gauge,
      text: formatMileage(car.mileage, lang, t("km")),
      testId: "car-row-mileage",
    },
    (car.fuel_type_t || car.fuel_type) && {
      key: "fuel",
      icon: Fuel,
      text: car.fuel_type_t || car.fuel_type,
    },
    (car.region_t || car.region) && {
      key: "region",
      icon: MapPin,
      text: car.region_t || car.region,
    },
  ].filter(Boolean);

  return (
    <article
      data-testid="car-row"
      data-car-id={car.id}
      data-under-contract={car.under_contract ? "true" : "false"}
      className="group relative flex items-stretch gap-4 overflow-hidden rounded-[14px] border border-border bg-card p-3 shadow-[var(--shadow-sm)] transition-shadow duration-200 hover:shadow-[var(--shadow-md)]"
    >
      {car.under_contract && (
        <span data-testid="car-row-contract-ribbon" className="ribbon">
          {t("underContract")}
        </span>
      )}

      {/* thumbnail */}
      <div className="relative w-[236px] shrink-0">
        <button
          type="button"
          data-testid="car-row-open"
          onClick={() => onOpen?.(car)}
          aria-label={`${carTitle(car)} \u2014 ${t("viewDetails")}`}
          className="block w-full cursor-pointer overflow-hidden rounded-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <div className="aspect-video w-full">
            <ImageWithFallback src={car.image} alt={carTitle(car)} testId="car-row-image" />
          </div>
        </button>

        {car.photo_count > 1 && (
          <span className="tnum absolute bottom-1.5 right-1.5 inline-flex items-center gap-1 rounded-full bg-card px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground shadow-[var(--shadow-sm)]">
            <Camera className="h-3 w-3" aria-hidden="true" />
            {car.photo_count}
          </span>
        )}
      </div>

      {/* details */}
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1.5 py-0.5">
        <button
          type="button"
          onClick={() => onOpen?.(car)}
          className="text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          tabIndex={-1}
        >
          <h3
            data-testid="car-row-title"
            className="line-clamp-1 text-[16px] font-semibold leading-tight text-foreground"
          >
            {carTitle(car)}
          </h3>
        </button>

        {subtitle && (
          <p className="line-clamp-1 text-[12.5px] leading-tight text-muted-foreground" title={subtitle}>
            {subtitle}
          </p>
        )}

        <div className="mt-0.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] leading-tight text-muted-foreground">
          {specs.map(({ key, icon: Icon, text, testId }) => (
            <span
              key={key}
              className="tnum inline-flex items-center gap-1.5"
              {...(testId ? { "data-testid": testId } : {})}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {text}
            </span>
          ))}
        </div>

        {badges.length > 0 && (
          <div className="mt-0.5 flex flex-wrap gap-1.5">
            {badges.map((b) => (
              <Badge
                key={b.label}
                className={`rounded-full border-0 px-2 py-0 text-[10.5px] font-medium leading-[17px] ${b.cls}`}
              >
                {b.label}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* price + actions, pinned right so every row lines up on the same axis */}
      <div className="flex w-[200px] shrink-0 flex-col items-end justify-center gap-2 border-l border-border pl-4">
        <button
          type="button"
          data-testid="car-row-save-button"
          onClick={(e) => {
            e.stopPropagation();
            toggleFavourite(car.id);
          }}
          aria-label={saved ? t("saved") : t("save")}
          aria-pressed={saved}
          className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card shadow-[var(--shadow-sm)] transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

        <div className="mt-6 text-right leading-none">
          <div
            data-testid="car-row-price"
            className="tnum text-[22px] font-semibold tracking-tight text-foreground"
          >
            {formatMoney(car.sale_eur, currency, lang, rates)}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">{t("finalPrice")}</div>
        </div>

        <Button
          data-testid="car-row-details-button"
          onClick={() => onOpen?.(car)}
          className="h-9 w-full rounded-[9px] bg-[hsl(var(--primary))] px-3 text-[13px] font-medium text-primary-foreground transition-all hover:brightness-110"
        >
          {t("viewDetails")}
        </Button>
      </div>
    </article>
  );
};

export default CarRow;
