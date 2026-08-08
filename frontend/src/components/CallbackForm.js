import { useMemo, useState } from "react";
import { Loader2, PhoneCall } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { requestCallback } from "@/lib/api";

/**
 * "Call me back at ..." — offered only when the office is shut.
 *
 * The days and slots offered are built from the owner's OWN hours as the server reported them,
 * in the office's own date (`local_date`), never from the phone's clock: a buyer in another
 * time zone would otherwise be offered a slot nobody works. The server re-checks the slot
 * anyway — a form is a suggestion, not a fact.
 */
const KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const STEP = 30;

const toMinutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const pad = (n) => String(n).padStart(2, "0");

/** The next fortnight's bookable days, in the office's own calendar. */
function openDays(info) {
  const start = new Date(`${info.local_date}T00:00:00`);
  const out = [];
  for (let i = 0; i < 14 && out.length < 7; i += 1) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const row = info.hours?.[KEYS[(d.getDay() + 6) % 7]] || {};
    if (row.closed || !row.open || !row.close) continue;
    const iso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const slots = slotsFor(row, iso === info.local_date, info.local_time);
    // A day whose last slot has already gone is not bookable. Offering today at 16:09 when we
    // shut at 15:00 left the time dropdown empty and the form impossible to submit.
    if (slots.length) out.push({ iso, row, slots });
  }
  return out;
}

function slotsFor(row, isToday, localTime) {
  const from = toMinutes(row.open);
  const to = toMinutes(row.close);
  const floor = isToday ? toMinutes(localTime) + STEP : -1;
  const out = [];
  for (let m = from; m <= to; m += STEP) {
    if (m > floor) out.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`);
  }
  return out;
}

export const CallbackForm = ({ info, car, title, onDone }) => {
  const { t, lang } = useApp();
  const { user } = useAuth();
  const days = useMemo(() => openDays(info), [info]);
  const [dayIso, setDayIso] = useState(days[0]?.iso || "");
  const day = days.find((d) => d.iso === dayIso) || days[0];
  const slots = day?.slots || [];
  const [time, setTime] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", email: "" });
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((p) => ({ ...p, [k]: e.target.value }));
  const name = form.name || user?.name || "";
  const email = form.email || user?.email || "";
  // A signed-in buyer should never retype their number to ask for a call back.
  const phone = form.phone || user?.phone || "";
  const chosen = time || slots[0] || "";

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await requestCallback({
        name,
        phone,
        email,
        day: dayIso,
        time: chosen,
        listing_id: car?.id || "",
        car_title: title || "",
        lang,
      });
      toast.success(t("callbackSent").replace("{when}", r.when));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("callbackFailed"));
    } finally {
      setBusy(false);
    }
  };

  const select =
    "h-10 w-full rounded-[9px] border border-border bg-background px-2 text-[13.5px]";

  return (
    <form onSubmit={submit} data-testid="callback-form" className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">{t("callbackDay")}</Label>
          <select
            data-testid="callback-day"
            value={dayIso}
            onChange={(e) => {
              setDayIso(e.target.value);
              setTime("");
            }}
            className={select}
          >
            {days.map((d) => (
              <option key={d.iso} value={d.iso}>
                {`${d.iso}  ${d.row.open}–${d.row.close}`}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">{t("callbackTime")}</Label>
          <select
            data-testid="callback-time"
            value={chosen}
            onChange={(e) => setTime(e.target.value)}
            className={select}
          >
            {slots.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-[12px] font-medium">{t("phoneLabel")}</Label>
        <Input
          data-testid="callback-phone"
          type="tel"
          required
          autoComplete="tel"
          value={phone}
          onChange={set("phone")}
          className="h-10 bg-background text-[14px]"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">{t("emailLabel")}</Label>
          <Input
            data-testid="callback-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={set("email")}
            className="h-10 bg-background text-[14px]"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-[12px] font-medium">{t("nameLabel")}</Label>
          <Input
            data-testid="callback-name"
            value={name}
            onChange={set("name")}
            autoComplete="name"
            className="h-10 bg-background text-[14px]"
          />
        </div>
      </div>

      <Button
        type="submit"
        data-testid="callback-submit"
        disabled={busy || !slots.length}
        className="h-auto min-h-12 w-full justify-center gap-2 whitespace-normal rounded-[12px] bg-[hsl(var(--primary))] px-4 py-3 text-center text-[14px] font-semibold leading-tight text-primary-foreground hover:brightness-110"
      >
        {busy ? (
          <Loader2 className="h-[17px] w-[17px] animate-spin" aria-hidden="true" />
        ) : (
          <PhoneCall className="h-[17px] w-[17px]" aria-hidden="true" />
        )}
        {t("callbackSubmit")}
      </Button>
    </form>
  );
};

export default CallbackForm;
