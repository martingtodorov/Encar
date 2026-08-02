import {
  Menu,
  Search,
  Heart,
  HelpCircle,
  LogIn,
  UserPlus,
  LogOut,
  Gauge,
  ShieldCheck,
  Sun,
  Moon,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { LANGS, CURRENCIES } from "@/i18n";

export const NavDrawer = () => {
  const { t, favourites, lang, setLang, currency, setCurrency, theme, toggleTheme } = useApp();
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const items = [
    { to: "/", label: t("navSearch"), icon: Search },
    { to: "/saved", label: t("savedCars"), icon: Heart, count: favourites.length },
    { to: "/how-it-works", label: t("navHowItWorks"), icon: HelpCircle },
  ];

  const go = (to) => {
    setOpen(false);
    navigate(to);
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          data-testid="nav-menu-button"
          variant="ghost"
          aria-label={t("navMenu")}
          className="h-10 w-10 shrink-0 p-0 hover:bg-muted"
        >
          <Menu className="h-6 w-6 text-foreground" aria-hidden="true" />
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
              const activeRoute = pathname === to;
              return (
                <Link
                  key={to}
                  to={to}
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

          {/* Language and currency as compact inline toggles - they are one-tap
              preferences, not sections worth scrolling through. */}
          <div className="flex flex-col gap-2.5 px-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("language")}
              </span>
              <div className="inline-flex rounded-[10px] border border-border bg-muted p-0.5">
                {LANGS.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    data-testid={`language-option-${l.code}`}
                    onClick={() => setLang(l.code)}
                    aria-pressed={l.code === lang}
                    className={`h-8 rounded-[8px] px-3 text-[12.5px] font-semibold uppercase transition-colors ${
                      l.code === lang
                        ? "bg-card text-[hsl(var(--primary))] shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {l.code}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("currency")}
              </span>
              <div className="inline-flex rounded-[10px] border border-border bg-muted p-0.5">
                {CURRENCIES.map((c) => (
                  <button
                    key={c.code}
                    type="button"
                    data-testid={`currency-option-${c.code}`}
                    onClick={() => setCurrency(c.code)}
                    aria-pressed={c.code === currency}
                    className={`h-8 rounded-[8px] px-3 text-[12.5px] font-semibold transition-colors ${
                      c.code === currency
                        ? "bg-card text-[hsl(var(--primary))] shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {c.code}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("appearance")}
              </span>
              <div className="inline-flex rounded-[10px] border border-border bg-muted p-0.5">
                {[
                  { key: "light", icon: Sun, label: t("lightMode") },
                  { key: "dark", icon: Moon, label: t("darkMode") },
                ].map(({ key, icon: Icon, label }) => (
                  <button
                    key={key}
                    type="button"
                    data-testid={key === "dark" ? "theme-toggle" : `theme-option-${key}`}
                    onClick={() => {
                      if (theme !== key) toggleTheme();
                    }}
                    aria-pressed={theme === key}
                    aria-label={label}
                    className={`inline-flex h-8 w-10 items-center justify-center rounded-[8px] transition-colors ${
                      theme === key
                        ? "bg-card text-[hsl(var(--primary))] shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
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
                    onClick={() => go("/admin")}
                    className="h-11 flex-1 justify-center gap-2 rounded-[10px] border-border bg-card text-[14px] font-medium hover:bg-muted"
                  >
                    <Gauge className="h-4 w-4" aria-hidden="true" />
                    Operations
                  </Button>
                )}
                <Button
                  data-testid="drawer-account-button"
                  variant="outline"
                  onClick={() => go("/account")}
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
                onClick={() => go("/login")}
                className="h-11 flex-1 justify-center gap-2 rounded-[10px] bg-[hsl(var(--primary))] text-[14px] font-semibold text-primary-foreground hover:brightness-110"
              >
                <LogIn className="h-4 w-4" aria-hidden="true" />
                {t("login")}
              </Button>
              <Button
                data-testid="drawer-register-button"
                variant="outline"
                onClick={() => go("/login?mode=register")}
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
