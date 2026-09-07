import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Route } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getEncarRoute, setEncarRoute, testEncarRoute } from "@/lib/api";
import { stampSofia } from "@/components/admin/AdminBits";

const MODES = [
  { id: "auto", label: "Автоматично", hint: "директно, прокси при отказ" },
  { id: "proxy", label: "През прокси", hint: "резидентен изход" },
  { id: "direct", label: "Директно", hint: "от сървъра" },
];
const ROUTE_WORD = { residential_proxy: "резидентно прокси", direct: "директно" };

/** Which way Encar traffic leaves. Switching takes effect at once — no restart. */
export const AdminEncarRoute = () => {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState("");
  const [probe, setProbe] = useState(null);

  const load = useCallback(async () => {
    try {
      setState(await getEncarRoute());
    } catch {
      /* the incident strip above already reports a broken panel */
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const pick = async (mode) => {
    setBusy(mode);
    setProbe(null);
    try {
      setState(await setEncarRoute(mode));
    } catch (e) {
      setProbe({ ok: false, error: e?.response?.data?.detail || "не се смени" });
    } finally {
      setBusy("");
    }
  };

  const runTest = async () => {
    setBusy("test");
    setProbe(null);
    try {
      setProbe(await testEncarRoute());
    } catch (e) {
      setProbe({ ok: false, error: e?.response?.data?.detail || "проверката не мина" });
    } finally {
      setBusy("");
      load();
    }
  };

  if (!state) return null;
  const breaker = state.breaker || {};
  const failover = state.last_failover;

  return (
    <div
      data-testid="admin-encar-route"
      data-mode={state.mode}
      data-route={state.route}
      className="flex flex-col gap-3 rounded-[12px] border border-border bg-card px-3 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Route className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="text-[13px] font-semibold">Маршрут към Encar</span>
        <span
          data-testid="admin-encar-route-current"
          className="rounded-full bg-muted px-2 py-px text-[11px] text-muted-foreground"
        >
          сега: {ROUTE_WORD[state.route] || state.route}
        </span>
        <span
          data-testid="admin-encar-route-breaker"
          className={`rounded-full px-2 py-px text-[11px] ${
            breaker.open ? "bg-destructive/15 text-destructive" : "bg-emerald-500/15 text-emerald-700"
          }`}
        >
          {breaker.open
            ? `прекъсвач отворен — още ${breaker.retry_in_s}s`
            : `прекъсвач затворен · ${breaker.consecutive_failures || 0} провала подред`}
        </span>
        <Button
          data-testid="admin-encar-route-test"
          variant="outline"
          onClick={runTest}
          disabled={!!busy}
          className="ml-auto h-8 gap-1.5 rounded-[8px] px-2.5 text-[12px]"
        >
          {busy === "test" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Пробвай сега
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {MODES.map((m) => {
          const on = state.mode === m.id;
          const off = m.id === "proxy" && !state.proxy_configured;
          return (
            <button
              key={m.id}
              type="button"
              data-testid={`admin-encar-route-${m.id}`}
              data-active={on}
              onClick={() => pick(m.id)}
              disabled={on || off || !!busy}
              className={`flex min-w-[132px] flex-col items-start rounded-[10px] border px-2.5 py-1.5 text-left transition-colors ${
                on
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-primary/50 disabled:opacity-40"
              }`}
            >
              <span className="flex items-center gap-1.5 text-[12px] font-semibold">
                {busy === m.id ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                {m.label}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {off ? "няма зададено прокси" : m.hint}
              </span>
            </button>
          );
        })}
      </div>

      {state.auto_on_proxy ? (
        <p
          data-testid="admin-encar-route-lean"
          className="flex items-start gap-1.5 text-[12px] text-amber-700"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Директният маршрут е отпаднал — временно през прокси. Проверка дали директното
            работи отново{" "}
            {state.probe_in_s != null ? `след ${Math.ceil(state.probe_in_s / 60)} мин` : "скоро"}
            {state.last_probe
              ? ` · последна проверка: ${state.last_probe.ok ? "успешна" : state.last_probe.detail}`
              : ""}
          </span>
        </p>
      ) : null}

      {failover ? (
        <p
          data-testid="admin-encar-route-failover"
          className="flex items-start gap-1.5 text-[12px] text-amber-700"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Автоматично превключен {ROUTE_WORD[failover.from] || failover.from} →{" "}
            {ROUTE_WORD[failover.to] || failover.to} · {failover.reason || "без причина в лога"}
          </span>
        </p>
      ) : null}

      {probe ? (
        <p
          data-testid="admin-encar-route-probe"
          className={`text-[12px] ${probe.ok ? "text-emerald-700" : "text-destructive"}`}
        >
          {probe.ok
            ? `Encar отговори за ${probe.latency_ms} ms · ${probe.count} обяви upstream`
            : `Encar не отговори: ${probe.error}`}
        </p>
      ) : null}

      {state.stored?.updated_at ? (
        <p className="text-[11px] text-muted-foreground/70">
          последна промяна {stampSofia(state.stored.updated_at)} · {state.stored.changed_by || "?"}
          {state.stored.reason ? ` · ${state.stored.reason}` : ""}
        </p>
      ) : null}
    </div>
  );
};

export default AdminEncarRoute;
