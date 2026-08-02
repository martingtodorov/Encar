import { useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { useApp } from "@/context/AppContext";
import { getTaxonomy } from "@/lib/api";
import { formatNumber } from "@/lib/format";

const ANY = "";

/**
 * Cascading Make -> Model -> Submodel dropdowns.
 *
 * Deliberately uses the NATIVE <select> element rather than a custom/Radix listbox,
 * so mobile Safari renders Apple's own picker wheel (and Android its native
 * spinner). Native controls also give free keyboard, VoiceOver and type-ahead
 * behaviour. Only the chrome is styled; the popup itself is the OS's.
 */
const Field = ({ id, label, items, current, onPick, disabled, busyKey, placeholder, busy, lang }) => (
  <div className="min-w-0 flex-1">
    <Label
      htmlFor={id}
      className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
    >
      {label}
      {busy[busyKey] && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
    </Label>
    <div className="relative">
      <select
        id={id}
        data-testid={`taxonomy-${busyKey}-select`}
        value={current || ANY}
        disabled={disabled}
        onChange={(e) =>
          onPick(
            e.target.value,
            items.find((i) => i.value === e.target.value)?.label || ""
          )
        }
        className="h-11 w-full appearance-none truncate rounded-[10px] border border-input bg-card pl-3 pr-9 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        <option value={ANY}>{placeholder}</option>
        {items.map((i) => (
          <option key={i.value} value={i.value}>
            {`${i.label || i.value} (${formatNumber(i.count, lang)})`}
          </option>
        ))}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
    </div>
  </div>
);

export const TaxonomySelects = ({ value, onChange, onLabels, layout = "row", trailing }) => {
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

  // Publish the human-readable label for each selection so the applied-filter chips
  // can show "Mercedes-Benz" instead of the raw Korean value. Derived from the loaded
  // options rather than stored, so it re-resolves when the language changes.
  useEffect(() => {
    if (!onLabels) return;
    const pick = (items, v) => (v ? items.find((i) => i.value === v)?.label || v : "");
    onLabels({
      make: pick(makes, make),
      model: pick(models, model),
      badge: pick(badges, badge),
      badgeDetail: pick(details, badgeDetail),
    });
  }, [makes, models, badges, details, make, model, badge, badgeDetail]);

  return (
    <div
      data-testid="taxonomy-selects"
      className={layout === "row" ? "grid grid-cols-2 gap-3 lg:grid-cols-4" : "grid grid-cols-1 gap-3"}
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
          placeholder={t("anyTrim")}
          onPick={(v) => onChange({ make, model, badge, badgeDetail: v })}
        />
      ) : null}
      {/* Mobile only: sits in the next grid cell after the selects, so Filters reads as
          part of the same control group instead of drifting down to the results header.
          The transparent label keeps it baseline-aligned with the dropdowns. */}
      {trailing ? (
        <div className="min-w-0 lg:hidden">
          <span
            aria-hidden="true"
            className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-transparent"
          >
            &nbsp;
          </span>
          {trailing}
        </div>
      ) : null}
    </div>
  );
};

export default TaxonomySelects;
