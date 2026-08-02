import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";
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
export const PhotoSwiper = ({
  images = [],
  alt = "",
  testId = "photo-swiper",
  index,
  onIndexChange,
  onTap,
  showCount = true,
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
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);

  // Guard against a parent handing us a shorter list than the current index.
  useEffect(() => {
    if (active > slides.length - 1) setActive(Math.max(0, slides.length - 1));
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

      {slides.length > 1 && (
        <>
          <div
            className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center gap-1.5"
            aria-hidden="true"
          >
            {slides.map((_, n) => (
              <span
                key={n}
                className={`h-1.5 rounded-full transition-all duration-200 ${
                  n === active ? "w-4 bg-white" : "w-1.5 bg-white/55"
                }`}
                style={{ boxShadow: "0 1px 3px rgba(0,0,0,.45)" }}
              />
            ))}
          </div>
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
