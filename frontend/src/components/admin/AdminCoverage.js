import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAdminCoverage, refreshAdminCoverage } from "@/lib/api";
import { Spinner, ago, num } from "@/components/admin/AdminBits";

const bar = (pct) => {
  if (pct === null || pct === undefined) return "bg-muted";
  if (pct >= 0.995) return "bg-[hsl(var(--success))]";
  if (pct >= 0.95) return "bg-[hsl(var(--info))]";
  return "bg-[hsl(var(--primary))]";
};

export const AdminCoverage = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => setData(await getAdminCoverage());

  useEffect(() => {
    load();
  }, []);

  // While the job walks the brand list, poll so the operator sees it fill in.
  useEffect(() => {
    if (data?.status !== "running") return;
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [data?.status]);

  const start = async () => {
    setBusy(true);
    try {
      await refreshAdminCoverage();
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Spinner />;

  const brands = data.brands || [];
  const running = data.status === "running";
  const totals = brands.reduce(
    (a, b) => ({
      upstream: a.upstream + (b.upstream || 0),
      ads: a.ads + (b.ads || 0),
      unique: a.unique + (b.unique || 0),
    }),
    { upstream: 0, ads: 0, unique: 0 }
  );

  return (
    <div data-testid="admin-coverage" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          {data.status === "never"
            ? "Never measured. One count-only request per brand, ~2 minutes."
            : running
              ? `Measuring… ${data.done} of ${data.total} brands`
              : `Measured ${ago(data.finished_at)} · ${brands.length} brands · ${
                  data.duration_s ? `${Math.round(data.duration_s)}s` : ""
                }`}
        </p>
        <Button
          data-testid="admin-coverage-refresh"
          onClick={start}
          disabled={busy || running}
          className="h-9 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-3 text-[13px] text-primary-foreground hover:brightness-110"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${running || busy ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
          {running ? "Measuring…" : "Measure now"}
        </Button>
      </div>

      {brands.length ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["Encar exportable ads", totals.upstream],
              ["Ads we hold", totals.ads],
              ["Unique cars", totals.unique],
            ].map(([k, v]) => (
              <div key={k} className="rounded-[12px] border border-border bg-card px-4 py-2.5">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{k}</div>
                <div className="tnum text-[17px] font-semibold text-foreground">{num(v)}</div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-[16px] border border-border bg-card shadow-sm">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2.5 font-semibold">Brand</th>
                  <th className="px-4 py-2.5 text-right font-semibold">On Encar</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Ours</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Unique</th>
                  <th className="w-[200px] px-4 py-2.5 font-semibold">Coverage</th>
                </tr>
              </thead>
              <tbody data-testid="coverage-rows">
                {brands.map((b) => (
                  <tr key={b.make} className="border-b border-border/60 last:border-0">
                    <td className="px-4 py-2 text-[13px] font-medium text-foreground">
                      {b.label || b.make}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-[13px] text-muted-foreground">
                      {num(b.upstream)}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-[13px] text-foreground">
                      {num(b.ads)}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-[13px] text-muted-foreground">
                      {num(b.unique)}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className={`h-full rounded-full ${bar(b.coverage)}`}
                            style={{
                              width: `${Math.min(100, (b.coverage || 0) * 100).toFixed(1)}%`,
                            }}
                          />
                        </div>
                        <span className="tnum w-[52px] text-right text-[12px] text-muted-foreground">
                          {b.coverage === null || b.coverage === undefined
                            ? "—"
                            : `${(b.coverage * 100).toFixed(1)}%`}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="rounded-[12px] bg-muted px-4 py-6 text-center text-[13px] text-muted-foreground">
          No measurement yet.
        </p>
      )}
    </div>
  );
};

export default AdminCoverage;
