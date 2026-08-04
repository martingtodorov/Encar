import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import http from "@/lib/api";

/**
 * Customer picker for the shipment form.
 *
 * The operator knows the buyer by name, so the list opens on click and filters as they
 * type across first name, surname and email. Every keystroke is debounced into one
 * request, and the chosen account is reported back as its email (the assignment key).
 */
export const CustomerPicker = ({ value, onChange }) => {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    setLoading(true);
    // The list is wanted the instant it opens; only typing is debounced.
    const id = setTimeout(async () => {
      try {
        const { data } = await http.get("/admin/customers", { params: { q: term } });
        setRows(data.items || []);
      } catch (e) {
        setRows([]);
      } finally {
        setLoading(false);
      }
    }, term ? 220 : 0);
    return () => clearTimeout(id);
  }, [term, open]);

  // Clicking anywhere else closes the list; a picker that stays open is a trap.
  useEffect(() => {
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        data-testid="shipment-customer"
        aria-label="Customer"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 w-full items-center justify-between gap-2 rounded-[10px] border border-input bg-background px-3 text-left text-[13.5px] text-foreground"
      >
        <span className={value ? "truncate" : "truncate text-muted-foreground"}>
          {value || "Pick a customer"}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>

      {open && (
        <div
          data-testid="shipment-customer-menu"
          className="absolute left-0 top-[calc(100%+4px)] z-50 w-full rounded-[12px] border border-border bg-card p-2 shadow-lg"
        >
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              data-testid="shipment-customer-search"
              autoFocus
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
              }}
              placeholder="Name, surname or email"
              className="h-9 bg-background pl-8 text-[13px]"
            />
          </div>

          <ul className="thin-scroll mt-2 max-h-64 overflow-y-auto">
            {rows.length === 0 ? (
              <li
                data-testid="shipment-customer-empty"
                className="px-2 py-2 text-[12.5px] text-muted-foreground"
              >
                {loading ? "Searching…" : "No matching customer"}
              </li>
            ) : (
              rows.map((r) => (
                <li key={r.email}>
                  <button
                    type="button"
                    data-testid={`shipment-customer-option-${r.email}`}
                    onClick={() => {
                      onChange(r.email);
                      setOpen(false);
                      setTerm("");
                    }}
                    className="flex w-full items-center gap-2 rounded-[8px] px-2 py-2 text-left transition-colors hover:bg-muted"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-foreground">
                        {r.name || r.email}
                      </span>
                      {r.name ? (
                        <span className="block truncate text-[12px] text-muted-foreground">
                          {r.email}
                        </span>
                      ) : null}
                    </span>
                    {value === r.email && (
                      <Check className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
                    )}
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
};

export default CustomerPicker;
