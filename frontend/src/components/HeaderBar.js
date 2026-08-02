import { Link } from "react-router-dom";
import { BrandLogo } from "@/components/BrandLogo";
import { NavDrawer } from "@/components/NavDrawer";
import { HeaderNav } from "@/components/HeaderNav";

export const HeaderBar = ({ hidden = false }) => {
  return (
    <header
      data-testid="header-bar"
      data-hidden={hidden ? "true" : "false"}
      className={`sticky top-0 z-40 border-b border-border bg-card shadow-sm transition-transform duration-300 lg:translate-y-0 ${
        hidden ? "-translate-y-full" : "translate-y-0"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-[1280px] items-center gap-3 px-3 sm:px-6">
        {/* Mobile: logo centred, menu at the right edge under the thumb; the empty
            left cell is what keeps the logo optically centred. Theme lives in the drawer.
            Desktop: logo left, full nav inline, no drawer at all. */}
        <div className="w-10 shrink-0 lg:hidden" aria-hidden="true" />

        <div className="flex flex-1 justify-center lg:flex-none lg:justify-start">
          <Link to="/" aria-label="Encar" className="inline-flex items-center">
            <BrandLogo compact />
          </Link>
        </div>

        <div className="hidden flex-1 lg:flex">
          <HeaderNav />
        </div>

        <div className="flex w-10 shrink-0 justify-end lg:hidden">
          <NavDrawer />
        </div>
      </div>
    </header>
  );
};

export default HeaderBar;
