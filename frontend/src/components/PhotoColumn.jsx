import { useCallback, useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { ColumnPhoto } from "@/components/ColumnPhoto";

/**
 * The mobile "all photos" column: every photo, one under the other, each zoomable where it
 * sits (double tap, then pinch and drag — see `ColumnPhoto`).
 *
 * WHY IT IS WRITTEN THIS WAY. Four separate failures, each measured or reported from a real
 * phone, shaped this file:
 *
 *   1. The first version handed every photo's FULL-resolution source to the browser at once
 *      and a preload chain fetched the same set again: twenty parallel requests, ~8 MB of
 *      decoded bitmap each. It locked up on the way to the bottom.
 *   2. Loading strictly one-after-another fixed the memory but left a visitor who scrolls
 *      ahead of the loader staring at black boxes.
 *   3. Letting the visible photo jump the queue fixed that, but "the visible one finished"
 *      dragged the sequential cursor to the end of the list, which opened every slot in
 *      between at once — the storm was back, and fast scrolling looked like loading had
 *      stopped dead.
 *   4. Even one request at a time, KEEPING every photo decoded is too much for iOS Safari:
 *      these listings include scanned service records that are enormously tall (600x6000 is
 *      ~14 MB decoded on its own). Safari throws the decoded data away under pressure and
 *      cannot get it back — every photo goes pitch black, and touch stops being delivered.
 *
 * So: a QUEUE with two requests in flight decides the ORDER (visible first, then filled in
 * from the top, nothing skipped, nothing fetched twice), and a WINDOW decides what stays
 * decoded. Outside the window a slot keeps its blurred thumbnail, which costs almost
 * nothing; the full file stays in the HTTP cache, so coming back to it is instant and does
 * not touch the network.
 */
const RESERVE = 4 / 3;      // Encar's landscape shape: the common case, so most slots keep
                            // exactly the height they reserved
const IN_FLIGHT = 2;        // one for the eyes, one for the queue behind it
const AHEAD = 3;            // how far past the visible photo counts as "coming next"
const WINDOW = 3;           // photos kept decoded either side of the one being looked at
const STALL_MS = 9000;      // a request this old stops holding a slot in the queue
const TICK_MS = 1200;

export const PhotoColumn = ({ photos, alt = "", onZoomChange, testId = "detail-lightbox" }) => {
  const [started, setStarted] = useState([]);     // indices whose file has been requested
  const [ratio, setRatio] = useState({});         // index -> real aspect ratio once known
  const [failed, setFailed] = useState({});
  const [looking, setLooking] = useState(0);      // the slot in front of the visitor
  const [zoomIdx, setZoomIdx] = useState(null);
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
    const { naturalWidth: w, naturalHeight: h } = el;
    if (w && h) setRatio((r) => (r[i] ? r : { ...r, [i]: w / h }));
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
        const known = !!ratio[i];
        // Decoded only near the eyes — plus the zoomed one, which must never be dropped
        // from under a finger.
        const near = Math.abs(i - looking) <= WINDOW || i === zoomIdx;
        return (
          <ColumnPhoto
            key={p.full_column || p.full || i}
            index={i}
            testId={`${testId}-photo-${i}`}
            src={p.full_column || p.full_lightbox || p.full}
            zoomSrc={p.full_lightbox || p.full}
            thumb={p.thumb}
            alt={alt}
            ratio={ratio[i]}
            reserve={RESERVE}
            loaded={known && near}
            mounted={started.includes(i) && near}
            failed={!!failed[i]}
            priority={i === looking}
            onSettle={(el) => settle(i, el)}
            onFail={() => setFailed((f) => ({ ...f, [i]: true }))}
            onZoom={handleZoom}
            placeholder={
              !known || !near ? (
                <span
                  className="absolute inset-0 flex items-center justify-center text-white/60"
                  aria-hidden="true"
                >
                  {failed[i] ? (
                    <ImageOff className="h-6 w-6" />
                  ) : !known ? (
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
