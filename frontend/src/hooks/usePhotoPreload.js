import { useEffect } from "react";

/**
 * Pull a set of photos into the browser cache ONE AT A TIME, starting from the one on
 * screen and wrapping around.
 *
 * Opening the gallery used to leave every swipe waiting on the CDN. Firing all forty
 * requests at once is worse, not better: they compete with the photo the visitor is
 * actually looking at. So the requests are chained — the next one starts when the previous
 * image has decoded — and the order begins at `startIndex`, which is where the swipes go
 * first. Everything afterwards is served from the browser cache.
 *
 * `active` gates the whole thing so a closed viewer downloads nothing. The chain is started
 * once per opening and is not restarted while it runs.
 *
 * `limit` caps how many photos ahead the chain runs. A full-resolution Encar photo decodes
 * to roughly 8 MB of bitmap, so pulling in all forty is how a phone runs out of memory and
 * locks up; a handful ahead of the finger is all a swipe can outrun anyway.
 */
export const usePhotoPreload = (urls, startIndex = 0, active = true, limit = Infinity) => {
  const total = urls?.length || 0;
  useEffect(() => {
    if (!active || !total) return undefined;
    let cancelled = false;
    let current = null;
    const first = ((startIndex % total) + total) % total;
    const reach = Math.max(1, Math.min(total, limit));
    const order = Array.from({ length: reach }, (_, i) => (first + i) % total);

    const step = (n) => {
      if (cancelled || n >= order.length) return;
      const src = urls[order[n]];
      if (!src) {
        step(n + 1);
        return;
      }
      const img = new Image();
      current = img;
      img.onload = () => step(n + 1);
      img.onerror = () => step(n + 1);
      img.src = src;
      // Already cached: `complete` is true synchronously and no event ever fires.
      if (img.complete) step(n + 1);
    };
    step(0);

    return () => {
      cancelled = true;
      if (current) {
        current.onload = null;
        current.onerror = null;
      }
    };
    // Deliberately not keyed on `startIndex`: restarting the chain on every swipe would
    // throw away a queue that is already most of the way through.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total, active, limit]);
};

export default usePhotoPreload;
