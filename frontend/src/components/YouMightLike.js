import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { CarCard } from "@/components/CarCard";
import { useApp } from "@/context/AppContext";
import { getRecommendations } from "@/lib/api";
import { getTaste } from "@/lib/taste";

/**
 * "You might also like", under the dealer's description.
 *
 * The shelf on the landing page asks with whatever the device has learned. Here the car in
 * front of them is the strongest signal there is, so it is weighed in on top of that profile —
 * a buyer reading a diesel E-Class gets diesel E-Classes even on their first ever visit, and
 * the backend still falls back to the fortnight's most opened ads if it has nothing at all.
 *
 * Raw upstream values on purpose: the recommender matches `manufacturer` / `model` / `fuel_type`
 * as Encar spells them, not their translations.
 */
const SEED = 4;                       // heavier than a favourite: they are looking at it now

export const YouMightLike = ({ car, excludeId, onOpen }) => {
  const { t, lang } = useApp();
  const [items, setItems] = useState([]);
  const strip = useRef(null);

  const { manufacturer, model, fuel_type: fuel, sale_eur: price, mileage } = car || {};

  useEffect(() => {
    if (!manufacturer) return undefined;
    const taste = getTaste();
    const bump = (map, key) =>
      key ? { ...map, [key]: (map[key] || 0) + SEED } : map;

    let alive = true;
    getRecommendations({
      makes: bump(taste.makes || {}, manufacturer),
      models: bump(taste.models || {}, model),
      fuels: bump(taste.fuels || {}, fuel),
      samples: [[Math.round(price || 0), Math.round(mileage || 0), SEED],
                ...(taste.samples || [])],
      exclude: [excludeId].filter(Boolean),
      lang,
      limit: 12,
    })
      .then((d) => alive && setItems((d.items || []).filter((c) => c.id !== excludeId)))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [manufacturer, model, fuel, price, mileage, excludeId, lang]);

  const nudge = (dir) => {
    const el = strip.current;
    if (el) el.scrollBy({ left: dir * Math.max(280, el.clientWidth * 0.8), behavior: "smooth" });
  };

  if (items.length < 2) return null;

  return (
    <section data-testid="you-might-like" className="mt-4">
      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-base font-semibold tracking-tight text-foreground md:text-lg">
            {t("likeTitle")}
          </h2>
          {/* Arrows are a desktop affordance; a phone flicks the strip. */}
          <div className="hidden items-center gap-1.5 sm:flex">
            <button
              type="button"
              data-testid="you-might-like-prev"
              onClick={() => nudge(-1)}
              aria-label={t("shelfPrev")}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid="you-might-like-next"
              onClick={() => nudge(1)}
              aria-label={t("shelfNext")}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Free-scrolling, no snap points: snapping fights the flick gesture on a phone and
            stops the strip dead on every card. */}
        <div
          ref={strip}
          data-testid="you-might-like-strip"
          className="-mx-4 mt-4 flex gap-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map((item) => (
            <div
              key={item.id}
              data-testid={`you-might-like-card-${item.id}`}
              className="w-[260px] shrink-0 sm:w-[280px]"
            >
              <CarCard car={item} onOpen={onOpen} showRegion={false} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default YouMightLike;
