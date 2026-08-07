import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Minus, Plus, Undo2, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { captureDeposit, getAdminDeposits, refundDeposit, releaseDeposit } from "@/lib/api";
import { Spinner, Stat, ago, num } from "@/components/admin/AdminBits";

const eur = (v) => `€${num(Math.round(v || 0))}`;
const STEP = 100;

const LABEL = {
  authorised: { text: "held", tone: "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]" },
  captured: { text: "captured", tone: "bg-emerald-500/10 text-emerald-600" },
  paid: { text: "charged", tone: "bg-emerald-500/10 text-emerald-600" },
  released: { text: "released", tone: "bg-muted text-muted-foreground" },
  expired: { text: "expired", tone: "bg-muted text-muted-foreground" },
  refunded: { text: "refunded", tone: "bg-muted text-muted-foreground" },
};

const days = (iso) => {
  if (!iso) return null;
  const left = Math.ceil((new Date(iso) - new Date()) / 86400000);
  return Number.isFinite(left) ? left : null;
};

/** How much of a hold to take, in round hundreds — the operator's only number. */
const CaptureBox = ({ row, busy, onCapture }) => {
  const max = Math.floor((row.amount || 0) / STEP) * STEP || STEP;
  const [amount, setAmount] = useState(Math.min(STEP, max));
  const step = (delta) =>
    setAmount((a) => Math.min(max, Math.max(STEP, a + delta * STEP)));

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center rounded-[10px] border border-border bg-card">
        <button
          type="button"
          data-testid={`capture-minus-${row.session_id}`}
          onClick={() => step(-1)}
          className="grid h-9 w-9 place-items-center text-muted-foreground transition-colors hover:text-foreground"
          aria-label="less"
        >
          <Minus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span
          data-testid={`capture-amount-${row.session_id}`}
          className="tnum w-[76px] text-center text-[13.5px] font-semibold text-foreground"
        >
          {eur(amount)}
        </span>
        <button
          type="button"
          data-testid={`capture-plus-${row.session_id}`}
          onClick={() => step(1)}
          className="grid h-9 w-9 place-items-center text-muted-foreground transition-colors hover:text-foreground"
          aria-label="more"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      <Button
        data-testid={`deposit-capture-all-${row.session_id}`}
        variant="outline"
        onClick={() => onCapture(row, row.amount)}
        disabled={busy}
        className="h-9 rounded-[10px] border-border bg-card px-3 text-[13px]"
      >
        All {eur(row.amount)}
      </Button>
      <Button
        data-testid={`deposit-capture-${row.session_id}`}
        onClick={() => onCapture(row, amount)}
        disabled={busy}
        className="h-9 gap-2 rounded-[10px] px-3 text-[13px]"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <Wallet className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        Capture
      </Button>
    </div>
  );
};

