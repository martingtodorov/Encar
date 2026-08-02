import { useEffect, useState } from "react";
import { Fingerprint, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { platformPasskeyAvailable } from "@/lib/passkey";

// Cancelling the OS prompt, or already having a passkey on this device, is a normal
// outcome of an OPTIONAL offer - never an error worth showing.
const QUIET = ["NotAllowedError", "AbortError", "SecurityError", "InvalidStateError", "ConstraintError"];

/**
 * Offered once, right after registration: the account exists and the session is live, so
 * the credential has something to belong to. The ceremony itself is started by the
 * button click - moving it into an effect loses the user gesture and the browser cancels.
 */
export const PasskeyPrompt = () => {
  const { t } = useApp();
  const { justRegistered, clearJustRegistered, addPasskey } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!justRegistered) return undefined;
    let cancelled = false;
    platformPasskeyAvailable().then((can) => {
      if (cancelled) return;
      if (can) setOpen(true);
      else clearJustRegistered();
    });
    return () => {
      cancelled = true;
    };
  }, [justRegistered, clearJustRegistered]);

  const close = () => {
    setOpen(false);
    setError("");
    clearJustRegistered();
  };

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      await addPasskey();
      close();
    } catch (e) {
      if (QUIET.includes(e?.name) || e?.message === "cancelled") close();
      else setError(t("passkeyPromptFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? setOpen(true) : close())}>
      <DialogContent data-testid="passkey-prompt" className="max-w-[420px] rounded-[18px]">
        <DialogHeader>
          <span className="mb-1 flex h-11 w-11 items-center justify-center rounded-[12px] bg-secondary">
            <Fingerprint className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
          </span>
          <DialogTitle className="text-left text-[18px]">{t("passkeyPromptTitle")}</DialogTitle>
          <DialogDescription className="text-left text-[13.5px] leading-relaxed">
            {t("passkeyPromptBody")}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <p data-testid="passkey-prompt-error" className="text-[13px] text-destructive">
            {error}
          </p>
        ) : null}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            data-testid="passkey-prompt-later"
            variant="ghost"
            disabled={busy}
            onClick={close}
            className="h-11 rounded-[10px] text-[14px] text-muted-foreground hover:text-foreground"
          >
            {t("maybeLater")}
          </Button>
          <Button
            data-testid="passkey-prompt-create"
            disabled={busy}
            onClick={create}
            className="h-11 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[14px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Fingerprint className="h-4 w-4" aria-hidden="true" />
            )}
            {t("createPasskey")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PasskeyPrompt;
