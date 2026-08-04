import { useCallback, useEffect, useState } from "react";
import { Loader2, Package, Ship } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { SiteFooter } from "@/components/SiteFooter";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { formatMoney } from "@/lib/format";
import { useSeo } from "@/lib/seo";
import http from "@/lib/api";

const day = (iso, lang) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(lang === "en" ? "en-GB" : lang, {
        day: "2-digit", month: "short", year: "numeric",
      });
};

/**
 * Every car this buyer has held with a deposit.
 *
 * Reads only our OWN archive, never Encar: the whole point of copying the listing at payment
 * time is that a withdrawn ad still has a page and its pictures here. Each car carries the
 * tracking button, which opens the shipment once a bill of lading is assigned.
 */
export default function MyPurchasesPage() {
  const { t, lang, currency, rates } = useApp();
  const { user, loading: authLoading } = useAuth();
  const { go, path } = useLangNav();
  const [rows, setRows] = useState(null);

  useSeo({ lang, title: `${t("purchasesTitle")} \u00b7 Encar`, noindex: true });

  const load = useCallback(async () => {
    try {
      const { data } = await http.get("/purchases");
      setRows(data.items || []);
    } catch (e) {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    if (user) load();
    else if (!authLoading) setRows([]);
  }, [user, authLoading, load]);

  const money = (v) => formatMoney(v, currency, lang, rates);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <HeaderBar />

      <main className="mx-auto w-full max-w-[1080px] flex-1 px-4 py-8 sm:px-6" data-testid="purchases-page">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {t("purchasesTitle")}
        </h1>
        <p className="mt-2 max-w-2xl text-base leading-relaxed text-muted-foreground">
          {t("purchasesBlurb")}
        </p>

        {rows === null ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
          </div>
        ) : rows.length === 0 ? (
          <div
            data-testid="purchases-empty"
            className="mt-8 rounded-[16px] border border-border bg-card px-6 py-12 text-center"
          >
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
              <Package className="h-7 w-7 text-[hsl(var(--primary))]" aria-hidden="true" />
            </div>
            <p className="mx-auto mt-4 max-w-md text-base leading-relaxed text-muted-foreground">
              {t("purchasesEmpty")}
            </p>
            <Button
              data-testid="purchases-browse"
              onClick={() => go("/")}
              className="mt-5 h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
            >
              {t("purchasesBrowse")}
            </Button>
          </div>
        ) : (
          <ul className="mt-7 flex flex-col gap-4" data-testid="purchases-list">
            {rows.map((row) => (
              <li
                key={row.car_id}
                data-testid={`purchase-${row.car_id}`}
                className="overflow-hidden rounded-[16px] border border-border bg-card shadow-sm"
              >
                <div className="flex flex-col gap-4 p-4 sm:flex-row">
                  <div className="w-full shrink-0 overflow-hidden rounded-[12px] bg-muted sm:w-[280px]">
                    {row.photo ? (
                      <img
                        data-testid={`purchase-photo-${row.car_id}`}
                        src={row.photo}
                        alt={row.title}
                        loading="lazy"
                        className="aspect-[16/10] w-full object-cover"
                      />
                    ) : (
                      <div className="flex aspect-[16/10] w-full items-center justify-center text-[12.5px] text-muted-foreground">
                        {t("purchasesArchiving")}
                      </div>
                    )}
                  </div>

                  <div className="flex min-w-0 flex-1 flex-col">
                    <h2 className="text-base font-semibold text-foreground md:text-lg">
                      {row.title}
                    </h2>
                    {row.subtitle && (
                      <div className="mt-0.5 text-[13px] text-muted-foreground">
                        {row.subtitle}
                      </div>
                    )}

                    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px] sm:max-w-sm">
                      <dt className="text-muted-foreground">{t("purchasesDeposit")}</dt>
                      <dd className="tnum text-right font-semibold text-foreground">
                        {money(row.deposit_eur)}
                      </dd>
                      <dt className="text-muted-foreground">{t("purchasesPaidOn")}</dt>
                      <dd className="tnum text-right text-foreground">
                        {day(row.paid_at, lang)}
                      </dd>
                      {row.price_eur ? (
                        <>
                          <dt className="text-muted-foreground">{t("finalPrice")}</dt>
                          <dd className="tnum text-right font-semibold text-foreground">
                            {money(row.price_eur)}
                          </dd>
                        </>
                      ) : null}
                    </dl>

                    <div className="mt-3 text-[12px] text-muted-foreground">
                      {row.archived
                        ? `${t("purchasesArchived")} · ${row.photo_count} ${t("purchasesPhotos")}`
                        : t("purchasesArchiving")}
                    </div>

                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <Button
                        data-testid={`purchase-track-${row.car_id}`}
                        onClick={() =>
                          go(row.ref ? `/track?ref=${row.ref}&by=${row.by || "bol"}` : "/track")
                        }
                        className="h-10 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
                      >
                        <Ship className="h-4 w-4" aria-hidden="true" />
                        {t("purchasesTrack")}
                      </Button>
                      {!row.ref && (
                        <span className="text-[12px] text-muted-foreground">
                          {t("purchasesNoRef")}
                        </span>
                      )}
                      <a
                        href={path(`/car/${row.car_id}`)}
                        data-testid={`purchase-open-${row.car_id}`}
                        className="text-[13px] font-medium text-[hsl(var(--primary))] hover:underline"
                      >
                        {t("viewDetails") || t("purchasesBrowse")}
                      </a>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
