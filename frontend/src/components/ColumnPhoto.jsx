import { useCallback, useEffect, useRef, useState } from "react";

const MAX = 4;
const DOUBLE_TAP_MS = 300;
const TAP_SLOP = 12;        // a tap that moves more than this was a scroll, not a tap
const DOUBLE_TAP_TO = 2.5;  // what a double tap zooms to
// A stray two-finger touch while scrolling used to leave a photo at 1.05x: invisible, but
// enough to count as zoomed, which froze the column's scrolling and put the photo's own
// full-screen touch layer over the close button. Anything under this snaps back to rest.
const SNAP = 1.2;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/**
 * One photo in the mobile column, zoomable in place.
 *
 * Double tap to zoom in, double tap again to come back out. While zoomed: two fingers change
 * the zoom, one finger moves the photo around, and the column underneath stops scrolling so a
 * drag pans the picture instead of sliding the page. Zooming in also swaps in the FULL
 * resolution file — the column itself is deliberately served at 800px, which is sharp at
 * arm's length but not under a magnifying glass.
 *
 * Written on Pointer Events rather than a library: touch and mouse arrive through the same
 * three handlers, and the browser only ever gets to interpret the gesture itself when the
 * photo is at rest (`touch-action: pan-y`, so the column still scrolls normally). Zoomed in,
 * `touch-action: none` hands every finger to us.
 *
 * Panning is clamped to the photo's own edges — a zoomed photo that can be flung off into
 * grey emptiness feels broken, and getting back is fiddly on a phone.
 */
