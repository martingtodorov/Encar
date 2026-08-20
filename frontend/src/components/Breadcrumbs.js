import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { useJsonLd } from "@/lib/seo";

/**
 * The trail from Home to the page a visitor is on, and the BreadcrumbList JSON-LD that
 * turns it into a Google-visible sitelinks strip.
 *
 * `items` is an array of `{ label, to }`. The last item is the current page; if `to` is
 * provided it stays a link (so a buyer can jump from a car back to the model's search
 * with one tap), otherwise it renders as plain text. External absolute URLs are
 * supported for the JSON-LD `item` field but the DOM keeps every link internal via
 * `<Link>`.
 *
 * Year spans (`Cayenne (2019-)`, `C-Class (2014-2021)`) belong on the taxonomy dropdown
 * where two generations must be told apart. Inside a breadcrumb they are noise, so the
 * suffix is stripped here — one place, so no caller can forget.
 */
const YEAR_SPAN_RE = /\s*\((?:19|20)\d{2}\s*[-\u2013]\s*(?:(?:19|20)\d{2})?\)\s*$/;
const stripYearSpan = (label) =>
  typeof label === "string" ? label.replace(YEAR_SPAN_RE, "").trim() : label;

export const Breadcrumbs = ({ items = [], testId = "breadcrumbs" }) => {
  const visible = items
    .filter((i) => i && i.label)
    .map((i) => ({ ...i, label: stripYearSpan(i.label) }));
  if (visible.length < 2) return null;

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const jsonld = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: visible.map((i, idx) => ({
      "@type": "ListItem",
      position: idx + 1,
      name: i.label,
      ...(i.to ? { item: `${origin}${i.to}` } : {}),
    })),
  };

  return (
    <nav
      aria-label="Breadcrumb"
      data-testid={testId}
      className="mx-auto w-full max-w-[1280px] px-4 pt-3 text-[12.5px] text-muted-foreground sm:px-6"
    >
      <BreadcrumbsJsonLd data={jsonld} testId={testId} />
      {/* One line, always. If the trail runs past the viewport on a phone, it scrolls
          horizontally rather than wrapping to a second row (which pushed the H1 down and
          read as a layout glitch). `no-scrollbar` hides the bar itself — the swipe
          affordance is enough. */}
      <ol className="no-scrollbar flex flex-nowrap items-center gap-1.5 overflow-x-auto whitespace-nowrap">
        {visible.map((item, idx) => {
          const isLast = idx === visible.length - 1;
          return (
            <li key={`${item.label}-${idx}`} className="flex shrink-0 items-center gap-1.5">
              {idx > 0 ? (
                <ChevronRight
                  className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                  aria-hidden="true"
                />
              ) : null}
              {!item.to ? (
                <span
                  data-testid={`${testId}-item-${idx}`}
                  aria-current={isLast ? "page" : undefined}
                  className="max-w-[52vw] truncate font-medium text-foreground sm:max-w-none"
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  data-testid={`${testId}-item-${idx}`}
                  to={item.to}
                  aria-current={isLast ? "page" : undefined}
                  className={
                    isLast
                      ? "max-w-[52vw] truncate font-medium text-foreground transition-colors hover:underline sm:max-w-none"
                      : "max-w-[40vw] truncate text-muted-foreground transition-colors hover:text-foreground hover:underline sm:max-w-none"
                  }
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

// A tiny wrapper so each Breadcrumbs instance gets its own JSON-LD script id: multiple
// nested pages could in theory render two of them, and useJsonLd needs a unique id per.
const BreadcrumbsJsonLd = ({ data, testId }) => {
  useJsonLd(data, `${testId}-jsonld`);
  return null;
};

export default Breadcrumbs;
