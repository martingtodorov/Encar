import { useEffect, useState } from "react";
import { Phone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { PhoneInput } from "@/components/PhoneInput";
import { isValidPhone } from "@/lib/phone";
import http from "@/lib/api";

/** Contact phone: billing, and reaching a buyer about a deal already agreed. Nothing else. */
export const PhonePanel = () => {
  const { t, lang } = useApp();
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    http
      .get("/notifications")
      .then(({ data }) => {
        setPhone(data.phone || "");
        setSaved(data.phone || "");
      })
      .catch(() => {});
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const { data } = await http.put("/phone", { phone, lang });
      setSaved(data.phone);
      setPhone(data.phone);
      toast.success(t("notifySaved"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not save that");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="account-phone"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <Phone className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        {t("phoneTitle")}
      </h2>
      <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted-foreground">
        {t("phoneBlurb")}
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("phoneLabel")}
          </span>
          <PhoneInput
            testId="account-phone"
            value={phone}
            onChange={setPhone}
            showError
            className="w-[340px]"
          />
        </label>
        <Button
          data-testid="account-phone-save"
          onClick={save}
          disabled={busy || phone === saved || (!!phone && !isValidPhone(phone, lang))}
          className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
        >
          {t("save")}
        </Button>
      </div>
    </section>
  );
};

export default PhonePanel;
