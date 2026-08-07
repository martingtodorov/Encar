import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertCircle, CheckCircle2, Loader2, LockKeyhole } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";
import { apiResetPassword, apiResetValid } from "@/lib/api";
import { RESET } from "@/constants/testIds/auth";

const MIN_PASSWORD = 8;

/**
 * Spend the link from the letter.
 *
 * The token is checked before the form is shown, so a dead link says so instead of taking a
 * password and then refusing it. A successful reset drops every session the account had,
 * which is the whole point: signing in again is the proof that the new password is known.
 */
export default function ResetPasswordPage() {
  const { t, lang } = useApp();
  const { path } = useLangNav();
  useSeo({ lang, title: `${t("resetTitle")} \u00b7 Encar`, noindex: true });

  const [params] = useSearchParams();
  const token = params.get("token") || "";

  const [state, setState] = useState("checking");   // checking | ready | dead | done
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState("dead");
      return undefined;
    }
    apiResetValid(token)
      .then(({ valid }) => !cancelled && setState(valid ? "ready" : "dead"))
      .catch(() => !cancelled && setState("dead"));
    return () => {
      cancelled = true;
    };
  }, [token]);

  const say = (err) => {
    const d = err?.response?.data?.detail;
    const kind = typeof d === "object" ? d.code : "";
    if (kind === "too_short") return t("passwordTooShort", { n: d.min ?? MIN_PASSWORD });
    if (kind === "expired" || kind === "bad_token") return t("resetDeadBlurb");
    return t("resetFailed");
  };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < MIN_PASSWORD) {
      setError(t("passwordTooShort", { n: MIN_PASSWORD }));
      return;
    }
    if (password !== confirm) {
      setError(t("resetMismatch"));
      return;
    }
    setBusy(true);
    try {
      await apiResetPassword(token, password);
      setState("done");
    } catch (err) {
      setError(say(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto flex max-w-[440px] flex-col px-4 py-12 sm:px-6">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-[hsl(var(--primary))]/10">
          {state === "done" ? (
            <CheckCircle2 className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
          ) : (
            <LockKeyhole className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
          )}
        </div>

        <h1
          data-testid="reset-title"
          className="mt-5 text-[26px] font-semibold tracking-tight text-foreground"
        >
          {state === "done" ? t("resetDoneTitle") : t("resetTitle")}
        </h1>

        {state === "checking" ? (
          <p className="mt-4 flex items-center gap-2 text-base text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t("resetChecking")}
          </p>
        ) : null}

        {state === "dead" ? (
          <>
            <p
              data-testid={RESET.deadLink}
              className="mt-3 text-base leading-relaxed text-muted-foreground"
            >
              {t("resetDeadBlurb")}
            </p>
            <Link
              to={path("/forgot-password")}
              className="mt-6 inline-flex h-12 items-center justify-center rounded-[12px] bg-[hsl(var(--primary))] px-5 text-[15px] font-semibold text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90"
            >
              {t("resetAskAgain")}
            </Link>
          </>
        ) : null}

        {state === "done" ? (
          <>
            <p
              data-testid={RESET.done}
              className="mt-3 text-base leading-relaxed text-muted-foreground"
            >
              {t("resetDoneBlurb")}
            </p>
            <Link
              to={path("/login")}
              className="mt-6 inline-flex h-12 items-center justify-center rounded-[12px] bg-[hsl(var(--primary))] px-5 text-[15px] font-semibold text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90"
            >
              {t("login")}
            </Link>
          </>
        ) : null}

        {state === "ready" ? (
          <>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">
              {t("resetBlurb")}
            </p>
            <form onSubmit={submit} className="mt-7 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reset-password" className="text-[12.5px] font-medium">
                  {t("passwordNew")}
                </Label>
                <Input
                  id="reset-password"
                  data-testid={RESET.passwordInput}
                  type="password"
                  required
                  autoFocus
                  minLength={MIN_PASSWORD}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-11 rounded-[10px] bg-card"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reset-confirm" className="text-[12.5px] font-medium">
                  {t("resetConfirmLabel")}
                </Label>
                <Input
                  id="reset-confirm"
                  data-testid={RESET.confirmInput}
                  type="password"
                  required
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="h-11 rounded-[10px] bg-card"
                />
              </div>

              {error ? (
                <div
                  data-testid={RESET.error}
                  role="alert"
                  className="flex items-start gap-2 rounded-[10px] border border-destructive/40 bg-secondary px-3 py-2.5 text-[13px] text-foreground"
                >
                  <AlertCircle
                    className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
                    aria-hidden="true"
                  />
                  <span>{error}</span>
                </div>
              ) : null}

              <Button
                type="submit"
                data-testid={RESET.submitButton}
                disabled={busy || !password || !confirm}
                className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {t("resetSave")}
              </Button>

              <p className="text-[11.5px] leading-relaxed text-muted-foreground">
                {t("resetSignsOut")}
              </p>
            </form>
          </>
        ) : null}
      </main>
    </div>
  );
}
