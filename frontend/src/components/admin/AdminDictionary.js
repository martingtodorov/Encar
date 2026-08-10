import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Check, Loader2, Pencil, Search, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  adminDictionaryBrowse,
  adminDictionaryEdit,
  adminDictionaryStats,
} from "@/lib/api";
import { Spinner, Stat, num } from "@/components/admin/AdminBits";

// The order mirrors how tokens are actually spent: the most-touched types (the ones a
// visitor sees on every search page) come first so the operator can audit those before
// scrolling down to the long tail.
const TYPE_OPTIONS = [
  { value: "", label: "Any type" },
  { value: "manufacturer", label: "Make" },
  { value: "model", label: "Model" },
  { value: "badge", label: "Trim (badge)" },
  { value: "badge_detail", label: "Trim detail" },
  { value: "fuel_type", label: "Fuel" },
  { value: "region", label: "Region" },
  { value: "sell_type", label: "Sell type" },
  { value: "description_line", label: "Description line" },
  { value: "description_full", label: "Full description" },
  { value: "misc", label: "Misc (options, panels…)" },
];

const LANG_OPTIONS = [
  { value: "", label: "Any lang" },
  { value: "bg", label: "BG" },
  { value: "ro", label: "RO" },
  { value: "en", label: "EN" },
];

const PAGE_SIZE = 50;

const StatsPanel = ({ stats }) => {
  const rollup = useMemo(() => {
    const byLang = { bg: 0, ro: 0, en: 0 };
    (stats?.rows || []).forEach((r) => {
      byLang[r.lang] = (byLang[r.lang] || 0) + r.count;
    });
    return byLang;
  }, [stats]);

  if (!stats) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat testId="dict-total" label="Total entries" value={num(stats.total)} />
      <Stat testId="dict-bg" label="Bulgarian" value={num(rollup.bg || 0)} />
      <Stat testId="dict-ro" label="Romanian" value={num(rollup.ro || 0)} />
      <Stat testId="dict-en" label="English" value={num(rollup.en || 0)} />
    </div>
  );
};

/** Editable table row so a wrong translation can be corrected in place. Saved rows
 *  flow straight into `db.translations`; every page that reads the cache picks them
 *  up on the next request without a rebuild. */
const Row = ({ item, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.target || "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const trimmed = value.trim();
    if (!trimmed) {
      toast.error("Translation cannot be empty");
      return;
    }
    if (trimmed === item.target) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await adminDictionaryEdit(item.lang, item._id, trimmed);
      toast.success("Translation updated");
      setEditing(false);
      onSaved({ ...item, target: trimmed });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr
      data-testid={`dict-row-${item._id?.slice(0, 12)}`}
      className="border-b border-border/60 last:border-0"
    >
      <td className="w-[110px] px-3 py-2 text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className="rounded-full bg-muted px-2 py-0.5">{item.type || "—"}</span>
      </td>
      <td className="w-[46px] px-3 py-2 text-[11.5px] font-semibold text-muted-foreground">
        {item.lang}
      </td>
      <td className="max-w-[360px] break-words px-3 py-2 text-[13px] text-foreground">
        {item.source}
      </td>
      <td className="max-w-[420px] px-3 py-2 text-[13px] text-foreground">
        {editing ? (
          <Input
            data-testid="dict-edit-input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-9 rounded-[8px] text-[13px]"
            autoFocus
          />
        ) : (
          <span className="break-words">{item.target}</span>
        )}
      </td>
      <td className="w-[110px] px-3 py-2 text-right">
        {editing ? (
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="dict-cancel"
              onClick={() => { setValue(item.target || ""); setEditing(false); }}
              disabled={busy}
              className="h-8 gap-1 rounded-[8px] px-2 text-[12px]"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              size="sm"
              data-testid="dict-save"
              onClick={save}
              disabled={busy}
              className="h-8 gap-1 rounded-[8px] px-2 text-[12px]"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
              )}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="dict-edit"
            onClick={() => setEditing(true)}
            className="h-8 gap-1 rounded-[8px] px-2 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            Edit
          </Button>
        )}
      </td>
    </tr>
  );
};

