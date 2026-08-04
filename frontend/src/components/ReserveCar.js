import { useEffect, useState } from "react";
import { Loader2, Lock, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { formatMoney } from "@/lib/format";
import http from "@/lib/api";

/**
 * Reservation deposit: 10% of the car, taken through Stripe Checkout.
 *
 * The deposit is not a holding fee — we buy the car with it, so it is not refundable if the
 * buyer withdraws. Because of that the terms have to be acknowledged before the button
 * works: an explicit tick is what stands behind us in a card dispute. The amount is quoted
 * by the backend, never computed here — a price in the browser is a price a buyer can edit.
 */
export const ReserveCar = ({ car }) => {
  const { t, lang, currency, rates } = useApp();
  const { user } = useAuth();
  const { path } = useLangNav();
  const [quote, setQuote] = useState(null);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!car?.id) return undefined;
    http
      .get(`/deposit/car/${car.id}`)
      .then(({ data }) => !cancelled && setQuote(data))
      .catch(() => !cancelled && setQuote(null));
    return () => {
      cancelled = true;
    };
  }, [car?.id]);

  const pay = async () => {
    if (!user) {
      window.location.assign(path("/login"));
      return;
    }
    setBusy(true);
    try {
      const { data } = await http.post("/deposit/checkout", {
        car_id: car.id,
        origin_url: `${window.location.origin}/${lang}`,
      });
      window.location.assign(data.checkout_url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not start the payment");
      setBusy(false);
    }
  };

  if (!quote?.configured) return null;

  const money = (v) => formatMoney(v, currency, lang, rates);

  if (quote.reserved) {
    return (
      <div
        data-testid="detail-reserve"
        className="flex h-12 items-center justify-center gap-2 rounded-[12px] border border-border bg-secondary px-4 text-[14px] font-semibold text-[hsl(var(--primary))]"
      >
        <ShieldCheck className="h-[18px] w-[18px]" aria-hidden="true" />
        <span data-testid="detail-reserve-taken">
          {quote.mine ? t("depositMine") : t("depositReserved")}
        </span>
      </div>
    );
  }

  return (
    <div data-testid="detail-reserve">
      <Button
        data-testid="detail-reserve-button"
        variant="outline"
        onClick={pay}
        disabled={busy || !agreed}
        className="h-12 w-full justify-center gap-2 rounded-[12px] border-2 border-[hsl(var(--primary))] bg-card text-[15px] font-semibold text-[hsl(var(--primary))] hover:bg-secondary disabled:border-border disabled:text-muted-foreground"
      >
        {busy ? (
          <Loader2 className="h-[18px] w-[18px] animate-spin" aria-hidden="true" />
        ) : (
          <Lock className="h-[18px] w-[18px]" aria-hidden="true" />
        )}
        {t("depositReserve")}
        <span data-testid="detail-reserve-amount" className="tnum">
          · {money(quote.amount_eur)}
        </span>
      </Button>

      <label className="mt-2.5 flex cursor-pointer items-start gap-2.5">
        <Checkbox
          data-testid="detail-reserve-terms"
          checked={agreed}
          onCheckedChange={(v) => setAgreed(v === true)}
          className="mt-0.5 shrink-0"
        />
        <span className="text-[11.5px] leading-relaxed text-foreground">
          {t("depositTerms")}
        </span>
      </label>

      <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("depositBlurb").replace("{sum}", money(quote.commission_eur))}
      </p>
    </div>
  );
};

export default ReserveCar;
