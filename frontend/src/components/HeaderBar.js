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

  return (
    <header
      data-testid="header-bar"
      data-hidden={hidden ? "true" : "false"}
      // `flush`: something sits immediately below (the mobile filter bar), and the
      // header's own shadow and border would read as a dividing line between them.
      className={`sticky top-0 z-40 bg-card transition-transform duration-300 lg:translate-y-0 ${
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
