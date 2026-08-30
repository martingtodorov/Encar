import { useEffect, useState } from "react";
import { Bell, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { pushSupported, enablePush } from "@/lib/push";

const DISMISS_KEY = "encar.notify.dismissed_until";
const DISMISS_DAYS = 30;
const SHOW_AFTER_MS = 1500;

/**
 * Only after the site has been added to the homescreen: nudge the visitor to enable
 * push. This is where the whole install-first flow pays off — Safari refuses to prompt
 * for notifications from a plain browser tab on iOS, but a homescreen PWA can.
 *
 * Shows a slim banner just under the site header, honours a 30-day dismissal, and only
 * asks when the browser permission is `default` (neither granted nor denied). The
 * permission request itself has to be triggered by a real user gesture — otherwise
 * Safari drops it — so the banner ships a real button rather than firing on mount.
 */
export const NotificationsPrompt = () => {
  const { t } = useApp();
  const standalone = useDisplayMode();
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!standalone) return;
    if (!pushSupported()) return;
    if (Notification.permission !== "default") return;
    try {
      const until = Number(localStorage.getItem(DISMISS_KEY) || 0);
      if (until && Date.now() < until) return;
    } catch { /* privacy mode: show anyway */ }
    const id = setTimeout(() => setVisible(true), SHOW_AFTER_MS);
    // eslint-disable-next-line consistent-return
    return () => clearTimeout(id);
  }, [standalone]);

  const dismiss = () => {
    setVisible(false);
    try {
      localStorage.setItem(
        DISMISS_KEY,
        String(Date.now() + DISMISS_DAYS * 24 * 60 * 60 * 1000)
      );
    } catch { /* localStorage blocked, banner will reappear */ }
  };

  const enable = async () => {
    setPending(true);
    try {
      await enablePush();
      toast.success(t("notifyPromptSuccess"));
      setVisible(false);
    } catch (err) {
      // "denied" comes back when the visitor refuses the OS-level dialog.
      const reason = String(err?.message || err);
      toast.error(reason === "denied" ? t("notifyPromptDenied") : t("notifyPromptFailed"));
      if (reason === "denied") setVisible(false);
    } finally {
      setPending(false);
    }
  };

  if (!visible) return null;

  return (
    <div
      data-testid="notify-prompt"
      role="region"
      aria-label={t("notifyPromptTitle")}
      // Same reasoning as InstallBanner: NOT sticky. The HeaderBar is sticky at
      // top-0 z-40, so anything else with the same top+z-index simply stacks on
      // top of it and hides the logo/menu. This banner lives at the very top of
      // document flow — it scrolls away with the page like any first-visit nag.
      // Sits at the very top of document flow, above the header, and scrolls away with
      // the page. No safe-area padding of its own: in standalone <body> already
      // reserves the Dynamic-Island inset for the whole document.
      className="relative z-40 flex items-center gap-3 border-b border-border bg-card px-3 py-2 shadow-sm sm:px-4"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]">
        <Bell className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-semibold leading-tight text-foreground">
          {t("notifyPromptTitle")}
        </span>
        <span className="mt-0.5 hidden text-[12px] leading-tight text-muted-foreground sm:block">
          {t("notifyPromptBody")}
        </span>
      </span>
      <Button
        data-testid="notify-prompt-enable"
        onClick={enable}
        disabled={pending}
        className="h-8 shrink-0 rounded-full bg-[hsl(var(--primary))] px-3 text-[12.5px] font-semibold text-primary-foreground hover:brightness-110"
      >
        {pending ? t("notifyPromptEnabling") : t("notifyPromptEnable")}
      </Button>
      <button
        type="button"
        data-testid="notify-prompt-dismiss"
        onClick={dismiss}
        aria-label={t("notifyPromptDismiss")}
        className="ml-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
};

export default NotificationsPrompt;
