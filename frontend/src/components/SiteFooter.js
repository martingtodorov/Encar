import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { COMPANY, LEGAL_LINKS } from "@/content/company";

/** Who we are and where the legal documents live. On every page. */
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
      <div className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 py-9 sm:px-6 lg:flex-row lg:justify-between">
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

        <nav className="flex flex-col gap-2" aria-label={t("legalTitle")}>
          <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
            {t("legalTitle")}
          </div>
          {LEGAL_LINKS.map(({ to, key }) => (
            <Link
              key={to}
              to={path(to)}
              data-testid={`footer-link-${to.slice(1)}`}
              className="w-fit whitespace-nowrap text-[13px] font-medium text-foreground hover:text-primary hover:underline"
            >
              {t(key)}
            </Link>
          ))}
        </nav>
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
