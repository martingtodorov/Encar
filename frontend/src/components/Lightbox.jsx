import React, { useEffect, useCallback, useRef, useState } from "react";
import { X, ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";

/**
 * Fullscreen image lightbox: one big photo, thumbnail strip, keyboard/swipe navigation.
 *
 * ZOOM IS OURS, NOT THE BROWSER'S. The stage is `touch-action: none` and iOS Safari's
 * `gesture*` events are cancelled, so the page itself never scales — what used to happen
 * was the whole document zooming, which dragged the strip and the close button off screen
 * and left the visitor stranded with no way back. In their place:
 *
 *   * pinch  — scales around the midpoint of the two fingers
 *   * double tap / double click — steps to 2.5x centred on the point tapped, and back
 *   * one finger while zoomed — pans, clamped so the photo's edge never travels inside
 *     the frame; while at 1x the same gesture is a swipe to the next photo
 *
 * Navigation: arrow buttons, thumbnail clicks, keyboard arrows, swipe, mouse drag and a
 * trackpad two-finger horizontal swipe. Swiping is suppressed while zoomed, so panning a
 * zoomed photo never jumps to the next one.
 *
 * Props:
 *  - images: string[] (full-resolution URLs)
 *  - thumbnails?: string[] (smaller tier for the strip)
 *  - index: number
 *  - onClose: () => void
 *  - onChange: (newIndex: number) => void
 */
const MAX_SCALE = 4;
const STEP_SCALE = 2.5;
const ZOOMED = 1.05;        // above this we treat the photo as zoomed
const DOUBLE_TAP_MS = 300;
const IDENTITY = { s: 1, x: 0, y: 0 };

export default function Lightbox({ images, thumbnails, index, onClose, onChange, label = "" }) {
  const total = images?.length || 0;
  const stripRef = useRef(null);
  const stageRef = useRef(null);
  const imgRef = useRef(null);

  const [zoom, setZoom] = useState(IDENTITY);
  // Only the discrete double-tap step is animated; a pinch or pan must track the fingers.
  const [gliding, setGliding] = useState(false);
  // The AUTHORITATIVE zoom during a gesture. Gesture handlers write it synchronously and
  // mirror it into state for rendering: a ref synced by an effect lags one render behind,
  // and when touchmove + touchend arrive in the same task (a quick pinch) `touchend` read
  // the stale 1x, decided the photo was not zoomed, and threw the pinch away.
  const zoomRef = useRef(IDENTITY);
  const applyZoom = useCallback((next) => {
    zoomRef.current = next;
    setZoom(next);
  }, []);

  const prev = useCallback(() => {
    if (!total) return;
    onChange((index - 1 + total) % total);
  }, [index, total, onChange]);

  const next = useCallback(() => {
    if (!total) return;
    onChange((index + 1) % total);
  }, [index, total, onChange]);

  // A new photo always starts unzoomed.
  useEffect(() => {
    setGliding(false);
    applyZoom(IDENTITY);
  }, [index]);

  // ── zoom maths ────────────────────────────────────────────────────
  // Keep the photo's own edges outside the frame: `offsetWidth/Height` is the UNSCALED
  // rendered size, so half the overflow is exactly how far it may travel.
  const clamp = useCallback((z) => {
    const s = Math.min(Math.max(z.s, 1), MAX_SCALE);
    const img = imgRef.current;
    if (!img || s <= 1) return IDENTITY;
    const maxX = (img.offsetWidth * (s - 1)) / 2;
    const maxY = (img.offsetHeight * (s - 1)) / 2;
    return {
      s,
      x: Math.min(Math.max(z.x, -maxX), maxX),
      y: Math.min(Math.max(z.y, -maxY), maxY),
    };
  }, []);

  // Point coordinates relative to the CENTRE of the stage, which is what a
  // centre-origin transform is measured from.
  const stagePoint = useCallback((clientX, clientY) => {
    const el = stageRef.current;
    if (!el) return [0, 0];
    const r = el.getBoundingClientRect();
    return [clientX - r.left - r.width / 2, clientY - r.top - r.height / 2];
  }, []);

  // The transform maps q -> s*q + t. To hold the point `p` still while the scale goes
  // from s0 to s1: t1 = p - (s1/s0)(p - t0). Anything else and the photo slides out
  // from under the finger.
  const zoomTo = useCallback((px, py, target, from) => {
    const z0 = from || zoomRef.current;
    const s = Math.min(Math.max(target, 1), MAX_SCALE);
    const k = s / z0.s;
    return clamp({ s, x: px - k * (px - z0.x), y: py - k * (py - z0.y) });
  }, [clamp]);

  const toggleZoomAt = useCallback((clientX, clientY) => {
    const [px, py] = stagePoint(clientX, clientY);
    setGliding(true);
    applyZoom(zoomRef.current.s > ZOOMED ? IDENTITY : zoomTo(px, py, STEP_SCALE));
  }, [stagePoint, zoomTo]);

  // ── touch gestures ────────────────────────────────────────────────
  // Attached by hand: React registers touchstart/touchmove passively at the root, where
  // preventDefault() is ignored, and without it iOS still tries to scroll the page.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return undefined;
    const g = {
      mode: null,
      startDist: 1,
      startZoom: IDENTITY,
      mid: [0, 0],
      startX: 0,
      startY: 0,
      lastTap: 0,
      lastTapAt: [0, 0],
    };
    const spread = (touches) =>
      Math.hypot(
        touches[0].clientX - touches[1].clientX,
        touches[0].clientY - touches[1].clientY
      ) || 1;

    const onStart = (e) => {
      if (e.touches.length === 2) {
        g.mode = "pinch";
        g.startDist = spread(e.touches);
        g.startZoom = zoomRef.current;
        g.mid = stagePoint(
          (e.touches[0].clientX + e.touches[1].clientX) / 2,
          (e.touches[0].clientY + e.touches[1].clientY) / 2
        );
        setGliding(false);
        e.preventDefault();
        return;
      }
      if (e.touches.length !== 1) {
        g.mode = null;
        return;
      }
      const t = e.touches[0];
      const now = performance.now();
      const nearLast =
        Math.hypot(t.clientX - g.lastTapAt[0], t.clientY - g.lastTapAt[1]) < 40;
      if (now - g.lastTap < DOUBLE_TAP_MS && nearLast) {
        g.lastTap = 0;
        g.mode = null;
        toggleZoomAt(t.clientX, t.clientY);
        e.preventDefault();
        return;
      }
      g.lastTap = now;
      g.lastTapAt = [t.clientX, t.clientY];
      g.mode = zoomRef.current.s > ZOOMED ? "pan" : "swipe";
      g.startX = t.clientX;
      g.startY = t.clientY;
      g.startZoom = zoomRef.current;
      setGliding(false);
    };

    const onMove = (e) => {
      if (g.mode === "pinch" && e.touches.length === 2) {
        const target = g.startZoom.s * (spread(e.touches) / g.startDist);
        applyZoom(zoomTo(g.mid[0], g.mid[1], target, g.startZoom));
        e.preventDefault();
        return;
      }
      if (g.mode === "pan" && e.touches.length === 1) {
        const t = e.touches[0];
        applyZoom(clamp({
          s: g.startZoom.s,
          x: g.startZoom.x + (t.clientX - g.startX),
          y: g.startZoom.y + (t.clientY - g.startY),
        }));
        e.preventDefault();
        return;
      }
      // A second finger landing mid-swipe cancels the swipe rather than flicking a photo.
      if (e.touches.length > 1 && g.mode === "swipe") g.mode = null;
    };

    const onEnd = (e) => {
      const mode = g.mode;
      g.mode = null;
      if (mode === "pinch") {
        // Pinched back to (or below) 1x: settle exactly on centre.
        if (zoomRef.current.s <= ZOOMED) {
          setGliding(true);
          applyZoom(IDENTITY);
        }
        return;
      }
      if (mode !== "swipe") return;
      const t = e.changedTouches?.[0];
      if (!t) return;
      const dx = t.clientX - g.startX;
      const dy = t.clientY - g.startY;
      if (Math.abs(dx) < 40) return;
      if (Math.abs(dx) < Math.abs(dy) * 1.2) return;
      if (dx < 0) next();
      else prev();
    };

    // macOS Safari does NOT report a trackpad pinch as ctrl+wheel the way Chrome and
    // Firefox do — it sends `gesture*` events carrying an absolute `scale`. Cancelling
    // them stops Safari zooming the page; driving our own transform from `e.scale` is
    // what makes the pinch actually work there. Skipped while a touch pinch is running
    // (iOS fires BOTH families for the same two fingers) so the zoom is not applied twice.
    const onGestureStart = (e) => {
      e.preventDefault();
      if (g.mode === "pinch") return;
      g.mode = "gesture";
      g.startZoom = zoomRef.current;
      g.mid = stagePoint(e.clientX, e.clientY);
      setGliding(false);
    };

    const onGestureChange = (e) => {
      e.preventDefault();
      if (g.mode !== "gesture") return;
      applyZoom(zoomTo(g.mid[0], g.mid[1], g.startZoom.s * (e.scale || 1), g.startZoom));
    };

    const onGestureEnd = (e) => {
      e.preventDefault();
      if (g.mode !== "gesture") return;
      g.mode = null;
      if (zoomRef.current.s <= ZOOMED) {
        setGliding(true);
        applyZoom(IDENTITY);
      }
    };

    el.addEventListener("touchstart", onStart, { passive: false });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd, { passive: false });
    el.addEventListener("touchcancel", onEnd, { passive: false });
    el.addEventListener("gesturestart", onGestureStart, { passive: false });
    el.addEventListener("gesturechange", onGestureChange, { passive: false });
    el.addEventListener("gestureend", onGestureEnd, { passive: false });
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
      el.removeEventListener("gesturestart", onGestureStart);
      el.removeEventListener("gesturechange", onGestureChange);
      el.removeEventListener("gestureend", onGestureEnd);
    };
  }, [next, prev, clamp, zoomTo, stagePoint, toggleZoomAt]);

  // ── Mouse: drag swipes at 1x, pans when zoomed; double click steps the zoom ──
  const dragRef = useRef({ startX: 0, startY: 0, mode: null, startZoom: IDENTITY });

  const onMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      mode: zoomRef.current.s > ZOOMED ? "pan" : "swipe",
      startZoom: zoomRef.current,
    };
    setGliding(false);
  }, []);

  const onMouseMove = useCallback((e) => {
    const s = dragRef.current;
    if (s.mode !== "pan") return;
    applyZoom(clamp({
      s: s.startZoom.s,
      x: s.startZoom.x + (e.clientX - s.startX),
      y: s.startZoom.y + (e.clientY - s.startY),
    }));
  }, [clamp]);

  const onMouseUp = useCallback((e) => {
    const s = dragRef.current;
    dragRef.current.mode = null;
    if (s.mode !== "swipe") return;
    const dx = e.clientX - s.startX;
    const dy = e.clientY - s.startY;
    if (Math.abs(dx) < 40) return;
    if (Math.abs(dx) < Math.abs(dy) * 1.2) return;
    if (dx < 0) next();
    else prev();
  }, [prev, next]);

  const onMouseLeave = useCallback(() => {
    dragRef.current.mode = null;
  }, []);

  // ── Trackpad horizontal wheel, with a cooldown so one fling moves one photo ──
  const wheelRef = useRef({ accum: 0, cooldownUntil: 0 });

  const onWheel = useCallback((e) => {
    // Horizontal fling stays navigation — that is a trackpad swipe, not a zoom.
    if (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
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
      return;
    }
    // Everything else — plain wheel, and the ctrl+wheel a trackpad pinch sends — zooms
    // towards the cursor. `preventDefault` is what stops the browser zooming the page.
    e.preventDefault();
    const [px, py] = stagePoint(e.clientX, e.clientY);
    // Trackpads report tiny deltas continuously, a wheel reports ~100 per notch: scaling
    // the step by the delta keeps both feeling the same speed.
    const step = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0022));
    setGliding(false);
    applyZoom(zoomTo(px, py, zoomRef.current.s * step));
  }, [prev, next, stagePoint, zoomTo]);

  useEffect(() => {
    wheelRef.current.accum = 0;
  }, [index]);

  // Zoom from the centre of the stage: what the +/- buttons and the keyboard use, since
  // neither carries a cursor position.
  const zoomByStep = useCallback((factor) => {
    setGliding(true);
    applyZoom(zoomTo(0, 0, zoomRef.current.s * factor));
  }, [zoomTo]);

  const resetZoom = useCallback(() => {
    setGliding(true);
    applyZoom(IDENTITY);
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "+" || e.key === "=") zoomByStep(1.4);
      else if (e.key === "-" || e.key === "_") zoomByStep(1 / 1.4);
      else if (e.key === "0") resetZoom();
    };
    document.addEventListener("keydown", handler);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = prevOverflow;
    };
  }, [prev, next, onClose, zoomByStep, resetZoom]);

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
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  if (!total || index == null) return null;

  const zoomed = zoom.s > ZOOMED;

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

      {/* Desktop zoom controls. A phone has pinch and double tap, but a mouse-only
          visitor needs something to click, and the readout is also the only cue that the
          photo is zoomed rather than the browser being broken. */}
      <div
        className="absolute bottom-24 left-1/2 z-10 hidden -translate-x-1/2 items-center gap-1 rounded-full border border-white/15 bg-black/60 px-1.5 py-1 backdrop-blur-sm sm:flex"
        onClick={(e) => e.stopPropagation()}
        data-testid="lightbox-zoom-controls"
      >
        <button
          type="button"
          onClick={() => zoomByStep(1 / 1.4)}
          disabled={zoom.s <= 1}
          aria-label="Zoom out"
          data-testid="lightbox-zoom-out"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white transition hover:bg-white/15 disabled:opacity-35"
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          onClick={resetZoom}
          aria-label="Reset zoom"
          data-testid="lightbox-zoom-reset"
          className="min-w-[52px] rounded-full px-2 font-mono text-xs text-white/85 transition hover:bg-white/15"
        >
          {Math.round(zoom.s * 100)}%
        </button>
        <button
          type="button"
          onClick={() => zoomByStep(1.4)}
          disabled={zoom.s >= MAX_SCALE}
          aria-label="Zoom in"
          data-testid="lightbox-zoom-in"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white transition hover:bg-white/15 disabled:opacity-35"
        >
          <Plus size={16} />
        </button>
      </div>

      <div
        ref={stageRef}
        data-testid="lightbox-stage"
        data-zoomed={zoomed ? "true" : "false"}
        className={`flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden px-4 pb-2 pt-14 ${
          zoomed ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"
        }`}
        // `none`: every gesture over the photo is handled here. Left to the browser it
        // would zoom the whole DOCUMENT, which pulls the strip and the close button off
        // screen — the bug this replaces.
        style={{ touchAction: "none" }}
        onClick={(e) => e.stopPropagation()}
        onDoubleClick={(e) => {
          e.stopPropagation();
          toggleZoomAt(e.clientX, e.clientY);
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      >
        <img
          ref={imgRef}
          src={images[index]}
          alt={label ? `${label} — ${index + 1}/${total}` : `Photo ${index + 1} of ${total}`}
          className="max-h-full max-w-full object-contain"
          data-testid="lightbox-image"
          draggable={false}
          decoding="async"
          style={{
            transform: `translate3d(${zoom.x}px, ${zoom.y}px, 0) scale(${zoom.s})`,
            transformOrigin: "center center",
            transition: gliding ? "transform 240ms cubic-bezier(0.22, 0.61, 0.36, 1)" : "none",
            willChange: "transform",
          }}
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
          // Horizontal scroll only: a pinch started on the strip used to zoom the page.
          style={{ scrollbarWidth: "thin", touchAction: "pan-x" }}
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
