import { useState } from "react";
import { ChevronDown, Moon, Sun } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { LanguageMenu } from "@/components/LanguageMenu";
import { ProfileMenu } from "@/components/ProfileMenu";
import { useNavItems } from "@/lib/nav";

/**
 * Desktop navigation, always visible in the header.
 *
 * On desktop there is no reason to hide navigation behind a hamburger: there is room for
 * it, and a drawer costs a click for every move. The drawer stays for mobile only.
 *
 * Words only, no icons: at this size the label already says everything, and a row of small
 * glyphs just adds noise. Each label is kept on ONE line and the items are evenly spaced.
 */
const LINK =
  "inline-flex h-10 items-center whitespace-nowrap rounded-[10px] px-2 text-[14px] font-medium transition-colors";

export const HeaderNav = () => {
  const { t, favourites, theme, toggleTheme, searches } = useApp();
  const { user } = useAuth();
  const { pathname } = useLocation();
  const { path } = useLangNav();
  const [openFav, setOpenFav] = useState(false);

  const items = useNavItems();
  const primary = items.find((i) => i.to === "/");
  const rest = items.filter(
    (i) => !["/", "/saved", "/searches"].includes(i.to)
  );

  const favItems = items.filter((i) => ["/saved", "/searches"].includes(i.to));
  const favActive = favItems.some((f) => pathname === path(f.to));
  const favCount = favourites.length + searches.length;

  const cls = (on) =>
    `${LINK} ${on
      ? "bg-secondary text-[hsl(var(--primary))]"
      : "text-muted-foreground hover:bg-muted hover:text-foreground"}`;

  return (
    <nav data-testid="header-nav" className="flex flex-1 items-center gap-5">
      <Link
        to={`${path(primary.to)}#search`}
        data-testid="header-nav-link-search"
        aria-current={pathname === path("/") ? "page" : undefined}
        className={cls(pathname === path("/"))}
      >
        {primary.label}
      </Link>

      {/* Favourites: one word in the bar, both lists a hover away. `focus-within` keeps it
          reachable with a keyboard, which a pure :hover menu would lock out. */}
      <div
        className="relative"
        onMouseEnter={() => setOpenFav(true)}
        onMouseLeave={() => setOpenFav(false)}
      >
        <button
          type="button"
          data-testid="header-nav-favourites"
          aria-expanded={openFav}
          aria-haspopup="true"
          onClick={() => setOpenFav((v) => !v)}
          className={`${cls(favActive)} gap-1.5`}
        >
          {t("navFavourites")}
          {favCount ? (
            <span className="tnum rounded-full bg-[hsl(var(--primary))] px-1.5 py-0.5 text-[10.5px] font-semibold text-primary-foreground">
              {favCount}
            </span>
          ) : null}
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform duration-200 ${openFav ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>

        <div
          data-testid="header-favourites-menu"
          className={`absolute left-0 top-[calc(100%+2px)] z-50 w-[230px] origin-top rounded-[12px] border border-border bg-card p-1.5 shadow-lg transition-all duration-150 ${
            openFav
              ? "visible translate-y-0 opacity-100"
              : "invisible -translate-y-1 opacity-0"
          }`}
        >
          {favItems.map(({ to, label, count }) => (
            <Link
              key={to}
              to={path(to)}
              data-testid={`header-nav-link-${to.slice(1)}`}
              onClick={() => setOpenFav(false)}
              className={`flex items-center justify-between gap-3 whitespace-nowrap rounded-[9px] px-3 py-2 text-[13.5px] font-medium transition-colors ${
                pathname === path(to)
                  ? "bg-secondary text-[hsl(var(--primary))]"
                  : "text-foreground hover:bg-muted"
              }`}
            >
              {label}
              {count ? (
                <span className="tnum text-[12px] font-semibold text-muted-foreground">
                  {count}
                </span>
              ) : null}
            </Link>
          ))}
        </div>
      </div>

      {rest.map(({ to, label }) => (
        <Link
          key={to}
          to={path(to)}
          data-testid={`header-nav-link-${to.slice(1)}`}
          aria-current={pathname === path(to) ? "page" : undefined}
          className={cls(pathname === path(to))}
        >
          {label}
        </Link>
      ))}

      {/* Everything that is not navigation lives on the right: language, theme and the
          account actions. With only sign-in/register over there the bar read lopsided. */}
      <div className="ml-auto flex items-center gap-2">
        <LanguageMenu />

        <Button
          data-testid="theme-toggle-desktop"
          variant="outline"
          onClick={toggleTheme}
          aria-label={t(theme === "dark" ? "lightMode" : "darkMode")}
          className="h-10 w-10 rounded-full border-input bg-card p-0 shadow-sm hover:bg-muted"
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4 text-[hsl(var(--accent))]" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          )}
        </Button>
      </div>

      <div className="flex items-center gap-2">
        {user ? (
          <ProfileMenu />
        ) : (
          <>
            <Link
              to={path("/login")}
              data-testid="header-login-link"
              className="inline-flex h-10 items-center whitespace-nowrap rounded-[10px] px-3 text-[13.5px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              {t("login")}
            </Link>
            <Link to={path("/login?mode=register")} data-testid="header-register-link">
              <Button className="h-10 whitespace-nowrap rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground shadow-sm transition-all hover:brightness-110">
                {t("register")}
              </Button>
            </Link>
          </>
        )}
      </div>
    </nav>
  );
};

export default HeaderNav;
