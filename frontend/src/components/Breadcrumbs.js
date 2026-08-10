import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { useJsonLd } from "@/lib/seo";

/**
 * The trail from Home to the page a visitor is on, and the BreadcrumbList JSON-LD that
 * turns it into a Google-visible sitelinks strip.
 *
 * `items` is an array of `{ label, to }`. The last item is the current page and is not
 * rendered as a link; `to` may be omitted for it. External absolute URLs are supported
 * for the JSON-LD `item` field but the DOM keeps every link internal via `<Link>`.
 */
export const Breadcrumbs = ({ items = [], testId = "breadcrumbs" }) => {
  const visible = items.filter((i) => i && i.label);
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
      <ol className="flex flex-wrap items-center gap-1.5">
        {visible.map((item, idx) => {
          const isLast = idx === visible.length - 1;
          return (
            <li key={`${item.label}-${idx}`} className="flex items-center gap-1.5">
              {idx > 0 ? (
                <ChevronRight
                  className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                  aria-hidden="true"
                />
              ) : null}
              {isLast || !item.to ? (
                <span
                  data-testid={`${testId}-item-${idx}`}
                  aria-current={isLast ? "page" : undefined}
                  className="truncate font-medium text-foreground"
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  data-testid={`${testId}-item-${idx}`}
                  to={item.to}
                  className="truncate text-muted-foreground transition-colors hover:text-foreground hover:underline"
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
