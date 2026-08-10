import { useEffect, useRef, useState } from "react";
import { CarCard } from "@/components/CarCard";
import { useApp } from "@/context/AppContext";
import { countRecoClick, getRecommendations } from "@/lib/api";
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
  // `null` while the fetch is in flight, [] after a genuinely empty answer, [...] on results.
  // The distinction matters: hiding the shelf as soon as `items` is [] pushes the whole grid
  // up 300 px when results arrive milliseconds later, and Lighthouse counted that jump as
  // 0.166 CLS (biggest single layout shift on the page).
  const [done, setDone] = useState(false);
  // Only the owner's hand-picked shelf is measured: a click on the popular list says nothing
  // about a choice the owner made.
  const [curated, setCurated] = useState(false);
  // The last language a fetch was successfully STARTED for. React 18's StrictMode double-
  // fires effects in dev and, in prod, an AppContext re-render toggled the `lang` dependency
  // briefly enough to run this twice back to back - the second response replaced the first,
  // every card in the shelf remounted, and every in-flight image request from the first
  // render was aborted mid-download. The visitor saw "impossible to load" images that were
  // actually loaded fine and then thrown away. One request per language, once and for all.
  const inflightLang = useRef(null);

  useEffect(() => {
    if (!lang || inflightLang.current === lang) return;
    inflightLang.current = lang;

    let alive = true;
    setDone(false);
    getRecommendations({ ...getTaste(), lang, limit: 12 })
      .then((d) => {
        if (!alive) return;
        setItems(d.items || []);
        setCurated(d.source === "curated");
      })
      .catch(() => alive && setItems([]))
      .finally(() => alive && setDone(true));
    return () => {
      alive = false;
    };
  }, [lang]);

  const open = (car) => {
    if (curated) countRecoClick(car.id);
    onOpen?.(car);
  };

  // Only hide once the fetch has definitively returned zero cars. While it is in flight the
  // section carries a same-height placeholder so the grid below never leaps.
  if (done && !items.length) return null;

  return (
    <section data-testid="recommended" className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1280px] px-4 py-4 sm:px-6 sm:py-7">
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
          className="-mx-4 mt-3 flex gap-4 sm:mt-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.length
            ? items.map((car, i) => (
                <div
                  key={car.id}
                  data-testid={`recommended-card-${car.id}`}
                  className="w-[280px] shrink-0 sm:w-[300px]"
                >
                  {/* The first four cards are above the fold on every viewport wider than
                      ~1024 CSS px. Marking them all eager (rather than only i === 0) is
                      what Lighthouse's "LCP resources should not use loading=lazy" audit
                      wants: the LCP image is whichever card the browser paints biggest,
                      and that is not always index 0 when the shelf renders in a single
                      wide row. `fetchpriority="high"` only applies to the very first so
                      bandwidth is not shared across four "high" images. */}
                  <CarCard
                    car={car}
                    onOpen={open}
                    showRegion={false}
                    eager={i < 4}
                    priority={i === 0}
                  />
                </div>
              ))
            : /* A placeholder tile reserves the height (aspect-video + body ≈ 300 px)
                 so the section holds space while /api/reco resolves. Six cards is what
                 the strip almost always returns, so the placeholder width matches. */
              Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={`ph-${i}`}
                  className="w-[280px] shrink-0 sm:w-[300px]"
                  aria-hidden="true"
                >
                  <div className="overflow-hidden rounded-[14px] border border-border bg-card">
                    <div className="aspect-video w-full bg-muted" />
                    <div className="flex h-[110px] flex-col gap-2 p-2.5">
                      <div className="h-4 w-2/3 rounded bg-muted" />
                      <div className="h-3 w-1/2 rounded bg-muted" />
                      <div className="mt-auto h-5 w-1/3 rounded bg-muted" />
                    </div>
                  </div>
                </div>
              ))}
        </div>
      </div>
    </section>
  );
};

export default Recommended;
