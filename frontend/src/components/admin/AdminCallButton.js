import { useCallback, useEffect, useState } from "react";
import { Loader2, Phone, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { adminCallButton, adminSaveCallButton } from "@/lib/api";
import { Spinner } from "@/components/admin/AdminBits";

/**
 * The "Call us" button on every car page: the number, and when somebody is there to answer.
 *
 * Whether the office is open is decided by the SERVER against these hours (Europe/Sofia), not
 * by the visitor's clock. Outside them the button still dials, but the buyer is warned first.
 */
const DAYS = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
];

export const AdminCallButton = () => {
  const [conf, setConf] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    adminCallButton()
      .then(setConf)
      .catch(() => setConf(null));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await adminSaveCallButton({
        enabled: conf.enabled,
        phone: conf.phone,
        phone_label: conf.phone_label,
        hours: conf.hours,
      });
      toast.success("Call button saved");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  if (!conf) return <Spinner />;

  const setDay = (day, patch) =>
    setConf((p) => ({ ...p, hours: { ...p.hours, [day]: { ...p.hours[day], ...patch } } }));

  return (
    <div
      data-testid="admin-call-button"
      className="rounded-[14px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-[620px]">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-foreground">
            <Phone className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
            The “Call us” button
          </h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            Sits beside “Send enquiry” on every car page. Right now it is{" "}
            <span
              data-testid="call-open-state"
              className={`font-semibold ${conf.open_now ? "text-[hsl(var(--primary))]" : "text-muted-foreground"}`}
            >
              {conf.open_now ? "inside" : "outside"}
            </span>{" "}
            working hours ({conf.local_time} {conf.timezone}). Outside them the buyer is told
            nobody is likely to pick up and asked whether to dial anyway.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Label className="text-[12.5px] font-medium">{conf.enabled ? "Shown" : "Hidden"}</Label>
          <Switch
            data-testid="call-enabled"
            checked={conf.enabled}
            onCheckedChange={(v) => setConf((p) => ({ ...p, enabled: v }))}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">Number to dial</Label>
          <Input
            data-testid="call-phone"
            value={conf.phone || ""}
            onChange={(e) => setConf((p) => ({ ...p, phone: e.target.value }))}
            className="h-10 bg-background text-[14px]"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">How it is written</Label>
          <Input
            data-testid="call-phone-label"
            value={conf.phone_label || ""}
            onChange={(e) => setConf((p) => ({ ...p, phone_label: e.target.value }))}
            className="h-10 bg-background text-[14px]"
          />
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2">
        {DAYS.map(([day, label]) => {
          const row = conf.hours[day] || {};
          return (
            <div
              key={day}
              data-testid={`call-day-${day}`}
              className={`flex flex-wrap items-center gap-3 rounded-[10px] border border-border px-3 py-2 ${
                day === conf.day ? "bg-secondary" : "bg-background"
              }`}
            >
              <span className="w-[86px] text-[13px] font-medium text-foreground">{label}</span>
              <Input
                data-testid={`call-open-${day}`}
                type="time"
                value={row.open || ""}
                disabled={row.closed}
                onChange={(e) => setDay(day, { open: e.target.value })}
                className="h-9 w-[120px] bg-card text-[13px] disabled:opacity-40"
              />
              <span className="text-[13px] text-muted-foreground">–</span>
              <Input
                data-testid={`call-close-${day}`}
                type="time"
                value={row.close || ""}
                disabled={row.closed}
                onChange={(e) => setDay(day, { close: e.target.value })}
                className="h-9 w-[120px] bg-card text-[13px] disabled:opacity-40"
              />
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
                <Switch
                  data-testid={`call-closed-${day}`}
                  checked={!!row.closed}
                  onCheckedChange={(v) => setDay(day, { closed: v })}
                />
                Closed
              </label>
            </div>
          );
        })}
      </div>

      <Button
        data-testid="call-save"
        onClick={save}
        disabled={busy}
        className="mt-4 h-10 gap-2 rounded-[10px]"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        Save the call button
      </Button>
    </div>
  );
};

export default AdminCallButton;
