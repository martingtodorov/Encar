import { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { changePassword } from "@/lib/api";

/**
 * Change the password, proving the current one first.
 *
 * An account that has only ever signed in with Google has no password to prove, so the same
 * card becomes "set a password" — the signed-in session is the proof there.
 */
export const PasswordPanel = () => {
  const { t } = useApp();
  const { user, refresh } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const has = Boolean(user?.has_password);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { signed_out: out } = await changePassword(current, next);
      setCurrent("");
      setNext("");
      await refresh();
      toast.success(t("passwordChanged"), {
        description: out ? t("passwordSignedOut", { n: out }) : undefined,
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("authFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="account-password"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <KeyRound className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        {has ? t("passwordTitle") : t("passwordSetTitle")}
      </h2>
      <p className="mt-1 max-w-lg text-[12.5px] leading-relaxed text-muted-foreground">
        {has ? t("passwordBlurb") : t("passwordSetBlurb")}
      </p>

      <form onSubmit={submit} className="mt-4 flex max-w-sm flex-col gap-3">
        {has && (
          <Input
            data-testid="password-current"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            placeholder={t("passwordCurrent")}
            className="h-11 bg-background text-[14px]"
          />
        )}
        <Input
          data-testid="password-new"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={next}
          onChange={(e) => setNext(e.target.value)}
          placeholder={t("passwordNew")}
          className="h-11 bg-background text-[14px]"
        />
        <Button
          data-testid="password-save"
          type="submit"
          disabled={busy || !next || (has && !current)}
          className="h-11 w-max gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
        >
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {has ? t("passwordSave") : t("passwordSetSave")}
        </Button>
      </form>
    </section>
  );
};

export default PasswordPanel;
