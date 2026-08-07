import { useEffect, useState } from "react";
import { useSearchParams, useLocation, Link } from "react-router-dom";
import { Fingerprint, Loader2, LogIn, UserPlus, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BLANK_BILLING, BillingFields } from "@/components/BillingFields";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";

const MIN_PASSWORD = 8;

/** Google's own mark. Their brand guidelines require the multicolour G, not an outline. */
function GoogleMark() {
  return (
    <svg className="h-[18px] w-[18px]" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h11.8c-.5 2.7-2.1 5-4.4 6.6v5.5h7.1c4.2-3.8 6.6-9.5 6.6-16.1z" />
      <path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.4l-7.1-5.5c-2 1.3-4.5 2.1-7.4 2.1-5.7 0-10.5-3.8-12.2-9H4.4v5.7C8 41.2 15.4 46 24 46z" />
      <path fill="#FBBC05" d="M11.8 28.2c-.4-1.3-.7-2.7-.7-4.2s.3-2.9.7-4.2v-5.7H4.4A22 22 0 0 0 2 24c0 3.6.9 6.9 2.4 9.9l7.4-5.7z" />
      <path fill="#EA4335" d="M24 10.3c3.2 0 6.1 1.1 8.4 3.3l6.3-6.3C34.9 3.8 29.9 2 24 2 15.4 2 8 6.8 4.4 13.9l7.4 5.7c1.7-5.2 6.5-9.3 12.2-9.3z" />
    </svg>
  );
}

