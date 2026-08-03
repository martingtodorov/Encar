import { useEffect, useMemo, useState } from "react";
import { Search, RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Separator } from "@/components/ui/separator";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { TaxonomySelects } from "@/components/TaxonomySelects";
import { useApp } from "@/context/AppContext";
import { formatNumber, convert } from "@/lib/format";

const CheckRow = ({ id, label, count, checked, onChange, testId }) => {
  const { lang } = useApp();
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-start gap-2.5 rounded-[8px] px-1.5 py-1.5 transition-colors hover:bg-muted"
    >
      <Checkbox
        id={id}
        data-testid={testId}
        checked={checked}
        onCheckedChange={onChange}
        className="mt-0.5 shrink-0 border-input data-[state=checked]:border-[#0b4f6c] data-[state=checked]:bg-[hsl(var(--primary))]"
      />
      <span className="min-w-0 flex-1 text-[13px] leading-tight text-foreground">{label}</span>
      {Number.isFinite(count) && (
        <span className="tnum shrink-0 text-[11px] text-muted-foreground">{formatNumber(count, lang)}</span>
      )}
    </label>
  );
};

const SectionTitle = ({ children }) => (
  <span className="text-[13px] font-semibold text-foreground">{children}</span>
);

/** Searchable, scrollable multi-select list (used for makes, models, regions). */
const PickList = ({ items, selected, onToggle, placeholder, testIdPrefix, emptyLabel, maxH = "max-h-56" }) => {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (i) =>
        (i.label || "").toLowerCase().includes(needle) ||
        (i.value || "").toLowerCase().includes(needle)
    );
  }, [items, q]);

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          data-testid={`${testIdPrefix}-search`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={placeholder}
          className="h-9 border-border bg-muted pl-8 text-[13px]"
        />
      </div>
      <div className={`thin-scroll ${maxH} space-y-0.5 overflow-y-auto pr-1`}>
        {filtered.length === 0 && (
          <p className="px-1.5 py-2 text-[12px] text-muted-foreground">{emptyLabel}</p>
        )}
        {filtered.map((i) => (
          <CheckRow
            key={i.value}
            id={`${testIdPrefix}-${i.value}`}
            testId={`${testIdPrefix}-option`}
            label={i.label || i.value}
            count={i.count}
            checked={selected.includes(i.value)}
            onChange={() => onToggle(i.value)}
          />
        ))}
      </div>
    </div>
  );
};

