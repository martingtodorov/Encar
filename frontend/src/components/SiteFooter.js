import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { COMPANY, FOOTER_COLUMNS } from "@/content/company";
import { openCookieSettings } from "@/components/CookieBar";

/** Pick the right response-time line based on what the owner typed. `24` → hourly copy,
 *  `2 business` → business-hours copy, blank → generic fallback. */
function responsePromiseCopy(raw, t) {
  const value = String(raw || "").trim();
  if (!value) return t("responsePromiseFallback");
  const match = value.match(/^(\d+(?:[.,]\d+)?)\s*(.*)$/);
  if (!match) return t("responsePromiseFallback");
  const hours = match[1].replace(",", ".");
  const suffix = match[2].toLowerCase();
  const business = /business|работн|lucrător|lucratoare/i.test(suffix);
  return t(business ? "responsePromiseBusiness" : "responsePromise", { hours });
}

/** Who we are, and every page on the site in three columns. On every page. */
export const SiteFooter = () => {
  const { t, cms } = useApp();
  const { path } = useLangNav();

  // The owner's own details win; the built-ins are the fallback.
  const co = { ...COMPANY, ...(cms?.company || {}) };

  return (
    <footer data-testid="site-footer" className="border-t border-border bg-card">
      <div className="mx-auto grid max-w-[1280px] gap-8 px-4 py-10 sm:px-6 lg:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,1fr))]">
        <div className="max-w-md">
          <img
            src="/logo-220.png"
            alt="Europe Encar"
            data-testid="footer-logo"
            width={127}
            height={36}
            loading="lazy"
            decoding="async"
            className="mb-4 block h-9 w-auto"
          />
          {/* The company name, EIK, address and phone were REMOVED from the footer at the
              owner's request. They still live in the legal pages (content/legal.js), which is
              where the identification obligation is met. */}
          <div className="mt-1 flex flex-col gap-0.5">
            <a
              href={`mailto:${co.email}`}
              data-testid="footer-email"
              className="text-[12.5px] font-medium text-primary hover:underline"
            >
              {co.email}
            </a>
          </div>
          {/* A response-time promise builds trust the way a phone number cannot: it says
              what "quick" means. Owner sets the hours in Admin -> Company. When the field
              is blank we fall back to a soft copy line rather than nothing. */}
          <p
            data-testid="footer-response-promise"
            className="mt-3 text-[12px] font-medium leading-relaxed text-foreground"
          >
            {responsePromiseCopy(co.response_hours, t)}
          </p>
          <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
            {t("footerNote")}
          </p>
          {/* Every price is a won amount converted at the day's rate, so it really does move
              overnight. Saying so here stops it reading as a mistake. */}
          <p
            data-testid="footer-fx-note"
            className="mt-2 text-[12px] leading-relaxed text-muted-foreground"
          >
            {t("fxNote")}
          </p>
        </div>

        {FOOTER_COLUMNS.map((column) => (
          <nav
            key={column.key}
            data-testid={`footer-column-${column.key}`}
            aria-label={t(column.key)}
            className="flex flex-col gap-2.5"
          >
            <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
              {t(column.key)}
            </div>
            {column.links.map(({ to, key }) => (
              <Link
                key={to}
                to={path(to)}
                data-testid={`footer-link-${key}`}
                className="w-fit text-[13px] font-medium text-foreground transition-colors hover:text-primary hover:underline"
              >
                {t(key)}
              </Link>
            ))}
          </nav>
        ))}
      </div>

      <div className="border-t border-border">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-2 px-4 py-3.5 text-[12px] text-muted-foreground sm:px-6">
          {/* The BRAND, not the legal entity: the owner asked for the company details to be
              off the footer, and `co.name` printed "Auto&Bid LTD" here. */}
          <span>
            © {new Date().getFullYear()} Encar Europe. {t("footerRights")}
          </span>
          {/* Withdrawing consent has to be as easy as giving it, so it lives on every page. */}
          <button
            type="button"
            data-testid="footer-cookie-settings"
            onClick={openCookieSettings}
            className="font-medium text-foreground transition-colors hover:text-primary hover:underline"
          >
            {t("cookieManage")}
          </button>
        </div>
      </div>
    </footer>
  );
};

export default SiteFooter;
