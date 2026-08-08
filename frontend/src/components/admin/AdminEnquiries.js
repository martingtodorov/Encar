import { useCallback, useEffect, useState } from "react";
import { Mail, Phone, Search, Trash2, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { deleteEnquiry, getAdminEnquiries, setEnquiryStatus } from "@/lib/api";
import { Spinner, num, stampSofia } from "@/components/admin/AdminBits";
import { AdminCallButton } from "@/components/admin/AdminCallButton";
import { AdminCallbacks } from "@/components/admin/AdminCallbacks";

const STATUSES = ["", "new", "contacted", "closed"];
const LABEL = { "": "All", new: "New", contacted: "Contacted", closed: "Closed" };
const PILL = {
  new: "bg-secondary text-[hsl(var(--primary))]",
  contacted: "bg-[hsl(var(--info-soft))] text-[hsl(var(--info))]",
  closed: "bg-muted text-muted-foreground",
};

const when = stampSofia;

export const AdminEnquiries = () => {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setData(await getAdminEnquiries({ status, q, page, page_size: 25 }));
  }, [status, q, page]);

  useEffect(() => {
    const id = setTimeout(load, q ? 300 : 0);
    return () => clearTimeout(id);
  }, [load, q]);

  const move = async (id, next) => {
    try {
      await setEnquiryStatus(id, next);
      toast.success(`Marked ${next}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not update");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this enquiry for good?")) return;
    try {
      await deleteEnquiry(id);
      toast.success("Enquiry deleted");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not delete");
    }
  };

  if (!data) return <Spinner />;

  const counts = data.counts || {};

  return (
    <div data-testid="admin-enquiries" className="flex flex-col gap-4">
      <AdminCallButton />
      <AdminCallbacks />
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-[10px] border border-border bg-muted p-0.5">
          {STATUSES.map((s) => (
            <button
              key={s || "all"}
              type="button"
              data-testid={`enquiry-filter-${s || "all"}`}
              onClick={() => {
                setStatus(s);
                setPage(1);
              }}
              className={`rounded-[8px] px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                status === s
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {LABEL[s]}
              {s && counts[s] ? ` (${counts[s]})` : ""}
            </button>
          ))}
        </div>

        <div className="relative min-w-[220px] flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            data-testid="enquiry-search"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Search car, name, email, phone, message…"
            className="h-10 rounded-[10px] border-border bg-card pl-9 text-[13px]"
          />
        </div>

        <span className="tnum text-[13px] text-muted-foreground">
          {num(data.total)} total
        </span>
      </div>

      {data.items.length === 0 ? (
        <p className="rounded-[12px] bg-muted px-4 py-10 text-center text-[13px] text-muted-foreground">
          No enquiries match.
        </p>
      ) : (
        <ul className="flex flex-col gap-3" data-testid="enquiry-list">
          {data.items.map((e) => (
            <li
              key={e.id}
              data-testid="enquiry-row"
              className="rounded-[14px] border border-border bg-card p-4 shadow-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <a
                    href={`/car/${e.listing_id}`}
                    target="_blank"
                    rel="noreferrer"
                    data-testid="enquiry-car-link"
                    className="text-[14px] font-semibold text-foreground hover:text-[hsl(var(--primary))]"
                  >
                    {e.car_title || `Listing ${e.listing_id}`}
                  </a>
                  <div className="mt-0.5 tnum text-[11.5px] text-muted-foreground">
                    #{e.listing_id} · {when(e.created_at)} · {e.lang?.toUpperCase()} ·{" "}
                    {e.is_guest ? "guest" : "signed in"}
                  </div>
                </div>
                <span
                  className={`rounded-full px-2.5 py-1 text-[11.5px] font-medium ${
                    PILL[e.status] || PILL.closed
                  }`}
                >
                  {e.status}
                </span>
              </div>

              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[13px]">
                {e.name ? (
                  <span className="inline-flex items-center gap-1.5 text-foreground">
                    <User className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                    {e.name}
                  </span>
                ) : null}
                {e.email ? (
                  <a
                    href={`mailto:${e.email}`}
                    data-testid="enquiry-email"
                    className="inline-flex items-center gap-1.5 text-foreground hover:text-[hsl(var(--primary))]"
                  >
                    <Mail className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                    {e.email}
                  </a>
                ) : null}
                {e.phone ? (
                  <a
                    href={`tel:${e.phone}`}
                    data-testid="enquiry-phone"
                    className="inline-flex items-center gap-1.5 text-foreground hover:text-[hsl(var(--primary))]"
                  >
                    <Phone className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                    {e.phone}
                  </a>
                ) : null}
              </div>

              {e.message ? (
                <p className="mt-3 whitespace-pre-line rounded-[10px] bg-muted px-3 py-2 text-[13px] leading-relaxed text-foreground">
                  {e.message}
                </p>
              ) : null}

              <div className="mt-3 flex gap-2">
                {["new", "contacted", "closed"]
                  .filter((s) => s !== e.status)
                  .map((s) => (
                    <Button
                      key={s}
                      variant="outline"
                      data-testid={`enquiry-mark-${s}`}
                      onClick={() => move(e.id, s)}
                      className="h-8 rounded-[8px] border-border bg-card px-3 text-[12px] font-medium hover:bg-muted"
                    >
                      Mark {s}
                    </Button>
                  ))}
                {e.status !== "new" && (
                  <Button
                    variant="outline"
                    data-testid="enquiry-delete"
                    onClick={() => remove(e.id)}
                    className="ml-auto h-8 gap-1.5 rounded-[8px] border-border bg-card px-3 text-[12px] font-medium text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.08)]"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Delete
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {data.pages > 1 ? (
        <div className="flex items-center justify-center gap-3">
          <Button
            variant="outline"
            data-testid="enquiry-prev"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="h-9 rounded-[10px] border-border bg-card px-3 text-[13px]"
          >
            Previous
          </Button>
          <span className="tnum text-[13px] text-muted-foreground">
            {page} / {data.pages}
          </span>
          <Button
            variant="outline"
            data-testid="enquiry-next"
            disabled={page >= data.pages}
            onClick={() => setPage((p) => p + 1)}
            className="h-9 rounded-[10px] border-border bg-card px-3 text-[13px]"
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
};

export default AdminEnquiries;
