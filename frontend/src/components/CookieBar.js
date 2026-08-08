import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Cookie } from "lucide-react";
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
 * Prior consent, the way the ePrivacy Directive asks for it — and impossible to walk past.
 *
 * It was a bar along the bottom of the page and buyers simply scrolled on, so nothing outside
 * the strictly necessary category could ever be written for them. It is now a BLOCKING dialog:
 * the page behind it cannot be scrolled, clicked or tabbed into, on every page including sign-up
 * and a car's own page, until a choice is made. There is no close button and no click-outside
 * while the choice is outstanding, because dismissing a consent request is not consent.
 *
 * Refusing stays exactly as easy and as prominent as accepting, the non-essential toggles start
 * OFF, and the whole thing reopens from the footer to change or withdraw a decision — reopened,
 * it CAN be closed, since a decision already exists.
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
  const panel = useRef(null);
  // Outstanding choice = nothing gets through. Reopened afterwards = an ordinary dialog.
  const blocking = show && !hasDecision();

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

  // The page behind must not scroll, and the keyboard must not reach it either.
  useEffect(() => {
    if (!show) return undefined;
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    const trap = (e) => {
      if (e.key === "Tab" && panel.current && !panel.current.contains(e.target)) {
        e.preventDefault();
        panel.current.querySelector("button, [href], input")?.focus();
      }
      // Escape is a dismissal, and a dismissal is not a decision.
      if (e.key === "Escape" && blocking) e.preventDefault();
    };
    document.addEventListener("keydown", trap, true);
    panel.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", trap, true);
    };
  }, [show, blocking]);

  if (!show) return null;

  const done = () => {
    // A signed-in buyer is asked once, not once per device: the decision is mirrored to the
    // account and adopted on the next device they sign in on.
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
      data-testid="cookie-overlay"
      className="fixed inset-0 z-[200] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      onMouseDown={(e) => {
        // Clicking the backdrop closes it ONLY when the decision has already been made.
        if (!blocking && e.target === e.currentTarget) setShow(false);
      }}
    >
      <div
        ref={panel}
        tabIndex={-1}
        data-testid="cookie-bar"
        role="dialog"
        aria-modal="true"
        aria-label={t("cookieTitle")}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-[18px] border border-border bg-card p-5 shadow-2xl outline-none sm:rounded-[18px] sm:p-6"
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary">
            <Cookie className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
          </span>
          <div>
            <div className="text-[15px] font-semibold text-foreground">{t("cookieTitle")}</div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
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
        </div>

        {details && (
          <div data-testid="cookie-categories" className="mt-4 flex flex-col gap-2.5">
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

            <div className="flex justify-end">
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

        {/* All three choices are one button each, same size, same weight: no dark pattern. */}
        <div className="mt-5 grid gap-2 sm:grid-cols-3">
          <Button
            data-testid="cookie-decline"
            variant="outline"
            onClick={takeNone}
            className="h-11 rounded-[10px] border-border bg-card text-[13px] font-semibold"
          >
            {t("cookieRejectAll")}
          </Button>
          <Button
            data-testid="cookie-settings"
            variant="outline"
            onClick={() => setDetails((v) => !v)}
            aria-expanded={details}
            className="h-11 rounded-[10px] border-border bg-card text-[13px] font-semibold"
          >
            {t("cookieSettings")}
          </Button>
          <Button
            data-testid="cookie-accept"
            onClick={takeAll}
            className="h-11 rounded-[10px] text-[13px] font-semibold"
          >
            {t("cookieAccept")}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default CookieBar;
