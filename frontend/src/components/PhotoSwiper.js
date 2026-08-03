import { useEffect, useRef, useState } from "react";
import { ArrowRight, Camera, ChevronLeft, ChevronRight } from "lucide-react";
import { ImageWithFallback } from "@/components/ImageWithFallback";

/**
 * Photo swiper built on NATIVE CSS scroll-snap.
 *
 * The gesture, inertia, momentum and the snap animation all come from the browser
 * (`snap-x snap-mandatory` + `snap-start snap-always`), which is why it feels right on a
 * phone and on a Mac trackpad without a single line of animation code. Only two things
 * need JavaScript:
 *   1. tap vs swipe — the browser synthesises a `click` where the finger lifts, so a
 *      swipe would otherwise open the car. A 6px horizontal threshold marks the gesture
 *      as a swipe and the click is swallowed in the CAPTURE phase, before it can reach
 *      the card underneath.
 *   2. which slide is showing — an IntersectionObserver at 0.55 instead of a scroll
 *      listener, so the dot never flickers mid-swipe.
 *
 * `touch-action: pan-x pan-y` is deliberate: with `pan-x` alone the page stops scrolling
 * vertically as soon as a finger lands on a photo, which in a long result list feels
 * broken.
 */
const DOT = 6;      // dot diameter in px
const GAP = 6;      // gap between dots in px
const WINDOW = 5;   // most dots ever shown at once
const SWIPE_PX = 6; // below this a gesture is a tap, above it a swipe

/**
 * Instagram-style dot rail: never more than five dots on screen. Longer galleries slide
 * the rail so the active dot stays centred, which animates as you swipe.
 */
