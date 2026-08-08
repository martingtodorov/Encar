import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  adminRecoDefaults,
  adminResetRecoDefaults,
  adminSaveRecoDefaults,
  getTaxonomy,
} from "@/lib/api";
import { Spinner } from "@/components/admin/AdminBits";

/**
 * The shelf a visitor we know nothing about sees first.
 *
 * Picks are stored as Encar's OWN values, so the dropdowns here send the value and only show
 * the English label. `Trim contains` is a substring of Encar's trim string, which is how one
 * pick can be "the C63 versions of the W205" rather than every C-class.
 */

const Row = ({ pick, onChange, onRemove, lang }) => {
  const [models, setModels] = useState([]);

  useEffect(() => {
    if (!pick.make) {
      setModels([]);
      return;
    }
    let alive = true;
    getTaxonomy({ level: 2, make: pick.make, lang })
      .then((d) => alive && setModels(d.items || []))
      .catch(() => alive && setModels([]));
    return () => {
      alive = false;
    };
  }, [pick.make, lang]);

  const dead = pick.available === 0;

  return (
    <tr data-testid={`reco-row-${pick.key}`} className="border-t border-border align-middle">
      <td className="py-2 pr-3 text-[13px] text-muted-foreground">{pick.rank || "—"}</td>
      <td className="py-2 pr-3">
        <div className="text-[13px] font-medium text-foreground">{pick.make_label}</div>
      </td>
      <td className="py-2 pr-3">
        <select
          data-testid={`reco-model-${pick.key}`}
          value={pick.model}
          onChange={(e) => onChange({ ...pick, model: e.target.value })}
          className="h-9 w-[220px] rounded-[8px] border border-border bg-background px-2 text-[13px]"
        >
          <option value={pick.model}>{pick.model_label || pick.model}</option>
          {models
            .filter((m) => m.value !== pick.model)
            .map((m) => (
              <option key={m.value} value={m.value}>
                {`${m.label} (${m.count})`}
              </option>
            ))}
        </select>
      </td>
      <td className="py-2 pr-3">
        <Input
          data-testid={`reco-badge-${pick.key}`}
          value={pick.badge}
          placeholder="any trim"
          onChange={(e) => onChange({ ...pick, badge: e.target.value })}
          className="h-9 w-[150px] bg-background text-[13px]"
        />
      </td>
      <td className={`tnum py-2 pr-3 text-right text-[13px] ${dead ? "text-destructive" : "text-foreground"}`}>
        {pick.available}
      </td>
      <td className="tnum py-2 pr-3 text-right text-[13px] text-muted-foreground">
        {pick.impressions}
      </td>
      <td className="tnum py-2 pr-3 text-right text-[13px] text-muted-foreground">
        {pick.clicks}
      </td>
      <td className="tnum py-2 pr-3 text-right text-[13px] font-semibold text-foreground">
        {pick.ctr}%
      </td>
      <td className="tnum py-2 pr-3 text-right text-[13px] font-semibold text-[hsl(var(--primary))]">
        {pick.deposits}
      </td>
      <td className="tnum py-2 pr-3 text-right text-[13px]">
        {pick.judged ? (
          <span className="font-semibold text-foreground">{pick.score}</span>
        ) : (
          <span
            className="text-muted-foreground"
            title="Not enough impressions yet to judge this pick fairly"
          >
            —
          </span>
        )}
      </td>
      <td className="py-2 text-right">
        <button
          type="button"
          data-testid={`reco-remove-${pick.key}`}
          onClick={onRemove}
          className="rounded-[8px] p-2 text-muted-foreground hover:text-destructive"
          aria-label="Remove"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </td>
    </tr>
  );
};

