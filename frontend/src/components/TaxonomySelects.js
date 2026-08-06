import { useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { useApp } from "@/context/AppContext";
import { getTaxonomy } from "@/lib/api";
import { cachedTaxonomy, rememberTaxonomy } from "@/lib/taxonomyCache";
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
        className="h-11 w-full appearance-none truncate rounded-[10px] border border-input bg-background pl-3 pr-9 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
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

export const TaxonomySelects = ({ value, onChange, onLabels, onSlugs, layout = "row", trailing }) => {
  const { t, lang } = useApp();
  const { make = "", model = "", badge = "", badgeDetail = "" } = value || {};

  // Seeded from the cache so a Back from a car renders the right labels immediately instead
  // of falling back to the raw Korean value while the request is in flight.
  const [makes, setMakes] = useState(() => cachedTaxonomy({ level: 1, lang }) || []);
  const [models, setModels] = useState(
    () => (make ? cachedTaxonomy({ level: 2, lang, make }) : null) || []
  );
  const [badges, setBadges] = useState(
    () => (make && model ? cachedTaxonomy({ level: 3, lang, make, model }) : null) || []
  );
  const [details, setDetails] = useState(
    () => (make && model && badge
      ? cachedTaxonomy({ level: 4, lang, make, model, badge })
      : null) || []
  );
  const [busy, setBusy] = useState({});

  /**
   * `alive` is not optional: these lookups are fired again the moment a parent selection
   * changes, and the answers do NOT come back in the order they were asked for. Without
   * the guard a stale (usually empty) response lands last and wipes a list that had just
   * been filled — which is exactly how the model and submodel dropdowns ended up with no
   * options at all after coming back from a car.
   */
  const load = async (level, params, setter, key, alive) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const d = await getTaxonomy({ level, lang, ...params });
      const sorted = [...(d.items || [])].sort((a, b) =>
        (a.label || a.value).localeCompare(b.label || b.value, lang, { numeric: true })
      );
      rememberTaxonomy({ level, lang, ...params }, sorted);
      if (alive()) setter(sorted);
    } catch (e) {
      // Keep whatever the cache gave us: an empty list here is what makes the chips fall
      // back to raw Korean.
      const kept = cachedTaxonomy({ level, lang, ...params });
      if (alive()) setter(kept || []);
    } finally {
      if (alive()) setBusy((b) => ({ ...b, [key]: false }));
    }
  };

  useEffect(() => {
    let ok = true;
    load(1, {}, setMakes, "make", () => ok);
    return () => {
      ok = false;
    };
  }, [lang]);

  useEffect(() => {
    if (!make) {
      setModels([]);
      return undefined;
    }
    let ok = true;
    // Cached list first (instant, correct), otherwise clear so the previous make's models
    // are not left on screen while the new ones are fetched.
    setModels(cachedTaxonomy({ level: 2, lang, make }) || []);
    load(2, { make }, setModels, "model", () => ok);
    return () => {
      ok = false;
    };
  }, [make, lang]);

  useEffect(() => {
    if (!make || !model) {
      setBadges([]);
      return undefined;
    }
    let ok = true;
    setBadges(cachedTaxonomy({ level: 3, lang, make, model }) || []);
    load(3, { make, model }, setBadges, "badge", () => ok);
    return () => {
      ok = false;
    };
  }, [make, model, lang]);

  useEffect(() => {
    if (!make || !model || !badge) {
      setDetails([]);
      return undefined;
    }
    let ok = true;
    setDetails(cachedTaxonomy({ level: 4, lang, make, model, badge }) || []);
    load(4, { make, model, badge }, setDetails, "badgeDetail", () => ok);
    return () => {
      ok = false;
    };
  }, [make, model, badge, lang]);

  // Publish the human-readable label for each selection so the applied-filter chips
  // can show "Mercedes-Benz" instead of the raw Korean value. Derived from the loaded
  // options rather than stored, so it re-resolves when the language changes.
  useEffect(() => {
    const pick = (items, v, field) => (v ? items.find((i) => i.value === v)?.[field] || "" : "");
    if (onLabels) {
      onLabels({
        make: pick(makes, make, "label") || make,
        model: pick(models, model, "label") || model,
        badge: pick(badges, badge, "label") || badge,
        badgeDetail: pick(details, badgeDetail, "label") || badgeDetail,
      });
    }
    // Slugs go into the query string, so the URL reads ?make=hyundai instead of Hangul.
    if (onSlugs) {
      onSlugs([
        ["make", make, pick(makes, make, "slug")],
        ["model", model, pick(models, model, "slug")],
        ["badge", badge, pick(badges, badge, "slug")],
        ["badge_detail", badgeDetail, pick(details, badgeDetail, "slug")],
      ].filter(([, v, sl]) => v && sl));
    }
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