export const AdminDictionary = () => {
  const [stats, setStats] = useState(null);
  const [type, setType] = useState("");
  const [lang, setLang] = useState("");
  const [q, setQ] = useState("");
  const [qBuf, setQBuf] = useState("");
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    adminDictionaryStats().then(setStats).catch(() => setStats({ total: 0, rows: [] }));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminDictionaryBrowse({ type, lang, q, limit: PAGE_SIZE, offset });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setItems([]);
      setTotal(0);
      toast.error(e?.response?.data?.detail || "Failed to load dictionary");
    } finally {
      setLoading(false);
    }
  }, [type, lang, q, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Debounce the search input so typing does not fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setQ(qBuf); setOffset(0); }, 250);
    return () => clearTimeout(t);
  }, [qBuf]);

  const patchRow = (updated) => {
    setItems((prev) =>
      (prev || []).map((it) => (it._id === updated._id ? updated : it))
    );
  };

  const pageStart = offset + 1;
  const pageEnd = Math.min(offset + (items?.length || 0), total);

  return (
    <div data-testid="admin-dictionary" className="flex flex-col gap-5">
      <div className="flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
        <h2 className="text-[15px] font-semibold text-foreground">
          Self-learning translation dictionary
        </h2>
      </div>
      <p className="text-[12.5px] text-muted-foreground">
        Every make, model, trim, fuel value and dealer boilerplate line the site has
        ever translated is stored here. The checkout on every page reads from this
        collection first; the LLM is only called when a term has never been seen.
        Correcting a translation below propagates to every future page load — no rebuild.
      </p>

      <StatsPanel stats={stats} />

      <div className="grid gap-3 sm:grid-cols-[minmax(200px,1fr)_140px_120px_100px]">
        <label className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            data-testid="dict-search"
            value={qBuf}
            placeholder="Search source or target…"
            onChange={(e) => setQBuf(e.target.value)}
            className="h-10 rounded-[10px] pl-9 text-[13px]"
          />
        </label>
        <select
          data-testid="dict-filter-type"
          value={type}
          onChange={(e) => { setType(e.target.value); setOffset(0); }}
          className="h-10 rounded-[10px] border border-input bg-card px-3 text-[13px] text-foreground"
        >
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          data-testid="dict-filter-lang"
          value={lang}
          onChange={(e) => { setLang(e.target.value); setOffset(0); }}
          className="h-10 rounded-[10px] border border-input bg-card px-3 text-[13px] text-foreground"
        >
          {LANG_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <Button
          data-testid="dict-refresh"
          variant="outline"
          onClick={load}
          className="h-10 rounded-[10px] text-[13px]"
        >
          Refresh
        </Button>
      </div>

      <div className="rounded-[14px] border border-border bg-card">
        {loading && !items ? (
          <Spinner />
        ) : items && items.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left">
              <thead className="border-b border-border bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-semibold">Type</th>
                  <th className="px-3 py-2 font-semibold">Lang</th>
                  <th className="px-3 py-2 font-semibold">Source (Korean)</th>
                  <th className="px-3 py-2 font-semibold">Translation</th>
                  <th className="w-[110px] px-3 py-2 font-semibold" />
                </tr>
              </thead>
              <tbody data-testid="dict-rows">
                {items.map((item) => (
                  <Row key={item._id} item={item} onSaved={patchRow} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-4 py-6 text-center text-[13px] text-muted-foreground">
            No entries match these filters.
          </p>
        )}

        {total > 0 ? (
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-[12.5px] text-muted-foreground">
            <span data-testid="dict-page-range">
              {pageStart}–{pageEnd} of {num(total)}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="dict-prev"
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="h-8 rounded-[8px] text-[12px]"
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="dict-next"
                disabled={pageEnd >= total || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="h-8 rounded-[8px] text-[12px]"
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default AdminDictionary;
