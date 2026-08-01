import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useApp } from "@/context/AppContext";
import { getTaxonomy } from "@/lib/api";
import { formatNumber } from "@/lib/format";

const ANY = "__any__";

const Field = ({
  id,
  label,
  items,
  current,
  onPick,
  disabled,
  busyKey,
  placeholder,
  busy,
  lang,
}) => (
  <div className="min-w-0 flex-1">
    <Label
      htmlFor={id}
      className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
    >
      {label}
      {busy[busyKey] && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
    </Label>
    <Select
      value={current || ANY}
      onValueChange={(v) => onPick(v === ANY ? "" : v)}
      disabled={disabled}
    >
      <SelectTrigger
        id={id}
        data-testid={`taxonomy-${busyKey}-select`}
        className="h-11 w-full border-input bg-card text-sm disabled:opacity-50"
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-72 bg-popover">
        <SelectItem value={ANY} data-testid={`taxonomy-${busyKey}-any`}>
          {placeholder}
        </SelectItem>
        {items.map((i) => (
          <SelectItem key={i.value} value={i.value} data-testid={`taxonomy-${busyKey}-option`}>
            <span className="flex w-full items-center justify-between gap-3">
              <span className="truncate">{i.label || i.value}</span>
              <span className="tnum shrink-0 text-[11px] text-muted-foreground">
                {formatNumber(i.count, lang)}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  </div>
);


/**
 * Cascading Make -> Model -> Submodel -> Trim dropdowns, replacing the free-text
 * search box. Data comes from a precomputed taxonomy tree, so each level opens in
 * milliseconds rather than running a live aggregation.
 */
export const TaxonomySelects = ({ value, onChange, layout = "row" }) => {
  const { t, lang } = useApp();
  const { make = "", model = "", badge = "", badgeDetail = "" } = value || {};

  const [makes, setMakes] = useState([]);
  const [models, setModels] = useState([]);
  const [badges, setBadges] = useState([]);
  const [details, setDetails] = useState([]);
  const [busy, setBusy] = useState({});

  const load = async (level, params, setter, key) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const d = await getTaxonomy({ level, lang, ...params });
      // alphabetical on the label the user actually sees
      const sorted = [...(d.items || [])].sort((a, b) =>
        (a.label || a.value).localeCompare(b.label || b.value, lang, { numeric: true })
      );
      setter(sorted);
    } catch (e) {
      setter([]);
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  };

  useEffect(() => {
    load(1, {}, setMakes, "make");
  }, [lang]);

  useEffect(() => {
    if (!make) {
      setModels([]);
      return;
    }
    load(2, { make }, setModels, "model");
  }, [make, lang]);

  useEffect(() => {
    if (!make || !model) {
      setBadges([]);
      return;
    }
    load(3, { make, model }, setBadges, "badge");
  }, [make, model, lang]);

  useEffect(() => {
    if (!make || !model || !badge) {
      setDetails([]);
      return;
    }
    load(4, { make, model, badge }, setDetails, "badgeDetail");
  }, [make, model, badge, lang]);

  return (
    <div
      data-testid="taxonomy-selects"
      className={
        layout === "row"
          ? "grid grid-cols-2 gap-3 lg:grid-cols-4"
          : "grid grid-cols-1 gap-3"
      }
    >
      <Field
        busy={busy}
        lang={lang}
        id="tax-make"
        label={t("make")}
        items={makes}
        current={make}
        busyKey="make"
        placeholder={t("anyMake")}
        onPick={(v) => onChange({ make: v, model: "", badge: "", badgeDetail: "" })}
      />
      <Field
        busy={busy}
        lang={lang}
        id="tax-model"
        label={t("model")}
        items={models}
        current={model}
        busyKey="model"
        disabled={!make}
        placeholder={make ? t("anyModel") : t("selectMakeFirst")}
        onPick={(v) => onChange({ make, model: v, badge: "", badgeDetail: "" })}
      />
      <Field
        busy={busy}
        lang={lang}
        id="tax-badge"
        label={t("submodel")}
        items={badges}
        current={badge}
        busyKey="badge"
        disabled={!model}
        placeholder={model ? t("anySubmodel") : t("selectModelFirst")}
        onPick={(v) => onChange({ make, model, badge: v, badgeDetail: "" })}
      />
      {details.length > 0 ? (
      <Field
        busy={busy}
        lang={lang}
        id="tax-detail"
        label={t("trimLevel")}
        items={details}
        current={badgeDetail}
        busyKey="badgeDetail"
        disabled={!badge}
        placeholder={badge ? t("anyTrim") : t("selectSubmodelFirst")}
        onPick={(v) => onChange({ make, model, badge, badgeDetail: v })}
      />
      ) : null}
    </div>
  );
};

export default TaxonomySelects;
