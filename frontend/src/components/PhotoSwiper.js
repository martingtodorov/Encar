import { useEffect, useRef, useState } from "react";
import { ArrowRight, Camera, ChevronLeft, ChevronRight } from "lucide-react";
import { ImageWithFallback } from "@/components/ImageWithFallback";

/**
 * Photo swiper built on NATIVE CSS scroll-snap.
 *
 * The gesture, inertia, momentum and the snap animation all come from the browser
 * (`snap-x snap-mandatory` + `snap-start snap-always`), which is why it feels right on a
 * phone and on a Mac trackpad without a single line of animation code. It also gets
 * two-finger horizontal trackpad scrolling and shift+wheel for free. Only three things
 * need JavaScript:
 *   1. tap vs swipe — the browser synthesises a `click` where the finger lifts, so a
 *      swipe would otherwise open the car. A 6px horizontal threshold marks the gesture
 *      as a swipe and the click is swallowed in the CAPTURE phase, before it can reach
 *      the card underneath.
 *   2. which slide is showing — an IntersectionObserver at 0.55 instead of a scroll
 *      listener, so the dot never flickers mid-swipe.
 *   3. arrows must win over the observer while their smooth scroll is running, otherwise
 *      twelve quick clicks only advance five slides (the observer reports every slide the
 *      animation passes through and each report restarts the scroll).
 *
 * `touch-action: pan-x pan-y` is deliberate: with `pan-x` alone the page stops scrolling
 * vertically as soon as a finger lands on a photo, which in a long result list feels
 * broken. `overscroll-behavior-x: contain` stops a trackpad flick past the first photo
 * from triggering the browser's back gesture.
 */
const DOT = 6;      // dot diameter in px
const GAP = 6;      // gap between dots in px
const WINDOW = 5;   // most dots ever shown at once
const SWIPE_PX = 6; // below this a gesture is a tap, above it a swipe
const SCROLL_MS = 900; // `scrollend` fallback for browsers without it (Safari < 18)

/**
 * Instagram-style dot rail: never more than five dots on screen. Longer galleries slide
 * the rail so the active dot stays centred, which animates as you swipe.
 */
const DotRail = ({ count, active }) => {
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
                width: DOT,
                height: DOT,
                background: "#fff",
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

const ARROW =
  // `group/card` as well as `group/photos`: on a result card the arrows appear as soon as
  // the pointer is anywhere on the card, not only over the photo itself.
  "absolute top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur-sm transition-opacity duration-200 hover:bg-black/65 focus-visible:opacity-100 group-hover/photos:opacity-100 group-hover/card:opacity-100 disabled:opacity-0 lg:flex";

export const PhotoSwiper = ({
  images = [],
  alt = "",
  testId = "photo-swiper",
  index,
  onIndexChange,
  onTap,
  showCount = true,
  countOnHover = false,
  hint = "",
  arrows = false,
  ctaLabel = "",
  ctaHint = "",
  onCtaReached,
  className = "",
}) => {
  const photos = images.filter(Boolean);
  // A final CTA panel instead of one more photo: the card carries just enough of the car to
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
  // While an arrow or a thumbnail is driving the scroller, IT is the source of truth and
  // the observer stays quiet until the animation ends.
  const driving = useRef(false);
  const target = useRef(null);
  const timer = useRef(null);

  // Only the first photo is fetched up front (it is the LCP candidate). From then on we
  // keep exactly ONE photo ahead of the visitor warm: standing on 14 downloads 15, so the
  // next swipe paints instantly instead of flashing a placeholder. Slides already seen stay
  // mounted, so going back is free, but a 24-photo car never downloads all 24 at once.
  const [reach, setReach] = useState(0);
  const prime = () => setReach((r) => Math.max(r, 1));

  useEffect(() => {
    setReach((r) => Math.max(r, active + 1));
  }, [active]);

  // The images are `loading="lazy"`, so mounting the next slide is not enough — an
  // off-screen one waits until it is nearly in view. This starts the fetch for real.
  const nextSrc = photos[active + 1];
  useEffect(() => {
    if (!nextSrc) return;
    const img = new Image();
    img.decoding = "async";
    img.src = nextSrc;
  }, [nextSrc]);

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
        if (driving.current) return;
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

  useEffect(() => () => clearTimeout(timer.current), []);

  // Swiping to the last photo already says the visitor is interested, so the car is warmed
  // in the background from that slide on, exactly as it is on hover.
  useEffect(() => {
    if (hasCta && active >= ctaIndex - 1) onCtaReachedRef.current?.();
  }, [active, ctaIndex, hasCta]);

  const glide = (n) => {
    const el = scroller.current;
    if (!el) return;
    setReach((r) => Math.max(r, n + 1));
    target.current = n;
    driving.current = true;
    el.scrollTo({ left: n * el.clientWidth, behavior: "smooth" });

    const done = () => {
      driving.current = false;
      target.current = null;
    };
    clearTimeout(timer.current);
    timer.current = setTimeout(done, SCROLL_MS);
    el.addEventListener("scrollend", done, { once: true });
  };

  // Follow an index chosen from outside (the detail page's thumbnail column).
  useEffect(() => {
    const el = scroller.current;
    if (!el || driving.current) return;
    if (Math.abs(el.scrollLeft - active * el.clientWidth) > el.clientWidth * 0.5) {
      glide(active);
    }
  }, [active]);

  if (count === 0) {
    return (
      <div className={`h-full w-full ${className}`}>
        <ImageWithFallback src={null} alt={alt} testId={`${testId}-image`} />
      </div>
    );
  }

  // Steps from the slide the arrows are already heading for, so rapid clicks add up
  // instead of fighting the animation in flight.
  const step = (dir) => {
    const from = target.current ?? active;
    const n = Math.min(count - 1, Math.max(0, from + dir));
    if (n !== from) {
      emit(n);
      glide(n);
    }
  };

  return (
    <div
      data-testid={testId}
      className={`group/photos relative h-full w-full overflow-hidden ${className}`}
      onMouseEnter={prime}
      onPointerDown={prime}
    >
      <div
        ref={scroller}
        data-testid={`${testId}-track`}
        className="no-scrollbar absolute inset-0 flex snap-x snap-mandatory overflow-x-auto overflow-y-hidden"
        style={{
          touchAction: "pan-x pan-y",
          overscrollBehaviorX: "contain",
          scrollbarWidth: "none",
        }}
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
            {n === 0 || n <= reach ? (
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
            className={`${ARROW} left-3`}
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
            className={`${ARROW} right-3`}
          >
            <ChevronRight className="h-5 w-5" aria-hidden="true" />
          </button>
        </>
      )}

      {count > 1 && (
        <>
          <DotRail count={count} active={active} />
          {showCount && active !== ctaIndex && (
            <span
              data-testid={`${testId}-counter`}
              className={
                countOnHover
                  ? "tnum pointer-events-none absolute bottom-3 right-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-medium text-white transition-opacity duration-200 lg:opacity-0 lg:group-hover/photos:opacity-100"
                  : "tnum pointer-events-none absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white"
              }
            >
              {!countOnHover && <Camera className="h-3 w-3" aria-hidden="true" />}
              {active + 1}/{photos.length}
              {hint && <span className="hidden lg:inline">· {hint}</span>}
            </span>
          )}
        </>
      )}
    </div>
  );
};

export default PhotoSwiper;
