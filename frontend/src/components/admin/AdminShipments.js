import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, RefreshCw, Ship, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import {
  assignShipment,
  deleteShipment,
  getAdminShipments,
  getTrackingQuota,
  refreshShipment,
} from "@/lib/api";
import { Spinner, ago } from "@/components/admin/AdminBits";
import { CustomerPicker } from "@/components/admin/CustomerPicker";

const BLANK = { email: "", ref: "", by: "bol" };

export const AdminShipments = () => {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState("");
  const [result, setResult] = useState(null);
  const [quota, setQuota] = useState(null);

  const load = useCallback(async () => {
    setRows(await getAdminShipments());
    setQuota(await getTrackingQuota().catch(() => null));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await assignShipment(form);
      toast.success(`${form.ref.toUpperCase()} assigned to ${form.email}`);
      setForm(BLANK);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "could not assign that reference");
    } finally {
      setBusy(false);
    }
  };

  // Reads Maersk's public track page in a real browser, so it takes a few seconds.
  const check = async (row) => {
    setChecking(row.ref);
    setResult(null);
    try {
      const data = await refreshShipment(row.ref, row.by);
      setResult({ ref: row.ref, data });
      toast.success(
        data.found && data.milestones?.length
          ? `${data.milestones.length} milestones from ${data.source}`
          : "the carrier has nothing public for that reference yet"
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "the carrier could not be read");
    } finally {
      setChecking("");
    }
  };

  const drop = async (ref) => {
    try {
      await deleteShipment(ref);
      toast.success(`${ref} removed`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "could not remove that reference");
    }
  };

  if (!rows) return <Spinner />;

  return (
    <div data-testid="admin-shipments" className="flex flex-col gap-5">
      <section className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
          <Ship className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          Assign a tracking reference
        </h2>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">
          The reference appears on the customer&apos;s Track page straight away. Milestones and
          the live ship position come from the tracking provider (and from the EDI feed once
          it is delivering); anything you fill in here is kept on top of whatever the carrier
          says.
        </p>

        {/* Shown even when the provider is NOT connected. Hiding this line when there is no
            key is what let a one-word misconfiguration read as "no shipments found" on the
            customer page with nothing anywhere to contradict it. */}
        {quota && (
          <p
            data-testid="tracking-quota"
            className={`tnum mt-2 text-[12px] font-medium ${
              quota.configured && !quota.error ? "text-muted-foreground" : "text-destructive"
            }`}
          >
            {!quota.configured
              ? `Tracking provider NOT connected — ${quota.hint || "no API key in this deployment"}`
              : quota.error
                ? quota.error
                : `Provider plan ${quota.plan}: ${quota.requests_available} of ${quota.requests_total} lookups left this month · carrier ${quota.shipping_line}`}
          </p>
        )}

        {/* The plan can be perfectly healthy while every single lookup fails — a wrong carrier
            answers 400 for every reference. So the last provider failure is reported here, not
            only in a log on the server. */}
        {quota?.last_error && (
          <p
            data-testid="tracking-last-error"
            className="mt-1 text-[12px] font-medium text-destructive"
          >
            Last provider failure on {quota.last_error.path}: {quota.last_error.message}
          </p>
        )}

        {/* Bill of lading only: the container number is our lookup key, never something the
            buyer is shown, so there is nothing for an operator to choose here. */}
        <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={submit}>
          {/* Not a <label>: a click on an option inside one is forwarded to the label's
              control (the picker's own trigger), which reopened the list every time an
              operator chose someone — and the open list then covered Assign. */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">Customer</span>
            <CustomerPicker
              value={form.email}
              onChange={(email) => setForm((f) => ({ ...f, email }))}
            />
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">
              Bill of lading
            </span>
            <Input
              data-testid="shipment-ref"
              value={form.ref}
              onChange={set("ref")}
              placeholder="9-character B/L"
              className="h-10 bg-background"
            />
          </label>

          <div className="sm:col-span-2">
            <Button
              data-testid="shipment-assign"
              type="submit"
              disabled={busy || !form.email.trim() || !form.ref.trim()}
              className="h-10 gap-2"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Assign
            </Button>
          </div>
        </form>
      </section>

      <section className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
        <h2 className="text-[14.5px] font-semibold text-foreground">
          Assigned shipments ({rows.length})
        </h2>

        {rows.length === 0 ? (
          <p className="mt-3 text-[12.5px] text-muted-foreground">
            Nothing assigned yet.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-border" data-testid="shipment-list">
            {rows.map((r) => (
              <li
                key={r.ref}
                data-testid={`shipment-row-${r.ref}`}
                className="flex flex-wrap items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0">
                  <div className="tnum text-[13.5px] font-semibold text-foreground">
                    {r.ref}
                    <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {r.by === "bol" ? "B/L" : "container"}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-muted-foreground">
                    {r.email}
                    {r.vessel_name ? ` · ${r.vessel_name}` : ""}
                    {r.vessel_imo ? ` (IMO ${r.vessel_imo})` : ""}
                    {r.eta ? ` · ETA ${r.eta}` : ""}
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                    assigned {ago(r.updated_at)} by {r.updated_by}
                    {r.car_id ? ` · car ${r.car_id}` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    data-testid={`shipment-check-${r.ref}`}
                    variant="outline"
                    onClick={() => check(r)}
                    disabled={checking === r.ref}
                    className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px]"
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${checking === r.ref ? "animate-spin" : ""}`}
                      aria-hidden="true"
                    />
                    Read carrier
                  </Button>
                  <Button
                    data-testid={`shipment-delete-${r.ref}`}
                    variant="ghost"
                    onClick={() => drop(r.ref)}
                    className="h-9 w-9 p-0 text-muted-foreground hover:text-destructive"
                    aria-label={`Remove ${r.ref}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {result && (
          <div
            data-testid="shipment-check-result"
            className="mt-4 rounded-[12px] border border-border bg-background p-4"
          >
            <div className="text-[12.5px] font-semibold text-foreground">
              {result.ref} · source {result.data.source || "none"} ·{" "}
              {result.data.milestones?.length || 0} milestones
            </div>
            <ul className="mt-2 space-y-1">
              {(result.data.milestones || []).slice(-8).map((m, i) => (
                <li key={`${m.when}-${m.code}-${i}`} className="tnum text-[12px] text-muted-foreground">
                  {m.when} · {m.text || m.code} {m.location ? `· ${m.location}` : ""}
                  {m.vessel_name ? ` · ${m.vessel_name}` : ""}
                  {m.estimated ? " (est.)" : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
};

export default AdminShipments;
