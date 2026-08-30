import { useEffect, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/BrandLogo";
import { useLangNav } from "@/hooks/useLangNav";
import { useApp } from "@/context/AppContext";
import { NavDrawer } from "@/components/NavDrawer";
import { HeaderNav } from "@/components/HeaderNav";

export const HeaderBar = ({ hidden = false, onBack, flush = false }) => {
  const { t } = useApp();
  const { path } = useLangNav();
  const ref = useRef(null);

  // Publish the header's REAL rendered height (which in a homescreen PWA includes the
  // Dynamic-Island safe-area padding) so every bar that has to hang below it can use
  // one number instead of re-deriving `4rem + env(...)` and drifting out of sync.
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    // `--header-bottom` is the live y of the header's bottom edge: at scroll 0 with a
    // banner above us that is lower than the sticky offset, and it follows the
    // hide-on-scroll transform too. Bars that must hug the header read this, so they
    // can never end up underneath it.
    let raf = 0;
    const publish = () => {
      raf = 0;
      const r = node.getBoundingClientRect();
      const root = document.documentElement.style;
      root.setProperty("--header-h", `${Math.round(r.height)}px`);
      root.setProperty("--header-bottom", `${Math.max(0, Math.round(r.bottom))}px`);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(publish);
    };
    publish();
    const ro = new ResizeObserver(schedule);
    ro.observe(node);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    window.addEventListener("orientationchange", schedule);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("orientationchange", schedule);
    };
  }, []);

  return (
    <header
      ref={ref}
      data-testid="header-bar"
      data-hidden={hidden ? "true" : "false"}
      // `flush`: something sits immediately below (the mobile filter bar), and the
      // header's own shadow and border would read as a dividing line between them.
      className={`sticky top-[var(--admin-bar-h,0px)] z-40 bg-card transition-transform duration-300 lg:translate-y-0 ${
        flush ? "border-b-0 shadow-none" : "border-b border-border shadow-sm"
      } ${hidden ? "-translate-y-full" : "translate-y-0"}`}
    >
      <div className="mx-auto flex h-16 max-w-[1280px] items-center gap-3 px-3 sm:px-6 lg:gap-8">
        {/* Mobile: logo centred, menu at the right edge under the thumb; the empty
            left cell is what keeps the logo optically centred. Theme lives in the drawer.
            Desktop: logo left, full nav inline, no drawer at all. */}
        {/* On a car page the way back belongs in the header on mobile, where the
            in-page button sat below the fold. Otherwise this cell just balances the
            menu button so the logo stays centred. */}
        <div className="flex w-12 shrink-0 lg:hidden">
          {onBack ? (
            <Button
              data-testid="header-back-button"
              variant="ghost"
              onClick={onBack}
              aria-label={t("backToResults")}
              className="h-12 w-12 rounded-full p-0 hover:bg-muted"
            >
              <ArrowLeft className="!h-6 !w-6 text-foreground" aria-hidden="true" />
            </Button>
          ) : null}
        </div>

        <div className="flex flex-1 justify-center lg:flex-none lg:justify-start">
          {/* The logo is a "start over" button: on a filtered search the URL alone would
              be rewritten straight back by the live filters, so it carries a reset flag. */}
          <Link
            to={path("/")}
            state={{ home: Date.now() }}
            data-testid="header-logo-link"
            aria-label="Encar"
            className="inline-flex items-center"
          >
            <BrandLogo compact />
          </Link>
        </div>

        <div className="hidden flex-1 lg:flex">
          <HeaderNav />
        </div>

        <div className="flex w-12 shrink-0 justify-end lg:hidden">
          <NavDrawer />
        </div>
      </div>
    </header>
  );
};

export default HeaderBar;
