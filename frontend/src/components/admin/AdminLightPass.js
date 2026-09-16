import { useState } from "react";
import { Loader2, Plus, X, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { putLightPass, runLightPass } from "@/lib/api";
import { ago, num, stampSofia } from "@/components/admin/AdminBits";

const ZONES = ["Europe/Sofia", "Europe/Bucharest", "Europe/London", "Asia/Seoul", "UTC"];
const MAX_TIMES = 12;

const formFrom = (l) => ({
  enabled: !!l?.enabled,
  mode: l?.mode === "times" ? "times" : "interval",
  every_min: l?.every_min || 60,
  times: (l?.times?.length ? l.times : ["12:00"]).slice(0, MAX_TIMES),
  tz: l?.tz || ZONES[0],
  max_pages: l?.max_pages || 6,
});

/** The light pass: the top of Encar's newest-first feed, a few requests, as often as you like. */
export const LightPass = ({ light, onChange, fullRunning }) => {
  const [form, setForm] = useState(() => formFrom(light));
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const last = light?.last;

  const save = async () => {
    setSaving(true);
    try {
      const saved = await putLightPass({
        enabled: form.enabled,
        mode: form.mode,
        every_min: Number(form.every_min),
        times: Array.from(new Set(form.times.filter(Boolean))).sort(),
        tz: form.tz,
        max_pages: Number(form.max_pages),
      });
      onChange?.(saved);
      setForm(formFrom(saved));
      toast.success(saved.enabled
        ? (saved.mode === "times"
          ? `Лекият проход ще тръгва в ${saved.times.join(", ")} ${saved.tz}`
          : `Лекият проход ще тръгва на всеки ${saved.every_min} мин`)
        : "Лекият проход е изключен");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Настройката не се запази");
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    try {
      const r = await runLightPass();
      toast[r.started ? "success" : "error"](
        r.started ? "Лекият проход тръгна — отнема под минута" : r.reason || "Не тръгна");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Не тръгна");
    } finally {
      setRunning(false);
    }
  };

  const setTime = (i, v) => setForm((f) => {
    const times = [...f.times];
    times[i] = v;
    return { ...f, times };
  });

  return (
    <div data-testid="admin-light-pass" className="rounded-[14px] border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        <h2 className="text-[15px] font-semibold text-foreground">
          Лек проход през деня
        </h2>
      </div>
      <p className="mt-2 max-w-[70ch] text-[12.5px] text-muted-foreground">
        Encar връща последно променените обяви първи, затова новите коли и новите цени са на
        първите една-две страници. Този проход чете само върха и спира щом страницата не носи
        нищо ново — 2 до 6 заявки вместо ~700. Не маркира продадени коли (за това е нощната
        пълна синхронизация); обяви „под договор“ излизат веднага.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="flex items-center gap-2.5">
          <Switch
            data-testid="light-pass-enabled"
            checked={form.enabled}
            onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
          />
          <span className="text-[13.5px] text-foreground">Включен</span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Кога
          </span>
          <select
            data-testid="light-pass-mode"
            value={form.mode}
            onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value }))}
            className="h-10 rounded-[10px] border border-input bg-card px-3 text-[13.5px] text-foreground"
          >
            <option value="interval">На всеки N минути</option>
            <option value="times">В точно определени часове</option>
          </select>
        </label>

        {form.mode === "interval" ? (
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Интервал (мин)
            </span>
            <Input
              data-testid="light-pass-interval"
              type="number"
              min={5}
              max={1440}
              value={form.every_min}
              onChange={(e) => setForm((f) => ({ ...f, every_min: e.target.value }))}
              className="h-10 w-[110px] rounded-[10px]"
            />
          </label>
        ) : (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Часове (до {MAX_TIMES})
            </span>
            <div data-testid="light-pass-times" className="flex flex-wrap items-center gap-2">
              {form.times.map((t, i) => (
                <div key={i} className="flex items-center gap-1">
                  <Input
                    data-testid={`light-pass-time-${i}`}
                    type="time"
                    value={t}
                    onChange={(e) => setTime(i, e.target.value)}
                    className="h-10 w-[126px] rounded-[10px]"
                  />
                  {form.times.length > 1 ? (
                    <button
                      type="button"
                      data-testid={`light-pass-time-remove-${i}`}
                      onClick={() => setForm((f) => ({
                        ...f, times: f.times.filter((_, k) => k !== i),
                      }))}
                      aria-label={`Премахни ${t}`}
                      className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <X className="h-4 w-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              ))}
              {form.times.length < MAX_TIMES ? (
                <Button
                  type="button"
                  data-testid="light-pass-time-add"
                  variant="outline"
                  onClick={() => setForm((f) => ({ ...f, times: [...f.times, "12:00"] }))}
                  className="h-10 gap-1.5 rounded-[10px] border-border bg-card px-3 text-[13px]"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  Добави час
                </Button>
              ) : null}
            </div>
          </div>
        )}

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Часова зона
          </span>
          <select
            data-testid="light-pass-tz"
            value={form.tz}
            onChange={(e) => setForm((f) => ({ ...f, tz: e.target.value }))}
            className="h-10 rounded-[10px] border border-input bg-card px-3 text-[13.5px] text-foreground"
          >
            {ZONES.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Макс. страници
          </span>
          <Input
            data-testid="light-pass-max-pages"
            type="number"
            min={1}
            max={20}
            value={form.max_pages}
            onChange={(e) => setForm((f) => ({ ...f, max_pages: e.target.value }))}
            className="h-10 w-[100px] rounded-[10px]"
          />
        </label>

        <Button
          data-testid="light-pass-save"
          onClick={save}
          disabled={saving}
          className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
        >
          {saving ? "Запазва…" : "Запази"}
        </Button>

        <Button
          data-testid="light-pass-run"
          variant="outline"
          onClick={runNow}
          disabled={running || light?.running || fullRunning}
          className="h-10 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
        >
          {running || light?.running ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Zap className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {light?.running ? "Върви…" : "Пусни сега"}
        </Button>
      </div>

      <p data-testid="light-pass-next" className="mt-3 text-[12.5px] text-muted-foreground">
        {light?.enabled
          ? (light.mode === "times"
            ? `Тръгва в ${(light.times || []).join(", ")} ${light.tz} · следващ: ${stampSofia(light.next_run_at)}`
            : `Тръгва на всеки ${light.every_min} мин · следващ: ${stampSofia(light.next_run_at)}`)
          : "Изключен — върви само когато го пуснеш ръчно."}
      </p>

      {last ? (
        <p data-testid="light-pass-last" className={`mt-1 text-[12.5px] ${last.ok ? "text-muted-foreground" : "text-destructive"}`}>
          {last.ok
            ? `Последен проход ${ago(last.ran_at)}: ${num(last.pages)} стр., ${num(last.new)} нови, ${num(last.changed)} променени, ${num(last.requests)} заявки за ${Math.round(last.duration_s || 0)}с`
            : `Последен проход ${ago(last.ran_at)} не мина: ${last.error}`}
        </p>
      ) : null}
    </div>
  );
};

export default LightPass;
