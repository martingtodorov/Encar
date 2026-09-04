import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BellOff, BellRing, CheckCircle2, Loader2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { getIncidents, testIncidentPush } from "@/lib/api";
import { enablePush, pushSupported } from "@/lib/push";
import { stampSofia } from "@/components/admin/AdminBits";


/**
 * Open incidents, loud and at the top of the panel.
 *
 * The outage that prompted this was found by hand, hours later, by loading a car page. The
 * server watchdog now pushes every administrator the moment a check fails twice; this strip
 * is the same state for whoever is looking at the panel instead of their phone — and, just
 * as importantly, it says out loud when NO device is subscribed, because a push channel with
 * no devices is silence, and silence looks exactly like "nothing is wrong".
 */
export const AdminIncidents = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await getIncidents());
    } catch {
      /* the panel has bigger problems than this strip if the call fails */
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const turnOn = async () => {
    setBusy("on");
    try {
      await enablePush();
      toast.success("Това устройство ще получава аварийните известия");
      await load();
    } catch (e) {
      toast.error(e?.message || "Известията не бяха включени");
    } finally {
      setBusy("");
    }
  };

  const sendTest = async () => {
    setBusy("test");
    try {
      const r = await testIncidentPush();
      if (r.sent) toast.success(`Тестовото известие тръгна към ${r.sent} устройства`);
      else toast.error("Нито едно устройство не беше достигнато — включи известията тук");
      await load();
    } catch {
      toast.error("Тестът не мина");
    } finally {
      setBusy("");
    }
  };

  if (!data) return null;

  const LABELS = data.labels || {};
  const open = data.open || [];
  const recent = (data.recent || []).filter((r) => r.closed_at).slice(0, 4);
  const devices = data.push_devices || 0;

  return (
    <div className="flex flex-col gap-2">
      {open.length ? (
        open.map((i) => (
          <div
            key={i.check}
            data-testid={`admin-incident-${i.check}`}
            className="flex items-start gap-3 rounded-[12px] border border-destructive/40 bg-destructive/10 px-4 py-3"
          >
            <ShieldAlert className="mt-0.5 h-[18px] w-[18px] shrink-0 text-destructive" aria-hidden="true" />
            <div className="min-w-0">
              <div className="text-[13.5px] font-semibold text-destructive">
                {i.severity === "critical" ? "Авария" : "Внимание"}: {LABELS[i.check] || i.check} — от {stampSofia(i.since)}
              </div>
              <p className="mt-0.5 break-words text-[12px] text-destructive/90">{i.reason}</p>
              <p className="mt-0.5 text-[11.5px] text-destructive/70">
                {devices
                  ? `Push известие е изпратено до ${devices} устройства${i.reminders ? `, ${i.reminders} напомняния` : ""}`
                  : "Няма абонирано устройство — известието тръгна по имейл"}
              </p>
            </div>
          </div>
        ))
      ) : (
        <div
          data-testid="admin-incidents-ok"
          className="flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-4 py-2.5 text-[12.5px] text-muted-foreground"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
          <span className="min-w-0 truncate">
            Всички {(data.checks || []).length} проверки минават — няма отворени инциденти.
            {recent.length
              ? ` Последен инцидент: ${LABELS[recent[0].check] || recent[0].check}, ${stampSofia(recent[0].opened_at)}.`
              : ""}
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 px-1">
        <span
          data-testid="admin-incident-devices"
          className={`flex items-center gap-1.5 text-[11.5px] ${
            devices ? "text-muted-foreground" : "text-destructive"
          }`}
        >
          {devices ? (
            <BellRing className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <BellOff className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {devices
            ? `Аварийни push известия към ${devices} устройства`
            : "Нито едно устройство не получава push известия"}
        </span>
        {pushSupported() ? (
          <Button
            variant="outline"
            data-testid="admin-incident-enable"
            onClick={turnOn}
            disabled={busy === "on"}
            className="h-7 gap-1.5 rounded-[8px] px-2.5 text-[11.5px]"
          >
            {busy === "on" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Включи на това устройство
          </Button>
        ) : null}
        <Button
          variant="outline"
          data-testid="admin-incident-test"
          onClick={sendTest}
          disabled={busy === "test"}
          className="h-7 gap-1.5 rounded-[8px] px-2.5 text-[11.5px]"
        >
          {busy === "test" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          Изпрати тестова авария
        </Button>
      </div>

      {recent.length ? (
        <div className="flex items-center gap-2 px-1 text-[11.5px] text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">
            Приключени:{" "}
            {recent
              .map((r) => `${LABELS[r.check] || r.check} (${stampSofia(r.opened_at)})`)
              .join(" · ")}
          </span>
        </div>
      ) : null}
    </div>
  );
};

export default AdminIncidents;
