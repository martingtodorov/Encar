import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import {
  CATEGORIES,
  acceptAll,
  chosen,
  hasDecision,
  onConsentChange,
  rejectAll,
  save,
} from "@/lib/consent";
import { syncConsent } from "@/lib/taste";

/**
 * Prior consent, the way the ePrivacy Directive asks for it.
 *
 * Nothing outside the strictly necessary category is written before a decision is taken here,
 * refusing is exactly as easy and as prominent as accepting, the non-essential toggles start
 * OFF, and the whole thing can be reopened from the footer to change or withdraw a decision.
 */
const OPEN_EVENT = "encar:cookie-settings";

/** Anything on the site can reopen the settings: `openCookieSettings()`. */
export const openCookieSettings = () =>
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));

export const CookieBar = () => {
  const { t } = useApp();
  const { path } = useLangNav();
  const [show, setShow] = useState(false);
  const [details, setDetails] = useState(false);
  const [cats, setCats] = useState(() => chosen());

  useEffect(() => {
    setShow(!hasDecision());
    const reopen = () => {
      setCats(chosen());
      setDetails(true);
      setShow(true);
    };
    window.addEventListener(OPEN_EVENT, reopen);
    const off = onConsentChange(() => setCats(chosen()));
    return () => {
      window.removeEventListener(OPEN_EVENT, reopen);
      off();
    };
  }, []);

  if (!show) return null;

  const done = () => {
    // A signed-in buyer is asked once, not once per device.
    syncConsent();
    setShow(false);
    setDetails(false);
  };

  const takeAll = () => {
    acceptAll();
    done();
  };
  const takeNone = () => {
    rejectAll();
    done();
  };
  const takeChosen = () => {
    save(cats);
    done();
  };

  return (
    <div
      data-testid="cookie-bar"
      role="dialog"
      aria-modal="false"
      aria-label={t("cookieTitle")}
      className="fixed bottom-0 left-0 right-0 z-[60] border-t border-border bg-card/95 backdrop-blur-md"
    >
      <div className="mx-auto max-w-[1280px] px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="max-w-2xl">
            <div className="text-[14px] font-semibold text-foreground">{t("cookieTitle")}</div>
            <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
              {t("cookieBarText")}{" "}
              <Link
                to={path("/cookies")}
                data-testid="cookie-bar-policy"
                className="font-medium text-primary hover:underline"
              >
                {t("legalCookies")}
              </Link>
              {" · "}
              <Link
                to={path("/privacy")}
                data-testid="cookie-bar-privacy"
                className="font-medium text-primary hover:underline"
              >
                {t("legalPrivacy")}
              </Link>
            </p>
          </div>

          {/* All three choices are one button each, same size, same weight: no dark pattern. */}
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button
              data-testid="cookie-decline"
              variant="outline"
              onClick={takeNone}
              className="h-10 whitespace-nowrap rounded-[10px] border-border bg-card px-4 text-[13px] font-semibold"
            >
              {t("cookieRejectAll")}
            </Button>
            <Button
              data-testid="cookie-settings"
              variant="outline"
              onClick={() => setDetails((v) => !v)}
              aria-expanded={details}
              className="h-10 whitespace-nowrap rounded-[10px] border-border bg-card px-4 text-[13px] font-semibold"
            >
              {t("cookieSettings")}
            </Button>
            <Button
              data-testid="cookie-accept"
              onClick={takeAll}
              className="h-10 whitespace-nowrap rounded-[10px] px-4 text-[13px] font-semibold"
            >
              {t("cookieAccept")}
            </Button>
          </div>
        </div>

        {details && (
          <div data-testid="cookie-categories" className="mt-4 border-t border-border pt-4">
            <div className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-4 rounded-[10px] bg-background p-3">
                <div>
                  <div className="text-[13px] font-semibold text-foreground">
                    {t("cookieNecessaryTitle")}
                  </div>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">
                    {t("cookieNecessaryBody")}
                  </p>
                </div>
                <span
                  data-testid="cookie-cat-necessary"
                  className="shrink-0 whitespace-nowrap rounded-full bg-secondary px-2.5 py-1 text-[11.5px] font-semibold text-[hsl(var(--primary))]"
                >
                  {t("cookieAlwaysOn")}
                </span>
              </div>

              {CATEGORIES.map((cat) => (
                <div
                  key={cat}
                  className="flex items-start justify-between gap-4 rounded-[10px] bg-background p-3"
                >
                  <div>
                    <div className="text-[13px] font-semibold text-foreground">
                      {t(`cookie_${cat}_title`)}
                    </div>
                    <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">
                      {t(`cookie_${cat}_body`)}
                    </p>
                  </div>
                  <Switch
                    data-testid={`cookie-toggle-${cat}`}
                    checked={!!cats[cat]}
                    onCheckedChange={(on) => setCats((p) => ({ ...p, [cat]: on }))}
                    aria-label={t(`cookie_${cat}_title`)}
                    className="mt-0.5 shrink-0"
                  />
                </div>
              ))}
            </div>

            <div className="mt-3 flex justify-end">
              <Button
                data-testid="cookie-save"
                variant="secondary"
                onClick={takeChosen}
                className="h-10 rounded-[10px] bg-secondary px-4 text-[13px] font-semibold text-[hsl(var(--primary))] hover:brightness-95"
              >
                {t("cookieSaveChoice")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CookieBar;
