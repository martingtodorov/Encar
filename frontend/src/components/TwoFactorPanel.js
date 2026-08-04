import { useState } from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import http from "@/lib/api";

/**
 * Authenticator-app second factor.
 *
 * Three states in one card: off (a button), enrolling (QR + code), and on (a badge, the
 * number of recovery codes left, and the two destructive actions behind the password).
 * The secret is never enabled until a real code proves the app actually has it.
 */
export const TwoFactorPanel = () => {
  const { t } = useApp();
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState(null);
  const [busy, setBusy] = useState(false);
  const on = Boolean(user?.twofa);

  const fail = (e, fallback) =>
    toast.error(e?.response?.data?.detail || fallback);

  const begin = async () => {
    setBusy(true);
    try {
      const { data } = await http.post("/auth/2fa/setup");
      setSetup(data);
    } catch (e) {
      fail(e, "could not start the setup");
    } finally {
      setBusy(false);
    }
  };

  const enable = async () => {
    setBusy(true);
    try {
      const { data } = await http.post("/auth/2fa/enable", { code });
      setCodes(data.recovery_codes);
      setSetup(null);
      setCode("");
      await refresh();
      toast.success(t("twofaEnabled"));
    } catch (e) {
      fail(e, t("twofaCodeWrong") || "that code is not right");
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      await http.post("/auth/2fa/disable", { password });
      setPassword("");
      await refresh();
      toast.success(t("twofaDisabled"));
    } catch (e) {
      fail(e, "wrong password");
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setBusy(true);
    try {
      const { data } = await http.post("/auth/2fa/recovery-codes", { password });
      setCodes(data.recovery_codes);
      setPassword("");
      await refresh();
    } catch (e) {
      fail(e, "wrong password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="account-2fa"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
            <ShieldCheck className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
            {t("twofaTitle")}
          </h2>
          <p className="mt-1 max-w-lg text-[12.5px] leading-relaxed text-muted-foreground">
            {t("twofaBlurb")}
          </p>
        </div>
        <span
          data-testid="account-2fa-state"
          className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold uppercase tracking-wide ${
            on
              ? "bg-secondary text-[hsl(var(--primary))]"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {on ? t("twofaOn") : t("twofaOff")}
        </span>
      </div>

      {!on && !setup && (
        <Button
          data-testid="account-2fa-start"
          onClick={begin}
          disabled={busy}
          className="mt-4 h-10 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {t("twofaEnable")}
        </Button>
      )}

      {setup && (
        <div className="mt-4 rounded-[12px] border border-border bg-background p-4">
          <p className="text-[12.5px] leading-relaxed text-muted-foreground">
            {t("twofaScan")}
          </p>
          {setup.qr_data_url && (
            <img
              data-testid="account-2fa-qr"
              src={setup.qr_data_url}
              alt={t("twofaTitle")}
              className="mt-3 h-44 w-44 rounded-[10px] bg-white p-2"
            />
          )}
          <div className="mt-3 text-[12px] text-muted-foreground">
            {t("twofaManualKey")}:{" "}
            <code data-testid="account-2fa-key" className="break-all font-medium text-foreground">
              {setup.manual_key}
            </code>
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-[12px] font-medium text-muted-foreground">
                {t("twofaCodeLabel")}
              </span>
              <Input
                data-testid="account-2fa-code"
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="tnum h-10 w-32 bg-card text-center text-[16px] tracking-[0.3em]"
              />
            </label>
            <Button
              data-testid="account-2fa-verify"
              onClick={enable}
              disabled={busy || code.length !== 6}
              className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
            >
              {t("twofaVerify")}
            </Button>
          </div>
        </div>
      )}

      {codes && (
        <div
          data-testid="account-2fa-recovery"
          className="mt-4 rounded-[12px] border border-[hsl(var(--primary))]/40 bg-secondary p-4"
        >
          <h3 className="text-[13.5px] font-semibold text-foreground">
            {t("twofaRecoveryTitle")}
          </h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            {t("twofaRecoveryBlurb")}
          </p>
          <pre className="tnum mt-3 grid grid-cols-2 gap-1 rounded-[10px] bg-card p-3 text-[12.5px] text-foreground">
            {codes.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </pre>
          <Button
            data-testid="account-2fa-copy"
            variant="outline"
            onClick={() => {
              navigator.clipboard?.writeText(codes.join("\n"));
              toast.success(t("twofaRecoveryCopy"));
            }}
            className="mt-3 h-9 rounded-[10px] border-border bg-card px-3 text-[13px]"
          >
            {t("twofaRecoveryCopy")}
          </Button>
        </div>
      )}

      {on && (
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <span className="tnum mr-auto text-[12px] text-muted-foreground">
            {user.recovery_codes_left} {t("twofaRecoveryLeft")}
          </span>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">
              {t("twofaPasswordLabel")}
            </span>
            <Input
              data-testid="account-2fa-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 w-48 bg-background"
            />
          </label>
          <Button
            data-testid="account-2fa-new-codes"
            variant="outline"
            onClick={regenerate}
            disabled={busy || !password}
            className="h-10 rounded-[10px] border-border bg-card px-3 text-[13px]"
          >
            {t("twofaNewCodes")}
          </Button>
          <Button
            data-testid="account-2fa-disable"
            variant="ghost"
            onClick={disable}
            disabled={busy || !password}
            className="h-10 rounded-[10px] px-3 text-[13px] text-destructive hover:bg-destructive/10"
          >
            {t("twofaDisable")}
          </Button>
        </div>
      )}
    </section>
  );
};

export default TwoFactorPanel;
