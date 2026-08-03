import { useEffect, useRef } from "react";
import { useApp } from "@/context/AppContext";
import { warmCar } from "@/lib/api";

/**
 * Warm a car in the background once the visitor shows intent, so the click is instant.
 *
 * Desktop waits 280ms of sustained hover: a pointer sweeping across the list is not
 * intent, a pointer that settles on a card is. Touch arms at 120ms and cancels on
 * touchmove, which is how a tap is told apart from the start of a scroll flick.
 *
 * Spread the returned props onto the card/row root.
 */
export const useCarWarm = (id) => {
  const { lang } = useApp();
  const timer = useRef(null);

  const cancel = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const arm = (ms) => {
    cancel();
    timer.current = setTimeout(() => {
      timer.current = null;
      warmCar(id, lang);
    }, ms);
  };

  useEffect(() => cancel, []);

  return {
    onMouseEnter: () => arm(280),
    onMouseLeave: cancel,
    // Left to fire after touchend on purpose: the detail page reuses the same promise.
    onTouchStart: () => arm(120),
    onTouchMove: cancel,
  };
};

export default useCarWarm;
