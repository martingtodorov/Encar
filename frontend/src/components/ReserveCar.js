import { useEffect, useState } from "react";
import { Loader2, Lock, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { formatMoney } from "@/lib/format";
import http from "@/lib/api";

/**
 * Reservation deposit: 10% of the car, no floor, taken through Stripe Checkout.
 *
 * Shaped as a single action so it can sit beside the enquiry button under the photos. The
 * amount is quoted by the backend, never computed here — a price in the browser is a price
 * a buyer can edit. A car somebody else already holds shows as reserved instead of offering
 * a second deposit.
 */
export const ReserveCar = ({ car }) => {
  const { t, lang, currency, rates } = useApp();
  const { user } = useAuth();
  const { path } = useLangNav();
  const [quote, setQuote] = useState(null);
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
        disabled={busy}
        className="h-12 w-full justify-center gap-2 rounded-[12px] border-2 border-[hsl(var(--primary))] bg-card text-[15px] font-semibold text-[hsl(var(--primary))] hover:bg-secondary"
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
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("depositBlurb")}
      </p>
    </div>
  );
};

export default ReserveCar;
