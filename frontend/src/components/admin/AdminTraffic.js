import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getTraffic, getTrafficHistory } from "@/lib/api";
import { daySofia } from "@/components/admin/AdminBits";

const RANGES = [
  { days: 7, label: "7 дни" },
  { days: 30, label: "30 дни" },
];

const fmt = (n) => new Intl.NumberFormat("bg-BG").format(n || 0);
const dayLabel = (iso) => daySofia(iso);

/**
 * Traffic over time, next to the live figures.
 *
 * Drawn by hand rather than with a charting library: recharts is in package.json but unused, so
 * importing it here would add a few hundred kilobytes to every visitor's bundle for one bar
 * chart that only an administrator ever opens.
 */
export const AdminTraffic = () => {
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState([]);
  const [now, setNow] = useState(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [history, snapshot] = await Promise.all([getTrafficHistory(days), getTraffic()]);
      setRows(history);
      setNow(snapshot);
    } finally {
      setBusy(false);
    }
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  const peak = Math.max(1, ...rows.map((r) => r.views));
  const totalViews = rows.reduce((a, r) => a + r.views, 0);
  const busiest = rows.reduce((best, r) => (r.views > (best?.views ?? -1) ? r : best), null);

  return (
    <section data-testid="admin-traffic" className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Users className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
            Трафик
          </h2>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            Посетителите се броят без бисквитки, а твоите собствени посещения като администратор
            не влизат в числата.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              data-testid={`traffic-range-${r.days}`}
              onClick={() => setDays(r.days)}
              className={`h-9 rounded-[9px] px-3 text-[12.5px] font-medium transition-colors ${
                days === r.days
                  ? "bg-[hsl(var(--primary))] text-primary-foreground"
                  : "border border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.label}
            </button>
          ))}
          <Button
            variant="outline"
            data-testid="traffic-reload"
            onClick={load}
            className="h-9 gap-1.5 rounded-[9px] text-[12.5px]"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Обнови
          </Button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat testId="traffic-stat-live" label={`Онлайн сега (${now?.live_minutes ?? 5} мин)`}
              value={now ? fmt(now.live) : "—"} accent />
        <Stat testId="traffic-stat-day" label="Днес (от 00:00)"
              value={now ? `${fmt(now.day.visitors)} / ${fmt(now.day.views)}` : "—"}
              hint="посетители / показвания" />
        <Stat testId="traffic-stat-week" label="Последните 7 дни (с днешния)"
              value={now ? `${fmt(now.week.visitors)} / ${fmt(now.week.views)}` : "—"}
              hint="посетители / показвания" />
        <Stat testId="traffic-stat-month" label="Последните 30 дни (с днешния)"
              value={now ? `${fmt(now.month.visitors)} / ${fmt(now.month.views)}` : "—"}
              hint="посетители / показвания" />
      </div>

      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[13px] font-semibold text-foreground">
            Показвания по дни
          </span>
          <span className="tnum text-[12px] text-muted-foreground">
            {fmt(totalViews)} показвания за периода
            {busiest && busiest.views > 0
              ? ` · най-силен ден ${dayLabel(busiest.day)} с ${fmt(busiest.views)}`
              : ""}
          </span>
        </div>

        {totalViews === 0 ? (
          <p data-testid="traffic-empty" className="py-8 text-center text-[13px] text-muted-foreground">
            Още няма записани посещения за този период.
          </p>
        ) : (
          <div data-testid="traffic-chart" className="flex h-[180px] items-end gap-[3px]">
            {rows.map((r) => (
              <div key={r.day} className="group relative flex h-full flex-1 items-end">
                <div
                  className="w-full rounded-t-[3px] bg-[hsl(var(--primary))]/25 transition-colors group-hover:bg-[hsl(var(--primary))]/40"
                  style={{ height: `${Math.max(2, (r.views / peak) * 100)}%` }}
                >
                  <div
                    className="w-full rounded-t-[3px] bg-[hsl(var(--primary))]"
                    style={{
                      height: r.views ? `${(r.visitors / r.views) * 100}%` : "0%",
                    }}
                  />
                </div>
                <span className="pointer-events-none absolute -top-1 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-[6px] bg-foreground px-2 py-1 text-[11px] font-medium text-background group-hover:block">
                  {dayLabel(r.day)}: {fmt(r.visitors)} посетители · {fmt(r.views)} показвания
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 flex items-center gap-4 text-[11.5px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-[hsl(var(--primary))]" />
            уникални посетители
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-[hsl(var(--primary))]/25" />
            общо показвания
          </span>
        </div>
      </div>

      {now?.pages?.length ? (
        <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
          <span className="text-[13px] font-semibold text-foreground">Гледа се в момента</span>
          <ul data-testid="traffic-now-pages" className="mt-3 flex flex-col gap-2">
            {now.pages.map((p) => (
              <li key={p.label} className="flex items-center justify-between gap-3 text-[13px]">
                <span className="truncate text-foreground">{p.label}</span>
                <span className="tnum shrink-0 font-semibold text-muted-foreground">
                  {fmt(p.count)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
};

const Stat = ({ label, value, hint, accent, testId }) => (
  <div
    data-testid={testId}
    className={`rounded-[12px] border p-3.5 ${
      accent ? "border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/5" : "border-border bg-card"
    }`}
  >
    <div className="text-[11.5px] font-medium text-muted-foreground">{label}</div>
    <div className="tnum mt-1 text-[22px] font-semibold leading-none text-foreground">{value}</div>
    {hint ? <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div> : null}
  </div>
);

export default AdminTraffic;
