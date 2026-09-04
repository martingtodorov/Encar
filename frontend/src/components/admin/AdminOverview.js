import { useEffect, useState } from "react";
import { AlertTriangle, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAdminOverview } from "@/lib/api";
import { AdminIncidents } from "@/components/admin/AdminIncidents";
import { Spinner, Stat, ago, num } from "@/components/admin/AdminBits";

export const AdminOverview = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getAdminOverview());
    } finally {
      setBusy(false);
    }
  };

  // Poll while a crawl is running so the operator watches it move, not a stale snapshot.
  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  if (!data) return <Spinner />;

  const job = data.job || {};
  const progress = job.progress || {};
  const part = data.partition || {};
  const stats = part.stats || {};
  const running = data.running || job.status === "running";
  const breaker = data.translation_breaker || {};
  const email = data.email || {};
  const held = data.listings_active || 0;
  const upstream = data.upstream || 0;

  return (
    <div data-testid="admin-overview" className="flex flex-col gap-5">
      <AdminIncidents />
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          Auto-refreshing every 15s · index last touched {ago(part.finished_at || job.finished_at)}
        </p>
        <Button
          data-testid="admin-overview-refresh"
          variant="outline"
          onClick={load}
          disabled={busy}
          className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px]"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden="true" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          testId="stat-upstream"
          label="Exportable ads on Encar"
          value={upstream}
          sub="live count, lease & rental excluded"
        />
        <Stat
          testId="stat-held"
          label="Ads indexed by us"
          value={held}
          sub={upstream ? `${((held / upstream) * 100).toFixed(2)}% of upstream` : "—"}
          tone={upstream && held / upstream > 0.98 ? "good" : "default"}
        />
        <Stat
          testId="stat-unique"
          label="Unique cars shown"
          value={data.unique_cars}
          sub={`${num(data.duplicate_ads_hidden)} duplicate ads hidden`}
        />
        <Stat
          testId="stat-translations"
          label="Translations cached"
          value={data.translations_cached}
          sub={
            breaker.open
              ? `provider paused, retry in ${breaker.retry_in_s}s`
              : `${num(breaker.trips)} provider trips so far`
          }
          tone={breaker.open ? "warn" : "default"}
        />
      </div>

      <section className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[14.5px] font-semibold text-foreground">Crawl</h2>
          <span
            data-testid="admin-sync-status"
            className={`rounded-full px-2.5 py-1 text-[12px] font-medium ${
              running
                ? "bg-[hsl(var(--info-soft))] text-[hsl(var(--info))]"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {running ? "running" : job.status || "idle"}
          </span>
        </div>

        {running && progress.percent != null ? (
          <div className="mt-3">
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-[hsl(var(--primary))] transition-[width] duration-500"
                style={{ width: `${Math.min(100, progress.percent)}%` }}
              />
            </div>
            <p className="mt-1.5 tnum text-[12px] text-muted-foreground">
              {progress.phase_label || "Crawling Encar"} · {num(progress.seen)} of about{" "}
              {num(progress.upstream)} cars
            </p>
          </div>
        ) : null}

        <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {[
            ["Last full crawl", ago(part.finished_at || job.finished_at)],
            ["Duration", part.duration_s ? `${Math.round(part.duration_s / 60)} min` : "—"],
            ["Partition leaves", num(stats.leaves)],
            ["Upstream requests", num(part.encar_requests)],
            ["Lease / rental skipped", num(stats.excluded_skipped ?? stats.lease_skipped)],
            ["Retired (gone from Encar)", num(part.retired)],
            ["Taxonomy nodes", `${num(data.taxonomy?.nodes)} · ${ago(data.taxonomy?.built_at)}`],
            ["Encar API errors", num(data.encar_stats?.errors)],
          ].map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5">
              <dt className="text-[12.5px] text-muted-foreground">{k}</dt>
              <dd className="tnum text-[12.5px] font-medium text-foreground">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
          <Mail className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          Email
        </h2>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">
          Sending from <span className="font-medium text-foreground">{email.sender}</span>.
          Notifications go to{" "}
          <span className="font-medium text-foreground">
            {email.notify_email || "nobody yet — ADMIN_NOTIFY_EMAIL is unset"}
          </span>
          .
        </p>
        {/* A key that is merely PRESENT proves nothing: Resend can reject it and every letter
            is dropped in silence. This is the loudest thing on the page when that happens. */}
        {email.auth?.ok === false ? (
          <p
            data-testid="admin-email-rejected"
            className="mt-3 flex items-start gap-2 rounded-[10px] border border-destructive bg-secondary px-3 py-2 text-[12px] font-medium leading-relaxed text-destructive"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>
              No email is going out at all — Resend rejects the API key ({email.auth.error}).
              Enquiries, call-back requests, deposit receipts and price-drop alerts are all being
              dropped. Put a valid <span className="font-semibold">RESEND_API_KEY</span> in the
              backend environment to switch them back on.
            </span>
          </p>
        ) : null}
        {email.auth?.ok === null && email.auth?.error ? (
          <p
            data-testid="admin-email-unreachable"
            className="mt-3 flex items-start gap-2 rounded-[10px] bg-secondary px-3 py-2 text-[12px] leading-relaxed text-muted-foreground"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Could not check the email key just now ({email.auth.error}).
          </p>
        ) : null}
        {email.shared_sender ? (
          <p
            data-testid="admin-email-warning"
            className="mt-3 flex items-start gap-2 rounded-[10px] bg-secondary px-3 py-2 text-[12px] leading-relaxed text-destructive"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Using Resend&apos;s shared test sender: mail only reaches the address that owns
            the Resend account. Verify your own domain before real buyers rely on it.
          </p>
        ) : null}
      </section>
    </div>
  );
};

export default AdminOverview;
