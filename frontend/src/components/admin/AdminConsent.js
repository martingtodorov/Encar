import { useCallback, useEffect, useState } from "react";
import { BellRing, Loader2, ShieldCheck, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getConsentLog, setConsentReask } from "@/lib/api";
import { Spinner, ago, stampSofia } from "@/components/admin/AdminBits";

const LABEL = { personalisation: "Personalisation", statistics: "Statistics" };

/**
 * Proof of consent, per customer — and the one control that asks everybody again.
 *
 * What an inspector asks for is not "is there a banner" but "show me what this person agreed
 * to, when, and against which version of the policy". A guest's decision never leaves their
 * own machine, so only accounts can appear here.
 */
export const AdminConsent = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getConsentLog().then(setData).catch(() => setData({ items: [] }));
  }, []);

  useEffect(load, [load]);

  const reask = async (on) => {
    setBusy(true);
    try {
      await setConsentReask(on);
      load();
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Spinner />;
  const rows = data.items || [];
  const active = !!data.reask_at;

  return (
    <div
      data-testid="admin-consent"
      className="rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <ShieldCheck className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        Cookie consent ({data.with_record || 0} of {data.total || 0} accounts)
      </h2>
      <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">
        What each signed-in customer agreed to, when they decided and which policy version they
        saw. Visitors without an account keep their decision in a cookie on their own device, so
        it is never sent to us and cannot be listed here — unless they open an account within 90
        days, in which case the choice they already made is carried onto it.
      </p>

      <div
        data-testid="admin-consent-reask"
        data-active={active}
        className={`mt-4 flex flex-col gap-2 rounded-[12px] border p-3.5 ${
          active ? "border-amber-500/50 bg-amber-500/10" : "border-border bg-background"
        }`}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-[13px] font-semibold text-foreground">
            Ask every visitor to decide again
          </span>
          <span className="text-[12px] text-muted-foreground">
            {data.not_asked || 0} accounts never decided
            {active ? ` · ${data.awaiting || 0} asked again, still waiting` : ""}
            {data.carried ? ` · ${data.carried} carried from a pre-account cookie` : ""}
          </span>
          {active ? (
            <Button
              data-testid="admin-consent-reask-cancel"
              variant="outline"
              onClick={() => reask(false)}
              disabled={busy}
              className="ml-auto h-9 gap-1.5 rounded-[9px] px-3 text-[12.5px]"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Undo2 className="h-3.5 w-3.5" />}
              Cancel the request
            </Button>
          ) : (
            <Button
              data-testid="admin-consent-reask-on"
              onClick={() => reask(true)}
              disabled={busy}
              className="ml-auto h-9 gap-1.5 rounded-[9px] px-3 text-[12.5px] font-semibold"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BellRing className="h-3.5 w-3.5" />}
              Ask everyone again
            </Button>
          )}
        </div>
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          {active ? (
            <>
              Active since <span className="font-medium">{stampSofia(data.reask_at)}</span>. Every
              decision taken before that moment stops counting: the dialog opens on the visitor's
              next page view — guests and signed-in buyers, on every device — and nothing outside
              the strictly necessary category is written until they answer. Cancelling restores
              the decisions already on record.
            </>
          ) : (
            <>
              Opens the consent dialog again for everyone, including visitors who answered long
              ago. Use it after a change to what personalisation or statistics actually do.
            </>
          )}
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="mt-4 text-[13px] text-muted-foreground">Nothing yet.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Customer</th>
                <th className="py-2 pr-3 font-medium">Agreed to</th>
                <th className="py-2 pr-3 font-medium">Policy</th>
                <th className="py-2 pr-3 font-medium">Decided</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {rows.map((r) => (
                <tr key={r.email} data-testid={`consent-row-${r.email}`}>
                  <td className="py-2.5 pr-3 text-[13px] text-foreground">{r.email}</td>
                  <td className="py-2.5 pr-3">
                    {!r.has_record ? (
                      <span className="text-[12.5px] text-muted-foreground">not asked yet</span>
                    ) : r.categories.length === 0 ? (
                      <span className="text-[12.5px] font-medium text-[hsl(var(--destructive))]">
                        refused everything optional
                      </span>
                    ) : (
                      <span className="flex flex-wrap items-center gap-1.5">
                        {r.categories.map((c) => (
                          <span
                            key={c}
                            className="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-semibold text-[hsl(var(--primary))]"
                          >
                            {LABEL[c] || c}
                          </span>
                        ))}
                        {r.carried ? (
                          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                            carried
                          </span>
                        ) : null}
                      </span>
                    )}
                  </td>
                  <td className="tnum py-2.5 pr-3 text-[12.5px] text-muted-foreground">
                    {r.version || "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-[12.5px] text-muted-foreground">
                    {r.stale ? (
                      <span data-testid={`consent-stale-${r.email}`} className="text-amber-700">
                        asked again — waiting
                      </span>
                    ) : r.recorded_at ? (
                      ago(r.recorded_at)
                    ) : (
                      r.decided_at || "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AdminConsent;
