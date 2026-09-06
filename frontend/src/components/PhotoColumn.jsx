import { useCallback, useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";

/**
 * The mobile "all photos" column: every photo, one under the other, tap one to zoom it.
 *
 * WHY IT IS WRITTEN THIS WAY — three separate ways this froze a phone, all measured on a
 * 390x844 viewport with a 20-photo car:
 *
 *   1. The first version handed every photo's FULL-resolution source to the browser at once
 *      and a preload chain fetched the same set again: twenty parallel CDN requests and
 *      ~8 MB of decoded bitmap per picture. The column locked up on the way to the bottom.
 *   2. Loading strictly one-after-another fixed the memory but meant scrolling ahead of the
 *      loader left the visitor looking at black boxes.
 *   3. Letting the visible photo jump the queue fixed THAT, but "the visible one finished"
 *      also moved the sequential cursor to the bottom of the list — which opened every slot
 *      in between at once and put the storm right back. Scrolling down fast made loading
 *      appear to stop dead.
 *
 * So loading is a QUEUE with a hard limit of two requests in flight. What the visitor is
 * looking at (and the next couple below it) goes first; whatever is left is filled in from
 * the top, so nothing is skipped and nothing is ever loaded twice. No `loading="lazy"`, no
 * unloading: once a photo is here it stays, so scrolling back up never re-fetches or
 * flickers. The scheduler also runs on a slow tick, so a request that stalls or an image the
 * cache satisfies without an event can never wedge the queue.
 *
 * Each slot reserves its height before its photo arrives and then takes the photo's real
 * aspect ratio, so the column's height never jumps under the finger.
 */
const RESERVE = 4 / 3;      // Encar's landscape shape: the common case, so most slots keep
                            // exactly the height they reserved
const IN_FLIGHT = 2;        // one for the eyes, one for the queue behind it
const AHEAD = 3;            // how far past the visible photo counts as "coming next"
const STALL_MS = 9000;      // a request this old stops holding a slot in the queue
const TICK_MS = 1200;

export const PhotoColumn = ({ photos, alt = "", onPick, testId = "detail-lightbox" }) => {
  const [started, setStarted] = useState([]);     // indices whose <img> is mounted
  const [ratio, setRatio] = useState({});         // index -> real aspect ratio once loaded
  const [failed, setFailed] = useState({});
  const [looking, setLooking] = useState(0);      // the slot in front of the visitor
  const [tick, setTick] = useState(0);
  const startedAt = useRef({});
  const hostRef = useRef(null);

  useEffect(() => {
    setStarted([]);
    setRatio({});
    setFailed({});
    setLooking(0);
    startedAt.current = {};
  }, [photos]);

  // A slow tick so the queue cannot wedge: a stalled request eventually stops counting, and
  // an image the browser served from cache without firing an event is noticed here.
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(id);
  }, []);

  // The scheduler: start at most one more photo per pass, never more than IN_FLIGHT at once.
  useEffect(() => {
    const n = photos.length;
    if (!n) return;
    const now = Date.now();
    const busy = started.filter(
      (i) => !ratio[i] && !failed[i] && now - (startedAt.current[i] || now) < STALL_MS
    ).length;
    if (busy >= IN_FLIGHT) return;

    const waiting = (i) => i >= 0 && i < n && !started.includes(i);
    let pick = -1;
    for (let i = looking; i < Math.min(n, looking + AHEAD) && pick < 0; i += 1) {
      if (waiting(i)) pick = i;
    }
    for (let i = 0; i < n && pick < 0; i += 1) {
      if (waiting(i)) pick = i;
    }
    if (pick < 0) return;
    startedAt.current[pick] = now;
    setStarted((s) => (s.includes(pick) ? s : [...s, pick]));
  }, [started, ratio, failed, looking, tick, photos]);

  // Which slot is on screen. Twenty observed elements costs nothing and replaces a scroll
  // handler that would fire on every frame.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        const seen = entries
          .filter((e) => e.isIntersecting)
          .map((e) => Number(e.target.dataset.idx))
          .filter((i) => !Number.isNaN(i));
        if (seen.length) setLooking(Math.min(...seen));
      },
      // Root is the viewport on purpose: the column scrolls inside the dialog, and a slot
      // clipped by that overflow is already reported as not intersecting.
      { threshold: 0.01 }
    );
    host.querySelectorAll("[data-idx]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [photos]);

  const settle = useCallback((i, el) => {
    if (!el) return;
    const { naturalWidth: w, naturalHeight: h } = el;
    if (w && h) setRatio((r) => (r[i] ? r : { ...r, [i]: w / h }));
  }, []);

  return (
    <div
      ref={hostRef}
      className="flex flex-col gap-1.5 bg-black py-1.5"
      data-testid={`${testId}-column`}
    >
      {photos.map((p, i) => {
        const src = p.full_column || p.full_lightbox || p.full;
        const done = !!ratio[i];
        const mounted = started.includes(i);
        return (
          <button
            key={src || i}
            type="button"
            data-idx={i}
            data-testid={`${testId}-photo-${i}`}
            data-loaded={done ? "true" : "false"}
            onClick={() => onPick?.(i)}
            className="relative block w-full overflow-hidden bg-black text-left"
            style={{ aspectRatio: String(ratio[i] || RESERVE) }}
          >
            {p.thumb && !done && (
              // The thumbnail is already in the cache from the card and the strip, so the
              // shape and colour of the car are there instantly and the full photo simply
              // sharpens into place instead of appearing out of black.
              <img
                src={p.thumb}
                alt=""
                aria-hidden="true"
                decoding="async"
                className="absolute inset-0 h-full w-full scale-105 object-cover opacity-45 blur-[6px]"
              />
            )}
            {mounted && !failed[i] && (
              <img
                // Deliberately NOT lazy: the queue above decides the order, and the
                // browser's own heuristics would fight it by skipping ahead or holding back.
                src={src}
                alt={alt}
                loading="eager"
                decoding="async"
                fetchPriority={i === looking ? "high" : "low"}
                draggable={false}
                // A cached photo can be complete before React attaches a load handler.
                ref={(el) => el?.complete && settle(i, el)}
                onLoad={(e) => settle(i, e.currentTarget)}
                onError={() => setFailed((f) => ({ ...f, [i]: true }))}
                className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-200 ${
                  done ? "opacity-100" : "opacity-0"
                }`}
              />
            )}
            {!done && (
              <span
                className="absolute inset-0 flex items-center justify-center text-white/60"
                aria-hidden="true"
              >
                {failed[i] ? (
                  <ImageOff className="h-6 w-6" />
                ) : (
                  <Loader2 className={`h-5 w-5 ${mounted ? "animate-spin" : "opacity-40"}`} />
                )}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};

export default PhotoColumn;
