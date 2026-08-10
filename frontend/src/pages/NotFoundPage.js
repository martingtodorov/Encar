import { Link } from "react-router-dom";
import { Search, Home } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";

/**
 * The 404 page. Kept inside `LangLayout` so the header, footer and cookie bar stay,
 * and marked `noindex` so a mistyped URL never enters the index. React Router alone
 * cannot return an HTTP 404 status — for a real 4xx status the nginx `try_files` in
 * front of the SPA is what closes the loop; here we just make sure the visitor and
 * search engines both know this is a dead end.
 */
export default function NotFoundPage() {
  const { t, lang } = useApp();
  const { path } = useLangNav();

  useSeo({
    lang,
    title: `${t("notFoundTitle")} · Encar`,
    description: t("notFoundLead"),
    noindex: true,
  });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main
        data-testid="not-found-page"
        className="mx-auto flex max-w-[720px] flex-col items-start gap-6 px-4 py-16 sm:px-6 sm:py-24"
      >
        <span
          className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground"
        >
          404
        </span>
        <h1
          data-testid="not-found-title"
          className="text-4xl font-semibold leading-[1.1] tracking-tight text-foreground sm:text-5xl"
        >
          {t("notFoundTitle")}
        </h1>
        <p
          data-testid="not-found-lead"
          className="max-w-[36rem] text-[15px] leading-relaxed text-muted-foreground"
        >
          {t("notFoundLead")}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button asChild data-testid="not-found-home" className="h-11 gap-2 rounded-[10px] px-5 text-[14px] font-semibold">
            <Link to={path("/")}>
              <Home className="h-4 w-4" aria-hidden="true" />
              {t("notFoundHomeCta")}
            </Link>
          </Button>
          <Button
            asChild
            variant="outline"
            data-testid="not-found-search"
            className="h-11 gap-2 rounded-[10px] border-border bg-card px-4 text-[14px] font-semibold"
          >
            <Link to={path("/")}>
              <Search className="h-4 w-4" aria-hidden="true" />
              {t("notFoundSearchCta")}
            </Link>
          </Button>
        </div>
      </main>
    </div>
  );
}
