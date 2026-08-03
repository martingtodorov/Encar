import { useEffect, useState } from "react";
import { CalendarClock, Loader2, Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { getCatalogueSync, putSyncSchedule, startCatalogueSync } from "@/lib/api";
import { Spinner, Stat, ago, num } from "@/components/admin/AdminBits";

const ZONES = ["Europe/Sofia", "Europe/Bucharest", "Europe/London", "Asia/Seoul", "UTC"];

const stamp = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
};

/** Start a whole-catalogue crawl, and choose a time for it to run by itself each day. */
export const AdminCatalogueSync = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ enabled: false, time: "03:30", tz: ZONES[0] });

  const load = async (keepForm = true) => {
    const d = await getCatalogueSync();
    setData(d);
    if (!keepForm || !data) {
      setForm({
        enabled: !!d.schedule?.enabled,
        time: d.schedule?.time || "03:30",
        tz: d.schedule?.tz || ZONES[0],
      });
    }
  };

  useEffect(() => {
    load(false).catch(() => setData(null));
    const id = setInterval(() => load().catch(() => {}), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!data) return <Spinner />;

  const job = data.job || {};
  const running = data.running || job.status === "running";
  const res = job.result || {};

  const run = async () => {
    setBusy(true);
    try {
      const r = await startCatalogueSync();
      toast[r.started ? "success" : "error"](
        r.started ? "Catalogue sync started" : r.reason || "Could not start"
      );
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start the sync");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const sched = await putSyncSchedule(form);
      setData((p) => ({ ...p, schedule: sched }));
      toast.success(
        sched.enabled ? `Daily sync set for ${sched.time} ${sched.tz}` : "Daily sync turned off"
      );
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save the schedule");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid="admin-catalogue-sync" className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          A full crawl walks every make and trim on Encar, retires cars that have sold, then
          rebuilds the dropdowns and URL slugs. It runs in the background — you can leave
          this page.
        </p>
        <Button
          data-testid="catalogue-sync-refresh"
          variant="outline"
          onClick={() => load().catch(() => {})}
          className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px]"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat testId="sync-status" label="Status" value={running ? "Running" : job.status || "idle"}
              sub={job.trigger ? `last trigger: ${job.trigger}` : null}
              tone={job.status === "error" ? "bad" : running ? "warn" : "default"} />
        <Stat testId="sync-started" label="Started" value={stamp(job.started_at)} sub={ago(job.started_at)} />
        <Stat testId="sync-finished" label="Finished" value={stamp(job.finished_at)} sub={ago(job.finished_at)} />
        <Stat testId="sync-active" label="Active listings after run" value={num(res.active)} />
      </div>

      {job.progress && (running || job.status === "done") ? (
        <div data-testid="sync-progress" className="rounded-[14px] border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[13.5px] font-semibold text-foreground">
              {running ? job.progress.phase_label : "Finished"}
            </span>
            <span data-testid="sync-progress-percent" className="tnum text-[13.5px] text-muted-foreground">
              {job.progress.percent}%
            </span>
          </div>
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              data-testid="sync-progress-bar"
              className="h-full rounded-full bg-[hsl(var(--primary))] transition-[width] duration-700"
              style={{ width: `${job.progress.percent}%` }}
            />
          </div>
          <p className="mt-2 text-[12.5px] text-muted-foreground">
            {num(job.progress.seen)} of about {num(job.progress.upstream)} cars indexed
            {job.progress.leaves ? ` · ${num(job.progress.leaves)} slices crawled` : ""}
          </p>
        </div>
      ) : null}

      {job.error ? (
        <p data-testid="sync-error" className="rounded-[12px] border border-destructive/40 bg-destructive/5 p-3 text-[13px] text-destructive">
          {job.error}
        </p>
      ) : null}

      <div className="rounded-[14px] border border-border bg-card p-4">
        <Button
          data-testid="catalogue-sync-run"
          onClick={run}
          disabled={busy || running}
          className="h-11 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[14px] font-semibold text-primary-foreground hover:brightness-110 disabled:opacity-60"
        >
          {busy || running ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Play className="h-4 w-4" aria-hidden="true" />
          )}
          {running ? "Sync in progress…" : "Synchronise all cars from Encar"}
        </Button>
      </div>

      <div className="rounded-[14px] border border-border bg-card p-4">
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          <h2 className="text-[15px] font-semibold text-foreground">Run it daily</h2>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="flex items-center gap-2.5">
            <Switch
              data-testid="sync-schedule-enabled"
              checked={form.enabled}
              onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
            />
            <span className="text-[13.5px] text-foreground">Enabled</span>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Time
            </span>
            <Input
              data-testid="sync-schedule-time"
              type="time"
              value={form.time}
              onChange={(e) => setForm((f) => ({ ...f, time: e.target.value }))}
              className="h-10 w-[130px] rounded-[10px]"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Time zone
            </span>
            <select
              data-testid="sync-schedule-tz"
              value={form.tz}
              onChange={(e) => setForm((f) => ({ ...f, tz: e.target.value }))}
              className="h-10 rounded-[10px] border border-input bg-card px-3 text-[13.5px] text-foreground"
            >
              {ZONES.map((z) => (
                <option key={z} value={z}>{z}</option>
              ))}
            </select>
          </label>

          <Button
            data-testid="sync-schedule-save"
            onClick={save}
            disabled={saving}
            className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {saving ? "Saving…" : "Save schedule"}
          </Button>
        </div>

        <p data-testid="sync-next-run" className="mt-3 text-[12.5px] text-muted-foreground">
          {data.schedule?.enabled
            ? `Next automatic run: ${stamp(data.schedule.next_run_at)}`
            : "No automatic run scheduled."}
        </p>
      </div>
    </div>
  );
};

export default AdminCatalogueSync;
