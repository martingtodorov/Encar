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
 * Returns `[props, warmNow]`: spread the props onto the card/row root, and call `warmNow`
 * from anywhere else that signals intent (reaching the last slide of the gallery).
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

  const warmNow = () => {
    cancel();
    warmCar(id, lang);
  };

  return [
    {
      onMouseEnter: () => arm(280),
      onMouseLeave: cancel,
      // Left to fire after touchend on purpose: the detail page reuses the same promise.
      onTouchStart: () => arm(120),
      onTouchMove: cancel,
    },
    warmNow,
  ];
};

export default useCarWarm;
