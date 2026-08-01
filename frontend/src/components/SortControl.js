import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApp } from "@/context/AppContext";

export const SORT_OPTIONS = [
  { value: "newest", key: "sortNewest" },
  { value: "price_asc", key: "sortPriceAsc" },
  { value: "price_desc", key: "sortPriceDesc" },
  { value: "mileage_asc", key: "sortMileageAsc" },
  { value: "year_desc", key: "sortYearDesc" },
];

export const SortControl = ({ value, onChange }) => {
  const { t } = useApp();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        data-testid="sort-control"
        className="h-11 w-full min-w-[190px] border-border bg-card text-sm sm:w-auto"
        aria-label={t("sortBy")}
      >
        <SelectValue placeholder={t("sortBy")} />
      </SelectTrigger>
      <SelectContent className="bg-card">
        {SORT_OPTIONS.map((o) => (
          <SelectItem key={o.value} value={o.value} data-testid={`sort-option-${o.value}`}>
            {t(o.key)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};

export default SortControl;
