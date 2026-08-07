import { useEffect, useRef, useState } from "react";
import { Loader2, MailCheck, RotateCw } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";
import { HeaderBar } from "@/components/HeaderBar";

const COOLDOWN = 60;

/**
 * The six digits that prove the address is real.
 *
 * The session already exists at this point — the buyer registered and is signed in — so this
 * page is a gate on TRUST, not on access: nothing sensitive is reachable until it is passed,
 * and the code is worthless after fifteen minutes or five wrong guesses.
 */
export default function VerifyEmailPage() {
  const { t, lang } = useApp();
  const { user, verifyEmail, resendCode, errorMessage } = useAuth();
  const { go } = useLangNav();
  useSeo({ lang, title: `${t("verifyTitle")} \u00b7 Encar`, noindex: true });

  const [code, setCode] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [left, setLeft] = useState(COOLDOWN);
  const timer = useRef(null);

  useEffect(() => {
    if (!user) go("/login", { replace: true });
    else if (user.email_verified) go("/account", { replace: true });
  }, [user, go]);

  useEffect(() => {
    timer.current = setInterval(() => setLeft((n) => (n > 0 ? n - 1 : 0)), 1000);
    return () => clearInterval(timer.current);
  }, []);

  /** The backend answers with a code, not a sentence: the words live in our own dictionary. */
  const say = (err) => {
    const d = err?.response?.data?.detail;
    const kind = typeof d === "object" ? d.code : "";
    if (kind === "wrong") return t("verifyWrong").replace("{n}", String(d.left ?? 0));
    if (kind === "expired") return t("verifyExpired");
    if (kind === "too_many_attempts") return t("verifyTooMany");
    if (kind === "cooldown") return t("verifyResendIn").replace("{n}", String(d.seconds ?? 0));
    if (kind === "too_many_sends") return t("verifyTooManySends");
    return errorMessage(err, t("verifyFailed"));
  };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy("verify");
    try {
      await verifyEmail(code.trim());
      go("/account", { replace: true });
    } catch (err) {
      setError(say(err));
    } finally {
      setBusy("");
    }
  };

  const again = async () => {
    setError("");
    setBusy("resend");
    try {
      await resendCode(lang);
      setLeft(COOLDOWN);
      setCode("");
    } catch (err) {
      setError(say(err));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto flex max-w-[440px] flex-col px-4 py-12 sm:px-6">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-[hsl(var(--primary))]/10">
          <MailCheck className="h-5 w-5 text-[hsl(var(--primary))]" aria-hidden="true" />
        </div>
        <h1
          data-testid="verify-title"
          className="mt-5 text-4xl font-semibold tracking-tight text-foreground sm:text-5xl"
        >
          {t("verifyTitle")}
        </h1>
        <p data-testid="verify-blurb" className="mt-3 text-base text-muted-foreground sm:text-lg">
          {t("verifyBlurb").replace("{email}", user?.email || "")}
        </p>

        <form onSubmit={submit} className="mt-8 flex flex-col gap-4">
          <input
            data-testid="verify-code-input"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            placeholder="000000"
            aria-label={t("verifyCodeLabel")}
            className="tnum h-14 rounded-[12px] border border-border bg-card px-4 text-center text-2xl font-semibold tracking-[0.4em] text-foreground outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-[hsl(var(--primary))]"
          />

          {error ? (
            <p data-testid="verify-error" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            data-testid="verify-submit"
            disabled={code.length < 6 || busy === "verify"}
            className="inline-flex h-12 items-center justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] px-5 text-[15px] font-semibold text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy === "verify" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : null}
            {t("verifyConfirm")}
          </button>

          <button
            type="button"
            data-testid="verify-resend"
            onClick={again}
            disabled={left > 0 || busy === "resend"}
            className="inline-flex items-center justify-center gap-2 text-[13.5px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-60"
          >
            <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
            {left > 0
              ? t("verifyResendIn").replace("{n}", String(left))
              : t("verifyResend")}
          </button>
        </form>

        <p data-testid="verify-later" className="mt-8 text-sm text-muted-foreground">
          {t("verifyLater")}
        </p>
      </main>
    </div>
  );
}
