import { useEffect, useState } from "react";
import { Layers, Check, Undo2 } from "lucide-react";
import {
  deleteTaxonomyOverride,
  getRawTaxonomy,
  getTaxonomyOverrides,
  saveTaxonomyOverride,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner, num } from "@/components/admin/AdminBits";

const Select = ({ value, onChange, items, placeholder, testId }) => (
  <select
    data-testid={testId}
    value={value}
    onChange={(e) => onChange(e.target.value)}
    className="h-10 w-full rounded-[10px] border border-input bg-card px-3 text-[13px] text-foreground"
  >
    <option value="">{placeholder}</option>
    {items.map((i) => (
      <option key={i.value} value={i.value}>
        {i.label} ({i.count})
      </option>
    ))}
  </select>
);

/** Rename Encar's model and trim names, or fold near-duplicates into one entry. */
export const AdminTaxonomy = () => {
  const [makes, setMakes] = useState([]);
  const [models, setModels] = useState([]);
  const [rows, setRows] = useState(null);
  const [overrides, setOverrides] = useState([]);
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState("");

  const level = model ? 3 : 2;

  const reloadOverrides = () => getTaxonomyOverrides().then(setOverrides).catch(() => {});

  useEffect(() => {
    getRawTaxonomy({ level: 1 }).then((d) => setMakes(d.items)).catch(() => setMakes([]));
    reloadOverrides();
  }, []);

  useEffect(() => {
    setModel("");
    if (!make) {
      setModels([]);
      return;
    }
    getRawTaxonomy({ level: 2, make }).then((d) => setModels(d.items)).catch(() => setModels([]));
  }, [make]);

  const loadRows = () => {
    if (!make) {
      setRows(null);
      return;
    }
    setRows(null);
    getRawTaxonomy({ level, make, model })
      .then((d) => setRows(d.items))
      .catch(() => setRows([]));
  };

  useEffect(loadRows, [make, model]);

  const save = async (row, patch) => {
    setBusy(row.value);
    try {
      await saveTaxonomyOverride({ level, make, model, value: row.value, ...patch });
      setDraft((d) => ({ ...d, [row.value]: {} }));
      loadRows();
      await reloadOverrides();
      if (level === 2) {
        getRawTaxonomy({ level: 2, make }).then((d) => setModels(d.items)).catch(() => {});
      }
    } finally {
      setBusy("");
    }
  };

  const undo = async (id) => {
    setBusy(id);
    try {
      await deleteTaxonomyOverride(id);
      loadRows();
      await reloadOverrides();
    } finally {
      setBusy("");
    }
  };

  const mine = overrides.filter((o) => o.level === level && (!make || o.make === make));

  return (
    <div
      data-testid="admin-taxonomy"
      className="rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <Layers className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        Models &amp; trims
      </h2>
      <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">
        Encar lists the same car under several names — "M2 Coupe", "M2 Coupe M Performance
        Steering Wheel Edition", "M2 Black Shadow". Rename what reads badly, or merge the
        duplicates into one entry: buyers then see a single option and it returns every car.
        Nothing is deleted, so any change can be undone.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Select
          testId="taxonomy-admin-make"
          value={make}
          onChange={setMake}
          items={makes}
          placeholder="Pick a make…"
        />
        <Select
          testId="taxonomy-admin-model"
          value={model}
          onChange={setModel}
          items={models}
          placeholder="All models (edit model names)"
        />
      </div>

      {!make ? (
        <p className="mt-4 text-[12.5px] text-muted-foreground">
          Pick a make to edit its model names, then a model to edit its trims.
        </p>
      ) : rows === null ? (
        <Spinner />
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-3 font-medium">{level === 2 ? "Model" : "Trim"}</th>
                <th className="pb-2 pr-3 font-medium">Cars</th>
                <th className="pb-2 pr-3 font-medium">Rename to</th>
                <th className="pb-2 font-medium">Merge into</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const d = draft[r.value] || {};
                return (
                  <tr
                    key={r.value}
                    data-testid={`taxonomy-row-${r.slug || r.value}`}
                    className="border-b border-border/60 align-middle"
                  >
                    <td className="py-2 pr-3">
                      <div className="text-[13px] text-foreground">{r.label}</div>
                      {r.merged_into ? (
                        <div className="text-[12px] text-[hsl(var(--primary))]">
                          merged away
                        </div>
                      ) : null}
                    </td>
                    <td className="tnum py-2 pr-3 text-[13px] text-muted-foreground">
                      {num(r.count)}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1.5">
                        <Input
                          data-testid={`taxonomy-rename-${r.slug || r.value}`}
                          value={d.label ?? ""}
                          onChange={(e) =>
                            setDraft((s) => ({ ...s, [r.value]: { ...d, label: e.target.value } }))
                          }
                          placeholder={r.label}
                          className="h-9 text-[13px]"
                        />
                        <Button
                          data-testid={`taxonomy-rename-save-${r.slug || r.value}`}
                          variant="outline"
                          disabled={!d.label || busy === r.value}
                          onClick={() => save(r, { label: d.label })}
                          className="h-9 w-9 shrink-0 p-0"
                          aria-label="Save name"
                        >
                          <Check className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </div>
                    </td>
                    <td className="py-2">
                      <select
                        data-testid={`taxonomy-merge-${r.slug || r.value}`}
                        value=""
                        disabled={busy === r.value}
                        onChange={(e) => e.target.value && save(r, { target: e.target.value })}
                        className="h-9 w-full rounded-[10px] border border-input bg-card px-2 text-[13px] text-foreground"
                      >
                        <option value="">—</option>
                        {rows
                          .filter((o) => o.value !== r.value && !o.merged_into)
                          .map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {mine.length > 0 && (
        <div className="mt-6 border-t border-border pt-4">
          <h3 className="text-[13px] font-semibold text-foreground">In force</h3>
          <ul className="mt-2 space-y-1.5">
            {mine.map((o) => (
              <li
                key={o.id}
                data-testid={`taxonomy-override-${o.id}`}
                className="flex items-center justify-between gap-3 text-[12.5px] text-muted-foreground"
              >
                <span>
                  <span className="text-foreground">{o.value_label}</span>
                  {o.target ? ` → merged into ${o.target_label}` : ` → renamed "${o.label}"`}
                </span>
                <Button
                  data-testid={`taxonomy-undo-${o.id}`}
                  variant="ghost"
                  disabled={busy === o.id}
                  onClick={() => undo(o.id)}
                  className="h-8 gap-1.5 px-2 text-[12.5px]"
                >
                  <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Undo
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default AdminTaxonomy;
