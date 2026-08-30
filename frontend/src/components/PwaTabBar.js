import { forwardRef, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Search, Heart, Bookmark, Ship, Share2 } from "lucide-react";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { useLangNav } from "@/hooks/useLangNav";

/**
 * Bottom tab bar that ONLY appears when the site is launched from the homescreen
 * (installed PWA). Follows Apple's iOS 26 Liquid Glass tab bar: floating capsule
 * anchored to the safe-area, tinted frosted-glass material, specular rim, generous
 * touch targets, and a fluid selected-pill behind the active tab. Refer to
 * `design_guidelines_liquid_glass.md` (the blueprint) for the layered material recipe
 * this class-set implements in `index.css` under `.lg-tabbar`.
 *
 * Five destinations, in order:
 *   loupe → Search / Home
 *   heart → Saved cars
 *   bookmark → Saved searches
 *   ship → Track my vehicle
 *   share (Safari-style) → hand the current URL to the OS share sheet
 *
 * The share entry is intentionally NOT a route: on iOS/Android homescreen it invokes
 * the native share sheet through `navigator.share`, matching what buyers already do
 * from Safari's own bottom bar. When the API is missing (desktop PWA) we copy the URL
 * to the clipboard and surface a toast, so the button is never a dead-end.
 */
// Tab order matters: it is what the scrub gesture walks through.
const TAB_KEYS = ["search", "saved", "searches", "track", "share"];
const TAB_ROUTES = {
  search: "/",
  saved: "/saved",
  searches: "/searches",
  track: "/track",
};

