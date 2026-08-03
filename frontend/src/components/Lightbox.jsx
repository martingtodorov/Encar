import React, { useEffect, useCallback, useRef } from "react";
import { X, ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Fullscreen image lightbox with keyboard navigation + thumbnail strip.
 * Supplied by the owner from their own codebase and used here for the DESKTOP viewer;
 * the phone keeps the vertical photo column, which reads better on a small screen.
 *
 * Navigation: arrow buttons, thumbnail clicks, keyboard arrows, horizontal swipe, mouse
 * drag and a trackpad two-finger horizontal swipe. Pinch-to-zoom stays enabled on the
 * image itself, and a swipe is suppressed while a pinch is in flight or the viewport is
 * already zoomed, so panning a zoomed photo never advances to the next one.
 *
 * Props:
 *  - images: string[] (full-resolution URLs)
 *  - thumbnails?: string[] (smaller tier for the strip)
 *  - index: number
 *  - onClose: () => void
 *  - onChange: (newIndex: number) => void
 */
export default function Lightbox({ images, thumbnails, index, onClose, onChange, label = "" }) {
  const total = images?.length || 0;
  const stripRef = useRef(null);

  const prev = useCallback(() => {
    if (!total) return;
    onChange((index - 1 + total) % total);
  }, [index, total, onChange]);

  const next = useCallback(() => {
    if (!total) return;
    onChange((index + 1) % total);
  }, [index, total, onChange]);

  // ── Touch swipe ───────────────────────────────────────────────────
  const swipeRef = useRef({ startX: 0, startY: 0, active: false });

  const onTouchStart = useCallback((e) => {
    if (e.touches.length !== 1) {
      swipeRef.current.active = false;
      return;
    }
    const scale = window.visualViewport?.scale ?? 1;
    if (scale > 1.05) {
      swipeRef.current.active = false;
      return;
    }
    swipeRef.current = {
      startX: e.touches[0].clientX,
      startY: e.touches[0].clientY,
      active: true,
    };
  }, []);

  const onTouchMove = useCallback((e) => {
    if (e.touches.length > 1) swipeRef.current.active = false;
  }, []);

  const onTouchEnd = useCallback((e) => {
    const s = swipeRef.current;
    if (!s.active) return;
    swipeRef.current.active = false;
    const touch = e.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - s.startX;
    const dy = touch.clientY - s.startY;
    if (Math.abs(dx) < 40) return;
    if (Math.abs(dx) < Math.abs(dy) * 1.2) return;
    if (dx < 0) next();
    else prev();
  }, [prev, next]);

  // ── Mouse drag: same gesture model as touch ───────────────────────
  const dragRef = useRef({ startX: 0, startY: 0, active: false });

  const onMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, active: true };
  }, []);

  const onMouseUp = useCallback((e) => {
    const s = dragRef.current;
    if (!s.active) return;
    dragRef.current.active = false;
    const dx = e.clientX - s.startX;
    const dy = e.clientY - s.startY;
    if (Math.abs(dx) < 40) return;
    if (Math.abs(dx) < Math.abs(dy) * 1.2) return;
    if (dx < 0) next();
    else prev();
  }, [prev, next]);

  const onMouseLeave = useCallback(() => {
    dragRef.current.active = false;
  }, []);

  // ── Trackpad horizontal wheel, with a cooldown so one fling moves one photo ──
  const wheelRef = useRef({ accum: 0, cooldownUntil: 0 });

  const onWheel = useCallback((e) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    e.preventDefault();
    const now = performance.now();
    if (now < wheelRef.current.cooldownUntil) return;
    wheelRef.current.accum += e.deltaX;
    if (Math.abs(wheelRef.current.accum) >= 80) {
      if (wheelRef.current.accum < 0) prev();
      else next();
      wheelRef.current.accum = 0;
      wheelRef.current.cooldownUntil = now + 400;
    }
  }, [prev, next]);

  useEffect(() => {
    wheelRef.current.accum = 0;
  }, [index]);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "ArrowRight") next();
    };
    document.addEventListener("keydown", handler);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = prevOverflow;
    };
  }, [prev, next, onClose]);

  // Keep the active thumbnail in view.
  useEffect(() => {
    const strip = stripRef.current;
    if (!strip || index == null) return;
    const active = strip.querySelector(`[data-thumb-idx="${index}"]`);
    if (active?.scrollIntoView) {
      active.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  }, [index]);

  // React's onWheel is passive, so preventDefault() would be ignored: the wheel listener
  // has to be attached by hand with {passive:false}.
  const stageRef = useRef(null);
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  if (!total || index == null) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex select-none flex-col items-center justify-between bg-black/95"
      onClick={onClose}
      data-testid="lightbox"
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20"
        aria-label="Close"
        data-testid="lightbox-close"
      >
        <X size={22} />
      </button>

      <div className="absolute left-1/2 top-5 z-10 -translate-x-1/2 font-mono text-sm text-white/80">
        {index + 1} / {total}
      </div>

      <div
        ref={stageRef}
        className="flex min-h-0 w-full flex-1 cursor-grab items-center justify-center overflow-auto px-4 pb-2 pt-14 active:cursor-grabbing"
        data-allow-pinch-zoom="1"
        style={{ touchAction: "pinch-zoom" }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      >
        <img
          src={images[index]}
          alt={label ? `${label} — ${index + 1}/${total}` : `Photo ${index + 1} of ${total}`}
          className="max-h-full max-w-full object-contain"
          data-testid="lightbox-image"
          draggable={false}
          decoding="async"
        />
      </div>

      {total > 1 && (
        <>
          <button
            onClick={(e) => {
              e.stopPropagation();
              prev();
            }}
            className="absolute left-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 sm:left-4 sm:h-14 sm:w-14"
            aria-label="Previous photo"
            data-testid="lightbox-prev"
          >
            <ChevronLeft size={28} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              next();
            }}
            className="absolute right-2 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 sm:right-4 sm:h-14 sm:w-14"
            aria-label="Next photo"
            data-testid="lightbox-next"
          >
            <ChevronRight size={28} />
          </button>
        </>
      )}

      {total > 1 && (
        <div
          ref={stripRef}
          onClick={(e) => e.stopPropagation()}
          className="flex w-full gap-2 overflow-x-auto overflow-y-hidden border-t border-white/10 bg-black/70 px-3 py-2.5 scroll-smooth backdrop-blur-sm"
          style={{ scrollbarWidth: "thin" }}
          data-testid="lightbox-strip"
        >
          {images.map((src, i) => (
            <button
              key={i}
              type="button"
              data-thumb-idx={i}
              onClick={(e) => {
                e.stopPropagation();
                onChange(i);
              }}
              className={`relative h-14 w-20 shrink-0 overflow-hidden rounded border-2 transition sm:h-16 sm:w-24 ${
                i === index ? "border-white" : "border-transparent opacity-60 hover:opacity-100"
              }`}
              aria-label={`Photo ${i + 1}`}
              data-testid={`lightbox-thumb-${i}`}
            >
              <img
                src={(thumbnails && thumbnails[i]) || src}
                alt=""
                loading="lazy"
                decoding="async"
                className="h-full w-full object-cover"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
