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
      className="flex flex-nowrap items-center justify-center gap-2 py-8 sm:justify-between sm:gap-4"
      aria-label={t("page")}
    >
      <div className="flex flex-nowrap items-center gap-1 sm:gap-1.5">
        <Button
          data-testid="pagination-prev"
          variant="outline"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="h-9 gap-1 border-border bg-card px-2 text-sm disabled:opacity-40 sm:h-10 sm:px-3"
          aria-label={t("page")}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </Button>

        {window.map((p, i) => {
          const gap = i > 0 && p - window[i - 1] > 1;
          // A phone has room for the current page and its neighbours only: everything
          // else (first, last, the ellipses) is desktop-only so the row stays ONE line.
          const near = Math.abs(p - page) <= 1;
          return (
            <span
              key={p}
              className={`items-center gap-1 sm:gap-1.5 ${near ? "flex" : "hidden sm:flex"}`}
            >
              {gap && <span className="px-1 text-muted-foreground">{"\u2026"}</span>}
              <Button
                data-testid={`pagination-page-${p}`}
                variant={p === page ? "default" : "outline"}
                onClick={() => onChange(p)}
                aria-current={p === page ? "page" : undefined}
                className={`tnum h-9 min-w-9 px-2 text-sm sm:h-10 sm:min-w-10 sm:px-3 ${
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
          className="h-9 gap-1 border-border bg-card px-2 text-sm disabled:opacity-40 sm:h-10 sm:px-3"
          aria-label={t("page")}
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      <form
        className="flex flex-nowrap items-center gap-1.5 sm:gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const n = parseInt(jump, 10);
          if (n >= 1 && n <= pages) {
            onChange(n);
            setJump("");
          }
        }}
      >
        {/* The label and the total only fit once there is room; on a phone the input's
            own placeholder (the current page) says what the field is for. */}
        <span className="hidden whitespace-nowrap text-[13px] text-muted-foreground sm:inline">
          {t("goToPage")}
        </span>
        <Input
          data-testid="pagination-jump-input"
          value={jump}
          onChange={(e) => setJump(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder={String(page)}
          aria-label={t("goToPage")}
          className="tnum h-9 w-14 border-border bg-card px-1 text-center text-sm sm:h-10 sm:w-20 sm:px-3"
        />
        <Button
          data-testid="pagination-jump-button"
          type="submit"
          variant="secondary"
          className="h-9 bg-secondary px-2.5 text-sm text-[hsl(var(--primary))] hover:brightness-95 sm:h-10 sm:px-3"
        >
          {t("go")}
        </Button>
        <span className="tnum hidden whitespace-nowrap text-[13px] text-muted-foreground sm:inline">
          / {formatNumber(pages, lang)}
        </span>
      </form>
    </nav>
  );
};

export default ResultsPagination;
