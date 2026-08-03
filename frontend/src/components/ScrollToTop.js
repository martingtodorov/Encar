import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Every new page starts at the top.
 *
 * The one exception is going BACK to the results, where the list restores the position the
 * buyer left it at — jumping them to the top there would lose their place in a long grid.
 */
export const ScrollToTop = () => {
  const { pathname, state } = useLocation();

  useEffect(() => {
    if (state?.restoreScroll) return;
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname, state]);

  return null;
};

export default ScrollToTop;
