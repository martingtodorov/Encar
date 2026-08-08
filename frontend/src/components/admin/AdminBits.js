import { Loader2 } from "lucide-react";

const nf = new Intl.NumberFormat("en-GB");

/**
 * Admin timestamps are read in SOFIA, always.
 *
 * These used to be plain `toLocaleString()`, which renders in whatever timezone the device
 * happens to be set to. The office works Sofia hours, so an enquiry that arrived at 17:40
 * showed as 14:40 to anyone looking from another zone — and the owner cannot tell whether a
 * call came inside working hours from a number that lies about it.
 */
export const OFFICE_TZ = "Europe/Sofia";

const stampFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: OFFICE_TZ,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** A date and time as the office reads it. `—` for anything unparseable. */
export const stampSofia = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : stampFmt.format(d);
};

/** A bare day (`2026-08-08`) as the office reads it — never shifted by a UTC boundary. */
export const daySofia = (iso, opts = { day: "numeric", month: "short" }) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T12:00:00Z`);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString("bg-BG", { ...opts, timeZone: OFFICE_TZ });
};

export const Stat = ({ label, value, sub, tone = "default", testId }) => (
  <div
    data-testid={testId}
    className="rounded-[14px] border border-border bg-card px-4 py-3.5 shadow-sm"
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
