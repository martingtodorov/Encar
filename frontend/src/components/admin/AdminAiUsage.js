import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Cpu, Loader2, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { getAiUsage, sendAiReport, setAiBudget } from "@/lib/api";
import { daySofia, stampSofia } from "@/components/admin/AdminBits";

const RANGES = [
  { days: 7, label: "7 дни" },
  { days: 30, label: "30 дни" },
  { days: 90, label: "90 дни" },
];

const KIND_LABELS = {
  description: "Описания на автомобили",
  labels: "Етикети и спецификации",
  latin: "Марки и модели (латиница)",
  always: "Марки и модели",
  spec: "Спецификации",
  manufacturer: "Марки (прегряване)",
  model: "Модели (прегряване)",
  badge: "Версии (прегряване)",
  badge_detail: "Подверсии (прегряване)",
  fuel_type: "Гориво (прегряване)",
  region: "Регион (прегряване)",
  other: "Друго",
};

// Cents matter here: a day of translation can genuinely cost $0.004, and rounding that
// to $0.00 makes the whole screen look broken.
const usd = (n) => {
  const v = Number(n || 0);
  const digits = v > 0 && v < 1 ? 4 : 2;
  return `$${new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)}`;
};
const fmt = (n) => new Intl.NumberFormat("bg-BG").format(n || 0);
const tok = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : fmt(n));

/**
 * What the translation engine costs, and which part of the site is spending it.
 *
 * Chart drawn by hand for the same reason as the traffic one: no charting library ends up
 * in a visitor's bundle for a screen only the owner opens.
 */
