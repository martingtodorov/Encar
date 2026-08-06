import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

/** Deep pagination: Encar has no offset cap, so we must handle thousands of pages. */
export const ResultsPagination = ({ page, pages, onChange, onPrefetch }) => {
  const { t, lang } = useApp();
  const [jump, setJump] = useState("");
  const navRef = useRef(null);

  // On a phone nobody hovers, so the row scrolling into view is the signal: the visitor has
  // reached the bottom of the results and the next page is the likely next click.
  useEffect(() => {
    const el = navRef.current;
    if (!el || !onPrefetch || page >= pages) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          onPrefetch(page + 1);
          io.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [onPrefetch, page, pages]);

  if (!pages || pages <= 1) return null;

  // Hover or keyboard focus on a page button warms exactly that page.
  const warm = (n) => ({
    onMouseEnter: () => onPrefetch && onPrefetch(n),
    onFocus: () => onPrefetch && onPrefetch(n),
  });

  // A phone gets a sliding run of five consecutive pages (clamped at both ends); the desktop
  // row adds the first and last page around it with ellipses.
  const RUN = 5;
  const start = Math.max(1, Math.min(page - Math.floor(RUN / 2), pages - RUN + 1));
  const near = new Set();
  for (let p = start; p < start + RUN && p <= pages; p += 1) near.add(p);

  const window = [];
  const push = (p) => {
    if (p >= 1 && p <= pages && !window.includes(p)) window.push(p);
  };
  push(1);
  near.forEach(push);
  push(pages);
  window.sort((a, b) => a - b);

  return (
    <nav
      ref={navRef}
      data-testid="pagination"
      className="flex flex-col items-center gap-3 py-8 sm:flex-row sm:justify-between sm:gap-4"
      aria-label={t("page")}
    >
      <div className="flex flex-nowrap items-center gap-1 sm:gap-1.5">
        <Button
          data-testid="pagination-prev"
          variant="outline"
          disabled={page <= 1}
          {...warm(page - 1)}
          onClick={() => onChange(page - 1)}
          className="h-9 gap-1 border-border bg-card px-2 text-sm disabled:opacity-40 sm:h-10 sm:px-3"
          aria-label={t("page")}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </Button>

        {window.map((p, i) => {
          const gap = i > 0 && p - window[i - 1] > 1;
          return (
            <span
              key={p}
              className={`items-center gap-1 sm:gap-1.5 ${
                near.has(p) ? "flex" : "hidden sm:flex"
              }`}
            >
              {gap && <span className="px-1 text-muted-foreground">{"\u2026"}</span>}
              <Button
                data-testid={`pagination-page-${p}`}
                variant={p === page ? "default" : "outline"}
                {...warm(p)}
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
          {...warm(page + 1)}
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
        <span className="whitespace-nowrap text-[13px] text-muted-foreground">
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
        <span className="tnum whitespace-nowrap text-[13px] text-muted-foreground">
          / {formatNumber(pages, lang)}
        </span>
      </form>
    </nav>
  );
};

export default ResultsPagination;
