import { ChevronDown } from "lucide-react";
import { useApp } from "@/context/AppContext";

// Sorting default depends on intent:
//  * browsing with no make/model chosen -> "relevant": cars in the makes, price band and
//    mileage range this visitor keeps coming back to. With no history it simply falls back
//    to newest, so a first-time visitor still sees the freshest arrivals.
//  * once a make or model is chosen -> "price_asc", because the question becomes
//    "what is the cheapest one of THESE?"
export const DEFAULT_SORT_BROWSE = "relevant";
export const DEFAULT_SORT_FILTERED = "price_asc";

export const SORT_OPTIONS = [
  { value: "relevant", key: "sortRelevant" },
  { value: "price_asc", key: "sortPriceAsc" },
  { value: "price_desc", key: "sortPriceDesc" },
  { value: "newest", key: "sortNewest" },
  { value: "mileage_asc", key: "sortMileageAsc" },
  { value: "year_desc", key: "sortYearDesc" },
];

/**
 * Deliberately the NATIVE <select> element, matching the Make/Model/Submodel
 * dropdowns: mobile Safari renders Apple's own picker wheel and Android its native
 * spinner, plus free keyboard, VoiceOver and type-ahead behaviour. Only the chrome
 * is styled - the popup itself belongs to the OS.
 */
export const SortControl = ({ value, onChange }) => {
  const { t } = useApp();
  return (
    <div className="relative w-full sm:w-auto">
      <label className="sr-only" htmlFor="sort-control">
        {t("sortBy")}
      </label>
      <select
        id="sort-control"
        data-testid="sort-control"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        aria-label={t("sortBy")}
        className="h-11 w-full min-w-[190px] appearance-none truncate rounded-[10px] border border-input bg-background pl-3 pr-9 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 sm:w-auto"
      >
        {SORT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value} data-testid={`sort-option-${o.value}`}>
            {t(o.key)}
          </option>
        ))}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
    </div>
  );
};

export default SortControl;
