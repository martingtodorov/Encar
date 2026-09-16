import { num, stampSofia } from "@/components/admin/AdminBits";

/** Where the gap between Encar's total and our indexed count goes, on every crawl. */
export const SyncCoverage = ({ crawl }) => {
  if (!crawl || !crawl.upstream) return null;
  const reachable = crawl.reachable || 0;
  const indexed = crawl.indexed || 0;
  const pct = reachable ? (indexed / reachable) * 100 : 0;
  const missing = Math.max(reachable - indexed, 0);
  const thin = pct < 99;

  return (
    <div data-testid="sync-coverage" className="rounded-[14px] border border-border bg-card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Покритие на последното обхождане
      </p>
      <p data-testid="sync-coverage-line" className="mt-2 text-[13.5px] text-foreground">
        {num(crawl.upstream)} в Encar
        {" − "}{num(crawl.excluded)} лизинг/рент/под договор/заглушки
        {" = "}{num(reachable)} за внос
        {" · "}
        <span className={thin ? "font-semibold text-destructive" : "font-semibold text-foreground"}>
          {num(indexed)} индексирани ({pct.toFixed(2)}%)
        </span>
      </p>
      {thin ? (
        <p data-testid="sync-coverage-warn" className="mt-2 text-[12.5px] text-destructive">
          {num(missing)} коли не влязоха. Encar сортира по дата на промяна и прозорецът се
          мести, докато теглим — {num(crawl.short_leaves || 0)} среза върнаха по-малко редове,
          отколкото обещаха
          {crawl.dropped_no_price ? `, ${num(crawl.dropped_no_price)} обяви дойдоха без цена` : ""}
          {crawl.dropped_no_id ? `, ${num(crawl.dropped_no_id)} без номер` : ""}.
        </p>
      ) : (
        <p data-testid="sync-coverage-ok" className="mt-2 text-[12.5px] text-muted-foreground">
          Разликата спрямо числото на Encar е умишлена — тези коли не могат да се изнесат.
          {crawl.short_leaves ? ` ${num(crawl.short_leaves)} среза върнаха по-малко редове от обещаното.` : ""}
        </p>
      )}
      <p data-testid="sync-coverage-meta" className="mt-2 text-[12px] text-muted-foreground">
        {num(crawl.leaves)} среза, {num(crawl.probes)} сонди
        {crawl.retired != null ? ` · ${num(crawl.retired)} продадени извадени` : ""}
        {crawl.finished_at ? ` · ${stampSofia(crawl.finished_at)}` : ""}
      </p>
      {crawl.retire_skipped ? (
        <p data-testid="sync-coverage-retire" className="mt-2 text-[12.5px] text-destructive">
          Изваждането на продадените беше отказано: {crawl.retire_skip_reason}
        </p>
      ) : null}
    </div>
  );
};

export default SyncCoverage;
