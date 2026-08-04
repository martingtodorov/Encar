import { useEffect, useState } from "react";
import { CarCard } from "@/components/CarCard";
import { useApp } from "@/context/AppContext";
import { getRecommendations } from "@/lib/api";
import { getTaste } from "@/lib/taste";

/**
 * "Picked for you" — the landing shelf.
 *
 * The profile lives in a per-device cookie, so a buyer who browsed on a laptop arrives on
 * their phone with nothing: asking for a profile before rendering is exactly why the shelf
 * was missing on mobile. It always asks, and the backend answers with the most opened ads of
 * the fortnight when it has no signal to work with. Only a genuinely empty answer hides it.
 */
export const Recommended = ({ onOpen }) => {
  const { t, lang } = useApp();
  const [items, setItems] = useState([]);

  useEffect(() => {
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
            <h2 className="text-lg font-semibold tracking-tight text-foreground">
              {t("recoTitle")}
            </h2>
          </div>
        </div>

        {/* Free-scrolling shelf: snap points fought the flick gesture on a phone, stopping
            the strip dead on every card. */}
        <div
          data-testid="recommended-strip"
          className="-mx-4 mt-4 flex gap-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map((car) => (
            <div
              key={car.id}
              data-testid={`recommended-card-${car.id}`}
              className="w-[280px] shrink-0 sm:w-[300px]"
            >
              <CarCard car={car} onOpen={onOpen} showRegion={false} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Recommended;
