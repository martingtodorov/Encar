import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check, PhoneCall, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { adminCallbacks, adminDeleteCallback, adminSetCallbackStatus } from "@/lib/api";
import { Spinner } from "@/components/admin/AdminBits";

/** Buyers who asked to be rung back, soonest first. */
const STATUSES = [
  ["", "All"],
  ["new", "New"],
  ["called", "Called"],
  ["closed", "Closed"],
];

const PILL = {
  new: "bg-[hsl(var(--primary))] text-primary-foreground",
  called: "bg-secondary text-foreground",
  closed: "bg-muted text-muted-foreground",
};

export const AdminCallbacks = () => {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");

  const load = useCallback(() => {
    adminCallbacks({ status, page: 1, page_size: 50 })
      .then(setData)
      .catch(() => setData({ items: [], counts: {}, total: 0 }));
  }, [status]);

  useEffect(load, [load]);

  const move = async (id, next) => {
    try {
      await adminSetCallbackStatus(id, next);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not update");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this call-back request?")) return;
    try {
      await adminDeleteCallback(id);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not delete");
    }
  };

  if (!data) return <Spinner />;

  return (
    <div
      data-testid="admin-callbacks"
      className="rounded-[14px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-foreground">
          <PhoneCall className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          Call-back requests
          <span className="text-[12.5px] font-normal text-muted-foreground">
            {data.counts?.new || 0} waiting
          </span>
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {STATUSES.map(([value, label]) => (
            <button
              key={value || "all"}
              type="button"
              data-testid={`callbacks-filter-${value || "all"}`}
              onClick={() => setStatus(value)}
              className={`rounded-[8px] px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                status === value
                  ? "bg-[hsl(var(--primary))] text-primary-foreground"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
              {value ? ` · ${data.counts?.[value] || 0}` : ""}
            </button>
          ))}
        </div>
      </div>

      {!data.items.length ? (
        <p className="py-6 text-center text-[13px] text-muted-foreground">
          Nobody is waiting for a call.
        </p>
      ) : (
        <div className="mt-4 flex flex-col gap-2">
          {data.items.map((c) => (
            <div
              key={c.id}
              data-testid={`callback-${c.id}`}
              className="flex flex-wrap items-center gap-3 rounded-[10px] border border-border bg-background px-3 py-2.5"
            >
              <span
                className={`rounded-[6px] px-2 py-0.5 text-[11px] font-semibold uppercase ${
                  PILL[c.status] || PILL.closed
                }`}
              >
                {c.status}
              </span>
              <span className="tnum text-[13px] font-semibold text-foreground">
                {c.when_label}
              </span>
              <a
                href={`tel:${c.phone}`}
                className="text-[13px] font-medium text-[hsl(var(--primary))] hover:underline"
              >
                {c.phone}
              </a>
              <span className="text-[13px] text-foreground">{c.name || "—"}</span>
              <span className="text-[12.5px] text-muted-foreground">{c.email}</span>
              {c.listing_id && (
                <Link
                  to={`/${c.lang || "bg"}/car/${c.listing_id}`}
                  className="max-w-[220px] truncate text-[12.5px] text-muted-foreground hover:text-foreground hover:underline"
                >
                  {c.car_title || c.listing_id}
                </Link>
              )}
              <div className="ml-auto flex items-center gap-1.5">
                {c.status !== "called" && (
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`callback-called-${c.id}`}
                    onClick={() => move(c.id, "called")}
                    className="h-8 gap-1.5 rounded-[8px] text-[12.5px]"
                  >
                    <Check className="h-3.5 w-3.5" />
                    Called
                  </Button>
                )}
                {c.status !== "closed" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid={`callback-close-${c.id}`}
                    onClick={() => move(c.id, "closed")}
                    className="h-8 rounded-[8px] text-[12.5px] text-muted-foreground"
                  >
                    Close
                  </Button>
                )}
                <button
                  type="button"
                  data-testid={`callback-delete-${c.id}`}
                  onClick={() => remove(c.id)}
                  className="rounded-[8px] p-2 text-muted-foreground hover:text-destructive"
                  aria-label="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default AdminCallbacks;