/**
 * Deposits held through Stripe, and the two decisions an operator makes on them.
 *
 * Nothing was charged at checkout: the amount is HELD for seven days. Capturing takes part
 * or all of it — whatever is left goes back for good, so the box counts in hundreds and asks
 * for a confirmation. Releasing takes nothing and puts the car back on the market. Older
 * deposits that were charged outright still show their refund button.
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

  const run = async (row, job, ok) => {
    setBusy(row.session_id);
    try {
      const out = await job();
      toast.success(ok(out));
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Stripe would not do that");
    } finally {
      setBusy("");
    }
  };

  const capture = (row, amount) => {
    const rest = Math.max(0, (row.amount || 0) - amount);
    if (
      !window.confirm(
        `Take ${eur(amount)} from ${row.email}? ${
          rest ? `The remaining ${eur(rest)} is released and cannot be taken later.` : ""
        }`
      )
    )
      return;
    run(row, () => captureDeposit(row.session_id, amount), (out) =>
      `Took ${eur(out.captured_eur)}${out.released_eur ? `, released ${eur(out.released_eur)}` : ""}`
    );
  };

  const release = (row) => {
    if (
      !window.confirm(
        `Release the ${eur(row.amount)} held on ${row.email} and put ` +
          `${row.car_title || row.car_id} back on the market?`
      )
    )
      return;
    run(row, () => releaseDeposit(row.session_id), () => "Hold released, car back on the market");
  };

  const refund = (row) => {
    const keep = row.commission_eur ?? 300;
    const back = Math.max(0, (row.amount || 0) - keep);
    if (
      !window.confirm(
        `Return ${eur(back)} to ${row.email}, keep ${eur(keep)} commission, and put ` +
          `${row.car_title || row.car_id} back on the market?`
      )
    )
      return;
    run(row, () => refundDeposit(row.session_id), (out) =>
      out.already
        ? "Stripe had already refunded this one — the car is released"
        : `Returned ${eur(out.returned_eur)}, kept ${eur(out.commission_eur)} and released the car`
    );
  };

  if (!rows) return <Spinner />;

  const held = rows.filter((r) => r.payment_status === "authorised");
  const captured = rows.filter((r) => r.payment_status === "captured");
  const holding = held.reduce((sum, r) => sum + (r.amount || 0), 0);
  const taken = captured.reduce((sum, r) => sum + (r.captured_eur || 0), 0);

  return (
    <div data-testid="admin-deposits" className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat testId="deposits-held" label="Cars held" value={num(held.length)} />
        <Stat testId="deposits-takings" label="Amount held" value={eur(holding)} />
        <Stat testId="deposits-captured" label="Captured" value={eur(taken)} />
      </div>

      {rows.length === 0 ? (
        <p data-testid="deposits-empty" className="text-[13px] text-muted-foreground">
          Nobody has reserved a car yet.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-[16px] border border-border bg-card px-5 shadow-sm"
            data-testid="deposits-list">
          {rows.map((r) => {
            const tag = LABEL[r.payment_status] || LABEL.released;
            const left = r.payment_status === "authorised" ? days(r.expires_at) : null;
            return (
              <li
                key={r.session_id}
                data-testid={`deposit-row-${r.session_id}`}
                className="flex flex-wrap items-center justify-between gap-3 py-4"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-semibold text-foreground">
                      {r.car_title || r.car_id}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tag.tone}`}>
                      {tag.text}
                    </span>
                    {left !== null ? (
                      <span
                        data-testid={`deposit-expiry-${r.session_id}`}
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          left <= 2 ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {left <= 0 ? "expires today" : `${left}d left`}
                      </span>
                    ) : null}
                    {r.payment_status === "authorised" && r.archive_ok === false ? (
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
                    {r.email} · {eur(r.amount)} of {eur(r.car_price_eur)} · car {r.car_id}
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                    reserved {ago(r.authorised_at || r.paid_at)}
                    {r.captured_at
                      ? ` · took ${eur(r.captured_eur)}${
                          r.released_eur ? ` and released ${eur(r.released_eur)}` : ""
                        } ${ago(r.captured_at)}${r.captured_by ? ` by ${r.captured_by}` : ""}`
                      : ""}
                    {r.released_at && !r.captured_at ? ` · released ${ago(r.released_at)}` : ""}
                    {r.refunded_at
                      ? ` · returned ${eur(r.returned_eur)} (kept ${eur(r.commission_eur)}) ` +
                        `${ago(r.refunded_at)} by ${r.refunded_by}`
                      : ""}
                  </div>
                </div>

                {r.payment_status === "authorised" ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <CaptureBox row={r} busy={busy === r.session_id} onCapture={capture} />
                    <Button
                      data-testid={`deposit-release-${r.session_id}`}
                      variant="outline"
                      onClick={() => release(r)}
                      disabled={busy === r.session_id}
                      className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px] hover:text-destructive"
                    >
                      <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                      Release
                    </Button>
                  </div>
                ) : null}

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
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default AdminDeposits;
