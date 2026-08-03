import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { getBuyers } from "@/lib/api";
import { Spinner, ago } from "@/components/admin/AdminBits";

const money = (n) => (n ? `€${Math.round(n).toLocaleString("en-GB")}` : "—");
const km = (n) => (n ? `${Math.round(n).toLocaleString("en-GB")} km` : "—");

const range = (low, high, fmt) =>
  low && high && Math.round(low) !== Math.round(high)
    ? `${fmt(low)} – ${fmt(high)}`
    : fmt(low || high);

/** What each customer is after, so the operator can offer the right car. */
export const AdminBuyers = () => {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    getBuyers().then(setRows).catch(() => setRows([]));
  }, []);

  if (!rows) return <Spinner />;

  const active = rows.filter((r) => r.events > 0);

  return (
    <div data-testid="admin-buyers" className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <Users className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        Buyer interests ({active.length} of {rows.length} with activity)
      </h2>
      <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">
        Built from what each signed-in customer searches, opens and lingers on. The price and
        mileage columns show the range they actually browse in, weighted by how long they
        spent on each car — not a single average.
      </p>

      {active.length === 0 ? (
        <p className="mt-4 text-[12.5px] text-muted-foreground">
          No signed-in customer has browsed enough yet for a profile to form.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[820px] text-left">
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-3 font-medium">Customer</th>
                <th className="pb-2 pr-3 font-medium">Wants</th>
                <th className="pb-2 pr-3 font-medium">Price range</th>
                <th className="pb-2 pr-3 font-medium">Mileage</th>
                <th className="pb-2 pr-3 font-medium">Saved</th>
                <th className="pb-2 font-medium">Last active</th>
              </tr>
            </thead>
            <tbody>
              {active.map((r) => (
                <tr
                  key={r.email}
                  data-testid={`buyer-row-${r.email}`}
                  className="border-b border-border/60 align-top"
                >
                  <td className="py-2.5 pr-3">
                    <div className="text-[13px] font-medium text-foreground">{r.email}</div>
                    {(r.name || r.city) && (
                      <div className="text-[12px] text-muted-foreground">
                        {[r.name, r.city].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="text-[13px] text-foreground">
                      {r.models.length ? r.models.join(", ") : r.makes.join(", ") || "—"}
                    </div>
                    {r.models.length > 0 && r.makes.length > 0 && (
                      <div className="text-[12px] text-muted-foreground">
                        {r.makes.join(", ")}
                        {r.fuels.length ? ` · ${r.fuels.join(", ")}` : ""}
                      </div>
                    )}
                  </td>
                  <td className="tnum py-2.5 pr-3 text-[13px] text-foreground">
                    {range(r.price_low, r.price_high, money)}
                  </td>
                  <td className="tnum py-2.5 pr-3 text-[13px] text-foreground">
                    {range(r.mileage_low, r.mileage_high, km)}
                  </td>
                  <td className="tnum py-2.5 pr-3 text-[13px] text-muted-foreground">
                    {r.favourites}
                  </td>
                  <td className="py-2.5 text-[12.5px] text-muted-foreground">
                    {r.updated_at ? ago(r.updated_at) : "—"}
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

export default AdminBuyers;
