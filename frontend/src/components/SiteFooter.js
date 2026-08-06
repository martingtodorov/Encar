import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { COMPANY, FOOTER_COLUMNS } from "@/content/company";

/** Who we are, and every page on the site in three columns. On every page. */
export const SiteFooter = () => {
  const { t, cms } = useApp();
  const { path } = useLangNav();

  // The owner's own details win; the built-ins are the fallback.
  const co = { ...COMPANY, ...(cms?.company || {}) };
  const facts = [
    `${co.name}`,
    co.eik ? `${t("legalEik")} ${co.eik}` : "",
    co.vat ? `${t("legalVat")} ${co.vat}` : "",
    co.address,
    co.phone,
  ].filter(Boolean);

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
          <div className="text-[13.5px] font-semibold text-foreground">{facts[0]}</div>
          <div className="mt-1 flex flex-col gap-0.5">
            {facts.slice(1).map((line) => (
              <span key={line} className="text-[12.5px] text-muted-foreground">
                {line}
              </span>
            ))}
            <a
              href={`mailto:${co.email}`}
              data-testid="footer-email"
              className="text-[12.5px] font-medium text-primary hover:underline"
            >
              {co.email}
            </a>
          </div>
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
        <div className="mx-auto max-w-[1280px] px-4 py-3.5 text-[12px] text-muted-foreground sm:px-6">
          © {new Date().getFullYear()} {co.name}. {t("footerRights")}
        </div>
      </div>
    </footer>
  );
};

export default SiteFooter;
