import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getIncidents } from "@/lib/api";
import { stampSofia } from "@/components/admin/AdminBits";
import { AdminEncarRoute } from "@/components/admin/AdminEncarRoute";

const DOT = {
  ok: "bg-emerald-500",
  fail: "bg-destructive",
  skip: "bg-muted-foreground/40",
  unknown: "bg-amber-400",
};
const WORD = { ok: "работи", fail: "ПАДНАЛО", skip: "не се прилага", unknown: "чака проверка" };

const Check = ({ c }) => (
  <div
    data-testid={`admin-health-${c.check}`}
    data-status={c.status}
    className={`flex flex-col gap-1 rounded-[12px] border px-3 py-2.5 ${
      c.status === "fail" ? "border-destructive/50 bg-destructive/10" : "border-border bg-card"
    }`}
  >
    <div className="flex items-center gap-2">
      <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[c.status] || DOT.unknown}`} aria-hidden="true" />
      <span className="min-w-0 truncate text-[13px] font-semibold">{c.label}</span>
      <span
        className={`ml-auto shrink-0 rounded-full px-1.5 py-px text-[10px] uppercase tracking-wide ${
          c.severity === "critical" ? "bg-destructive/15 text-destructive" : "bg-amber-500/15 text-amber-700"
        }`}
      >
        {c.severity === "critical" ? "авария" : "внимание"}
      </span>
    </div>
    <p className={`break-words text-[12px] ${c.status === "fail" ? "text-destructive" : "text-muted-foreground"}`}>
      <span className="font-medium">{WORD[c.status] || c.status}</span>
      {c.detail ? ` · ${c.detail}` : ""}
    </p>
    <p className="text-[11px] text-muted-foreground/70">
      {c.at ? `${stampSofia(c.at)}` : "—"}
      {c.latency_ms != null ? ` · ${c.latency_ms} ms` : ""}
      {` · на всеки ${c.every_s >= 3600 ? `${Math.round(c.every_s / 3600)} ч` : `${Math.round(c.every_s / 60)} мин`}`}
    </p>
  </div>
);

/** Live state of every watchdog check; "Провери сега" forces a full round on the server. */
export const AdminHealth = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (run = false) => {
    if (run) setBusy(true);
    try {
      setData(await getIncidents(run));
    } catch {
      /* the strip above already reports a broken panel */
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(false), 30000);
    return () => clearInterval(id);
  }, [load]);

  const checks = data?.checks || [];
  const failing = checks.filter((c) => c.status === "fail").length;
  const critical = checks.filter((c) => c.severity === "critical");
  const warning = checks.filter((c) => c.severity !== "critical");

  return (
    <section data-testid="admin-health" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[14px] font-semibold">
          <Activity className="h-4 w-4" aria-hidden="true" />
          Здраве на системата
          <span data-testid="admin-health-summary" className="text-[12px] font-normal text-muted-foreground">
            {checks.length
              ? ` · ${checks.length} проверки${failing ? `, ${failing} паднали` : ", всички минават"}`
              : " · чака първата проверка"}
          </span>
        </h3>
        <Button
          data-testid="admin-health-run"
          variant="outline"
          onClick={() => load(true)}
          disabled={busy}
          className="h-8 gap-1.5 rounded-[8px] px-2.5 text-[12px]"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Провери сега
        </Button>
      </div>
      <AdminEncarRoute />
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {critical.map((c) => <Check key={c.check} c={c} />)}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {warning.map((c) => <Check key={c.check} c={c} />)}
      </div>
    </section>
  );
};

export default AdminHealth;
