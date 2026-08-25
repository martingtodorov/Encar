import {
  Menu,
  LogIn,
  UserPlus,
  LogOut,
  Gauge,
  ShieldCheck,
  Sun,
  Moon,
  Check,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useNavItems } from "@/lib/nav";
import { LANGS, CURRENCIES } from "@/i18n";

// Circular one-tap preference buttons in the drawer: the current value is on the face and a
// click moves to the next one.
const CIRCLE =
  "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-border bg-card text-[12.5px] font-bold uppercase tracking-tight text-foreground transition-all duration-200 hover:border-[hsl(var(--primary)/0.45)] hover:text-[hsl(var(--primary))] active:scale-95";

export const NavDrawer = () => {
  const { t, favourites, lang, currency, setCurrency, theme, toggleTheme, searches } = useApp();
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const { path, go, switchLang } = useLangNav();
  const [open, setOpen] = useState(false);

  const items = useNavItems();

  const navTo = (to) => {
    setOpen(false);
    go(to);
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          data-testid="nav-menu-button"
          variant="ghost"
          aria-label={t("navMenu")}
          className="h-12 w-12 shrink-0 rounded-full p-0 hover:bg-muted"
        >
          <Menu className="!h-6 !w-6 text-foreground" aria-hidden="true" />
        </Button>
      </SheetTrigger>

      {/* Slides DOWN from the top edge. Capped height + scroll so a long menu still
          works on a short phone, with the account actions pinned at the bottom. */}
      <SheetContent
        side="top"
        data-testid="nav-drawer-panel"
        className="thin-scroll max-h-[92vh] overflow-y-auto rounded-b-[18px] border-border bg-card p-0"
      >
        <SheetHeader className="border-b border-border px-4 py-4 text-left">
          <SheetTitle className="text-[15px] font-semibold">{t("navMenu")}</SheetTitle>
        </SheetHeader>

        <nav className="flex flex-col p-2" data-testid="nav-drawer">
          <div className="sm:grid sm:grid-cols-3 sm:gap-2">
            {items.map(({ to, label, icon: Icon, count }) => {
              const activeRoute = pathname === path(to);
              return (
                <Link
                  key={to}
                  to={path(to)}
                  onClick={() => setOpen(false)}
                  data-testid={`nav-link-${to === "/" ? "search" : to.slice(1)}`}
                  className={`flex items-center gap-3 rounded-[10px] px-3 py-3 text-[14px] font-medium transition-colors ${
                    activeRoute
                      ? "bg-secondary text-[hsl(var(--primary))]"
                      : "text-foreground hover:bg-muted"
                  }`}
                >
                  <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                  <span className="flex-1">{label}</span>
                  {count ? (
                    <Badge className="h-5 min-w-5 justify-center rounded-full bg-[hsl(var(--primary))] px-1.5 text-[11px] text-primary-foreground">
                      {count}
                    </Badge>
                  ) : null}
                </Link>
              );
            })}
          </div>

          <Separator className="my-3" />

          {/* One line, three circles. A press OPENS the list and you pick — cycling made you
              tap twice to get from BG to EN and gave no idea what was next. Theme stays a
              straight switch: with two states a menu is one tap too many. */}
          <div className="flex items-center gap-2.5 px-2">
            {/* modal={false} on both menus: Radix's default is `modal: true`, which pins
                `pointer-events: none` on <body> while the dropdown Portal is mounted.
                If the outer Sheet unmounts (via `setOpen(false)` below) BEFORE the menu
                finishes closing, Radix's cleanup misses the body style and every button
                on the page reads as unresponsive until a full navigation happens. A
                non-modal dropdown does not touch <body> at all, so nothing to leak. */}
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="language-cycle"
                  aria-label={`${t("language")}: ${lang.toUpperCase()}`}
                  className={CIRCLE}
                >
                  {lang.toUpperCase()}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[9rem]">
                <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  {t("language")}
                </DropdownMenuLabel>
                {LANGS.map((l) => (
                  <DropdownMenuItem
                    key={l.code}
                    data-testid={`language-option-${l.code}`}
                    onSelect={() => {
                      // Close the outer Sheet at the same time as we swap the language.
                      // If we do not, Radix keeps the Sheet's overlay mounted while the
                      // route changes underneath it, and the whole page reads as frozen
                      // because every tap after that lands on the invisible overlay.
                      setOpen(false);
                      switchLang(l.code);
                    }}
                    className="justify-between text-[13.5px]"
                  >
                    {l.label}
                    {l.code === lang ? (
                      <Check className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="currency-cycle"
                  aria-label={`${t("currency")}: ${currency}`}
                  className={CIRCLE}
                >
                  {currency}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[9rem]">
                <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  {t("currency")}
                </DropdownMenuLabel>
                {CURRENCIES.map((c) => (
                  <DropdownMenuItem
                    key={c.code}
                    data-testid={`currency-option-${c.code}`}
                    onSelect={() => {
                      // Same reason as the language menu above: close the Sheet so the
                      // page becomes tappable again. Radix leaves the overlay mounted
                      // while state updates ripple through the tree, which reads as
                      // "every button is broken" until the drawer is dismissed.
                      setOpen(false);
                      setCurrency(c.code);
                    }}
                    className="justify-between text-[13.5px]"
                  >
                    {c.label || c.code}
                    {c.code === currency ? (
                      <Check className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <button
              type="button"
              data-testid="theme-toggle"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? t("lightMode") : t("darkMode")}
              title={theme === "dark" ? t("lightMode") : t("darkMode")}
              className={CIRCLE}
            >
              {theme === "dark" ? (
                <Sun className="h-[18px] w-[18px]" aria-hidden="true" />
              ) : (
                <Moon className="h-[18px] w-[18px]" aria-hidden="true" />
              )}
            </button>
          </div>

          {/* account actions, always last in the drawer */}
          <Separator className="my-3" />

          {user ? (
            <div data-testid="drawer-account" className="px-1 pb-2">
              <div className="flex items-center gap-2 px-2 pb-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-[13px] font-semibold text-[hsl(var(--primary))]">
                  {(user.email || "?").slice(0, 1).toUpperCase()}
                </span>
                <div className="min-w-0">
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {t("signedInAs")}
                  </div>
                  <div
                    data-testid="drawer-account-email"
                    className="truncate text-[13.5px] font-medium text-foreground"
                  >
                    {user.email}
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row">
                {user.is_admin && (
                  <Button
                    data-testid="drawer-admin-button"
                    variant="outline"
                    onClick={() => navTo("/admin")}
                    className="h-11 flex-1 justify-center gap-2 rounded-[10px] border-border bg-card text-[14px] font-medium hover:bg-muted"
                  >
                    <Gauge className="h-4 w-4" aria-hidden="true" />
                    Operations
                  </Button>
                )}
                <Button
                  data-testid="drawer-account-button"
                  variant="outline"
                  onClick={() => navTo("/account")}
                  className="h-11 flex-1 justify-center gap-2 rounded-[10px] border-border bg-card text-[14px] font-medium hover:bg-muted"
                >
                  <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  {t("myAccount")}
                </Button>
                <Button
                  data-testid="drawer-logout-button"
                  variant="ghost"
                  onClick={async () => {
                    await logout();
                    setOpen(false);
                  }}
                  className="h-11 flex-1 justify-center gap-2 rounded-[10px] text-[14px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <LogOut className="h-4 w-4" aria-hidden="true" />
                  {t("logout")}
                </Button>
              </div>
            </div>
          ) : (
            <div data-testid="drawer-auth" className="flex flex-col gap-2 px-1 pb-2 sm:flex-row">
              <Button
                data-testid="drawer-login-button"
                onClick={() => navTo("/login")}
                className="h-11 flex-1 justify-center gap-2 rounded-[10px] bg-[hsl(var(--primary))] text-[14px] font-semibold text-primary-foreground hover:brightness-110"
              >
                <LogIn className="h-4 w-4" aria-hidden="true" />
                {t("login")}
              </Button>
              <Button
                data-testid="drawer-register-button"
                variant="outline"
                onClick={() => navTo("/login?mode=register")}
                className="h-11 flex-1 justify-center gap-2 rounded-[10px] border-border bg-card text-[14px] font-medium hover:bg-muted"
              >
                <UserPlus className="h-4 w-4" aria-hidden="true" />
                {t("register")}
              </Button>
            </div>
          )}
        </nav>
      </SheetContent>
    </Sheet>
  );
};

export default NavDrawer;
