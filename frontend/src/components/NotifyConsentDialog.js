import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { pushSupported, enablePush } from "@/lib/push";

// Shared with `NotificationsPrompt`: whichever of the two the visitor waves away, the
// other one honours it, so signing in never turns into two nags in a row.
const DISMISS_KEY = "encar.notify.dismissed_until";
const LATER_DAYS = 7;
const OPEN_AFTER_MS = 700;

/**
 * The moment a buyer signs in inside the homescreen app, ask for notifications.
 *
 * This is the one instant where the ask makes sense: notifications are about THEIR saved
 * searches and cars, which only exist now that there is an account, and iOS only grants
 * push to an installed PWA. Deliberately a dialog rather than the slim banner — the
 * banner is easy to scroll past, and Safari only honours a permission request that comes
 * from a real tap, so it has to be something the visitor answers.
 *
 * Fires on the signed-out → signed-in transition ONLY. A cold launch that restores an
 * existing session is not a sign-in, and asking every time the app opens would be the
 * fastest way to get the permission denied for good.
 */
export const NotifyConsentDialog = () => {
  const { t } = useApp();
  const { user, loading } = useAuth();
  const standalone = useDisplayMode();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  // `null` until the session probe finishes, so a restored session is not read as a login.
  const wasSignedIn = useRef(null);

  useEffect(() => {
    if (loading) return undefined;
    const signedIn = !!user;
    const before = wasSignedIn.current;
    wasSignedIn.current = signedIn;
    if (before === null || before || !signedIn) return undefined;
    if (!standalone || !pushSupported()) return undefined;
    if (Notification.permission !== "default") return undefined;
    try {
      const until = Number(localStorage.getItem(DISMISS_KEY) || 0);
      if (until && Date.now() < until) return undefined;
    } catch { /* privacy mode: ask anyway */ }
    // A breath after the redirect so it lands on the page they signed in for, not on
    // top of the login form unmounting.
    const id = setTimeout(() => setOpen(true), OPEN_AFTER_MS);
    return () => clearTimeout(id);
  }, [user, loading, standalone]);

  const later = () => {
    setOpen(false);
    try {
      localStorage.setItem(
        DISMISS_KEY,
        String(Date.now() + LATER_DAYS * 24 * 60 * 60 * 1000)
      );
    } catch { /* localStorage blocked: it will ask again next sign-in */ }
  };

  const enable = async () => {
    setPending(true);
    try {
      await enablePush();
      toast.success(t("notifyPromptSuccess"));
      setOpen(false);
    } catch (err) {
      const reason = String(err?.message || err);
      toast.error(reason === "denied" ? t("notifyPromptDenied") : t("notifyPromptFailed"));
      if (reason === "denied") setOpen(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : later())}>
      <DialogContent
        data-testid="notify-consent-dialog"
        className="max-w-sm gap-4 rounded-[18px] bg-card p-5 text-center"
      >
        <DialogHeader className="items-center gap-2">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]">
            <Bell className="h-6 w-6" aria-hidden="true" />
          </span>
          <DialogTitle className="text-[17px] font-semibold">
            {t("notifyPromptTitle")}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {t("notifyPromptBody")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2">
          <Button
            data-testid="notify-consent-enable"
            onClick={enable}
            disabled={pending}
            className="h-11 w-full rounded-full bg-[hsl(var(--primary))] text-sm font-semibold text-primary-foreground hover:brightness-110"
          >
            {pending ? t("notifyPromptEnabling") : t("notifyPromptEnable")}
          </Button>
          <Button
            data-testid="notify-consent-later"
            variant="ghost"
            onClick={later}
            className="h-10 w-full rounded-full text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {t("notifyPromptLater")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default NotifyConsentDialog;
