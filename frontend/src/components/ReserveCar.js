import { useEffect, useState } from "react";
import { Loader2, Lock, MailWarning, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  const [open, setOpen] = useState(false);
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
      const d = e?.response?.data?.detail;
      // The backend answers unverified addresses with a code, not a sentence: the wording
      // belongs in our own dictionary, and a raw object thrown at a toast renders as junk.
      if (typeof d === "object" && d?.code === "email_unverified")
        toast.error(t("depositVerifyFirst"));
      else if (typeof d === "object" && d?.code === "car_contracted") {
        // Encar took the car under contract while this page was open.
        toast.error(t("depositContracted"));
        setQuote((q) => ({ ...q, contracted: true }));
      } else toast.error(typeof d === "string" ? d : "could not start the payment");
      setBusy(false);
    }
  };

  if (!quote?.configured) return null;

  const money = (v) => formatMoney(v, currency, lang, rates);

  if (quote.reserved || quote.contracted) {
    return (
      <div
        data-testid="detail-reserve"
        className="flex h-12 items-center justify-center gap-2 rounded-[12px] border border-border bg-secondary px-4 text-[14px] font-semibold text-[hsl(var(--primary))]"
      >
        <ShieldCheck className="h-[18px] w-[18px]" aria-hidden="true" />
        <span data-testid="detail-reserve-taken">
          {quote.contracted
            ? t("depositContracted")
            : quote.mine
              ? t("depositMine")
              : t("depositReserved")}
        </span>
      </div>
    );
  }

  // A reservation holds money on a card and takes the car off the market for a week, so the
  // address has to be proved first. The button is shown DEAD rather than hidden: a buyer who
  // cannot see the price of reserving cannot decide to do it.
  if (user && user.email_verified === false) {
    return (
      <div data-testid="detail-reserve">
        <Button
          data-testid="detail-reserve-button"
          variant="outline"
          disabled
          className="h-12 w-full justify-center gap-2 rounded-[12px] border-2 border-border bg-card text-[14px] font-semibold text-muted-foreground"
        >
          <MailWarning className="h-[18px] w-[18px]" aria-hidden="true" />
          {t("depositVerifyFirst")}
        </Button>
        <a
          href={path("/verify-email")}
          data-testid="detail-reserve-verify-link"
          className="mt-2.5 inline-block text-[12.5px] font-semibold text-[hsl(var(--primary))] transition-opacity hover:opacity-80"
        >
          {t("depositVerifyLink")}
        </a>
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("depositVerifyBlurb")}
        </p>
      </div>
    );
  }

  return (
    <div data-testid="detail-reserve">
      <Button
        data-testid="detail-reserve-button"
        variant="outline"
        onClick={() => setOpen(true)}
        className="h-12 w-full justify-center gap-2 rounded-[12px] border-2 border-[hsl(var(--primary))] bg-card text-[15px] font-semibold text-[hsl(var(--primary))] hover:bg-secondary dark:text-white"
      >
        <Lock className="h-[18px] w-[18px]" aria-hidden="true" />
        {t("depositReserve")}
        <span data-testid="detail-reserve-amount" className="tnum">
          · {money(quote.amount_eur)}
        </span>
      </Button>

      {/* The terms used to sit under the button as small print with a tick. Nobody reads small
          print, and this is money on a card: the dialog puts the whole thing in front of the
          buyer and the single button IS the acknowledgement. */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="deposit-terms-dialog" className="max-w-[460px] bg-card">
          <DialogHeader>
            <DialogTitle className="text-[17px]">
              {t("depositTitle")}
              <span data-testid="deposit-dialog-amount" className="tnum ml-1.5">
                · {money(quote.amount_eur)}
              </span>
            </DialogTitle>
            <DialogDescription className="text-[13px] leading-relaxed">
              {t("depositTerms")}
            </DialogDescription>
          </DialogHeader>

          <p
            data-testid="deposit-dialog-blurb"
            className="rounded-[12px] border border-border bg-background p-3.5 text-[12.5px] leading-relaxed text-muted-foreground"
          >
            {t("depositBlurb").replace("{sum}", money(quote.commission_eur))}
          </p>

          <Button
            data-testid="deposit-agree-continue"
            onClick={pay}
            disabled={busy}
            className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[14px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {busy ? (
              <Loader2 className="h-[18px] w-[18px] animate-spin" aria-hidden="true" />
            ) : (
              <ShieldCheck className="h-[18px] w-[18px]" aria-hidden="true" />
            )}
            {t("depositAgreeContinue")}
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ReserveCar;
