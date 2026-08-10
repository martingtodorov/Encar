import { useEffect, useState } from "react";
import { CalendarClock, Loader2, Play, Plus, RefreshCw, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { getCatalogueSync, putSyncSchedule, startCatalogueSync } from "@/lib/api";
import { Spinner, Stat, ago, num, stampSofia } from "@/components/admin/AdminBits";

const ZONES = ["Europe/Sofia", "Europe/Bucharest", "Europe/London", "Asia/Seoul", "UTC"];
const MAX_TIMES = 6;

const stamp = stampSofia;

const timesFrom = (s) => {
  if (Array.isArray(s?.times) && s.times.length) return [...s.times];
  if (s?.time) return [s.time];
  return ["03:30"];
};

/** Start a whole-catalogue crawl, and choose one or more times for it to run by itself each day. */
export const AdminCatalogueSync = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ enabled: false, times: ["03:30"], tz: ZONES[0] });

  const load = async (keepForm = true) => {
    const d = await getCatalogueSync();
    setData(d);
    if (!keepForm || !data) {
      setForm({
        enabled: !!d.schedule?.enabled,
        times: timesFrom(d.schedule),
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
  const checkpoint = !running ? job.checkpoint : null;

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

  const updateTime = (idx, value) =>
    setForm((f) => {
      const next = [...f.times];
      next[idx] = value;
      return { ...f, times: next };
    });

  const removeTime = (idx) =>
    setForm((f) => {
      if (f.times.length <= 1) return f;
      return { ...f, times: f.times.filter((_, i) => i !== idx) };
    });

  const addTime = () =>
    setForm((f) => {
      if (f.times.length >= MAX_TIMES) return f;
      return { ...f, times: [...f.times, "12:00"] };
    });

  const save = async () => {
    // De-duplicate and sort locally so the payload matches what the server will store.
    const cleaned = Array.from(new Set(form.times.filter(Boolean))).sort();
    if (!cleaned.length) {
      toast.error("Add at least one time");
      return;
    }
    setSaving(true);
    try {
      const sched = await putSyncSchedule({
        enabled: form.enabled, times: cleaned, tz: form.tz,
      });
      setData((p) => ({ ...p, schedule: sched }));
      setForm((f) => ({ ...f, times: timesFrom(sched) }));
      toast.success(
        sched.enabled
          ? `Daily sync set for ${sched.times.join(", ")} ${sched.tz}`
          : "Daily sync turned off"
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
        {checkpoint ? (
          <p data-testid="sync-checkpoint" className="mb-3 text-[12.5px] text-muted-foreground">
            {checkpoint.crawl_done
              ? "The last run was interrupted after the crawl finished. Starting it will pick up at the remaining passes."
              : `The last run was interrupted with ${num(checkpoint.slices)} slices already indexed (${ago(checkpoint.updated_at)}). Starting it will carry on from there.`}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            data-testid="catalogue-sync-run"
            onClick={() => run(false)}
            disabled={busy || running}
            className="h-11 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[14px] font-semibold text-primary-foreground hover:brightness-110 disabled:opacity-60"
          >
            {busy || running ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Play className="h-4 w-4" aria-hidden="true" />
            )}
            {running
              ? "Sync in progress…"
              : checkpoint
                ? "Resume the interrupted sync"
                : "Synchronise all cars from Encar"}
          </Button>
          {checkpoint ? (
            <Button
              data-testid="catalogue-sync-fresh"
              variant="outline"
              onClick={() => run(true)}
              disabled={busy || running}
              className="h-11 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Start from scratch
            </Button>
          ) : null}
        </div>
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

          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Times (up to {MAX_TIMES}/day)
            </span>
            <div data-testid="sync-schedule-times" className="flex flex-wrap items-center gap-2">
              {form.times.map((t, i) => (
                <div
                  key={i}
                  data-testid={`sync-schedule-time-row-${i}`}
                  className="flex items-center gap-1"
                >
                  <Input
                    data-testid={`sync-schedule-time-${i}`}
                    type="time"
                    value={t}
                    onChange={(e) => updateTime(i, e.target.value)}
                    className="h-10 w-[130px] rounded-[10px]"
                  />
                  {form.times.length > 1 ? (
                    <button
                      type="button"
                      data-testid={`sync-schedule-time-remove-${i}`}
                      onClick={() => removeTime(i)}
                      aria-label={`Remove time ${t}`}
                      className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <X className="h-4 w-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              ))}
              {form.times.length < MAX_TIMES ? (
                <Button
                  type="button"
                  data-testid="sync-schedule-time-add"
                  variant="outline"
                  onClick={addTime}
                  className="h-10 gap-1.5 rounded-[10px] border-border bg-card px-3 text-[13px]"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  Add time
                </Button>
              ) : null}
            </div>
          </div>

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
            ? `Runs daily at ${(data.schedule.times || []).join(", ")} ${data.schedule.tz} · next: ${stamp(data.schedule.next_run_at)}`
            : "No automatic run scheduled."}
        </p>
      </div>
    </div>
  );
};

export default AdminCatalogueSync;