export const ColumnPhoto = ({
  src,
  zoomSrc,
  thumb,
  alt = "",
  ratio,
  reserve,
  loaded,
  mounted,
  failed,
  priority,
  onSettle,
  onFail,
  onZoom,
  testId,
  index,
  placeholder,
}) => {
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [sharp, setSharp] = useState(false);      // the full-resolution file has arrived
  const boxRef = useRef(null);
  const points = useRef(new Map());
  const gesture = useRef(null);
  const lastTap = useRef({ at: 0, x: 0, y: 0 });

  const zoomed = scale > 1.01;

  useEffect(() => {
    onZoom?.(index, zoomed);
  }, [zoomed, index, onZoom]);

  // The photo always stays in its own slot: the column keeps every photo visible and a
  // zoomed one simply grows OVER its neighbours (the slot drops its clipping and rises on
  // top), so zooming back out leaves the column exactly as it was.
  const surface = useCallback(() => boxRef.current?.getBoundingClientRect(), []);

  // How far the photo may travel before its own edge would leave the window.
  const bounds = useCallback(
    (s) => {
      const box = surface();
      if (!box) return { x: 0, y: 0 };
      return { x: (box.width * (s - 1)) / 2, y: (box.height * (s - 1)) / 2 };
    },
    [surface]
  );

  const apply = useCallback(
    (s, x, y) => {
      const next = clamp(s, 1, MAX);
      const lim = bounds(next);
      setScale(next);
      setPan(
        next <= 1.01
          ? { x: 0, y: 0 }
          : { x: clamp(x, -lim.x, lim.x), y: clamp(y, -lim.y, lim.y) }
      );
    },
    [bounds]
  );

  const reset = useCallback(() => {
    setScale(1);
    setPan({ x: 0, y: 0 });
    setSharp(false);      // next zoom re-checks whether the full file is there
  }, []);

  /** Zoom to `s` keeping the point under the finger where it is. */
  const zoomAt = useCallback(
    (s, clientX, clientY) => {
      const box = surface();
      if (!box) return;
      const cx = clientX - (box.left + box.width / 2);
      const cy = clientY - (box.top + box.height / 2);
      const k = s / scale;
      apply(s, (pan.x - cx) * k + cx, (pan.y - cy) * k + cy);
    },
    [apply, pan.x, pan.y, scale, surface]
  );

  const down = (e) => {
    points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (points.current.size === 2) {
      const [a, b] = [...points.current.values()];
      gesture.current = {
        kind: "pinch",
        dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        scale,
        pan: { ...pan },
      };
    } else if (points.current.size === 1) {
      gesture.current = {
        kind: "drag",
        from: { x: e.clientX, y: e.clientY },
        pan: { ...pan },
        moved: 0,
      };
      if (zoomed) e.currentTarget.setPointerCapture?.(e.pointerId);
    }
  };

  const move = (e) => {
    if (!points.current.has(e.pointerId)) return;
    points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const g = gesture.current;
    if (!g) return;

    if (g.kind === "pinch" && points.current.size >= 2) {
      const [a, b] = [...points.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const next = clamp((g.scale * dist) / g.dist, 1, MAX);
      const box = surface();
      if (!box) return;
      const cx = g.mid.x - (box.left + box.width / 2);
      const cy = g.mid.y - (box.top + box.height / 2);
      const k = next / g.scale;
      apply(next, (g.pan.x - cx) * k + cx, (g.pan.y - cy) * k + cy);
      return;
    }

    if (g.kind === "drag") {
      const dx = e.clientX - g.from.x;
      const dy = e.clientY - g.from.y;
      g.moved = Math.max(g.moved, Math.hypot(dx, dy));
      // At rest the column is scrolling: leave the finger alone.
      if (zoomed) apply(scale, g.pan.x + dx, g.pan.y + dy);
    }
  };

  const up = (e) => {
    points.current.delete(e.pointerId);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    const g = gesture.current;
    if (points.current.size === 0) {
      gesture.current = null;
      // Barely magnified is not magnified: come all the way back so the column scrolls and
      // the close button is reachable again.
      if (scale > 1.01 && scale < SNAP) {
        reset();
        return;
      }
    } else if (points.current.size === 1) {
      // One finger lifted out of a pinch: carry on as a drag from where it is.
      const [only] = [...points.current.values()];
      gesture.current = { kind: "drag", from: only, pan: { ...pan }, moved: 0 };
      return;
    }
    if (!g || g.kind !== "drag" || g.moved > TAP_SLOP) return;

    const now = Date.now();
    const prev = lastTap.current;
    const near = Math.hypot(e.clientX - prev.x, e.clientY - prev.y) < 40;
    if (now - prev.at < DOUBLE_TAP_MS && near) {
      lastTap.current = { at: 0, x: 0, y: 0 };
      if (zoomed) reset();
      else zoomAt(DOUBLE_TAP_TO, e.clientX, e.clientY);
      return;
    }
    lastTap.current = { at: now, x: e.clientX, y: e.clientY };
  };

  const cancel = (e) => {
    points.current.delete(e.pointerId);
    // A capture left behind by an interrupted gesture is one of the ways a phone stops
    // delivering touches at all, so it is released on every exit path.
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (points.current.size === 0) {
      gesture.current = null;
      // iOS cancels touches freely (a notification, an edge swipe). A pinch interrupted
      // halfway must not leave the photo stuck barely-zoomed with the column frozen.
      if (scale > 1.01 && scale < SNAP) reset();
    }
  };

  // Scanned service records are absurdly tall (6000px and up). Given the whole photo, the
  // slot would be a 3000px-high layer for Safari to rasterise and the picture itself would
  // be a postage stamp. Past 1:2 the slot stops growing and shows the top of the sheet at
  // full width; zoom is there to read the rest.
  const real = ratio || reserve;
  const tall = real < 0.5;
  const shownRatio = tall ? 0.5 : real;

  const hands = {
    onPointerDown: down,
    onPointerMove: move,
    onPointerUp: up,
    onPointerCancel: cancel,
  };
  const moving = {
    transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${scale})`,
    transition: gesture.current ? "none" : "transform 220ms ease-out",
  };

  return (
    <div
      ref={boxRef}
      data-idx={index}
      data-testid={testId}
      data-loaded={loaded ? "true" : "false"}
      data-zoom={zoomed ? scale.toFixed(2) : "1"}
      // Zoomed, every finger belongs to the full-viewport capture layer below, so the slot
      // itself stops listening — otherwise the same gesture would arrive twice by bubbling.
      {...(zoomed ? {} : hands)}
      // Only take the gestures away from the browser once there is something to pan: at rest
      // the column has to keep scrolling exactly as it did.
      // Zoomed, the slot stops clipping and rises above its neighbours, so the magnified
      // photo spills over them instead of being letterboxed into its own 4:3 window. The
      // slot itself never moves or changes size, so nothing in the column reflows.
      style={{
        aspectRatio: String(shownRatio),
        touchAction: zoomed ? "none" : "pan-y",
        zIndex: zoomed ? 60 : undefined,
      }}
      className={`relative block w-full select-none bg-black ${
        zoomed ? "overflow-visible" : "overflow-hidden"
      }`}
    >
      {thumb && !loaded && !zoomed && (
        // Already in the cache from the card and the strip. Outside the decoded window this
        // IS the photo — soft, but never a black rectangle, which is what iOS showed once it
        // started throwing decoded images away.
        <img
          src={thumb}
          alt=""
          aria-hidden="true"
          decoding="async"
          className={`absolute inset-0 h-full w-full object-cover ${
            mounted ? "scale-105 opacity-45 blur-[6px]" : "opacity-90 blur-[2px]"
          }`}
        />
      )}
      {mounted && !failed && (
        <img
          src={src}
          alt={alt}
          loading="eager"
          decoding="async"
          fetchPriority={priority ? "high" : "low"}
          draggable={false}
          ref={(el) => el?.complete && onSettle?.(el)}
          onLoad={(e) => onSettle?.(e.currentTarget)}
          onError={onFail}
          className={`absolute inset-0 h-full w-full ${
            tall ? "object-cover object-top" : "object-contain"
          } ${loaded && !zoomed ? "opacity-100" : "opacity-0"}`}
        />
      )}
      {placeholder}
      {/* Zoomed in, the magnified photo is drawn LAST so nothing in the slot can paint over
          it, and the FULL resolution file is swapped in over the column's own 800px copy —
          sharp at arm's length, not under a magnifying glass.
          The gestures are taken on a transparent layer the size of the whole screen: the
          picture spills far outside its little slot, and a finger landing on the part that
          hangs over the neighbours has to move THIS photo. The picture itself is
          `pointer-events-none` so every touch reaches that layer. */}
      {zoomed && (
        <>
          <div
            data-testid={`${testId}-capture`}
            {...hands}
            style={{ touchAction: "none" }}
            className="fixed inset-0 z-[1]"
          />
          <div
            data-testid={`${testId}-stage`}
            className="pointer-events-none absolute inset-0 z-[2] overflow-visible"
          >
            {!sharp && (
              <img
                src={src}
                alt=""
                aria-hidden="true"
                style={moving}
                className={`absolute inset-0 h-full w-full ${
                  tall ? "object-cover object-top" : "object-contain"
                }`}
              />
            )}
            <img
              src={zoomSrc || src}
              alt={alt}
              decoding="async"
              fetchPriority="high"
              draggable={false}
              onLoad={() => setSharp(true)}
              style={moving}
              className={`absolute inset-0 h-full w-full ${
                tall ? "object-cover object-top" : "object-contain"
              } ${sharp ? "opacity-100" : "opacity-0"}`}
            />
          </div>
        </>
      )}
    </div>
  );
};

export default ColumnPhoto;
