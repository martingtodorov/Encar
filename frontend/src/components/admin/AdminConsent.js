import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { getConsentLog } from "@/lib/api";
import { Spinner, ago } from "@/components/admin/AdminBits";

const LABEL = { personalisation: "Personalisation", statistics: "Statistics" };

/**
 * Proof of consent, per customer.
 *
 * What an inspector asks for is not "is there a banner" but "show me what this person agreed
 * to, when, and against which version of the policy". A guest's decision never leaves their
 * own machine, so only accounts can appear here.
 */
export const AdminConsent = () => {
  const [data, setData] = useState(null);

  useEffect(() => {
    getConsentLog().then(setData).catch(() => setData({ items: [] }));
  }, []);

  if (!data) return <Spinner />;
  const rows = data.items || [];

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
        it is never sent to us and cannot be listed here.
      </p>

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
                      <span className="flex flex-wrap gap-1.5">
                        {r.categories.map((c) => (
                          <span
                            key={c}
                            className="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-semibold text-[hsl(var(--primary))]"
                          >
                            {LABEL[c] || c}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="tnum py-2.5 pr-3 text-[12.5px] text-muted-foreground">
                    {r.version || "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-[12.5px] text-muted-foreground">
                    {r.recorded_at ? ago(r.recorded_at) : r.decided_at || "—"}
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
