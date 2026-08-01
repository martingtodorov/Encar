import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

/** Deep pagination: Encar has no offset cap, so we must handle thousands of pages. */
export const ResultsPagination = ({ page, pages, onChange }) => {
  const { t, lang } = useApp();
  const [jump, setJump] = useState("");

  if (!pages || pages <= 1) return null;

  const window = [];
  const push = (p) => {
    if (p >= 1 && p <= pages && !window.includes(p)) window.push(p);
  };
  push(1);
  for (let p = page - 2; p <= page + 2; p += 1) push(p);
  push(pages);
  window.sort((a, b) => a - b);

  return (
    <nav
      data-testid="pagination"
      className="flex flex-col items-center gap-4 py-8 sm:flex-row sm:justify-between"
      aria-label={t("page")}
    >
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        <Button
          data-testid="pagination-prev"
          variant="outline"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="h-10 gap-1 border-border bg-card px-3 text-sm disabled:opacity-40"
          aria-label={t("page")}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </Button>

        {window.map((p, i) => {
          const gap = i > 0 && p - window[i - 1] > 1;
          return (
            <span key={p} className="flex items-center gap-1.5">
              {gap && <span className="px-1 text-muted-foreground">{"\u2026"}</span>}
              <Button
                data-testid={`pagination-page-${p}`}
                variant={p === page ? "default" : "outline"}
                onClick={() => onChange(p)}
                aria-current={p === page ? "page" : undefined}
                className={`tnum h-10 min-w-10 px-3 text-sm ${
                  p === page
                    ? "bg-[hsl(var(--primary))] text-primary-foreground hover:brightness-110"
                    : "border-border bg-card text-foreground hover:bg-muted"
                }`}
              >
                {formatNumber(p, lang)}
              </Button>
            </span>
          );
        })}

        <Button
          data-testid="pagination-next"
          variant="outline"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
          className="h-10 gap-1 border-border bg-card px-3 text-sm disabled:opacity-40"
          aria-label={t("page")}
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const n = parseInt(jump, 10);
          if (n >= 1 && n <= pages) {
            onChange(n);
            setJump("");
          }
        }}
      >
        <span className="whitespace-nowrap text-[13px] text-muted-foreground">
          {t("goToPage")}
        </span>
        <Input
          data-testid="pagination-jump-input"
          value={jump}
          onChange={(e) => setJump(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder={String(page)}
          aria-label={t("goToPage")}
          className="tnum h-10 w-20 border-border bg-card text-center text-sm"
        />
        <Button
          data-testid="pagination-jump-button"
          type="submit"
          variant="secondary"
          className="h-10 bg-secondary px-3 text-sm text-[hsl(var(--primary))] hover:brightness-95"
        >
          {t("go")}
        </Button>
        <span className="tnum whitespace-nowrap text-[13px] text-muted-foreground">
          / {formatNumber(pages, lang)}
        </span>
      </form>
    </nav>
  );
};

export default ResultsPagination;