export default function LoginPage() {
  const { t, lang } = useApp();
  const { user, login, loginMfa, register, passkeyLogin, passkeySupported,
          errorMessage } = useAuth();
  const { path, go } = useLangNav();

  useSeo({ lang, title: `${t("login")} \u00b7 Encar`, noindex: true });
  const [params] = useSearchParams();
  const location = useLocation();

  const [mode, setMode] = useState(params.get("mode") === "register" ? "register" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [billing, setBilling] = useState(BLANK_BILLING);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  // Set when the password was right but a second factor is still owed. A Google sign-in on
  // an account with 2FA on lands here too, carrying its ticket in the navigation state.
  const [pending, setPending] = useState(location.state?.mfaPending || "");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);

  useEffect(() => {
    // An account that has not proved its address goes to the code screen, not home: this is
    // also what stops the register redirect from racing with the one below.
    if (user && user.email_verified === false) go("/verify-email", { replace: true });
    else if (user) go("/", { replace: true });
  }, [user, go]);

  const run = async (kind, fn) => {
    setError("");
    setBusy(kind);
    try {
      const to = await fn();
      go(to || "/", { replace: true });
    } catch (e) {
      if (e?.mfa) return;          // a second factor is owed, not a failure
      const msg = errorMessage(e, t("authFailed"));
      if (msg) setError(msg);
    } finally {
      setBusy("");
    }
  };

  const submit = (e) => {
    e.preventDefault();
    // The minimum is a rule for CHOOSING a password, not for typing one that already
    // exists: an older or seeded account can legitimately have a shorter one, and a login
    // form that refuses it locks the owner out of their own site.
    if (mode === "register" && password.length < MIN_PASSWORD) {
      setError(t("passwordTooShort", { n: MIN_PASSWORD }));
      return;
    }
    if (mode === "register")
      // Straight to the code screen: the letter is already on its way, and an address nobody
      // proves is an account we can never send a reset or a reservation to.
      run("register", async () => {
        await register(email, password, name, billing, lang);
        return "/verify-email";
      });
    else
      run("login", async () => {
        const answer = await login(email, password);
        if (answer?.mfa_required) {
          setPending(answer.pending_id);
          // Stop `run` from navigating: the sign-in is not finished yet.
          throw { mfa: true };
        }
      });
  };

  const submitCode = (e) => {
    e.preventDefault();
    run("mfa", () => loginMfa(pending, code, recovery));
  };

  const registering = mode === "register";

  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS
  // THE AUTH. The buyer must come back to the exact origin they are on, whichever domain
  // that is, so the redirect is built from the browser's own location.
  const googleSignIn = () => {
    const redirectUrl = window.location.origin + path("/");
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(
      redirectUrl
    )}`;
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />

      <main className="mx-auto flex max-w-[440px] flex-col px-4 py-10 sm:px-6">
        <h1
          data-testid="login-title"
          className="text-[26px] font-semibold tracking-tight text-foreground"
        >
          {registering ? t("createAccount") : t("welcomeBack")}
        </h1>
        <p className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground">
          {registering ? t("registerBlurb") : t("loginBlurb")}
        </p>

        {pending ? (
          <form
            onSubmit={submitCode}
            data-testid="auth-mfa-form"
            className="mt-6 flex flex-col gap-4"
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="auth-mfa-code" className="text-[12.5px] font-medium">
                {recovery ? t("mfaUseRecovery") : t("mfaTitle")}
              </Label>
              <p className="text-[12.5px] leading-relaxed text-muted-foreground">
                {t("mfaBlurb")}
              </p>
              <Input
                id="auth-mfa-code"
                data-testid="auth-mfa-input"
                autoFocus
                inputMode={recovery ? "text" : "numeric"}
                maxLength={recovery ? 20 : 6}
                value={code}
                onChange={(e) =>
                  setCode(recovery ? e.target.value : e.target.value.replace(/\D/g, ""))
                }
                className={`h-12 bg-background text-[16px] ${
                  recovery ? "" : "tnum text-center tracking-[0.4em]"
                }`}
              />
            </div>

            {error && (
              <div
                data-testid="auth-error"
                role="alert"
                className="flex items-start gap-2 rounded-[10px] border border-destructive/40 bg-secondary px-3 py-2.5 text-[13px] text-foreground"
              >
                <AlertCircle
                  className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
                  aria-hidden="true"
                />
                <span>{error}</span>
              </div>
            )}

            <Button
              data-testid="auth-mfa-submit"
              type="submit"
              disabled={!!busy || code.length < (recovery ? 4 : 6)}
              className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
            >
              {busy === "mfa" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <LogIn className="h-[18px] w-[18px]" aria-hidden="true" />
              )}
              {t("mfaContinue")}
            </Button>

            <button
              type="button"
              data-testid="auth-mfa-toggle"
              onClick={() => {
                setRecovery((v) => !v);
                setCode("");
                setError("");
              }}
              className="text-[13.5px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {recovery ? t("mfaUseApp") : t("mfaUseRecovery")}
            </button>
          </form>
        ) : (
          <>
        {/* Google works for both modes: an unknown email creates the account, a known one
            signs into it, so there is nothing to choose between login and register. */}
        <Button
          data-testid="google-login-button"
          type="button"
          variant="outline"
          onClick={googleSignIn}
          className="mt-6 h-12 w-full justify-center gap-2.5 rounded-[12px] border-border bg-card text-[14.5px] font-medium hover:bg-muted"
        >
          <GoogleMark />
          {t("continueWithGoogle")}
        </Button>

        {/* Passkeys are offered AFTER the account exists (see PasskeyPrompt), never on the
            registration form where there is no account for the credential to belong to. */}
        {passkeySupported && !registering && (
          <Button
            data-testid="passkey-login-button"
            type="button"
            variant="outline"
            disabled={busy === "passkey"}
            onClick={() => run("passkey", passkeyLogin)}
            className="mt-3 h-12 w-full justify-center gap-2 rounded-[12px] border-border bg-card text-[14.5px] font-medium hover:bg-muted"
          >
            {busy === "passkey" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Fingerprint className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
            )}
            {t("signInWithPasskey")}
          </Button>
        )}

        <div className="my-5 flex items-center gap-3">
          <Separator className="flex-1" />
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("orDivider")}
          </span>
          <Separator className="flex-1" />
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4" data-testid="auth-form">
          {registering && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="auth-name" className="text-[12.5px] font-medium">
                {t("nameLabel")}
              </Label>
              <Input
                id="auth-name"
                data-testid="auth-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                className="h-11 rounded-[10px] bg-card"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auth-email" className="text-[12.5px] font-medium">
              {t("emailLabel")}
            </Label>
            <Input
              id="auth-email"
              data-testid="auth-email-input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className="h-11 rounded-[10px] bg-card"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auth-password" className="text-[12.5px] font-medium">
              {t("passwordLabel")}
            </Label>
            <Input
              id="auth-password"
              data-testid="auth-password-input"
              type="password"
              required
              minLength={registering ? MIN_PASSWORD : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={registering ? "new-password" : "current-password"}
              className="h-11 rounded-[10px] bg-card"
            />
            {registering && (
              <p className="text-[11.5px] text-muted-foreground">
                {t("passwordHint", { n: MIN_PASSWORD })}
              </p>
            )}
          </div>

          {registering && (
            <div className="rounded-[12px] border border-border bg-background p-4">
              <h2 className="text-[13.5px] font-semibold text-foreground">
                {t("billingTitle")}
              </h2>
              <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
                {t("billingBlurb")} {t("billingOptional")}
              </p>
              <div className="mt-3">
                <BillingFields value={billing} onChange={setBilling} />
              </div>
            </div>
          )}

          {error && (
            <div
              data-testid="auth-error"
              role="alert"
              className="flex items-start gap-2 rounded-[10px] border border-destructive/40 bg-secondary px-3 py-2.5 text-[13px] text-foreground"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <Button
            data-testid="auth-submit-button"
            type="submit"
            disabled={!!busy}
            className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {busy === "login" || busy === "register" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : registering ? (
              <UserPlus className="h-[18px] w-[18px]" aria-hidden="true" />
            ) : (
              <LogIn className="h-[18px] w-[18px]" aria-hidden="true" />
            )}
            {registering ? t("register") : t("login")}
          </Button>
        </form>

        <div className="mt-6 flex flex-col items-center gap-2.5">
          <p className="text-base text-muted-foreground">
            {registering ? t("haveAccountPrompt") : t("noAccountPrompt")}
          </p>
          <Button
            type="button"
            variant="outline"
            data-testid="auth-switch-mode"
            onClick={() => {
              setError("");
              setMode(registering ? "login" : "register");
            }}
            className="h-11 w-full text-[15px] font-semibold"
          >
            {registering ? t("login") : t("register")}
          </Button>
        </div>
          </>
        )}

        <Link
          to={path("/")}
          className="mt-2 text-[13px] text-[hsl(var(--primary))] transition-opacity hover:opacity-80"
        >
          {t("backToSearch")}
        </Link>
      </main>
    </div>
  );
}
