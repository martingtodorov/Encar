import { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import { getAuditLog } from "@/lib/api";
import { Spinner, ago } from "@/components/admin/AdminBits";

const TONE = {
  "customer deleted": "text-[hsl(var(--destructive))]",
  "enquiry deleted": "text-[hsl(var(--destructive))]",
  "deposit refunded": "text-[hsl(var(--primary))]",
};

/** Who changed or threw away what. Deletions leave no other trace. */
export const AdminAudit = () => {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    getAuditLog().then(setRows).catch(() => setRows([]));
  }, []);

  if (!rows) return <Spinner />;

  return (
    <div
      data-testid="admin-audit"
      className="rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <ScrollText className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        Activity ({rows.length})
      </h2>
      <p className="mt-2 text-[12.5px] text-muted-foreground">
        Every deletion, merge, rename and refund, newest first.
      </p>

      {rows.length === 0 ? (
        <p className="mt-4 text-[13px] text-muted-foreground">Nothing yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-border/60">
          {rows.map((r) => (
            <li
              key={r.id}
              data-testid={`audit-row-${r.id}`}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2.5"
            >
              <span className={`text-[13px] font-medium ${TONE[r.action] || "text-foreground"}`}>
                {r.action}
              </span>
              <span className="text-[13px] text-foreground">{r.target}</span>
              {r.detail ? (
                <span className="text-[12.5px] text-muted-foreground">{r.detail}</span>
              ) : null}
              <span className="ml-auto text-[12px] text-muted-foreground">
                {r.actor} · {r.at ? ago(r.at) : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default AdminAudit;
