import { useEffect, useRef, useState } from "react";
import { Camera, ChevronLeft, ChevronRight } from "lucide-react";
import { ImageWithFallback } from "@/components/ImageWithFallback";

/**
 * Finger-tracking photo swiper.
 *
 * The track follows the pointer 1:1 while dragging (no snap-on-touch feeling), then
 * animates to the nearest slide on release. A short drag that barely moves counts as a
 * tap, so the same surface can still open the car.
 *
 * `touch-action: pan-y` keeps vertical page scrolling working: only horizontal intent
 * is captured, which matters because these sit inside a long scrolling result list.
 */
const DOT = 6;      // dot diameter in px
const GAP = 6;      // gap between dots in px
const WINDOW = 5;   // most dots ever shown at once

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
              className="shrink-0 rounded-full bg-white transition-all duration-300"
              style={{
                width: DOT,
                height: DOT,
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
  className = "",
}) => {
  const slides = images.filter(Boolean);
  const [i, setI] = useState(0);
  const active = index === undefined ? i : index;
  const setActive = (n) => {
    if (index === undefined) setI(n);
    onIndexChange?.(n);
  };

  const box = useRef(null);
  const drag = useRef(null);
  const wheel = useRef({ acc: 0, last: 0, locked: false });
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);

  // The wheel listener is registered once, so it must read the current index and setter
  // through refs rather than closing over a stale render.
  const activeRef = useRef(active);
  const setActiveRef = useRef(setActive);
  activeRef.current = active;
  setActiveRef.current = setActive;

  // Guard against a parent handing us a shorter list than the current index.
  useEffect(() => {
    if (active > slides.length - 1) setActive(Math.max(0, slides.length - 1));
  }, [slides.length]);

  // Mac trackpads emit a horizontal wheel for a two-finger sideways swipe, so the same
  // gesture that works on a phone works here. Registered natively because React's onWheel
  // is passive and cannot preventDefault the browser's own sideways scroll. Deltas are
  // accumulated to a threshold with a short cooldown, otherwise one flick would race
  // through the whole gallery.
  useEffect(() => {
    const el = box.current;
    if (!el || slides.length < 2) return;

    const onWheel = (e) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;   // vertical: let the page scroll
      e.preventDefault();
      const w = wheel.current;
      const now = Date.now();
      // A quiet gap means fingers left the pad and came back: a brand new gesture.
      const fresh = now - w.last > 140;
      w.last = now;
      if (fresh) {
        w.acc = 0;
        w.locked = false;
      } else if (w.locked) {
        return;   // still riding the momentum tail of a gesture we already handled
      }
      // A deliberate direction reversal also starts over.
      if (w.acc !== 0 && Math.sign(e.deltaX) !== Math.sign(w.acc)) w.acc = 0;
      w.acc += e.deltaX;
      if (Math.abs(w.acc) < 45) return;
      const step = w.acc > 0 ? 1 : -1;
      w.acc = 0;
      w.locked = true;
      setActiveRef.current(
        Math.min(slides.length - 1, Math.max(0, activeRef.current + step))
      );
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [slides.length]);

  if (slides.length === 0) {
    return (
      <div className={`h-full w-full ${className}`}>
        <ImageWithFallback src={null} alt={alt} testId={`${testId}-image`} />
      </div>
    );
  }

  const width = () => box.current?.offsetWidth || 1;

  const down = (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, t: Date.now(), axis: null };
    setDragging(true);
  };

  const move = (e) => {
    const d = drag.current;
    if (!d) return;
    const mx = e.clientX - d.x;
    const my = e.clientY - d.y;
    // Decide once whether this gesture is a horizontal swipe or a vertical scroll.
    if (!d.axis) {
      if (Math.abs(mx) < 6 && Math.abs(my) < 6) return;
      d.axis = Math.abs(mx) > Math.abs(my) ? "x" : "y";
      if (d.axis === "x") e.currentTarget.setPointerCapture?.(e.pointerId);
    }
    if (d.axis !== "x") return;
    // Rubber-band at the ends so the list feels bounded rather than broken.
    const atEdge = (mx > 0 && active === 0) || (mx < 0 && active === slides.length - 1);
    setDx(atEdge ? mx * 0.35 : mx);
  };

  const up = (e) => {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d) return;

    const moved = Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y);
    if (d.axis !== "x") {
      setDx(0);
      if (moved < 8 && Date.now() - d.t < 500) onTap?.();
      return;
    }

    const travelled = e.clientX - d.x;
    const fast = Math.abs(travelled) / Math.max(1, Date.now() - d.t) > 0.35;
    const far = Math.abs(travelled) > width() * 0.18;
    if ((fast || far) && travelled < 0 && active < slides.length - 1) setActive(active + 1);
    else if ((fast || far) && travelled > 0 && active > 0) setActive(active - 1);
    setDx(0);
  };

  return (
    <div
      ref={box}
      data-testid={testId}
      className={`relative h-full w-full overflow-hidden ${className}`}
      style={{ touchAction: "pan-y" }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
    >
      <div
        className="flex h-full w-full"
        style={{
          transform: `translate3d(calc(${-active * 100}% + ${dx}px), 0, 0)`,
          transition: dragging ? "none" : "transform 320ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        {slides.map((src, n) => (
          <div key={`${src}-${n}`} className="h-full w-full shrink-0">
            <ImageWithFallback
              src={src}
              alt={alt}
              testId={n === 0 ? `${testId}-image` : undefined}
            />
          </div>
        ))}
      </div>

      {slides.length > 1 && arrows && (
        <>
          <button
            type="button"
            data-testid={`${testId}-prev`}
            aria-label="Previous photo"
            disabled={active === 0}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setActive(Math.max(0, active - 1));
            }}
            className="absolute left-2 top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition-opacity hover:bg-black/65 disabled:opacity-0 lg:flex"
          >
            <ChevronLeft className="h-5 w-5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`${testId}-next`}
            aria-label="Next photo"
            disabled={active === slides.length - 1}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setActive(Math.min(slides.length - 1, active + 1));
            }}
            className="absolute right-2 top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-sm transition-opacity hover:bg-black/65 disabled:opacity-0 lg:flex"
          >
            <ChevronRight className="h-5 w-5" aria-hidden="true" />
          </button>
        </>
      )}

      {slides.length > 1 && (
        <>
          <DotRail count={slides.length} active={active} />
          {showCount && (
            <span
              data-testid={`${testId}-counter`}
              className="tnum pointer-events-none absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white"
            >
              <Camera className="h-3 w-3" aria-hidden="true" />
              {active + 1}/{slides.length}
            </span>
          )}
        </>
      )}
    </div>
  );
};

export default PhotoSwiper;
