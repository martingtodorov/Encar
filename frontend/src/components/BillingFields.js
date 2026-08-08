import { useEffect, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { PhoneInput } from "@/components/PhoneInput";
import { useDialCodes } from "@/lib/dialcodes";

export const BLANK_BILLING = {
  full_name: "", street: "", city: "", post_code: "", country: "", phone: "",
};

const FIELDS = [
  ["full_name", "billingName", "name", "sm:col-span-2"],
  ["street", "billingStreet", "street-address", "sm:col-span-2"],
  ["city", "billingCity", "address-level2", ""],
  ["post_code", "billingPost", "postal-code", ""],
];

/** The delivery address, shared by the sign-up form and the account page. */
export const BillingFields = ({ value, onChange, prefix = "billing" }) => {
  const { t } = useApp();
  const { codes, country } = useDialCodes();

  const sorted = useMemo(
    () => [...codes].sort((a, b) => a.name.localeCompare(b.name)),
    [codes]
  );

  // The country was two letters typed by hand, which produced "bg", "BGR" and "Бг" in the same
  // column. It is a list now, and an empty field starts on the country the visitor's own IP
  // suggests — still theirs to change.
  useEffect(() => {
    if (!codes.length) return;
    const current = value.country || "";
    if (!current) {
      if (country && codes.some((c) => c.iso === country)) onChange({ ...value, country });
      return;
    }
    if (codes.some((c) => c.iso === current)) return;
    // Addresses saved when this was a free-text field hold "bg", "BGR" or "Bulgaria"; matched
    // here so an old account does not open with an empty country.
    const guess = codes.find(
      (c) =>
        c.iso === current.trim().toUpperCase().slice(0, 2) ||
        c.name.toLowerCase() === current.trim().toLowerCase()
    );
    if (guess) onChange({ ...value, country: guess.iso });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [country, codes.length]);

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {FIELDS.map(([key, label, autoComplete, span]) => (
        <label key={key} className={`flex flex-col gap-1.5 ${span}`}>
          <span className="text-[12px] font-medium text-muted-foreground">{t(label)}</span>
          <Input
            data-testid={`${prefix}-${key}`}
            value={value[key] || ""}
            onChange={(e) => onChange({ ...value, [key]: e.target.value })}
            autoComplete={autoComplete}
            maxLength={160}
            className="h-11 rounded-[10px] bg-card"
          />
        </label>
      ))}

      <label className="flex flex-col gap-1.5">
        <span className="text-[12px] font-medium text-muted-foreground">
          {t("billingCountry")}
        </span>
        <select
          data-testid={`${prefix}-country`}
          value={value.country || ""}
          onChange={(e) => onChange({ ...value, country: e.target.value })}
          autoComplete="country"
          className="h-11 rounded-[10px] border border-border bg-card px-3 text-[14px] text-foreground outline-none transition-colors focus:border-[hsl(var(--primary))]"
        >
          <option value="">{t("billingCountryPick")}</option>
          {sorted.map((c) => (
            <option key={c.iso} value={c.iso}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1.5 sm:col-span-2">
        <span className="text-[12px] font-medium text-muted-foreground">
          {t("billingPhone")}
        </span>
        <PhoneInput
          testId={`${prefix}-phone`}
          value={value.phone || ""}
          onChange={(v) => onChange({ ...value, phone: v })}
          showError
        />
      </label>
    </div>
  );
};

export default BillingFields;
