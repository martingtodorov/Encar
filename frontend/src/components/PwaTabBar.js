import { useEffect, useState } from "react";
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
export const PwaTabBar = () => {
  const { t } = useApp();
  const { path } = useLangNav();
  const location = useLocation();
  const standalone = useDisplayMode();
  const [minimized, setMinimized] = useState(false);

  // Minimize on scroll down, restore on scroll up. Mirrors iOS 26's
  // `.tabBarMinimizeBehavior(.onScrollDown)` so long lists don't fight the bar for
  // vertical real estate.
  useEffect(() => {
    if (!standalone) return undefined;
    let lastY = window.scrollY || 0;
    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const y = window.scrollY || 0;
        const delta = y - lastY;
        if (Math.abs(delta) > 8) {
          setMinimized(delta > 0 && y > 80);
          lastY = y;
        }
        ticking = false;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [standalone]);

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

  // Match the current route to a tab so the selected pill is right even for deep
  // routes (a car detail lives under Search, an enquiry list under Saved cars).
  const p = location.pathname;
  const strip = (s) => s.replace(/^\/[a-z]{2}(?=\/|$)/, "");
  const currentPath = strip(p);
  const activeTab = currentPath.startsWith("/saved")
    ? "saved"
    : currentPath.startsWith("/searches")
      ? "searches"
      : currentPath.startsWith("/track")
        ? "track"
        : "search";

  return (
    <nav
      data-testid="pwa-tabbar"
      aria-label={t("pwaTabBarAria")}
      className={`lg-tabbar ${minimized ? "lg-tabbar-min" : ""}`}
    >
      {/* Layer 1: base blur + adaptive tint. Real refraction (SVG displacement) is
          Chromium-only and the actual iOS PWA runs on Safari, so we ship the frosted
          approximation everywhere and let Chromium enjoy the extra crispness. */}
      <span className="lg-blur" aria-hidden="true" />
      <span className="lg-tint" aria-hidden="true" />
      {/* Layer 3: specular rim — a lit bezel that reads as convex glass. */}
      <span className="lg-rim" aria-hidden="true" />
      {/* Layer 4: content (icons + labels). */}
      <div className="lg-tabs">
        <Tab
          testid="pwa-tab-search"
          to={path("/")}
          label={t("navSearch")}
          icon={Search}
          active={activeTab === "search"}
        />
        <Tab
          testid="pwa-tab-saved"
          to={path("/saved")}
          label={t("savedCars")}
          icon={Heart}
          active={activeTab === "saved"}
        />
        <Tab
          testid="pwa-tab-searches"
          to={path("/searches")}
          label={t("savedSearches")}
          icon={Bookmark}
          active={activeTab === "searches"}
        />
        <Tab
          testid="pwa-tab-track"
          to={path("/track")}
          label={t("navTrack")}
          icon={Ship}
          active={activeTab === "track"}
        />
        <button
          type="button"
          data-testid="pwa-tab-share"
          onClick={onShare}
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

const Tab = ({ testid, to, label, icon: Icon, active }) => (
  <NavLink
    to={to}
    data-testid={testid}
    end={to.match(/^\/[a-z]{2}$/) != null}
    className={`lg-tab ${active ? "lg-tab-active" : ""}`}
    aria-current={active ? "page" : undefined}
  >
    {active ? <span className="lg-tab-pill" aria-hidden="true" /> : null}
    <span className="lg-tab-icon">
      <Icon className="h-[22px] w-[22px]" aria-hidden="true" />
    </span>
    <span className="lg-tab-label">{label}</span>
  </NavLink>
);

export default PwaTabBar;
