import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import { getIncidents } from "@/lib/api";
import { stampSofia } from "@/components/admin/AdminBits";

const LABELS = {
  egress: "Изход към интернет",
  encar: "Encar upstream",
  mongo: "База данни",
  mail: "Имейли (Resend)",
};

/**
 * Open incidents, loud and at the top of the panel.
 *
 * The outage that prompted this was found by hand hours later. The watchdog on the server
 * pushes and emails every administrator the moment a check fails twice in a row; this is the
 * same state, for whoever happens to be looking at the panel instead of their phone.
 */
export const AdminIncidents = () => {
  const [data, setData] = useState(null);

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

  if (!data) return null;

  const open = data.open || [];
  const recent = (data.recent || []).filter((r) => r.closed_at).slice(0, 4);

  if (!open.length) {
    return (
      <div
        data-testid="admin-incidents-ok"
        className="flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-4 py-2.5 text-[12.5px] text-muted-foreground"
      >
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
        <span>
          Всички проверки минават: изход към интернет, Encar, база данни, имейли.
          {recent.length ? ` Последен инцидент: ${LABELS[recent[0].check] || recent[0].check}, ${stampSofia(recent[0].opened_at)}.` : ""}
        </span>
      </div>
    );
  }

  return (
    <div data-testid="admin-incidents" className="flex flex-col gap-2">
      {open.map((i) => (
        <div
          key={i.check}
          data-testid={`admin-incident-${i.check}`}
          className="flex items-start gap-3 rounded-[12px] border border-destructive/40 bg-destructive/10 px-4 py-3"
        >
          <ShieldAlert className="mt-0.5 h-[18px] w-[18px] shrink-0 text-destructive" aria-hidden="true" />
          <div className="min-w-0">
            <div className="text-[13.5px] font-semibold text-destructive">
              {LABELS[i.check] || i.check} — авария от {stampSofia(i.since)}
            </div>
            <p className="mt-0.5 break-words text-[12px] text-destructive/90">{i.reason}</p>
            {i.reminders ? (
              <p className="mt-0.5 text-[11.5px] text-destructive/70">
                Изпратени {i.reminders + 1} предупреждения до администраторите
              </p>
            ) : (
              <p className="mt-0.5 text-[11.5px] text-destructive/70">
                Предупреждение е изпратено до всички администратори
              </p>
            )}
          </div>
        </div>
      ))}
      {recent.length ? (
        <div className="flex items-center gap-2 px-1 text-[11.5px] text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">
            Приключени:{" "}
            {recent.map((r) => `${LABELS[r.check] || r.check} (${stampSofia(r.opened_at)})`).join(" · ")}
          </span>
        </div>
      ) : null}
    </div>
  );
};

export default AdminIncidents;
