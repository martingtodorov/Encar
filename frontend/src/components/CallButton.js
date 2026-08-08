import { useEffect, useState } from "react";
import { Phone, PhoneOff } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { getCallButton } from "@/lib/api";

/**
 * "Call us", beside the enquiry button and in the same colour.
 *
 * Whether anybody is there to answer is decided by the SERVER against the owner's own
 * opening hours — a phone's clock and time zone cannot be trusted. Outside those hours the
 * button still works, but it says so first and asks whether to dial anyway: a call nobody
 * picks up costs more trust than a warning does.
 */
const DAY_KEY = ["callMon", "callTue", "callWed", "callThu", "callFri", "callSat", "callSun"];
const ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const CallButton = () => {
  const { t } = useApp();
  const [info, setInfo] = useState(null);
  const [warn, setWarn] = useState(false);

  useEffect(() => {
    let alive = true;
    getCallButton()
      .then((d) => alive && setInfo(d))
      .catch(() => alive && setInfo(null));
    return () => {
      alive = false;
    };
  }, []);

  if (!info?.enabled || !info.phone) return null;

  const dial = () => {
    setWarn(false);
    window.location.href = `tel:${info.phone}`;
  };

  const button = (
    <Button
      data-testid="call-button"
      onClick={() => (info.open_now ? dial() : setWarn(true))}
      className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
    >
      <Phone className="h-[17px] w-[17px]" aria-hidden="true" />
      {t("callUs")}
    </Button>
  );

  return (
    <>
      {button}

      <Dialog open={warn} onOpenChange={setWarn}>
        <DialogContent
          data-testid="call-closed-dialog"
          className="max-h-[88svh] w-[calc(100vw-2rem)] max-w-[400px] overflow-y-auto bg-card"
        >
          <DialogHeader>
            <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-[12px] bg-secondary">
              <PhoneOff
                className="h-[20px] w-[20px] text-[hsl(var(--primary))]"
                aria-hidden="true"
              />
            </div>
            <DialogTitle data-testid="call-closed-title" className="text-[17px]">
              {t("callClosedTitle")}
            </DialogTitle>
            <DialogDescription className="text-[13px] leading-relaxed">
              {t("callClosedBody")}
            </DialogDescription>
          </DialogHeader>

          <dl
            data-testid="call-hours"
            className="rounded-[12px] border border-border bg-background p-3 text-[13px]"
          >
            {ORDER.map((day, i) => {
              const row = info.hours?.[day] || {};
              const shut = row.closed || !row.open || !row.close;
              return (
                <div
                  key={day}
                  className={`flex items-center justify-between py-1 ${
                    day === info.day ? "font-semibold text-foreground" : "text-muted-foreground"
                  }`}
                >
                  <dt>{t(DAY_KEY[i])}</dt>
                  <dd className="tnum">{shut ? t("callClosedDay") : `${row.open}–${row.close}`}</dd>
                </div>
              );
            })}
          </dl>

          <div className="flex flex-col gap-2.5 sm:flex-row-reverse">
            <Button
              data-testid="call-anyway"
              onClick={dial}
              className="h-11 flex-1 justify-center gap-2 rounded-[11px] bg-[hsl(var(--primary))] text-[14.5px] font-semibold text-primary-foreground hover:brightness-110"
            >
              <Phone className="h-[17px] w-[17px]" aria-hidden="true" />
              {t("callAnyway")}
            </Button>
            <Button
              variant="outline"
              data-testid="call-cancel"
              onClick={() => setWarn(false)}
              className="h-11 flex-1 justify-center rounded-[11px] border-border bg-card text-[14.5px] font-medium hover:bg-muted"
            >
              {t("close")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default CallButton;
