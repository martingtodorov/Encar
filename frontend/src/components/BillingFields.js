import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";

export const BLANK_BILLING = {
  full_name: "", street: "", city: "", post_code: "", country: "", phone: "",
};

const FIELDS = [
  ["full_name", "billingName", "name", "sm:col-span-2"],
  ["street", "billingStreet", "street-address", "sm:col-span-2"],
  ["city", "billingCity", "address-level2", ""],
  ["post_code", "billingPost", "postal-code", ""],
  ["country", "billingCountry", "country", ""],
  ["phone", "billingPhone", "tel", ""],
];

/** The delivery address, shared by the sign-up form and the account page. */
export const BillingFields = ({ value, onChange, prefix = "billing" }) => {
  const { t } = useApp();

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
            maxLength={key === "country" ? 2 : 160}
            className="h-11 rounded-[10px] bg-card"
          />
        </label>
      ))}
    </div>
  );
};

export default BillingFields;
