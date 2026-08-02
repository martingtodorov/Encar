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
      {/*
        Flex + `order` rather than two rendered copies, so there is exactly ONE menu
        button in the DOM (one element, one test id) while its position differs:
          mobile  -> logo, theme, menu   (thumb reaches the menu at the right edge)
          desktop -> menu, logo, theme  (unchanged from before)
      */}
      <div className="mx-auto flex h-16 max-w-[1280px] items-center gap-2 px-3 sm:px-6">
        <div className="order-3 flex shrink-0 lg:order-1">
          <NavDrawer />
        </div>

        <div className="order-1 flex flex-1 justify-start lg:order-2 lg:justify-center">
          <Link to="/" aria-label="Encar" className="inline-flex items-center">
            <BrandLogo compact />
          </Link>
        </div>

        <div className="order-2 flex shrink-0 items-center justify-end lg:order-3">
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
