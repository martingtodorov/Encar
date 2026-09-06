import { useEffect, useRef, useState } from "react";

const MAX = 4;
const DOUBLE_TAP_MS = 300;
const TAP_SLOP = 12;        // a tap that moves more than this was a scroll, not a tap
const DOUBLE_TAP_TO = 2.5;  // what a double tap zooms to
// A pinch has to grow the fingers by this much before the photo starts to scale. Below it
// the gesture was almost certainly a two-fingered scroll, and a photo left at 1.05x is the
// worst possible outcome: invisible, yet the column stops scrolling.
const PINCH_START = 1.15;
// ...and on the way back, anything under this snaps all the way to rest for the same reason.
const SNAP = 1.25;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ZERO = { s: 1, x: 0, y: 0 };

/**
 * One photo in the mobile column, zoomable where it sits.
 *
 * Double tap to zoom in, double tap again to come back out. While zoomed: two fingers change
 * the zoom, one finger moves the photo around, and the photo grows OVER its neighbours
 * instead of being letterboxed into its own slot — the slot itself never moves, so the
 * column is exactly as it was the moment the zoom is released. Zooming in also swaps in the
 * FULL resolution file; the column is deliberately served at 800px.
 *
 * WHY THE LISTENERS ARE NATIVE AND WHY ZOOM SNAPS BACK. On iOS the browser cancels our
 * pointers the instant it decides a gesture belongs to it (a two-fingered swipe over a
 * `pan-y` element, a notification, an edge swipe). Two things came out of that:
 *
 *   1. The handlers are attached to the element itself and read refs, so a `pointercancel`
 *      is never missed because React had swapped a prop mid-gesture — which is exactly how
 *      a photo used to get stuck barely-zoomed with the column frozen and the close button
 *      buried underneath it. `window` gets the same end handler as a last resort.
 *   2. A pinch must clear PINCH_START before it counts, and anything left under SNAP when
 *      the last finger lifts goes back to rest. Half a zoom is never a state you can be
 *      left in: either the photo is properly magnified or the column scrolls.
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
  const [view, setView] = useState(ZERO);
  const [sharp, setSharp] = useState(false);      // the full-resolution file has arrived
  const boxRef = useRef(null);
  const viewRef = useRef(ZERO);                   // what the native handlers read
  const points = useRef(new Map());
  const gesture = useRef(null);
  const lastTap = useRef({ at: 0, x: 0, y: 0 });

  const zoomed = view.s > 1.01;

  useEffect(() => {
    onZoom?.(index, zoomed);
  }, [zoomed, index, onZoom]);

  // The photo is only allowed to take every touch on screen once it is magnified; at rest
  // the finger belongs to the column, which has to scroll exactly as it always did.
  useEffect(() => {
    const el = boxRef.current;
    if (el) el.style.touchAction = zoomed ? "none" : "pan-y";
  }, [zoomed]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return undefined;

    const rect = () => el.getBoundingClientRect();

    const put = (v) => {
      viewRef.current = v;
      setView(v);
    };

    const apply = (s, x, y) => {
      const next = clamp(s, 1, MAX);
      const box = rect();
      // How far the photo may travel before its own edge would come inside the slot.
      const lx = (box.width * (next - 1)) / 2;
      const ly = (box.height * (next - 1)) / 2;
      put(
        next <= 1.01
          ? ZERO
          : { s: next, x: clamp(x, -lx, lx), y: clamp(y, -ly, ly) }
      );
    };

    const rest = () => {
      put(ZERO);
      setSharp(false);      // the next zoom re-checks whether the full file is there
    };

    /** Zoom to `s` keeping the point under the finger where it is. */
    const zoomAt = (s, cx, cy) => {
      const box = rect();
      const { s: was, x, y } = viewRef.current;
      const dx = cx - (box.left + box.width / 2);
      const dy = cy - (box.top + box.height / 2);
      const k = s / was;
      apply(s, (x - dx) * k + dx, (y - dy) * k + dy);
    };

    const down = (e) => {
      points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (points.current.size === 2) {
        const [a, b] = [...points.current.values()];
        // Two fingers are ours from here on, whatever the element was allowing a moment ago.
        el.style.touchAction = "none";
        gesture.current = {
          kind: "pinch",
          dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
          mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
          live: viewRef.current.s > 1.01,   // already zoomed: no threshold to clear
          from: { ...viewRef.current },
        };
      } else if (points.current.size === 1) {
        gesture.current = {
          kind: "drag",
          at: { x: e.clientX, y: e.clientY },
          from: { ...viewRef.current },
          moved: 0,
        };
        if (viewRef.current.s > 1.01) el.setPointerCapture?.(e.pointerId);
      }
    };

    const move = (e) => {
      if (!points.current.has(e.pointerId)) return;
      points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const g = gesture.current;
      if (!g) return;

      if (g.kind === "pinch" && points.current.size >= 2) {
        const [a, b] = [...points.current.values()];
        const spread = (Math.hypot(a.x - b.x, a.y - b.y) || 1) / g.dist;
        // Not yet a pinch: a couple of percent is a two-fingered scroll, and reacting to it
        // is what froze the column.
        if (!g.live) {
          if (spread < PINCH_START) return;
          g.live = true;
        }
        const box = rect();
        const next = clamp(g.from.s * spread, 1, MAX);
        const dx = g.mid.x - (box.left + box.width / 2);
        const dy = g.mid.y - (box.top + box.height / 2);
        const k = next / g.from.s;
        apply(next, (g.from.x - dx) * k + dx, (g.from.y - dy) * k + dy);
        return;
      }

      if (g.kind === "drag") {
        const dx = e.clientX - g.at.x;
        const dy = e.clientY - g.at.y;
        g.moved = Math.max(g.moved, Math.hypot(dx, dy));
        // At rest the column is scrolling: leave the finger alone.
        if (viewRef.current.s > 1.01) apply(viewRef.current.s, g.from.x + dx, g.from.y + dy);
      }
    };

    /** Every way a gesture can end passes through here, so nothing is ever left half done. */
    const settleGesture = () => {
      if (points.current.size) return;
      gesture.current = null;
      const { s } = viewRef.current;
      if (s > 1.01 && s < SNAP) rest();
      else if (s <= 1.01) el.style.touchAction = "pan-y";
    };

    const up = (e) => {
      points.current.delete(e.pointerId);
      try {
        el.releasePointerCapture?.(e.pointerId);
      } catch {
        // not ours to release
      }
      const g = gesture.current;
      if (points.current.size === 1) {
        // One finger lifted out of a pinch: carry on as a drag from where it is.
        const [only] = [...points.current.values()];
        gesture.current = { kind: "drag", at: only, from: { ...viewRef.current }, moved: 0 };
        return;
      }

      const tap = g && g.kind === "drag" && g.moved <= TAP_SLOP;
      settleGesture();
      if (!tap) return;

      const now = Date.now();
      const prev = lastTap.current;
      const near = Math.hypot(e.clientX - prev.x, e.clientY - prev.y) < 40;
      if (now - prev.at < DOUBLE_TAP_MS && near) {
        lastTap.current = { at: 0, x: 0, y: 0 };
        if (viewRef.current.s > 1.01) rest();
        else zoomAt(DOUBLE_TAP_TO, e.clientX, e.clientY);
        return;
      }
      lastTap.current = { at: now, x: e.clientX, y: e.clientY };
    };

    const cancel = (e) => {
      points.current.delete(e.pointerId);
      try {
        el.releasePointerCapture?.(e.pointerId);
      } catch {
        // not ours to release
      }
      settleGesture();
    };

    // The photo's own listeners: on the element, so a gesture cannot be orphaned by a
    // re-render. `window` sees the ends the element never gets — iOS delivers a cancel to
    // whatever it likes once it takes a gesture over.
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", cancel);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", settleGesture);
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", cancel);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("blur", settleGesture);
    };
  }, []);

  // Scanned service records are absurdly tall (6000px and up). Given the whole photo, the
  // slot would be a 3000px-high layer for Safari to rasterise and the picture itself would
  // be a postage stamp. Past 1:2 the slot stops growing and shows the top of the sheet at
  // full width; zoom is there to read the rest.
  const real = ratio || reserve;
  const tall = real < 0.5;
  const shownRatio = tall ? 0.5 : real;
  const fit = tall ? "object-cover object-top" : "object-contain";

  const moving = {
    transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.s})`,
    transition: gesture.current ? "none" : "transform 220ms ease-out",
  };

  return (
    <div
      ref={boxRef}
      data-idx={index}
      data-testid={testId}
      data-loaded={loaded ? "true" : "false"}
      data-zoom={zoomed ? view.s.toFixed(2) : "1"}
      // Zoomed, the slot stops clipping and rises above its neighbours so the magnified
      // photo spills over them. The slot itself keeps its size and place, so nothing in the
      // column reflows and letting go puts everything back.
      //
      // `content-visibility: auto` is the difference between a column that survives a fast
      // flick to the bottom and a tab that dies on the way: offscreen slots keep the height
      // their aspect ratio reserves but stop being rendered at all, so twenty photos are
      // never rasterised at once. It brings paint containment with it, which would clip a
      // zoomed photo back into its slot — hence off the moment there is something to spill.
      style={{
        aspectRatio: String(shownRatio),
        zIndex: zoomed ? 60 : undefined,
        contentVisibility: zoomed ? "visible" : "auto",
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
          className={`absolute inset-0 h-full w-full ${fit} ${
            loaded && !zoomed ? "opacity-100" : "opacity-0"
          }`}
        />
      )}
      {placeholder}
      {/* Zoomed in, the magnified photo is drawn LAST so nothing in the slot can paint over
          it, and the FULL resolution file replaces the column's 800px copy — sharp at arm's
          length, not under a magnifying glass. The picture itself takes no touches: the
          gestures are read from the slot, which reaches the whole screen through the
          transparent layer below, so a finger on the part hanging over the neighbours still
          moves THIS photo. */}
      {zoomed && (
        <>
          <div
            data-testid={`${testId}-capture`}
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
                className={`absolute inset-0 h-full w-full ${fit}`}
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
              className={`absolute inset-0 h-full w-full ${fit} ${
                sharp ? "opacity-100" : "opacity-0"
              }`}
            />
          </div>
        </>
      )}
    </div>
  );
};

export default ColumnPhoto;