const RangeRow = ({ minValue, maxValue, onMin, onMax, testIdPrefix, suffix, placeholderMin, placeholderMax }) => {
  const { t } = useApp();
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1">
        <Label className="mb-1 block text-[11px] text-muted-foreground">{t("from")}</Label>
        <Input
          data-testid={`${testIdPrefix}-min`}
          inputMode="numeric"
          value={minValue ?? ""}
          onChange={(e) => onMin(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder={placeholderMin}
          className="tnum h-10 border-border bg-background text-[13px]"
        />
      </div>
      <span className="mt-5 text-muted-foreground">{"\u2013"}</span>
      <div className="flex-1">
        <Label className="mb-1 block text-[11px] text-muted-foreground">
          {t("to")} {suffix ? `(${suffix})` : ""}
        </Label>
        <Input
          data-testid={`${testIdPrefix}-max`}
          inputMode="numeric"
          value={maxValue ?? ""}
          onChange={(e) => onMax(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder={placeholderMax}
          className="tnum h-10 border-border bg-background text-[13px]"
        />
      </div>
    </div>
  );
};

export const FilterSidebar = ({
  filters,
  setFilter,
  toggleInArray,
  facets,
  onReset,
  inSheet = false,
  tax,
  onTaxChange,
  onTaxLabels,
  onTaxSlugs,
}) => {
  const { t, lang, currency, rates } = useApp();
  const bounds = facets?.bounds || {};

  const priceCeiling = Math.min(Math.ceil((bounds.price_max || 250000) / 1000) * 1000, 400000);
  const [priceSlider, setPriceSlider] = useState([
    Number(filters.price_min) || 0,
    Number(filters.price_max) || priceCeiling,
  ]);

  useEffect(() => {
    setPriceSlider([
      Number(filters.price_min) || 0,
      Number(filters.price_max) || priceCeiling,
    ]);
  }, [filters.price_min, filters.price_max, priceCeiling]);

  const transmissionItems = [
    { value: "auto", label: t("auto") },
    { value: "manual", label: t("manual") },
  ];

  const sliderLabel = (eur) => {
    const v = convert(eur, currency, rates);
    return `${formatNumber(Math.round(v), lang)} ${currency}`;
  };

  return (
    <div
      data-testid={inSheet ? "filter-sidebar-sheet" : "filter-sidebar"}
      className={
        inSheet
          ? "flex h-full flex-col"
          : "rounded-[14px] border border-border bg-background shadow-[0_1px_2px_rgba(18,20,23,0.06)]"
      }
    >
      {!inSheet && (
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <SectionTitle>{t("filters")}</SectionTitle>
          <Button
            data-testid="filters-reset-button"
            variant="ghost"
            onClick={onReset}
            className="h-8 gap-1.5 px-2 text-[12px] font-medium text-[hsl(var(--primary))] hover:bg-secondary"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            {t("clearAll")}
          </Button>
        </div>
      )}

      <div
        className={`thin-scroll flex-1 overflow-y-auto px-4 pb-6 pt-2 ${
          inSheet ? "" : "max-h-[calc(100vh-210px)]"
        }`}
      >
        {/* The drawer is the only filter surface on mobile, so the car itself has to be
            choosable here too. On desktop these live above the results instead. */}
        {inSheet && onTaxChange && (
          <div className="mb-4 border-b border-border pb-4 pt-1">
            <TaxonomySelects
              value={tax}
              onChange={onTaxChange}
              onLabels={onTaxLabels}
              onSlugs={onTaxSlugs}
              layout="col"
            />
          </div>
        )}

        <Accordion
          type="multiple"
          defaultValue={["price", "year", "mileage"]}
          className="w-full"
        >
          <AccordionItem value="price" className="border-border">
            <AccordionTrigger data-testid="filter-section-price" className="py-3 hover:no-underline">
              <SectionTitle>
                {t("price")} <span className="font-normal text-muted-foreground">({currency})</span>
              </SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="space-y-3 pb-3">
              <div className="px-1 pt-1">
                <Slider
                  data-testid="filter-price-slider"
                  value={priceSlider}
                  min={0}
                  max={priceCeiling}
                  step={500}
                  onValueChange={setPriceSlider}
                  onValueCommit={(v) => {
                    setFilter("price_min", v[0] || "");
                    setFilter("price_max", v[1] >= priceCeiling ? "" : v[1]);
                  }}
                  className="py-2"
                />
                <div className="tnum mt-1 flex justify-between text-[11px] text-muted-foreground">
                  <span>{sliderLabel(priceSlider[0])}</span>
                  <span>
                    {sliderLabel(priceSlider[1])}
                    {priceSlider[1] >= priceCeiling ? "+" : ""}
                  </span>
                </div>
              </div>
              <RangeRow
                minValue={filters.price_min}
                maxValue={filters.price_max}
                onMin={(v) => setFilter("price_min", v)}
                onMax={(v) => setFilter("price_max", v)}
                testIdPrefix="filter-price"
                placeholderMin="0"
                placeholderMax={String(priceCeiling)}
              />
              <p className="text-[11px] leading-snug text-muted-foreground">{t("trust1Body")}</p>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="year" className="border-border">
            <AccordionTrigger data-testid="filter-section-year" className="py-3 hover:no-underline">
              <SectionTitle>{t("year")}</SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <RangeRow
                minValue={filters.year_min}
                maxValue={filters.year_max}
                onMin={(v) => setFilter("year_min", v)}
                onMax={(v) => setFilter("year_max", v)}
                testIdPrefix="filter-year"
                placeholderMin={String(bounds.year_min || 1990)}
                placeholderMax={String(bounds.year_max || new Date().getFullYear())}
              />
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="mileage" className="border-border">
            <AccordionTrigger data-testid="filter-section-mileage" className="py-3 hover:no-underline">
              <SectionTitle>
                {t("mileage")} <span className="font-normal text-muted-foreground">({t("km")})</span>
              </SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <RangeRow
                minValue={filters.mileage_min}
                maxValue={filters.mileage_max}
                onMin={(v) => setFilter("mileage_min", v)}
                onMax={(v) => setFilter("mileage_max", v)}
                testIdPrefix="filter-mileage"
                placeholderMin="0"
                placeholderMax={String(bounds.mileage_max || 300000)}
              />
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="fuel" className="border-border">
            <AccordionTrigger data-testid="filter-section-fuel" className="py-3 hover:no-underline">
              <SectionTitle>{t("fuel")}</SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="space-y-0.5 pb-3">
              {(facets?.fuels || []).map((f) => (
                <CheckRow
                  key={f.value}
                  id={`fuel-${f.value}`}
                  testId="filter-fuel-option"
                  label={f.label || f.value}
                  count={f.count}
                  checked={(filters.fuels || []).includes(f.value)}
                  onChange={() => toggleInArray("fuels", f.value)}
                />
              ))}
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="transmission" className="border-border">
            <AccordionTrigger
              data-testid="filter-section-transmission"
              className="py-3 hover:no-underline"
            >
              <SectionTitle>{t("transmission")}</SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="space-y-0.5 pb-3">
              {transmissionItems.map((tr) => {
                const facet = (facets?.transmissions || []).find((x) => x.value === tr.value);
                return (
                  <CheckRow
                    key={tr.value}
                    id={`transmission-${tr.value}`}
                    testId="filter-transmission-option"
                    label={tr.label}
                    count={facet?.count}
                    checked={(filters.transmissions || []).includes(tr.value)}
                    onChange={() => toggleInArray("transmissions", tr.value)}
                  />
                );
              })}
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="region" className="border-border">
            <AccordionTrigger data-testid="filter-section-region" className="py-3 hover:no-underline">
              <SectionTitle>{t("region")}</SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <PickList
                items={facets?.regions || []}
                selected={filters.regions || []}
                onToggle={(v) => toggleInArray("regions", v)}
                placeholder={t("searchMake")}
                testIdPrefix="filter-region"
                emptyLabel={t("noneFound")}
                maxH="max-h-44"
              />
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="documents" className="border-b-0">
            <AccordionTrigger
              data-testid="filter-section-documents"
              className="py-3 hover:no-underline"
            >
              <SectionTitle>{t("documents")}</SectionTitle>
            </AccordionTrigger>
            <AccordionContent className="space-y-0.5 pb-3">
              <CheckRow
                id="only-inspection"
                testId="filter-only-inspection"
                label={t("onlyInspection")}
                checked={!!filters.only_inspection}
                onChange={(v) => setFilter("only_inspection", !!v)}
              />
              <CheckRow
                id="only-record"
                testId="filter-only-record"
                label={t("onlyRecord")}
                checked={!!filters.only_record}
                onChange={(v) => setFilter("only_record", !!v)}
              />
              <CheckRow
                id="only-diagnosed"
                testId="filter-only-diagnosed"
                label={t("onlyDiagnosed")}
                checked={!!filters.only_diagnosed}
                onChange={(v) => setFilter("only_diagnosed", !!v)}
              />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
        <Separator className="my-2 bg-border" />
      </div>
    </div>
  );
};

export default FilterSidebar;
