import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { formatMoney, formatNumber } from "@/lib/format";

/** Removable chips summarising every active filter, so nothing is ever hidden. */
export const AppliedFiltersChips = ({ filters, tax, taxLabels, facets, onRemove, onClearAll }) => {
  const { t, lang, currency, rates } = useApp();

  const labelFor = (list, value) =>
    (list || []).find((x) => x.value === value)?.label || value;

  const chips = [];

  // Taxonomy selections (make -> model -> submodel -> trim). Use the TRANSLATED label
  // published by TaxonomySelects; the raw value is Korean and is only a fallback.
  if (tax?.make)
    chips.push({ key: "make", label: `${t("make")}: ${taxLabels?.make || tax.make}` });
  if (tax?.model)
    chips.push({ key: "model", label: `${t("model")}: ${taxLabels?.model || tax.model}` });
  if (tax?.badge)
    chips.push({ key: "badge", label: `${t("submodel")}: ${taxLabels?.badge || tax.badge}` });
  if (tax?.badgeDetail)
    chips.push({
      key: "badgeDetail",
      label: `${t("trimLevel")}: ${taxLabels?.badgeDetail || tax.badgeDetail}`,
    });

  (filters.fuels || []).forEach((f) =>
    chips.push({ key: `fuels:${f}`, label: labelFor(facets?.fuels, f) })
  );
  (filters.regions || []).forEach((r) =>
    chips.push({ key: `regions:${r}`, label: labelFor(facets?.regions, r) })
  );
  (filters.transmissions || []).forEach((tr) =>
    chips.push({ key: `transmissions:${tr}`, label: t(tr === "manual" ? "manual" : "auto") })
  );

  if (filters.year_min || filters.year_max) {
    chips.push({
      key: "year",
      label: `${t("year")}: ${filters.year_min || ""}\u2013${filters.year_max || ""}`,
    });
  }
  if (filters.price_min || filters.price_max) {
    const a = filters.price_min ? formatMoney(filters.price_min, currency, lang, rates) : "";
    const b = filters.price_max ? formatMoney(filters.price_max, currency, lang, rates) : "";
    chips.push({ key: "price", label: `${t("price")}: ${a}\u2013${b}` });
  }
  if (filters.mileage_min || filters.mileage_max) {
    const a = filters.mileage_min ? formatNumber(filters.mileage_min, lang) : "";
    const b = filters.mileage_max ? formatNumber(filters.mileage_max, lang) : "";
    chips.push({ key: "mileage", label: `${t("mileage")}: ${a}\u2013${b} ${t("km")}` });
  }
  if (filters.only_inspection) chips.push({ key: "only_inspection", label: t("onlyInspection") });
  if (filters.only_record) chips.push({ key: "only_record", label: t("onlyRecord") });
  if (filters.only_diagnosed) chips.push({ key: "only_diagnosed", label: t("onlyDiagnosed") });

  if (!chips.length) return null;

  return (
    <div data-testid="applied-filters" className="flex flex-wrap items-center gap-2">
      {chips.map((c) => (
        <span
          key={c.key}
          data-testid={`applied-filter-${c.key}`}
          className="inline-flex max-w-[280px] items-center gap-1.5 rounded-full bg-muted py-1 pl-3 pr-1 text-[13px] text-foreground"
          title={c.label}
        >
          <span className="truncate">{c.label}</span>
          <button
            type="button"
            onClick={() => onRemove(c.key)}
            aria-label={`${t("clearAll")}: ${c.label}`}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground transition-colors hover:bg-[#e6ded2] hover:text-foreground"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      <Button
        data-testid="applied-filters-clear"
        variant="ghost"
        onClick={onClearAll}
        className="h-8 px-2 text-[13px] font-medium text-[hsl(var(--primary))] hover:bg-secondary"
      >
        {t("clearAll")}
      </Button>
    </div>
  );
};

export default AppliedFiltersChips;
