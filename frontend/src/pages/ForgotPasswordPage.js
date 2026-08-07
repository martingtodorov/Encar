import { useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound, Loader2, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";
import { apiForgotPassword } from "@/lib/api";
import { FORGOT } from "@/constants/testIds/auth";

/**
 * Ask for a reset link.
 *
 * The screen says the same thing whatever happens — sent, unknown address, unconfirmed
 * address — because the backend answers the same way for all three on purpose: a page that
 * distinguishes them is a free tool for working out who has an account here.
 */
export default function ForgotPasswordPage() {
  const { t, lang } = useApp();
  const { path } = useLangNav();
  useSeo({ lang, title: `${t("forgotTitle")} \u00b7 Encar`, noindex: true });

  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await apiForgotPassword(email.trim(), lang);
    } catch {
      // Deliberately swallowed: the outcome shown must not depend on the answer.
    } finally {
      setBusy(false);
      setSent(true);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto flex max-w-[440px] flex-col px-4 py-12 sm:px-6">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-[hsl(var(--primary))]/10">
          {sent ? (
            <MailCheck className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
          ) : (
            <KeyRound className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
          )}
        </div>

        <h1
          data-testid="forgot-title"
          className="mt-5 text-[26px] font-semibold tracking-tight text-foreground"
        >
          {sent ? t("forgotSentTitle") : t("forgotTitle")}
        </h1>

        {sent ? (
          <p
            data-testid={FORGOT.sentNotice}
            className="mt-3 text-base leading-relaxed text-muted-foreground"
          >
            {t("forgotSentBlurb")}
          </p>
        ) : (
          <>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">
              {t("forgotBlurb")}
            </p>
            <form onSubmit={submit} className="mt-7 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="forgot-email" className="text-[12.5px] font-medium">
                  {t("emailLabel")}
                </Label>
                <Input
                  id="forgot-email"
                  data-testid={FORGOT.emailInput}
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-11 rounded-[10px] bg-card"
                />
              </div>
              <Button
                type="submit"
                data-testid={FORGOT.submitButton}
                disabled={busy || !email.trim()}
                className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {t("forgotSend")}
              </Button>
            </form>
          </>
        )}

        <Link
          to={path("/login")}
          data-testid={FORGOT.backToLogin}
          className="mt-7 text-[13.5px] text-[hsl(var(--primary))] transition-opacity hover:opacity-80"
        >
          {t("forgotBackToLogin")}
        </Link>
      </main>
    </div>
  );
}
