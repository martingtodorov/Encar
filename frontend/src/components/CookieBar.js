import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { getConsent, setConsent, syncConsent } from "@/lib/taste";

/**
 * Consent for the cookies that are NOT strictly necessary.
 *
 * The personalisation profile is only ever written after an explicit yes here, so
 * declining genuinely stops it rather than just hiding a banner.
 */
export const CookieBar = () => {
  const { t } = useApp();
  const { path } = useLangNav();
  const [show, setShow] = useState(false);

  useEffect(() => {
    setShow(!getConsent());
  }, []);

  if (!show) return null;

  const decide = (value) => {
    setConsent(value);
    syncConsent();
    setShow(false);
  };

  return (
    <div
      data-testid="cookie-bar"
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card/95 backdrop-blur-md"
    >
      <div className="mx-auto flex max-w-[1280px] flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
          {t("cookieBarText")}{" "}
          <Link
            to={path("/cookies")}
            data-testid="cookie-bar-policy"
            className="font-medium text-primary hover:underline"
          >
            {t("legalCookies")}
          </Link>
        </p>
        <div className="flex shrink-0 gap-2">
          <Button
            data-testid="cookie-decline"
            variant="outline"
            onClick={() => decide("necessary")}
            className="h-10 whitespace-nowrap rounded-[10px] border-border bg-card px-4 text-[13px]"
          >
            {t("cookieDecline")}
          </Button>
          <Button
            data-testid="cookie-accept"
            onClick={() => decide("all")}
            className="h-10 whitespace-nowrap rounded-[10px] px-4 text-[13px] font-semibold"
          >
            {t("cookieAccept")}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default CookieBar;
