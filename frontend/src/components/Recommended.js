import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { CarCard } from "@/components/CarCard";
import { useApp } from "@/context/AppContext";
import { getRecommendations } from "@/lib/api";
import { getTaste, hasTaste } from "@/lib/taste";

/**
 * "Picked for you" — the landing row built from this visitor's own 90-day profile.
 * Renders nothing at all until there is real signal, so a first-time visitor never sees
 * an empty or randomly filled shelf.
 */
export const Recommended = ({ onOpen }) => {
  const { t, lang } = useApp();
  const [items, setItems] = useState([]);

  useEffect(() => {
    if (!hasTaste()) return;
    let alive = true;
    getRecommendations({ ...getTaste(), lang, limit: 12 })
      .then((d) => alive && setItems(d.items || []))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [lang]);

  if (!items.length) return null;

  return (
    <section data-testid="recommended" className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1280px] px-4 py-7 sm:px-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
              <Sparkles className="h-4 w-4 text-[hsl(var(--accent))]" aria-hidden="true" />
              {t("recoTitle")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("recoSubtitle")}</p>
          </div>
        </div>

        {/* One swipeable shelf on every screen size: the same scroll-snap language the
            photo galleries use, so the gesture is already learned. */}
        <div
          data-testid="recommended-strip"
          className="-mx-4 mt-4 flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map((car) => (
            <div
              key={car.id}
              data-testid={`recommended-card-${car.id}`}
              className="w-[280px] shrink-0 snap-start sm:w-[300px]"
            >
              <CarCard car={car} onOpen={onOpen} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Recommended;
