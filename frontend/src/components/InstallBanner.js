import { useEffect, useRef, useState } from "react";
import { Bell, X, Share, Plus, MoreVertical, Apple } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useDisplayMode, platformTag } from "@/hooks/useDisplayMode";

const DISMISS_KEY = "encar.install.dismissed_until";
const DISMISS_DAYS = 30;
const SHOW_AFTER_MS = 2500;

/**
 * Top-of-page nag asking the visitor to install the site as a homescreen PWA. Shown to
 * BOTH signed-in and anonymous visitors — the whole point of push is to keep casual
 * shoppers in the loop about their saved searches, which they can save without an
 * account. Hidden entirely when the site is already running as a homescreen PWA
 * (`display-mode: standalone`), and honours a 30-day dismissal cookie.
 *
 * On Android/Chrome we intercept the browser's own `beforeinstallprompt` and hand the
 * visitor the native "Add to Home screen" sheet instead of a screenshot walkthrough,
 * which converts much better than "read these five steps". iOS has no equivalent API,
 * so it always gets the illustrated instructions.
 */
export const InstallBanner = () => {
  const { t } = useApp();
  const standalone = useDisplayMode();
  const [visible, setVisible] = useState(false);
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const deferredPrompt = useRef(null);

  useEffect(() => {
    if (standalone) return undefined;
    // Chrome-based Android/desktop: it stores the install invitation for later. We hijack
    // the event so the browser's own bar does NOT appear (that would clash with ours), then
    // fire the sheet when the visitor taps our button.
    const onBeforeInstall = (e) => {
      e.preventDefault();
      deferredPrompt.current = e;
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    return () => window.removeEventListener("beforeinstallprompt", onBeforeInstall);
  }, [standalone]);

  useEffect(() => {
    if (standalone) return undefined;
    // A `dismissed_until` timestamp beats a boolean: the dismissal expires on its own
    // and the banner comes back after 30 days without any extra bookkeeping on our part.
    try {
      const until = Number(localStorage.getItem(DISMISS_KEY) || 0);
      if (until && Date.now() < until) return undefined;
    } catch {
      // Access might throw in privacy-mode Safari; act as if it was never dismissed.
    }
    // Small delay so the banner does not slam in on top of the first paint — the CookieBar
    // dialog gets to appear first and settle.
    const id = setTimeout(() => setVisible(true), SHOW_AFTER_MS);
    return () => clearTimeout(id);
  }, [standalone]);

  const dismiss = () => {
    setVisible(false);
    try {
      localStorage.setItem(
        DISMISS_KEY,
        String(Date.now() + DISMISS_DAYS * 24 * 60 * 60 * 1000)
      );
    } catch {
      /* localStorage may be blocked; the banner will just reappear next visit. */
    }
  };

  const openInstructions = async () => {
    // Prefer the native Android install prompt if the browser gave us one — no manual
    // walkthrough needed, tapping "Install" adds the PWA in one gesture.
    if (deferredPrompt.current) {
      const evt = deferredPrompt.current;
      deferredPrompt.current = null;
      try {
        evt.prompt();
        const { outcome } = await evt.userChoice;
        if (outcome === "accepted") dismiss();
      } catch {
        setInstructionsOpen(true);
      }
      return;
    }
    setInstructionsOpen(true);
  };

  if (standalone || !visible) return null;

  return (
    <>
      <div
        data-testid="install-banner"
        role="region"
        aria-label={t("installBannerAria")}
        className="sticky top-0 z-40 flex items-center gap-3 border-b border-border bg-[hsl(var(--primary))] px-3 py-2 text-primary-foreground shadow-sm sm:px-4"
      >
        <button
          type="button"
          onClick={openInstructions}
          data-testid="install-banner-cta"
          className="flex flex-1 items-center gap-2.5 text-left focus:outline-none"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/15">
            <Bell className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold leading-tight">
              {t("installBannerTitle")}
            </span>
            <span className="mt-0.5 hidden text-[12px] leading-tight opacity-90 sm:block">
              {t("installBannerBody")}
            </span>
          </span>
        </button>
        <Button
          data-testid="install-banner-open"
          onClick={openInstructions}
          className="h-8 shrink-0 rounded-full bg-white/95 px-3 text-[12.5px] font-semibold text-[hsl(var(--primary))] hover:bg-white"
        >
          {t("installBannerCta")}
        </Button>
        <button
          type="button"
          data-testid="install-banner-dismiss"
          onClick={dismiss}
          aria-label={t("installBannerDismiss")}
          className="ml-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white/85 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <InstallInstructionsDialog
        open={instructionsOpen}
        onOpenChange={setInstructionsOpen}
      />
    </>
  );
};

/** Illustrated iOS / Android steps for adding the site to the homescreen. */
const InstallInstructionsDialog = ({ open, onOpenChange }) => {
  const { t } = useApp();
  const [tab, setTab] = useState(() => (platformTag() === "android" ? "android" : "ios"));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="install-instructions"
        className="max-w-md gap-3 rounded-[18px] bg-card p-5"
      >
        <DialogHeader>
          <DialogTitle className="text-[17px] font-semibold">
            {t("installDialogTitle")}
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t("installDialogIntro")}</p>

        <div
          role="tablist"
          className="mt-1 grid grid-cols-2 rounded-[12px] bg-secondary p-1 text-sm"
        >
          <button
            type="button"
            role="tab"
            aria-selected={tab === "ios"}
            data-testid="install-tab-ios"
            onClick={() => setTab("ios")}
            className={`flex items-center justify-center gap-1.5 rounded-[10px] px-3 py-1.5 font-medium transition ${
              tab === "ios"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Apple className="h-4 w-4" aria-hidden="true" />
            iPhone / iPad
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "android"}
            data-testid="install-tab-android"
            onClick={() => setTab("android")}
            className={`flex items-center justify-center gap-1.5 rounded-[10px] px-3 py-1.5 font-medium transition ${
              tab === "android"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <AndroidGlyph className="h-4 w-4" />
            Android
          </button>
        </div>

        {tab === "ios" ? (
          <ol className="mt-2 space-y-3 text-sm text-foreground">
            <Step
              index={1}
              icon={<Share className="h-4 w-4" aria-hidden="true" />}
              text={t("installIosStep1")}
            />
            <Step
              index={2}
              icon={<Plus className="h-4 w-4" aria-hidden="true" />}
              text={t("installIosStep2")}
            />
            <Step index={3} text={t("installIosStep3")} />
          </ol>
        ) : (
          <ol className="mt-2 space-y-3 text-sm text-foreground">
            <Step
              index={1}
              icon={<MoreVertical className="h-4 w-4" aria-hidden="true" />}
              text={t("installAndroidStep1")}
            />
            <Step
              index={2}
              icon={<Plus className="h-4 w-4" aria-hidden="true" />}
              text={t("installAndroidStep2")}
            />
            <Step index={3} text={t("installAndroidStep3")} />
          </ol>
        )}

        <p className="mt-2 rounded-[10px] bg-secondary/60 px-3 py-2 text-[12px] text-muted-foreground">
          {t("installDialogNotifyNote")}
        </p>
      </DialogContent>
    </Dialog>
  );
};

const Step = ({ index, icon, text }) => (
  <li className="flex items-start gap-3">
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary))]/10 text-[12px] font-semibold text-[hsl(var(--primary))]">
      {index}
    </span>
    <span className="flex-1 leading-snug">
      {text}
      {icon ? (
        <span className="ml-1.5 inline-flex h-6 w-6 -translate-y-0.5 items-center justify-center rounded-[6px] bg-secondary align-middle text-foreground">
          {icon}
        </span>
      ) : null}
    </span>
  </li>
);

/** Small vector: `lucide-react` doesn't ship an Android glyph, so we hand-roll one. */
const AndroidGlyph = ({ className = "" }) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="currentColor">
    <path d="M6.2 9.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm11.6 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm-.6-2.6.9-1.6a.3.3 0 0 0-.5-.3l-.9 1.6a7.7 7.7 0 0 0-7.4 0L8.4 5a.3.3 0 0 0-.5.3l.9 1.6A6.6 6.6 0 0 0 5 12.5h14a6.6 6.6 0 0 0-3.8-5.6ZM5 13.5v5.6c0 .7.6 1.3 1.3 1.3h1V22a1 1 0 0 0 2 0v-1.6h5.4V22a1 1 0 0 0 2 0v-1.6h1c.7 0 1.3-.6 1.3-1.3v-5.6H5Z" />
  </svg>
);

export default InstallBanner;