const AddPick = ({ lang, onAdd }) => {
  const [makes, setMakes] = useState([]);
  const [make, setMake] = useState("");
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [badge, setBadge] = useState("");

  useEffect(() => {
    getTaxonomy({ level: 1, lang })
      .then((d) => setMakes(d.items || []))
      .catch(() => setMakes([]));
  }, [lang]);

  useEffect(() => {
    setModel("");
    if (!make) {
      setModels([]);
      return;
    }
    let alive = true;
    getTaxonomy({ level: 2, make, lang })
      .then((d) => alive && setModels(d.items || []))
      .catch(() => alive && setModels([]));
    return () => {
      alive = false;
    };
  }, [make, lang]);

  return (
    <div
      data-testid="reco-add"
      className="flex flex-wrap items-end gap-3 rounded-[12px] border border-dashed border-border p-4"
    >
      <div className="flex flex-col gap-1.5">
        <Label className="text-[12px] font-medium">Make</Label>
        <select
          data-testid="reco-add-make"
          value={make}
          onChange={(e) => setMake(e.target.value)}
          className="h-9 w-[190px] rounded-[8px] border border-border bg-background px-2 text-[13px]"
        >
          <option value="">Pick a make…</option>
          {makes.map((m) => (
            <option key={m.value} value={m.value}>
              {`${m.label} (${m.count})`}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label className="text-[12px] font-medium">Model</Label>
        <select
          data-testid="reco-add-model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={!make}
          className="h-9 w-[230px] rounded-[8px] border border-border bg-background px-2 text-[13px] disabled:opacity-50"
        >
          <option value="">Pick a model…</option>
          {models.map((m) => (
            <option key={m.value} value={m.value}>
              {`${m.label} (${m.count})`}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label className="text-[12px] font-medium">Trim contains</Label>
        <Input
          data-testid="reco-add-badge"
          value={badge}
          placeholder="e.g. M40i"
          onChange={(e) => setBadge(e.target.value)}
          className="h-9 w-[150px] bg-background text-[13px]"
        />
      </div>
      <Button
        type="button"
        data-testid="reco-add-save"
        disabled={!make || !model}
        onClick={() => {
          onAdd({ make, model, badge: badge.trim() });
          setMake("");
          setModel("");
          setBadge("");
        }}
        className="h-9 gap-2 rounded-[9px] text-[13px]"
      >
        <Plus className="h-4 w-4" />
        Add pick
      </Button>
    </div>
  );
};

export const AdminRecommendations = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");
  const lang = "en";

  const load = useCallback(() => {
    adminRecoDefaults()
      .then(setData)
      .catch(() => setData({ enabled: true, picks: [] }));
  }, []);

  useEffect(load, [load]);

  const save = async (next) => {
    setBusy("save");
    try {
      await adminSaveRecoDefaults({
        enabled: next.enabled,
        auto_rank: next.auto_rank,
        min_impressions: Number(next.min_impressions) || 1,
        picks: next.picks.map((p) => ({ make: p.make, model: p.model, badge: p.badge || "" })),
      });
      toast.success("Default shelf saved");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy("");
    }
  };

  const reset = async (stats) => {
    if (
      !window.confirm(
        stats ? "Clear every impression, click and deposit count?" : "Go back to the built-in seven cars?"
      )
    )
      return;
    setBusy(stats ? "stats" : "reset");
    try {
      await adminResetRecoDefaults(stats);
      toast.success(stats ? "Counters cleared" : "Back to the built-in picks");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not reset");
    } finally {
      setBusy("");
    }
  };

  if (!data) return <Spinner />;

  const set = (picks) => setData((p) => ({ ...p, picks }));
  const totals = data.picks.reduce(
    (a, p) => ({
      impressions: a.impressions + p.impressions,
      clicks: a.clicks + p.clicks,
      deposits: a.deposits + p.deposits,
    }),
    { impressions: 0, clicks: 0, deposits: 0 }
  );

  return (
    <div data-testid="admin-recommendations" className="flex flex-col gap-5">
      <div className="rounded-[14px] border border-border bg-card p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[620px]">
            <h2 className="text-[15px] font-semibold text-foreground">
              First impression: the shelf a brand-new visitor sees
            </h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
              Somebody arriving with no history at all gets these cars under “Picked for you”.
              Switch it off and they see the most opened ads of the fortnight instead. The
              moment a visitor looks at anything, their own taste takes over.
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <Label className="text-[12.5px] font-medium">
              {data.enabled ? "On" : "Off"}
            </Label>
            <Switch
              data-testid="reco-enabled"
              checked={data.enabled}
              onCheckedChange={(v) => {
                const next = { ...data, enabled: v };
                setData(next);
                save(next);
              }}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 rounded-[12px] border border-border bg-background p-3.5">
          <div className="flex items-center gap-2.5">
            <Switch
              data-testid="reco-auto-rank"
              checked={data.auto_rank}
              onCheckedChange={(v) => {
                const next = { ...data, auto_rank: v };
                setData(next);
                save(next);
              }}
            />
            <Label className="text-[13px] font-medium">Order by results automatically</Label>
          </div>
          <div className="flex items-center gap-2">
            <Label className="text-[12.5px] text-muted-foreground">
              Not judged below
            </Label>
            <Input
              data-testid="reco-min-impressions"
              type="number"
              min={1}
              value={data.min_impressions}
              onChange={(e) => setData((p) => ({ ...p, min_impressions: e.target.value }))}
              className="h-9 w-[90px] bg-card text-[13px]"
            />
            <Label className="text-[12.5px] text-muted-foreground">impressions</Label>
          </div>
          <p className="max-w-[520px] text-[12px] leading-relaxed text-muted-foreground">
            Score is <span className="font-medium text-foreground">deposits × 10 + CTR</span> — a
            reservation is real proof, a click is only interest. A pick that has not been shown
            enough yet is not judged at all: it keeps its place and keeps collecting numbers,
            so one lucky click can never win the front row.
          </p>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead>
              <tr className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-3">#</th>
                <th className="pb-2 pr-3">Make</th>
                <th className="pb-2 pr-3">Model</th>
                <th className="pb-2 pr-3">Trim contains</th>
                <th className="pb-2 pr-3 text-right">In stock</th>
                <th className="pb-2 pr-3 text-right">Shown</th>
                <th className="pb-2 pr-3 text-right">Opened</th>
                <th className="pb-2 pr-3 text-right">CTR</th>
                <th className="pb-2 pr-3 text-right">Deposits</th>
                <th className="pb-2 pr-3 text-right">Score</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {data.picks.map((p, i) => (
                <Row
                  key={p.key}
                  pick={p}
                  lang={lang}
                  onChange={(next) =>
                    set(data.picks.map((row, n) => (n === i ? next : row)))
                  }
                  onRemove={() => save({ ...data, picks: data.picks.filter((_, n) => n !== i) })}
                />
              ))}              {!data.picks.length && (
                <tr className="border-t border-border">
                  <td colSpan={11} className="py-6 text-center text-[13px] text-muted-foreground">
                    No picks yet — the popular list is being shown instead.
                  </td>
                </tr>
              )}
            </tbody>
            {data.picks.length > 0 && (
              <tfoot>
                <tr className="border-t border-border text-[12.5px] font-semibold text-foreground">
                  <td className="py-2 pr-3" colSpan={5}>
                    All picks
                  </td>
                  <td className="tnum py-2 pr-3 text-right">{totals.impressions}</td>
                  <td className="tnum py-2 pr-3 text-right">{totals.clicks}</td>
                  <td className="tnum py-2 pr-3 text-right">
                    {totals.impressions
                      ? `${Math.round((totals.clicks / totals.impressions) * 1000) / 10}%`
                      : "0%"}
                  </td>
                  <td className="tnum py-2 pr-3 text-right">{totals.deposits}</td>
                  <td />
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>

        <p className="mt-3 text-[12px] text-muted-foreground">
          “Shown” counts one impression per pick each time the shelf is built, “Opened” a car
          from it being clicked, and “Deposits” the reservations those cars have earned — the
          combination with the best CTR and deposit count is the one keeping people here.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            data-testid="reco-save"
            onClick={() => save(data)}
            disabled={!!busy}
            className="h-10 gap-2 rounded-[10px]"
          >
            {busy === "save" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save the shelf
          </Button>
          <Button
            variant="outline"
            data-testid="reco-reset"
            onClick={() => reset(false)}
            disabled={!!busy}
            className="h-10 gap-2 rounded-[10px]"
          >
            {busy === "reset" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}
            Back to the built-in seven
          </Button>
          <Button
            variant="outline"
            data-testid="reco-reset-stats"
            onClick={() => reset(true)}
            disabled={!!busy}
            className="h-10 gap-2 rounded-[10px] text-destructive"
          >
            {busy === "stats" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Clear the counters
          </Button>
        </div>
      </div>

      <AddPick lang={lang} onAdd={(p) => save({ ...data, picks: [...data.picks, p] })} />
    </div>
  );
};

export default AdminRecommendations;
