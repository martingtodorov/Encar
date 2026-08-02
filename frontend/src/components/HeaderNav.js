import { Heart, HelpCircle, Moon, Search, Sun, Gauge, Bookmark } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { LANGS } from "@/i18n";

/**
 * Desktop navigation, always visible in the header.
 *
 * On desktop there is no reason to hide navigation behind a hamburger: there is room for
 * it, and a drawer costs a click for every move. The drawer stays for mobile only.
 */
export const HeaderNav = () => {
  const { t, favourites, lang, theme, toggleTheme, searches } = useApp();
  const { user } = useAuth();
  const { pathname } = useLocation();
  const { path, switchLang } = useLangNav();

  const items = [
    { to: "/", label: t("navSearch"), icon: Search },
    { to: "/saved", label: t("savedCars"), icon: Heart, count: favourites.length },
    { to: "/searches", label: t("savedSearches"), icon: Bookmark, count: searches.length },
    { to: "/how-it-works", label: t("navHowItWorks"), icon: HelpCircle },
  ];

  return (
    <nav data-testid="header-nav" className="flex flex-1 items-center gap-1">
      {items.map(({ to, label, icon: Icon, count }) => {
        const on = pathname === path(to);
        return (
          <Link
            key={to}
            to={path(to)}
            data-testid={`header-nav-link-${to === "/" ? "search" : to.slice(1)}`}
            aria-current={on ? "page" : undefined}
            className={`inline-flex h-10 items-center gap-2 rounded-[10px] px-3 text-[13.5px] font-medium transition-colors ${
              on
                ? "bg-secondary text-[hsl(var(--primary))]"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {label}
            {count ? (
              <span className="tnum ml-0.5 rounded-full bg-[hsl(var(--primary))] px-1.5 py-0.5 text-[10.5px] font-semibold text-primary-foreground">
                {count}
              </span>
            ) : null}
          </Link>
        );
      })}

      <div className="ml-auto flex items-center gap-2">
        <div className="inline-flex rounded-[10px] border border-input bg-muted p-0.5 shadow-sm">
          {LANGS.map((l) => (
            <button
              key={l.code}
              type="button"
              data-testid={`header-language-${l.code}`}
              onClick={() => switchLang(l.code)}
              aria-pressed={l.code === lang}
              className={`h-8 rounded-[8px] px-2.5 text-[12px] font-semibold uppercase transition-colors ${
                l.code === lang
                  ? "bg-card text-[hsl(var(--primary))] shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {l.short}
            </button>
          ))}
        </div>

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

        {user ? (
          <>
            {user.is_admin && (
              <Link
                to={path("/admin")}
                data-testid="header-admin-link"
                className="inline-flex h-10 items-center gap-2 rounded-[10px] px-3 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Gauge className="h-4 w-4" aria-hidden="true" />
                Operations
              </Link>
            )}
            <Link
              to={path("/account")}
              data-testid="header-account-link"
              className="inline-flex h-10 items-center gap-2 rounded-[10px] border border-input bg-card px-3 text-[13.5px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted"
            >
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-[hsl(var(--primary))]">
                {(user.email || "?").slice(0, 1).toUpperCase()}
              </span>
              {t("myAccount")}
            </Link>
          </>
        ) : (
          <>
            <Link
              to={path("/login")}
              data-testid="header-login-link"
              className="inline-flex h-10 items-center rounded-[10px] px-3 text-[13.5px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              {t("login")}
            </Link>
            <Link to={path("/login?mode=register")} data-testid="header-register-link">
              <Button className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground shadow-sm transition-all hover:brightness-110">
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
