import { useEffect, useState } from "react";
import { Heart, ExternalLink, Gauge, Calendar, Fuel, Cog } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { useApp } from "@/context/AppContext";
import { useGate } from "@/components/SignInGate";
import { getQuote } from "@/lib/api";
import {
  carSubtitle,
  carTitle,
  formatMileage,
  formatMoney,
  formatNumber,
  formatYearMonth,
} from "@/lib/format";

const Row = ({ label, value, strong, muted, testId }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5">
    <span className={`text-[13px] ${muted ? "text-muted-foreground" : "text-muted-foreground"}`}>{label}</span>
    <span
      data-testid={testId}
      className={`tnum text-right text-[13px] ${
        strong ? "text-[15px] font-semibold text-foreground" : "text-foreground"
      }`}
    >
      {value}
    </span>
  </div>
);

export const QuickViewDialog = ({ car, open, onOpenChange }) => {
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();
  const { requireAccount } = useGate();
  const [quote, setQuote] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !car?.price_krw) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getQuote(car.price_krw)
      .then((q) => !cancelled && setQuote(q))
      .catch(() => !cancelled && setQuote(null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, car]);

  if (!car) return null;
  const saved = isFavourite(car.id);
  const money = (v) => formatMoney(v, currency, lang, rates);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="quick-view-dialog"
        className="max-h-[92vh] max-w-3xl overflow-y-auto bg-card p-0"
      >
        <DialogHeader className="space-y-1 border-b border-border px-5 py-4 text-left">
          <DialogTitle className="pr-8 text-[18px] font-semibold leading-snug text-foreground">
            {carTitle(car)}
          </DialogTitle>
          <DialogDescription className="text-[13px] text-muted-foreground">
            {carSubtitle(car) || t("quickView")}
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 py-4">
          <div className="aspect-[16/10] w-full overflow-hidden rounded-[14px] border border-border">
            <ImageWithFallback
              src={car.image}
              alt={carTitle(car)}
              testId="quick-view-image"
            />
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <h4 className="mb-2 text-[13px] font-semibold text-foreground">{t("specs")}</h4>
              <div className="rounded-[12px] border border-border bg-muted px-3 py-2">
                <Row
                  label={t("year")}
                  value={formatYearMonth(car.year_month, car.form_year)}
                />
                <Row label={t("mileage")} value={formatMileage(car.mileage, lang, t("km"))} />
                {(car.fuel_type_t || car.fuel_type) && (
                  <Row label={t("fuel")} value={car.fuel_type_t || car.fuel_type} />
                )}
                {car.transmission && (
                  <Row
                    label={t("transmission")}
                    value={t(car.transmission === "manual" ? "manual" : "auto")}
                  />
                )}
                {car.photo_count ? (
                  <Row label={t("photos")} value={formatNumber(car.photo_count, lang)} muted />
                ) : null}
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {car.diagnosed && (
                  <Badge className="rounded-full border-0 bg-[hsl(var(--warning-soft))] px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--accent))] hover:bg-[hsl(var(--warning-soft))]">
                    {t("diagnosed")}
                  </Badge>
                )}
                {car.has_inspection && (
                  <Badge className="rounded-full border-0 bg-secondary px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--primary))] hover:bg-secondary">
                    {t("inspected")}
                  </Badge>
                )}
                {car.has_record && (
                  <Badge className="rounded-full border-0 bg-[hsl(var(--success-soft))] px-2 py-0.5 text-[11px] font-medium text-[hsl(var(--success))] hover:bg-[hsl(var(--success-soft))]">
                    {t("insured")}
                  </Badge>
                )}
              </div>
            </div>

            <div>
              <h4 className="mb-2 text-[13px] font-semibold text-foreground">
                {t("priceBreakdown")}
              </h4>
              <div className="rounded-[12px] border border-border bg-card px-3 py-2">
                {loading && (
                  <div className="space-y-2 py-2">
                    <Skeleton className="h-3 w-full bg-muted" />
                    <Skeleton className="h-3 w-4/5 bg-muted" />
                    <Skeleton className="h-3 w-3/5 bg-muted" />
                  </div>
                )}
                {!loading && quote && (
                  <>
                    <Row
                      label={t("encarPrice")}
                      value={money(quote.encar_eur)}
                      testId="quote-encar-price"
                    />
                    <Row label={t("exportFee")} value={money(quote.autowini_fee_eur)} />
                    <Row
                      label={t("customsDuty")}
                      value={money(quote.duty)}
                      testId="quote-duty"
                    />
                    {quote.vat > 0 && (
                      <Row label={t("vat")} value={money(quote.vat)} testId="quote-vat" />
                    )}
                    <Row label={t("domestic")} value={money(quote.domestic_total)} />
                    <Separator className="my-1.5 bg-border" />
                    <Row
                      label={t("finalPrice")}
                      value={money(quote.suggested_sale)}
                      strong
                      testId="quote-final-price"
                    />
                  </>
                )}
                {!loading && !quote && (
                  <Row label={t("finalPrice")} value={money(car.sale_eur)} strong />
                )}
              </div>
              <p className="mt-2 text-[11px] leading-snug text-muted-foreground">{t("trust1Body")}</p>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Button
              data-testid="quick-view-save"
              variant="outline"
              onClick={() => requireAccount("car") && toggleFavourite(car.id, car)}
              className="h-11 gap-2 border-border bg-card px-4 text-sm hover:bg-muted"
            >
              <Heart
                className={`h-4 w-4 ${
                  saved ? "fill-[hsl(var(--primary))] text-destructive" : "text-muted-foreground"
                }`}
                aria-hidden="true"
              />
              {saved ? t("saved") : t("save")}
            </Button>
            <Button
              data-testid="quick-view-close"
              onClick={() => onOpenChange(false)}
              className="h-11 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-sm text-primary-foreground hover:brightness-110"
            >
              {t("close")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default QuickViewDialog;
