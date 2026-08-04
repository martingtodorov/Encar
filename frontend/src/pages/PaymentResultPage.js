import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { formatMoney } from "@/lib/format";
import http from "@/lib/api";

/**
 * Where Stripe Checkout returns to.
 *
 * The browser is never trusted: `?session_id` is only a handle, and the state comes from
 * our own record, which the backend confirms against Stripe while it is still pending. So
 * the page polls a few times rather than announcing success on arrival.
 */
export default function PaymentResultPage({ outcome = "success" }) {
  const { t, lang, currency, rates } = useApp();
  const { go, path } = useLangNav();
  const { search } = useLocation();
  const sessionId = new URLSearchParams(search).get("session_id") || "";
  const [record, setRecord] = useState(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    if (outcome !== "success" || !sessionId) return undefined;
    let cancelled = false;
    let timer = null;
    const poll = async (n) => {
      try {
        const { data } = await http.get(`/deposit/status/${sessionId}`);
        if (cancelled) return;
        setRecord(data);
        if (data.payment_status !== "paid" && n < 8) {
          timer = setTimeout(() => {
            setTries(n + 1);
            poll(n + 1);
          }, 2000);
        }
      } catch (e) {
        if (!cancelled) setRecord({ payment_status: "unknown" });
      }
    };
    poll(0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sessionId, outcome]);

  const paid = record?.payment_status === "paid";
  const pending = outcome === "success" && !paid && tries < 8;
  const money = (v) => formatMoney(v, currency, lang, rates);

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[640px] px-4 py-16 text-center sm:px-6">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
          {pending ? (
            <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" aria-hidden="true" />
          ) : paid ? (
            <CheckCircle2 className="h-7 w-7 text-[hsl(var(--success))]" aria-hidden="true" />
          ) : (
            <XCircle className="h-7 w-7 text-destructive" aria-hidden="true" />
          )}
        </div>

        <h1
          data-testid="payment-result-title"
          className="mt-4 text-2xl font-semibold text-foreground sm:text-3xl"
        >
          {pending
            ? t("payPending")
            : paid
              ? t("payPaid")
              : outcome === "cancel"
                ? t("payCancelled")
                : t("payFailed")}
        </h1>

        {paid && (
          <>
            <p className="tnum mt-2 text-base text-muted-foreground">
              {record.car_title} · {money(record.amount_eur)}
            </p>
            <p
              data-testid="payment-result-next"
              className="mx-auto mt-3 max-w-[460px] text-[13px] leading-relaxed text-muted-foreground"
            >
              {t("payDepositNext").replace("{sum}", money(record.commission_eur))}
            </p>
          </>
        )}

        <div className="mt-6 flex flex-wrap justify-center gap-3">
          {record?.car_id && (
            <Button
              data-testid="payment-result-car"
              onClick={() => go(`/car/${record.car_id}`)}
              className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
            >
              {t("payBackToCar")}
            </Button>
          )}
          <Button
            data-testid="payment-result-browse"
            variant="outline"
            onClick={() => go("/")}
            className="h-10 rounded-[10px] border-border bg-card px-5 text-[13.5px]"
          >
            {t("payBrowse")}
          </Button>
        </div>
        <span className="sr-only">{path("/")}</span>
      </main>
    </div>
  );
}
