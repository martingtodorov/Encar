import { Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/BrandLogo";
import { NavDrawer } from "@/components/NavDrawer";
import { useApp } from "@/context/AppContext";

export const HeaderBar = ({ hidden = false }) => {
  const { theme, toggleTheme, t } = useApp();

  return (
    <header
      data-testid="header-bar"
      data-hidden={hidden ? "true" : "false"}
      className={`sticky top-0 z-40 border-b border-border bg-card shadow-[var(--shadow-sm)] transition-transform duration-300 lg:translate-y-0 ${
        hidden ? "-translate-y-full" : "translate-y-0"
      }`}
    >
      <div className="mx-auto grid h-16 max-w-[1280px] grid-cols-[auto_1fr_auto] items-center gap-2 px-3 sm:px-6">
        {/* left: navigation drawer (also holds language + currency) */}
        <NavDrawer />

        {/* centre: logo */}
        <div className="flex justify-center">
          <Link to="/" aria-label="Encar" className="inline-flex items-center">
            <BrandLogo compact />
          </Link>
        </div>

        {/* right: theme toggle only */}
        <div className="flex items-center justify-end">
          <Button
            data-testid="theme-toggle"
            variant="outline"
            onClick={toggleTheme}
            aria-label={t(theme === "dark" ? "lightMode" : "darkMode")}
            className="h-10 w-10 rounded-full border-border bg-card p-0 hover:bg-muted"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-[hsl(var(--accent))]" aria-hidden="true" />
            ) : (
              <Moon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            )}
          </Button>
        </div>
      </div>
    </header>
  );
};

export default HeaderBar;
