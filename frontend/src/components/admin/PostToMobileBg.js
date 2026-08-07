import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, Send, XCircle } from "lucide-react";
import { toast } from "sonner";
import { getMobileBgStatus, queueForMobileBg } from "@/lib/api";

/**
 * Queue one car for mobile.bg. The posting itself is done by an outside bot: it polls the
 * queue, posts at our final price and reports back, so this button's whole job is to say
 * "this one" and then show what came of it.
 */
export const PostToMobileBg = ({ carId }) => {
  const [row, setRow] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRow(await getMobileBgStatus(carId));
    } catch {
      setRow(null);
    }
  }, [carId]);

  useEffect(() => {
    load();
  }, [load]);

  const send = async () => {
    setBusy(true);
    try {
      setRow(await queueForMobileBg(carId));
      toast.success("Queued for mobile.bg — the bot posts it on its next pass");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not queue that car");
    } finally {
      setBusy(false);
    }
  };

  const status = row?.status;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
      <button
        type="button"
        data-testid="post-to-mobilebg"
        onClick={send}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-card px-3 py-1.5 text-[12.5px] font-medium text-foreground transition-colors hover:border-[hsl(var(--primary))] hover:text-[hsl(var(--primary))] disabled:opacity-60"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <Send className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {status ? "Post to mobile.bg again" : "Post to mobile.bg"}
      </button>

      {status === "pending" ? (
        <span data-testid="mobilebg-status" className="text-[12.5px] text-muted-foreground">
          Pending…
        </span>
      ) : null}

      {status === "posted" ? (
        <a
          data-testid="mobilebg-status"
          href={row.mobilebg_url || "#"}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-emerald-600 underline-offset-4 hover:underline"
        >
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          Posted
        </a>
      ) : null}

      {status === "failed" ? (
        <span
          data-testid="mobilebg-status"
          className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-destructive"
        >
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
          Failed{row.note ? `: ${row.note}` : ""}
        </span>
      ) : null}
    </div>
  );
};

export default PostToMobileBg;
