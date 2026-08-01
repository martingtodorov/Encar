import { Menu, Search, Heart, HelpCircle, Globe, Coins, Check } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useApp } from "@/context/AppContext";
import { LANGS, CURRENCIES } from "@/i18n";

const SectionLabel = ({ icon: Icon, children }) => (
  <div className="mb-1.5 mt-2 flex items-center gap-2 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
    <Icon className="h-3.5 w-3.5" aria-hidden="true" />
    {children}
  </div>
);

export const NavDrawer = () => {
  const { t, favourites, lang, setLang, currency, setCurrency } = useApp();
  const { pathname } = useLocation();

  const items = [
    { to: "/", label: t("navSearch"), icon: Search },
    { to: "/saved", label: t("savedCars"), icon: Heart, count: favourites.length },
    { to: "/how-it-works", label: t("navHowItWorks"), icon: HelpCircle },
  ];

  return (
    <Sheet>
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
      <SheetContent side="left" className="thin-scroll w-[86vw] max-w-xs overflow-y-auto bg-card p-0">
        <SheetHeader className="border-b border-border px-4 py-4 text-left">
          <SheetTitle className="text-[15px] font-semibold">{t("navMenu")}</SheetTitle>
        </SheetHeader>

        <nav className="flex flex-col p-2" data-testid="nav-drawer">
          {items.map(({ to, label, icon: Icon, count }) => {
            const activeRoute = pathname === to;
            return (
              <Link
                key={to}
                to={to}
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

          <Separator className="my-3" />

          <SectionLabel icon={Globe}>{t("language")}</SectionLabel>
          <div className="flex flex-col">
            {LANGS.map((l) => (
              <button
                key={l.code}
                type="button"
                data-testid={`language-option-${l.code}`}
                onClick={() => setLang(l.code)}
                className={`flex items-center justify-between rounded-[10px] px-3 py-2.5 text-left text-[14px] transition-colors ${
                  l.code === lang
                    ? "bg-secondary font-semibold text-[hsl(var(--primary))]"
                    : "text-foreground hover:bg-muted"
                }`}
              >
                {l.label}
                {l.code === lang && <Check className="h-4 w-4" aria-hidden="true" />}
              </button>
            ))}
          </div>

          <Separator className="my-3" />

          <SectionLabel icon={Coins}>{t("currency")}</SectionLabel>
          <div className="flex flex-col">
            {CURRENCIES.map((c) => (
              <button
                key={c.code}
                type="button"
                data-testid={`currency-option-${c.code}`}
                onClick={() => setCurrency(c.code)}
                className={`flex items-center justify-between rounded-[10px] px-3 py-2.5 text-left text-[14px] transition-colors ${
                  c.code === currency
                    ? "bg-secondary font-semibold text-[hsl(var(--primary))]"
                    : "text-foreground hover:bg-muted"
                }`}
              >
                <span>
                  <span className="mr-2 text-muted-foreground">{c.symbol}</span>
                  {c.code}
                </span>
                {c.code === currency && <Check className="h-4 w-4" aria-hidden="true" />}
              </button>
            ))}
          </div>
        </nav>
      </SheetContent>
    </Sheet>
  );
};

export default NavDrawer;