const DotRail = ({ count, active, ctaIndex }) => {
  const pitch = DOT + GAP;
  const shown = Math.min(WINDOW, count);
  const maxOffset = Math.max(0, count - WINDOW);
  const offset = Math.min(maxOffset, Math.max(0, active - Math.floor(WINDOW / 2)));

  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center"
      aria-hidden="true"
    >
      <div className="overflow-hidden" style={{ width: shown * pitch - GAP }}>
        <div
          className="flex"
          style={{
            gap: GAP,
            transform: `translate3d(${-offset * pitch}px, 0, 0)`,
            transition: "transform 320ms cubic-bezier(0.22, 1, 0.36, 1)",
          }}
        >
          {Array.from({ length: count }).map((_, n) => (
            <span
              key={n}
              className="shrink-0 rounded-full transition-all duration-300"
              style={{
                width: n === ctaIndex && n === active ? DOT * 2 : DOT,
                height: DOT,
                background: n === ctaIndex ? "hsl(var(--primary))" : "#fff",
                boxShadow: "0 1px 3px rgba(0,0,0,.45)",
                opacity: n === active ? 1 : 0.5,
                transform: n === active ? "scale(1)" : "scale(0.72)",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export const PhotoSwiper = ({
  images = [],
  alt = "",
  testId = "photo-swiper",
  index,
  onIndexChange,
  onTap,
  showCount = true,
  arrows = false,
  ctaLabel = "",
  ctaHint = "",
  onCtaReached,
  className = "",
}) => {
  const photos = images.filter(Boolean);
  // A final CTA panel instead of a fifth photo: the card carries just enough of the car to
  // create interest, then hands the visitor a clear way into the listing. Pointless on a
  // single-photo car, so it only appears once there is a deck to swipe.
  const hasCta = Boolean(ctaLabel) && photos.length >= 2;
  const count = photos.length + (hasCta ? 1 : 0);
  const ctaIndex = hasCta ? photos.length : -1;
  const [i, setI] = useState(0);
  const active = index === undefined ? i : index;

  const scroller = useRef(null);
  const start = useRef(null);
  const swiping = useRef(false);
  // Suppresses the follow-the-index effect while our own smooth scroll is still running,
  // otherwise the observer's updates would restart the scroll and it would stutter.
  const lock = useRef(0);

  // Only the first photo is fetched up front (it is the LCP candidate); the rest wait for
  // a sign the visitor is actually interested in this car.
  const [primed, setPrimed] = useState(false);
  const prime = () => setPrimed(true);

  const emit = (n) => {
    if (index === undefined) setI(n);
    onIndexChange?.(n);
  };
  const emitRef = useRef(emit);
  emitRef.current = emit;
  const onCtaReachedRef = useRef(onCtaReached);
  onCtaReachedRef.current = onCtaReached;

  useEffect(() => {
    const root = scroller.current;
    if (!root || count < 2) return;
    const io = new IntersectionObserver(
      (entries) => {
        let best = null;
        entries.forEach((e) => {
          if (!best || e.intersectionRatio > best.intersectionRatio) best = e;
        });
        if (best && best.isIntersecting) {
          emitRef.current(Number(best.target.getAttribute("data-slide-index")));
        }
      },
      { root, threshold: [0.55] }
    );
    root.querySelectorAll("[data-slide-index]").forEach((c) => io.observe(c));
    return () => io.disconnect();
  }, [count]);

  // Swiping to the last photo already says the visitor is interested, so the car is warmed
  // from that slide on (one before the closing CTA panel), exactly as it is on hover.
  useEffect(() => {
    if (hasCta && active >= ctaIndex - 1) onCtaReachedRef.current?.();
  }, [active, ctaIndex, hasCta]);

  // Follow an index chosen from outside (the detail page's thumbnail column).
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (active > 0) setPrimed(true);
    if (Date.now() < lock.current) return;
    const target = active * el.clientWidth;
    if (Math.abs(el.scrollLeft - target) > el.clientWidth * 0.5) {
      lock.current = Date.now() + 450;
      el.scrollTo({ left: target, behavior: "smooth" });
    }
  }, [active]);

  if (count === 0) {
    return (
      <div className={`h-full w-full ${className}`}>
        <ImageWithFallback src={null} alt={alt} testId={`${testId}-image`} />
      </div>
    );
  }

  const step = (dir) => {
    const el = scroller.current;
    if (!el) return;
    setPrimed(true);
    lock.current = Date.now() + 450;
    el.scrollBy({ left: dir * el.clientWidth, behavior: "smooth" });
  };

  return (
    <div
      data-testid={testId}
      className={`relative h-full w-full overflow-hidden ${className}`}
      onMouseEnter={prime}
      onPointerDown={prime}
    >
      <div
        ref={scroller}
        data-testid={`${testId}-track`}
        className="no-scrollbar absolute inset-0 flex snap-x snap-mandatory overflow-x-auto overflow-y-hidden"
        style={{ touchAction: "pan-x pan-y", scrollbarWidth: "none" }}
        onTouchStart={(e) => {
          const t = e.touches[0];
          start.current = { x: t.clientX, y: t.clientY };
          swiping.current = false;
          prime();
        }}
        onTouchMove={(e) => {
          const s = start.current;
          if (!s) return;
          if (Math.abs(e.touches[0].clientX - s.x) > SWIPE_PX) swiping.current = true;
        }}
        onClickCapture={(e) => {
          if (swiping.current) {
            e.preventDefault();
            e.stopPropagation();
            swiping.current = false;
            return;
          }
          onTap?.();
        }}
      >
        {photos.map((src, n) => (
          <div
            key={`${src}-${n}`}
            data-slide-index={n}
            className="h-full w-full shrink-0 snap-start snap-always"
          >
            {n === 0 || primed ? (
              <ImageWithFallback
                src={src}
                alt={alt}
                testId={n === 0 ? `${testId}-image` : undefined}
              />
            ) : (
              <div className="h-full w-full bg-muted" aria-hidden="true" />
            )}
          </div>
        ))}

        {hasCta && (
          <div
            data-slide-index={ctaIndex}
            data-testid={`${testId}-cta`}
            className="flex h-full w-full shrink-0 snap-start snap-always flex-col items-center justify-center gap-1 bg-gradient-to-br from-background to-muted px-6 text-center"
          >
            <ArrowRight className="mb-1 h-8 w-8 text-primary" aria-hidden="true" />
            <span className="text-sm font-semibold text-foreground">{ctaLabel}</span>
            {ctaHint && (
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                {ctaHint}
              </span>
            )}
          </div>
        )}
      </div>

      {count > 1 && arrows && (
        <>
          <button
            type="button"
            data-testid={`${testId}-prev`}
            aria-label="Previous photo"
            disabled={active === 0}
            onClick={(e) => {
              e.stopPropagation();
              step(-1);
            }}
            className="absolute left-2 top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition-opacity hover:bg-black/65 disabled:opacity-0 lg:flex"
          >
            <ChevronLeft className="h-5 w-5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`${testId}-next`}
            aria-label="Next photo"
            disabled={active === count - 1}
            onClick={(e) => {
              e.stopPropagation();
              step(1);
            }}
            className="absolute right-2 top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition-opacity hover:bg-black/65 disabled:opacity-0 lg:flex"
          >
            <ChevronRight className="h-5 w-5" aria-hidden="true" />
          </button>
        </>
      )}

      {count > 1 && (
        <>
          <DotRail count={count} active={active} ctaIndex={ctaIndex} />
          {showCount && active !== ctaIndex && (
            <span
              data-testid={`${testId}-counter`}
              className="tnum pointer-events-none absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white"
            >
              <Camera className="h-3 w-3" aria-hidden="true" />
              {active + 1}/{photos.length}
            </span>
          )}
        </>
      )}
    </div>
  );
};

export default PhotoSwiper;
