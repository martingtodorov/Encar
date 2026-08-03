import { useEffect, useRef, useState } from "react";

/**
 * Reports whether the user is scrolling DOWN and is past a threshold.
 * Used to collapse the mobile header so the grid gets the full screen,
 * leaving only the filter button reachable.
 */
// Programmatic scrolls (pagination jumping back to the top of the list) must not be
// mistaken for the visitor scrolling up to reach the menu.
let suppressedUntil = 0;

export function suppressScrollDirection(ms = 900) {
  suppressedUntil = Date.now() + ms;
}

export function useScrollDirection(threshold = 120) {
  const [hidden, setHidden] = useState(false);
  const last = useRef(0);
  const frame = useRef(null);

  useEffect(() => {
    const onScroll = () => {
      if (frame.current) return;
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        const y = window.scrollY || 0;
        if (Date.now() < suppressedUntil) {
          last.current = y;
          return;
        }
        const delta = y - last.current;
        if (y < threshold) {
          setHidden(false);
        } else if (Math.abs(delta) > 6) {
          setHidden(delta > 0);
        }
        last.current = y;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [threshold]);

  return hidden;
}

export default useScrollDirection;
