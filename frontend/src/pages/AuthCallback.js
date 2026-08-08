import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertCircle, Loader2 } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { TERMS_VERSION } from "@/lib/legal";

/**
 * The landing strip for the Google redirect: `#session_id=…` arrives in the fragment, is
 * spent exactly once against our backend and then dropped from the address bar.
 *
 * A FIRST-TIME Google buyer has accepted nothing yet, so the backend refuses to create the
 * account (409 `terms_required`) and this screen asks here, before anything is written. The tick
 * made on the sign-up form travels through the redirect in sessionStorage; when it is missing —
 * somebody signing in who turns out not to have an account — the box is shown on this page.
 *
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS
 * THE AUTH.
 */
export const TERMS_HANDOFF = "encar:terms-accepted";

export default function AuthCallback() {
  const { lang, t } = useApp();
  const { googleSession, errorMessage } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState("");
  const [needsTerms, setNeedsTerms] = useState(false);
  const [ticked, setTicked] = useState(false);
  const [busy, setBusy] = useState(false);
  // A ref, not state: it must be set before React can run the effect a second time.
  const started = useRef(false);
  const session = useRef("");
  const back = useRef("");

  const finish = async (termsVersion) => {
    try {
      setBusy(true);
      const answer = await googleSession(session.current, termsVersion);
      if (answer?.mfa_required) {
        navigate(`/${lang}/login`, {
          replace: true,
          state: { mfaPending: answer.pending_id },
        });
        return;
      }
      navigate(back.current || `/${lang}`, { replace: true });
    } catch (e) {
      // 409 is not a failure: it is the account asking to be allowed to exist.
      if (e?.response?.status === 409 && e.response.data?.detail === "terms_required") {
        setNeedsTerms(true);
        return;
      }
      setError(errorMessage(e, t("authFailed")) || t("authFailed"));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const id = new URLSearchParams((location.hash || "").replace(/^#/, "")).get("session_id");
    // Navigating (rather than history.replaceState) is what drops the fragment: the router
    // has to see the change, otherwise this screen would stay up.
    back.current = `${location.pathname}${location.search}`;
    if (!id) {
      navigate(back.current || `/${lang}`, { replace: true });
      return;
    }
    session.current = id;
    const handed = sessionStorage.getItem(TERMS_HANDOFF) || "";
    sessionStorage.removeItem(TERMS_HANDOFF);
    finish(handed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (needsTerms) {
    return (
      <div
        data-testid="auth-callback-terms"
        className="flex min-h-screen items-center justify-center bg-background px-6"
      >
        <div className="w-full max-w-[420px] rounded-[16px] border border-border bg-card p-6">
          <h1 className="text-[17px] font-semibold text-foreground">{t("createAccount")}</h1>
          <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-[12px] border border-border bg-background p-3.5">
            <Checkbox
              data-testid="callback-terms-checkbox"
              checked={ticked}
              onCheckedChange={(v) => setTicked(!!v)}
              className="mt-0.5 shrink-0"
            />
            <span className="text-[12.5px] leading-relaxed text-muted-foreground">
              {t("termsAcceptLead")}{" "}
              <a
                href={`/${lang}/terms`}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-primary hover:underline"
              >
                {t("legalTerms")}
              </a>{" "}
              {t("termsAcceptAnd")}{" "}
              <a
                href={`/${lang}/privacy`}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-primary hover:underline"
              >
                {t("legalPrivacy")}
              </a>
              .
            </span>
          </label>
          <Button
            data-testid="callback-terms-continue"
            disabled={!ticked || busy}
            onClick={() => finish(TERMS_VERSION)}
            className="mt-4 h-11 w-full rounded-[10px] text-[14px] font-semibold"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : t("createAccount")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="auth-callback"
      className="flex min-h-screen items-center justify-center bg-background px-6"
    >
      {error ? (
        <div className="flex max-w-[380px] flex-col items-center gap-4 text-center">
          <AlertCircle className="h-7 w-7 text-destructive" aria-hidden="true" />
          <p data-testid="auth-callback-error" className="text-[14px] text-foreground">
            {error}
          </p>
          <button
            type="button"
            data-testid="auth-callback-retry"
            onClick={() => navigate(`/${lang}/login`, { replace: true })}
            className="text-[13.5px] font-semibold text-[hsl(var(--primary))] hover:opacity-80"
          >
            {t("login")}
          </button>
        </div>
      ) : (
        <Loader2
          data-testid="auth-callback-spinner"
          className="h-6 w-6 animate-spin text-muted-foreground"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
