import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { COMPANY, FOOTER_COLUMNS } from "@/content/company";

/** Who we are, and every page on the site in three columns. On every page. */
export const SiteFooter = () => {
  const { t } = useApp();
  const { path } = useLangNav();

  const facts = [
    `${COMPANY.name}`,
    COMPANY.eik ? `${t("legalEik")} ${COMPANY.eik}` : "",
    COMPANY.vat ? `${t("legalVat")} ${COMPANY.vat}` : "",
    COMPANY.address,
  ].filter(Boolean);

  return (
    <footer data-testid="site-footer" className="border-t border-border bg-card">
      <div className="mx-auto grid max-w-[1280px] gap-8 px-4 py-10 sm:px-6 lg:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,1fr))]">
        <div className="max-w-md">
          <div className="text-[13.5px] font-semibold text-foreground">{facts[0]}</div>
          <div className="mt-1 flex flex-col gap-0.5">
            {facts.slice(1).map((line) => (
              <span key={line} className="text-[12.5px] text-muted-foreground">
                {line}
              </span>
            ))}
            <a
              href={`mailto:${COMPANY.email}`}
              data-testid="footer-email"
              className="text-[12.5px] font-medium text-primary hover:underline"
            >
              {COMPANY.email}
            </a>
          </div>
          <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
            {t("footerNote")}
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
          © {new Date().getFullYear()} {COMPANY.name}. {t("footerRights")}
        </div>
      </div>
    </footer>
  );
};

export default SiteFooter;
