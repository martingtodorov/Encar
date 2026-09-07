import { useCallback, useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { ColumnPhoto } from "@/components/ColumnPhoto";

/**
 * The mobile "all photos" column: every photo, one under the other, each zoomable where it
 * sits (double tap, then pinch and drag — see `ColumnPhoto`).
 *
 * WHAT DECIDES WHAT LOADS. Two rules, in this order:
 *
 *   1. Everything ON SCREEN is loaded. No queue, no waiting its turn: a photo the visitor
 *      is looking at jumps every other request, because a blurred thumbnail under their
 *      nose while the loader works through the list is the one thing they will notice.
 *   2. What is off screen is filled in afterwards — a couple of slots ahead first, since
 *      that is where they are going, then the one they just passed.
 *
 * AND WHAT KEEPS THE PHONE ALIVE. These listings carry twenty photos including scanned
 * service records; handing them all to iOS at once locks the tab up, and Safari then throws
 * decoded images away and cannot get them back (every photo goes black, touch stops being
 * delivered). So a photo is only decoded while it is on screen or just off it, and while the
 * column is being FLICKED past nothing off screen is even asked for — the cached thumbnails
 * cover it, and the real files arrive the moment it stands still.
 */
const RESERVE = 4 / 3;      // every slot, whatever the photo: see `ColumnPhoto`
const AHEAD = 2;            // slots past the last visible one, once the scrolling calms
const BEHIND = 1;           // and the one just scrolled past, in case they come back
const IN_FLIGHT = 2;        // off-screen fetches at a time; on-screen ones ignore this
const FLING_PX = 60;        // a scroll step bigger than this is a flick, not reading
const CALM_MS = 200;        // how long after the last step it counts as standing still
const STALL_MS = 9000;      // a request this old stops holding a slot in the queue
const TICK_MS = 1200;

export const PhotoColumn = ({ photos, alt = "", onZoomChange, testId = "detail-lightbox" }) => {
  const [started, setStarted] = useState([]);     // indices whose file has been requested
  const [done, setDone] = useState({});           // index -> the file is decoded and shown
  const [failed, setFailed] = useState({});
  const [span, setSpan] = useState({ lo: 0, hi: 0 });   // the slots on screen right now
  const [zoomIdx, setZoomIdx] = useState(null);
  const [flying, setFlying] = useState(false);
  const [tick, setTick] = useState(0);
  const startedAt = useRef({});
  const hostRef = useRef(null);
  const seen = useRef(new Set());

  useEffect(() => {
    setStarted([]);
    setDone({});
    setFailed({});
    setSpan({ lo: 0, hi: 0 });
    seen.current = new Set();
    startedAt.current = {};
  }, [photos]);

  // A slow tick so the queue cannot wedge: a stalled request eventually stops counting, and
  // an image the browser served from cache without firing an event is noticed here.
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(id);
  }, []);

  // Which slots are on screen. Twenty observed elements costs nothing and replaces a scroll
  // handler that would fire on every frame. The set is committed immediately — this is the
  // one thing that must never lag behind the visitor.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          const i = Number(e.target.dataset.idx);
          if (Number.isNaN(i)) return;
          if (e.isIntersecting) seen.current.add(i);
          else seen.current.delete(i);
        });
        if (!seen.current.size) return;
        const list = [...seen.current];
        const lo = Math.min(...list);
        const hi = Math.max(...list);
        setSpan((s) => (s.lo === lo && s.hi === hi ? s : { lo, hi }));
      },
      // Root is the viewport on purpose: the column scrolls inside the dialog, and a slot
      // clipped by that overflow is already reported as not intersecting.
      { threshold: 0 }
    );
    host.querySelectorAll("[data-idx]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [photos]);

  // Is the column being thrown past, or read?
  useEffect(() => {
    const box = hostRef.current?.parentElement;
    if (!box) return undefined;
    let at = box.scrollTop;
    let calm = 0;
    const onScroll = () => {
      const top = box.scrollTop;
      const step = Math.abs(top - at);
      at = top;
      if (step > FLING_PX) setFlying(true);
      clearTimeout(calm);
      calm = setTimeout(() => setFlying(false), CALM_MS);
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      clearTimeout(calm);
      box.removeEventListener("scroll", onScroll);
    };
  }, [photos]);

  // The scheduler. Anything on screen is started at once, whatever else is in flight; off
  // screen, one or two at a time and only while the column is standing still.
  useEffect(() => {
    const n = photos.length;
    if (!n) return;
    const waiting = (i) => i >= 0 && i < n && !started.includes(i);
    let pick = -1;
    for (let i = span.lo; i <= span.hi && pick < 0; i += 1) {
      if (waiting(i)) pick = i;
    }
    if (pick < 0 && !flying) {
      const now = Date.now();
      const busy = started.filter(
        (i) => !done[i] && !failed[i] && now - (startedAt.current[i] || now) < STALL_MS
      ).length;
      if (busy >= IN_FLIGHT) return;
      for (let i = span.hi + 1; i <= span.hi + AHEAD && pick < 0; i += 1) {
        if (waiting(i)) pick = i;
      }
      for (let i = span.lo - 1; i >= span.lo - BEHIND && pick < 0; i -= 1) {
        if (waiting(i)) pick = i;
      }
    }
    if (pick < 0) return;
    startedAt.current[pick] = Date.now();
    setStarted((s) => (s.includes(pick) ? s : [...s, pick]));
  }, [started, done, failed, span, flying, tick, photos]);

  // A photo scrolled away from before it arrived forgets it was ever asked for, so coming
  // back to it starts again instead of waiting on a request with no slot left to land in.
  useEffect(() => {
    setStarted((s) =>
      s.some((i) => !done[i] && (i < span.lo - BEHIND || i > span.hi + AHEAD))
        ? s.filter((i) => done[i] || (i >= span.lo - BEHIND && i <= span.hi + AHEAD))
        : s
    );
  }, [span, done]);

  const settle = useCallback((i) => {
    setDone((d) => (d[i] ? d : { ...d, [i]: true }));
  }, []);

  // Only one photo is ever zoomed, and while one is the column must not scroll: a drag has
  // to move the picture, not slide the page out from under it.
  const handleZoom = useCallback(
    (i, on) => {
      setZoomIdx((cur) => {
        const next = on ? i : cur === i ? null : cur;
        if (next !== cur) onZoomChange?.(next !== null);
        return next;
      });
    },
    [onZoomChange]
  );

  return (
    <div
      ref={hostRef}
      className="flex flex-col gap-1.5 bg-black py-1.5"
      data-testid={`${testId}-column`}
      data-zoomed={zoomIdx === null ? "false" : "true"}
    >
      {photos.map((p, i) => {
        const onScreen = i >= span.lo && i <= span.hi;
        // Decoded while on screen or just off it — and off-screen slots are dropped
        // entirely while the column is being flicked past. The zoomed one is the
        // exception: it must never be taken from under a finger.
        const keep =
          onScreen ||
          i === zoomIdx ||
          (!flying && i >= span.lo - BEHIND && i <= span.hi + AHEAD);
        return (
          <ColumnPhoto
            key={p.full_column || p.full || i}
            index={i}
            testId={`${testId}-photo-${i}`}
            src={p.full_column || p.full_lightbox || p.full}
            zoomSrc={p.full_lightbox || p.full}
            thumb={p.thumb}
            alt={alt}
            reserve={RESERVE}
            loaded={!!done[i] && keep}
            mounted={started.includes(i) && keep}
            failed={!!failed[i]}
            priority={onScreen}
            onSettle={() => settle(i)}
            onFail={() => setFailed((f) => ({ ...f, [i]: true }))}
            onZoom={handleZoom}
            placeholder={
              !done[i] || !keep ? (
                <span
                  className="absolute inset-0 flex items-center justify-center text-white/60"
                  aria-hidden="true"
                >
                  {failed[i] ? (
                    <ImageOff className="h-6 w-6" />
                  ) : !done[i] ? (
                    <Loader2
                      className={`h-5 w-5 ${
                        started.includes(i) ? "animate-spin" : "opacity-40"
                      }`}
                    />
                  ) : null}
                </span>
              ) : null
            }
          />
        );
      })}
    </div>
  );
};

export default PhotoColumn;