export const PwaTabBar = () => {
  const { t } = useApp();
  const { path, go } = useLangNav();
  const location = useLocation();
  const standalone = useDisplayMode();

  // Match the current route to a tab so the selected pill is right even for deep
  // routes (a car detail lives under Search, an enquiry list under Saved cars).
  const currentPath = location.pathname.replace(/^\/[a-z]{2}(?=\/|$)/, "");
  const activeTab = currentPath.startsWith("/saved")
    ? "saved"
    : currentPath.startsWith("/searches")
      ? "searches"
      : currentPath.startsWith("/track")
        ? "track"
        : "search";

  const tabsRef = useRef(null);
  const tabRefs = useRef({});
  const [pill, setPill] = useState({ x: 0, w: 0 });
  const [animate, setAnimate] = useState(false);
  // Scrubbing: `dragX` is the pill's live position under the finger (free-form, not
  // snapped), `scrub` is the tab a finished drag committed to — kept until the route
  // catches up so the pill does not bounce back to the old tab while the page loads.
  const [scrub, setScrub] = useState(null);
  const [dragX, setDragX] = useState(null);
  // Finger is down on the bar: the pill swells until it is released.
  const [pressed, setPressed] = useState(false);
  const drag = useRef({ active: false, moved: false, startX: 0, suppressClick: false });

  const shownTab = scrub || activeTab;

  // Once the route matches what the gesture picked, the override is no longer needed.
  useEffect(() => {
    if (scrub && scrub === activeTab) setScrub(null);
  }, [scrub, activeTab]);

  // Measure the shown tab and park the single pill on it. `useLayoutEffect` so the
  // first position is written before the browser paints — otherwise the pill is
  // visible at x=0 for one frame on a cold start.
  useLayoutEffect(() => {
    if (!standalone) return undefined;
    const node = tabRefs.current[shownTab];
    if (!node || !tabsRef.current) return undefined;
    const measure = () => setPill({ x: node.offsetLeft, w: node.offsetWidth });
    measure();
    // Transitions are switched on one frame later, so the very first placement is a
    // jump and every placement after that slides.
    const raf = requestAnimationFrame(() => setAnimate(true));
    window.addEventListener("resize", measure);
    window.addEventListener("orientationchange", measure);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
      window.removeEventListener("orientationchange", measure);
    };
  }, [shownTab, standalone]);

  if (!standalone) return null;

  const onShare = async () => {
    const url = window.location.href;
    const title = document.title;
    if (navigator.share) {
      try {
        await navigator.share({ title, url });
      } catch {
        /* visitor cancelled or share failed — silence, no-op */
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t("pwaShareCopied"));
    } catch {
      toast.error(t("pwaShareFailed"));
    }
  };

  // Which tab sits under a given x. Falls back to the nearest one so a finger that
  // strays past the first or last tab still commits to something sensible.
  const tabAt = (clientX) => {
    let nearest = null;
    let best = Infinity;
    for (const key of TAB_KEYS) {
      const node = tabRefs.current[key];
      if (!node) continue;
      const r = node.getBoundingClientRect();
      if (clientX >= r.left && clientX <= r.right) return key;
      const d = Math.min(Math.abs(clientX - r.left), Math.abs(clientX - r.right));
      if (d < best) {
        best = d;
        nearest = key;
      }
    }
    return nearest;
  };

  // The pill's free-form x for a given finger position: centred on the finger and
  // clamped to the first and last tab, so it never leaves the capsule.
  const dragPos = (clientX) => {
    const wrap = tabsRef.current;
    const first = tabRefs.current[TAB_KEYS[0]];
    const last = tabRefs.current[TAB_KEYS[TAB_KEYS.length - 1]];
    if (!wrap || !first || !last) return 0;
    const w = pill.w || first.offsetWidth;
    const rel = clientX - wrap.getBoundingClientRect().left - w / 2;
    return Math.min(Math.max(rel, first.offsetLeft), last.offsetLeft + last.offsetWidth - w);
  };

  const onPointerDown = (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    drag.current = { active: true, moved: false, startX: e.clientX, suppressClick: false };
    setPressed(true);
    // Capture on the container, so the gesture keeps reporting even after the finger
    // leaves the tab it started on.
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e) => {
    if (!drag.current.active) return;
    // Below the threshold this is still a tap, and the pill must not twitch.
    if (Math.abs(e.clientX - drag.current.startX) > 6) drag.current.moved = true;
    if (drag.current.moved) setDragX(dragPos(e.clientX));
  };

  const onPointerUp = (e) => {
    if (!drag.current.active) return;
    const key = tabAt(e.clientX);
    const moved = drag.current.moved;
    drag.current.active = false;
    setPressed(false);
    // Dropping the free position hands the pill back to the measured tab geometry,
    // and the spring transition turns that into the snap.
    setDragX(null);
    if (!moved) return; // a plain tap: let the link handle itself, natively
    // A drag ends on whatever tab the finger was released over. The anchor's own
    // click still fires afterwards (pointer capture retargets it), so it is swallowed
    // once to avoid navigating twice.
    drag.current.suppressClick = true;
    // Share is not a route: nothing to commit to, so the pill springs back to the page
    // the visitor is actually on.
    if (key === "share") {
      onShare();
      return;
    }
    if (!key) return;
    setScrub(key);
    // `go()` already applies the language prefix — passing `path()` into it produced
    // `/bg/bg/searches`, which the search page happily read as make/model slugs.
    go(TAB_ROUTES[key]);
  };

  const onPointerCancel = () => {
    drag.current.active = false;
    setPressed(false);
    setDragX(null);
    setScrub(null);
  };

  const onClickCapture = (e) => {
    if (!drag.current.suppressClick) return;
    drag.current.suppressClick = false;
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <nav
      data-testid="pwa-tabbar"
      aria-label={t("pwaTabBarAria")}
      // Deliberately static: hiding on scroll-down and springing back on scroll-up made
      // the whole bar feel jittery on long lists, and the visitor complained. The bar
      // now stays anchored to the safe-area bottom for the whole session.
      className="lg-tabbar"
    >
      {/* Layer 1: base blur + adaptive tint. Real refraction (SVG displacement) is
          Chromium-only and the actual iOS PWA runs on Safari, so we ship the frosted
          approximation everywhere and let Chromium enjoy the extra crispness. */}
      <span className="lg-blur" aria-hidden="true" />
      {/* Layer 2: refraction — the edge-only lens bend (see `.lg-refract`). */}
      <span className="lg-refract" aria-hidden="true" />
      <span className="lg-tint" aria-hidden="true" />
      {/* Layer 3: specular rim — a lit bezel that reads as convex glass. */}
      <span className="lg-rim" aria-hidden="true" />
      {/* Layer 4: content (icons + labels). */}
      <div
        className="lg-tabs"
        ref={tabsRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onClickCapture={onClickCapture}
      >
        {/* ONE pill for the whole bar, moved to the active tab, instead of a pill
            rendered inside each tab: a single element can animate between positions,
            five separate ones can only appear and disappear. Hidden until measured so
            it never flashes at x=0 on first paint. */}
        <span
          aria-hidden="true"
          className={`lg-pill ${pill.w ? "lg-pill-ready" : ""} ${
            animate ? "lg-pill-anim" : ""
          } ${dragX !== null ? "lg-pill-drag" : ""} ${pressed ? "lg-pill-grab" : ""}`}
          style={{ translate: `${dragX ?? pill.x}px 0`, width: `${pill.w}px` }}
        />
        <Tab
          ref={(el) => { tabRefs.current.search = el; }}
          testid="pwa-tab-search"
          to={path("/")}
          label={t("pwaTabSearch")}
          icon={Search}
          active={activeTab === "search"}
        />
        <Tab
          ref={(el) => { tabRefs.current.saved = el; }}
          testid="pwa-tab-saved"
          to={path("/saved")}
          label={t("pwaTabSaved")}
          icon={Heart}
          active={activeTab === "saved"}
        />
        <Tab
          ref={(el) => { tabRefs.current.searches = el; }}
          testid="pwa-tab-searches"
          to={path("/searches")}
          label={t("pwaTabSearches")}
          icon={Bookmark}
          active={activeTab === "searches"}
        />
        <Tab
          ref={(el) => { tabRefs.current.track = el; }}
          testid="pwa-tab-track"
          to={path("/track")}
          label={t("pwaTabTrack")}
          icon={Ship}
          active={activeTab === "track"}
        />
        <button
          type="button"
          ref={(el) => { tabRefs.current.share = el; }}
          data-testid="pwa-tab-share"
          onClick={onShare}
          onContextMenu={(e) => e.preventDefault()}
          className="lg-tab"
        >
          <span className="lg-tab-icon">
            <Share2 className="h-[22px] w-[22px]" aria-hidden="true" />
          </span>
          <span className="lg-tab-label">{t("pwaShare")}</span>
        </button>
      </div>
    </nav>
  );
};

const Tab = forwardRef(({ testid, to, label, icon: Icon, active }, ref) => (
  <NavLink
    ref={ref}
    to={to}
    data-testid={testid}
    end={to.match(/^\/[a-z]{2}$/) != null}
    className={`lg-tab ${active ? "lg-tab-active" : ""}`}
    aria-current={active ? "page" : undefined}
    // iOS pops a link-preview sheet on a long press, which on a tab bar reads as the
    // app misbehaving. `-webkit-touch-callout: none` kills it on iOS; this handles the
    // desktop/Android context menu, and `draggable` stops the link-drag ghost.
    onContextMenu={(e) => e.preventDefault()}
    draggable={false}
  >
    <span className="lg-tab-icon">
      <Icon className="h-[22px] w-[22px]" aria-hidden="true" />
    </span>
    <span className="lg-tab-label">{label}</span>
  </NavLink>
));
Tab.displayName = "PwaTab";

export default PwaTabBar;
