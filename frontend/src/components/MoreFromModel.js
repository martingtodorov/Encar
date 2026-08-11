import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { CarCard } from "@/components/CarCard";
import { useApp } from "@/context/AppContext";
import { getMoreFromModel } from "@/lib/api";

/**
 * "More from this model" - a strict same-make + same-model shelf.
 *
 * Distinct from `YouMightLike`, which blends taste with the current car; here the
 * shopper's clear signal is the ad in front of them, so we only pull other listings
 * of the exact same model (curation-aware on the backend). Two cars minimum before
 * the shelf renders - a lonely single card is worse than nothing.
 */
export const MoreFromModel = ({ carId, onOpen }) => {
  const { t, lang } = useApp();
  const [items, setItems] = useState([]);
  const [modelLabel, setModelLabel] = useState("");
  const strip = useRef(null);

  useEffect(() => {
    if (!carId) return undefined;
    let alive = true;
    getMoreFromModel(carId, lang, 12)
      .then((d) => {
        if (!alive) return;
        setItems(d.items || []);
        setModelLabel(d.model_t || d.model || "");
      })
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [carId, lang]);

  const nudge = (dir) => {
    const el = strip.current;
    if (el) el.scrollBy({ left: dir * Math.max(280, el.clientWidth * 0.8), behavior: "smooth" });
  };

  if (items.length < 2) return null;

  return (
    <section data-testid="more-from-model" className="mt-4">
      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-base font-semibold tracking-tight text-foreground md:text-lg">
            {modelLabel
              ? t("moreFromModel", { model: modelLabel })
              : t("moreFromModelFallback")}
          </h2>
          <div className="hidden items-center gap-1.5 sm:flex">
            <button
              type="button"
              data-testid="more-from-model-prev"
              onClick={() => nudge(-1)}
              aria-label={t("shelfPrev")}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid="more-from-model-next"
              onClick={() => nudge(1)}
              aria-label={t("shelfNext")}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div
          ref={strip}
          data-testid="more-from-model-strip"
          className="-mx-4 mt-4 flex gap-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map((item) => (
            <div
              key={item.id}
              data-testid={`more-from-model-card-${item.id}`}
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

export default MoreFromModel;
