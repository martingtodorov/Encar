import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { getAdminDeposits, refundDeposit } from "@/lib/api";
import { Spinner, Stat, ago, num } from "@/components/admin/AdminBits";

const eur = (v) => `€${num(Math.round(v || 0))}`;

/**
 * Deposits taken through Stripe, and the one action an operator needs on them: refund.
 *
 * A refund is not only money — it releases the car, so somebody else can reserve it. Both
 * happen in one call, and the `charge.refunded` webhook makes the same two writes, so a
 * refund issued straight from the Stripe dashboard settles here too.
 */
export const AdminDeposits = () => {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const { items } = await getAdminDeposits();
    setRows(items || []);
  }, []);

  useEffect(() => {
    load().catch(() => setRows([]));
  }, [load]);

  const refund = async (row) => {
    const keep = row.commission_eur ?? 300;
    const back = Math.max(0, (row.amount || 0) - keep);
    if (
      !window.confirm(
        `Return ${eur(back)} to ${row.email}, keep ${eur(keep)} commission, and put ` +
          `${row.car_title || row.car_id} back on the market?`
      )
    )
      return;
    setBusy(row.session_id);
    try {
      const out = await refundDeposit(row.session_id);
      toast.success(
        out.already
          ? "Stripe had already refunded this one — the car is released"
          : `Returned ${eur(out.returned_eur)}, kept ${eur(out.commission_eur)} and released the car`
      );
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not refund that deposit");
    } finally {
      setBusy("");
    }
  };

  if (!rows) return <Spinner />;

  const held = rows.filter((r) => r.payment_status === "paid");
  const refunded = rows.filter((r) => r.payment_status === "refunded");
  const takings = held.reduce((sum, r) => sum + (r.amount || 0), 0);

  return (
    <div data-testid="admin-deposits" className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat testId="deposits-held" label="Cars held" value={num(held.length)} />
        <Stat testId="deposits-takings" label="Deposits held" value={eur(takings)} />
        <Stat testId="deposits-refunded" label="Refunded" value={num(refunded.length)} />
      </div>

      {rows.length === 0 ? (
        <p data-testid="deposits-empty" className="text-[13px] text-muted-foreground">
          No deposit has been paid yet.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-[16px] border border-border bg-card px-5 shadow-sm"
            data-testid="deposits-list">
          {rows.map((r) => (
            <li
              key={r.session_id}
              data-testid={`deposit-row-${r.session_id}`}
              className="flex flex-wrap items-center justify-between gap-3 py-4"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[13.5px] font-semibold text-foreground">
                    {r.car_title || r.car_id}
                  </span>
                  {r.payment_status === "refunded" ? (
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      refunded
                    </span>
                  ) : (
                    <span className="rounded-full bg-[hsl(var(--primary))]/10 px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--primary))]">
                      held
                    </span>
                  )}
                  {r.payment_status === "paid" && r.archive_ok === false ? (
                    <span
                      data-testid={`deposit-archive-warning-${r.session_id}`}
                      className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-medium text-destructive"
                      title="The car's photos and data were not copied to our server"
                    >
                      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                      not archived
                    </span>
                  ) : null}
                </div>
                <div className="tnum mt-0.5 text-[12px] text-muted-foreground">
                  {r.email} · deposit {eur(r.amount)} of {eur(r.car_price_eur)} · car {r.car_id}
                </div>
                <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                  paid {ago(r.paid_at)}
                  {r.refunded_at
                    ? ` · returned ${eur(r.returned_eur)} (kept ${eur(r.commission_eur)}) ` +
                      `${ago(r.refunded_at)} by ${r.refunded_by}`
                    : ""}
                </div>
              </div>

              {r.payment_status === "paid" ? (
                <Button
                  data-testid={`deposit-refund-${r.session_id}`}
                  variant="outline"
                  onClick={() => refund(r)}
                  disabled={busy === r.session_id}
                  className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px] hover:text-destructive"
                >
                  {busy === r.session_id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : (
                    <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  Return and release
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default AdminDeposits;
