import { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { Fingerprint, Loader2, LogIn, UserPlus, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";

const MIN_PASSWORD = 8;

export default function LoginPage() {
  const { t, lang } = useApp();
  const { user, login, register, passkeyLogin, passkeySupported, errorMessage } = useAuth();
  const { path, go } = useLangNav();

  useSeo({ lang, title: `${t("login")} \u00b7 Encar` });
  const [params] = useSearchParams();

  const [mode, setMode] = useState(params.get("mode") === "register" ? "register" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (user) go("/", { replace: true });
  }, [user, go]);

  const run = async (kind, fn) => {
    setError("");
    setBusy(kind);
    try {
      await fn();
      go("/", { replace: true });
    } catch (e) {
      const msg = errorMessage(e, t("authFailed"));
      if (msg) setError(msg);
    } finally {
      setBusy("");
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(t("passwordTooShort", { n: MIN_PASSWORD }));
      return;
    }
    if (mode === "register") run("register", () => register(email, password, name));
    else run("login", () => login(email, password));
  };

  const registering = mode === "register";

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

        {passkeySupported && (
          <>
            <Button
              data-testid="passkey-login-button"
              type="button"
              variant="outline"
              disabled={busy === "passkey"}
              onClick={() => run("passkey", passkeyLogin)}
              className="mt-6 h-12 w-full justify-center gap-2 rounded-[12px] border-border bg-card text-[14.5px] font-medium hover:bg-muted"
            >
              {busy === "passkey" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Fingerprint className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
              )}
              {t("signInWithPasskey")}
            </Button>

            <div className="my-5 flex items-center gap-3">
              <Separator className="flex-1" />
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("orDivider")}
              </span>
              <Separator className="flex-1" />
            </div>
          </>
        )}

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
              minLength={MIN_PASSWORD}
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

        <button
          type="button"
          data-testid="auth-switch-mode"
          onClick={() => {
            setError("");
            setMode(registering ? "login" : "register");
          }}
          className="mt-5 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground"
        >
          {registering ? t("haveAccount") : t("noAccount")}
        </button>

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