export const AdminAiUsage = () => {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [limit, setLimit] = useState("");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const got = await getAiUsage(days);
      setData(got);
      setLimit(String(got.budget_usd ?? ""));
    } finally {
      setBusy(false);
    }
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  const saveLimit = async () => {
    setSaving(true);
    try {
      const got = await setAiBudget(limit);
      setLimit(String(got.daily_usd));
      toast.success(`Дневният лимит е $${got.daily_usd}`);
    } catch {
      toast.error("Лимитът не беше запазен");
    } finally {
      setSaving(false);
    }
  };

  const sendNow = async () => {
    setSending(true);
    try {
      await sendAiReport();
      toast.success("Отчетът е изпратен на собственика");
      await load();
    } catch {
      toast.error("Отчетът не беше изпратен");
    } finally {
      setSending(false);
    }
  };

  const series = data?.series || [];
  const peak = Math.max(0.000001, ...series.map((r) => r.cost));
  const perDay = series.length ? (data?.period?.cost || 0) / series.length : 0;

  return (
    <section data-testid="admin-ai-usage" className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Cpu className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
            AI разходи
          </h2>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            Всяко извикване към езиковия модел се записва с моделa, изразходваните токени и
            причината за него. Сумите са по официалните тарифи и са ориентир, не фактура.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              data-testid={`ai-range-${r.days}`}
              onClick={() => setDays(r.days)}
              className={`h-9 rounded-[9px] px-3 text-[12.5px] font-medium transition-colors ${
                days === r.days
                  ? "bg-[hsl(var(--primary))] text-primary-foreground"
                  : "border border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.label}
            </button>
          ))}
          <Button
            variant="outline"
            data-testid="ai-reload"
            onClick={load}
            className="h-9 gap-1.5 rounded-[9px] text-[12.5px]"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Обнови
          </Button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat testId="ai-stat-today" accent label="Днес"
              value={usd(data?.today?.cost)}
              hint={`${fmt(data?.today?.calls)} извиквания`} />
        <Stat testId="ai-stat-week" label="Последните 7 дни"
              value={usd(data?.week?.cost)}
              hint={`${fmt(data?.week?.calls)} извиквания`} />
        <Stat testId="ai-stat-month" label="Последните 30 дни"
              value={usd(data?.month?.cost)}
              hint={`${fmt(data?.month?.calls)} извиквания`} />
        <Stat testId="ai-stat-avg" label="Средно на ден"
              value={usd(perDay)}
              hint={`${tok(data?.period?.in_tokens)} вход · ${tok(data?.period?.out_tokens)} изход`} />
      </div>

      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[13px] font-semibold text-foreground">Разход по дни</span>
          <span className="tnum text-[12px] text-muted-foreground">
            {usd(data?.period?.cost)} за периода
            {data?.period?.failed ? ` · ${fmt(data.period.failed)} неуспешни` : ""}
          </span>
        </div>
        {series.every((r) => !r.calls) ? (
          <p data-testid="ai-empty" className="py-8 text-center text-[13px] text-muted-foreground">
            Още няма записани извиквания за този период.
          </p>
        ) : (
          <div data-testid="ai-chart" className="flex h-[180px] items-end gap-[3px]">
            {series.map((r) => (
              <div key={r.day} className="group relative flex h-full flex-1 items-end">
                <div
                  className="w-full rounded-t-[3px] bg-[hsl(var(--primary))] transition-colors group-hover:bg-[hsl(var(--primary))]/70"
                  style={{ height: `${Math.max(2, (r.cost / peak) * 100)}%` }}
                />
                <span className="pointer-events-none absolute -top-1 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-[6px] bg-foreground px-2 py-1 text-[11px] font-medium text-background group-hover:block">
                  {daySofia(r.day)}: {usd(r.cost)} · {fmt(r.calls)} извиквания
                  {r.billed != null ? ` · фактурирано ${usd(r.billed)}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Table
          testId="ai-by-kind"
          title="За какво се плаща"
          rows={(data?.by_kind || []).map((r) => ({
            key: r.kind,
            label: KIND_LABELS[r.kind] || r.kind,
            cost: r.cost,
            calls: r.calls,
            tokens: r.in_tokens + r.out_tokens,
          }))}
        />
        <Table
          testId="ai-by-model"
          title="По модел"
          rows={(data?.by_model || []).map((r) => ({
            key: r.model,
            label: r.model,
            cost: r.cost,
            calls: r.calls,
            tokens: r.in_tokens + r.out_tokens,
          }))}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat testId="ai-cache-phrases" label="Фрази в кеша"
              value={fmt(data?.cache?.phrases)} hint="преведени еднократно, завинаги" />
        <Stat testId="ai-cache-desc" label="Кеширани описания"
              value={fmt(data?.cache?.descriptions)} hint="второ отваряне = 0 токена" />
        <Stat testId="ai-cache-lines" label="Кеширани редове"
              value={fmt(data?.cache?.description_lines)}
              hint="повтарящи се дилърски редове" />
      </div>

      {data && data.budget_usd && (data.today?.cost || 0) >= data.budget_usd ? (
        <div
          data-testid="ai-budget-banner"
          className="flex items-start gap-2.5 rounded-[12px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[12.5px] text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Днешният разход е {usd(data.today.cost)} — над дневния лимит от{" "}
            {usd(data.budget_usd)}. Предупреждение е изпратено на собственика.
          </span>
        </div>
      ) : null}

      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <span className="text-[13px] font-semibold text-foreground">
              Реално фактурирано от Anthropic
            </span>
            <p className="mt-1 text-[12px] text-muted-foreground">
              {data?.billing?.available
                ? `${usd(data.billing.period)} за периода · днес ${usd(data.billing.today)}`
                : "Няма Admin ключ (ANTHROPIC_ADMIN_KEY) — показва се само нашата калкулация."}
            </p>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-[11.5px] text-muted-foreground">Дневен лимит ($)</span>
              <Input
                data-testid="ai-budget-input"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
                inputMode="decimal"
                className="h-9 w-[110px] rounded-[9px] text-[13px]"
              />
            </label>
            <Button
              data-testid="ai-budget-save"
              onClick={saveLimit}
              disabled={saving}
              className="h-9 rounded-[9px] text-[12.5px]"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Запази"}
            </Button>
            <Button
              variant="outline"
              data-testid="ai-report-send"
              onClick={sendNow}
              disabled={sending}
              className="h-9 gap-1.5 rounded-[9px] text-[12.5px]"
            >
              {sending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Mail className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Изпрати отчет сега
            </Button>
          </div>
        </div>
        <p className="mt-3 text-[11.5px] text-muted-foreground">
          Отчетът тръгва автоматично всяка вечер в 21:00 (София) към собственика. Ако дневният
          разход мине лимита, веднага идва отделно предупреждение.
        </p>
      </div>

      {data?.reports?.length ? (
        <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
          <span className="text-[13px] font-semibold text-foreground">Дневни отчети</span>
          <ul data-testid="ai-reports" className="mt-3 flex flex-col gap-2">
            {data.reports.map((r) => (
              <li key={r.day} className="flex items-center justify-between gap-3 text-[12.5px]">
                <span className="text-foreground">{daySofia(r.day)}</span>
                <span className="tnum text-muted-foreground">
                  {usd(r.cost_est)}
                  {r.cost_billed != null ? ` · фактурирано ${usd(r.cost_billed)}` : ""}
                  {" · "}
                  {fmt(r.calls)} изв.
                  {r.alerted ? " · над лимита" : ""}
                  {r.emailed ? " · изпратен" : " · неизпратен"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {data?.breaker?.open ? (
        <div
          data-testid="ai-breaker"
          className="flex items-start gap-2.5 rounded-[12px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[12.5px] text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Преводите са спрени временно ({data.breaker.retry_in_s}s): {data.breaker.reason}
          </span>
        </div>
      ) : null}

      {data?.errors?.length ? (
        <div className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
          <span className="text-[13px] font-semibold text-foreground">Последни грешки</span>
          <ul data-testid="ai-errors" className="mt-3 flex flex-col gap-2">
            {data.errors.map((e, i) => (
              <li key={`${e.at}-${i}`} className="text-[12px]">
                <span className="tnum text-muted-foreground">{stampSofia(e.at)}</span>
                <span className="mx-2 text-muted-foreground">·</span>
                <span className="text-foreground">{e.provider} {e.model}</span>
                <span className="mx-2 text-muted-foreground">·</span>
                <span className="text-destructive">{e.error}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
};

const Table = ({ title, rows, testId }) => (
  <div data-testid={testId} className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
    <span className="text-[13px] font-semibold text-foreground">{title}</span>
    {rows.length ? (
      <ul className="mt-3 flex flex-col gap-2">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center justify-between gap-3 text-[12.5px]">
            <span className="truncate text-foreground">{r.label}</span>
            <span className="tnum shrink-0 text-muted-foreground">
              {usd(r.cost)} · {fmt(r.calls)} изв. · {tok(r.tokens)} ток.
            </span>
          </li>
        ))}
      </ul>
    ) : (
      <p className="py-6 text-center text-[12.5px] text-muted-foreground">Няма данни.</p>
    )}
  </div>
);

const Stat = ({ label, value, hint, accent, testId }) => (
  <div
    data-testid={testId}
    className={`rounded-[12px] border p-3.5 ${
      accent
        ? "border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/5"
        : "border-border bg-card"
    }`}
  >
    <div className="text-[11.5px] font-medium text-muted-foreground">{label}</div>
    <div className="tnum mt-1 text-[22px] font-semibold leading-none text-foreground">{value}</div>
    {hint ? <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div> : null}
  </div>
);

export default AdminAiUsage;
