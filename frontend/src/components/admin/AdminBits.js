import { Loader2 } from "lucide-react";

const nf = new Intl.NumberFormat("en-GB");

export const Stat = ({ label, value, sub, tone = "default", testId }) => (
  <div
    data-testid={testId}
    className="rounded-[14px] border border-border bg-card px-4 py-3.5 shadow-[var(--shadow-sm)]"
  >
    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {label}
    </div>
    <div
      className={`tnum mt-1.5 text-[22px] font-semibold leading-none ${
        tone === "warn"
          ? "text-destructive"
          : tone === "good"
            ? "text-[hsl(var(--success))]"
            : "text-foreground"
      }`}
    >
      {typeof value === "number" ? nf.format(value) : value}
    </div>
    {sub ? <div className="mt-1.5 text-[12px] text-muted-foreground">{sub}</div> : null}
  </div>
);

export const Spinner = () => (
  <div className="flex justify-center py-16">
    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
  </div>
);

export const num = (v) => (typeof v === "number" ? nf.format(v) : "—");

export const ago = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};
