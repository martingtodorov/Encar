import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertCircle, Loader2 } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";

/**
 * The landing strip for the Google redirect: `#session_id=…` arrives in the fragment, is
 * spent exactly once against our backend and then dropped from the address bar.
 *
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS
 * THE AUTH.
 */
export default function AuthCallback() {
  const { lang, t } = useApp();
  const { googleSession, errorMessage } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState("");
  // A ref, not state: it must be set before React can run the effect a second time.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const id = new URLSearchParams((location.hash || "").replace(/^#/, "")).get("session_id");
    // Navigating (rather than history.replaceState) is what drops the fragment: the router
    // has to see the change, otherwise this screen would stay up.
    const back = `${location.pathname}${location.search}`;
    if (!id) {
      navigate(back || `/${lang}`, { replace: true });
      return;
    }
    (async () => {
      try {
        const answer = await googleSession(id);
        if (answer?.mfa_required) {
          navigate(`/${lang}/login`, {
            replace: true,
            state: { mfaPending: answer.pending_id },
          });
          return;
        }
        navigate(back || `/${lang}`, { replace: true });
      } catch (e) {
        setError(errorMessage(e, t("authFailed")) || t("authFailed"));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
