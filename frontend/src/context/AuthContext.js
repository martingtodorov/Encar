import { getConsent, markSignedIn, setConsent } from "@/lib/taste";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  apiGoogleSession,
  apiLogin,
  apiLogout,
  apiMe,
  apiPasskeyLoginOptions,
  apiPasskeyLoginVerify,
  apiPasskeyRegisterOptions,
  apiPasskeyRegisterVerify,
  apiPutFavourites,
  apiPutSearches,
  apiRegister,
  apiResendCode,
  apiVerifyEmail,
  saveBilling,
} from "@/lib/api";
import http from "@/lib/api";
import { createCredential, getCredential, passkeySupported } from "@/lib/passkey";
import { TERMS_VERSION } from "@/lib/legal";
import { useApp } from "@/context/AppContext";

const AuthContext = createContext(null);

/** Turn an axios error into something worth showing a human. */
function message(e, fallback) {
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (e?.name === "NotAllowedError" || e?.message === "cancelled") return null; // user cancelled
  return e?.message || fallback;
}

export function AuthProvider({ children }) {
  const { favourites, replaceFavourites, searches, replaceSearches, setAuthed } = useApp();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // Drives the one-time passkey offer: set by registration, cleared once it is answered.
  const [justRegistered, setJustRegistered] = useState(false);

  // Which account's lists are actually in memory. The debounced writers below refuse to
  // run until this matches the signed-in user: before hydration the lists are empty, and
  // an empty PUT would erase every favourite and saved search on the account.
  const hydratedFor = useRef(null);

  // Take the account's lists as they are. There is nothing to merge any more: favourites
  // and saved searches are only ever created while signed in, so the server copy is the
  // only copy — a signed-out browser holds nothing to fold in.
  const adopt = useCallback(
    (nextUser) => {
      hydratedFor.current = nextUser?.id || null;
      setUser(nextUser);
      setAuthed(!!nextUser);
      replaceFavourites(nextUser?.favourites || []);
      replaceSearches(nextUser?.saved_searches || []);
    },
    [replaceFavourites, replaceSearches, setAuthed]
  );

  useEffect(() => {
    let alive = true;
    // Coming back from the Google redirect the cookie does not exist YET: AuthCallback is
    // about to exchange the session_id. Probing /auth/me here would only race it.
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const { user: u } = await apiMe();
        if (!alive) return;
        // Straight from the account: these lists have no local counterpart to reconcile.
        adopt(u);
      } catch (e) {
        /* not signed in */
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the account copy up to date while signed in.
  useEffect(() => {
    if (!user || hydratedFor.current !== user.id) return;
    const id = setTimeout(() => {
      apiPutFavourites(favourites).catch(() => {});
    }, 800);
    return () => clearTimeout(id);
  }, [favourites, user?.id]);

  useEffect(() => {
    if (!user || hydratedFor.current !== user.id) return;
    const id = setTimeout(() => {
      apiPutSearches(searches).catch(() => {});
    }, 800);
    return () => clearTimeout(id);
  }, [searches, user?.id]);

  const login = useCallback(
    async (email, password) => {
      const answer = await apiLogin({ email, password });
      // With 2FA on the password buys a ticket, not a session: the caller collects the code.
      if (answer.mfa_required) return answer;
      adopt(answer.user);
      return answer.user;
    },
    [adopt]
  );

  /** Google sign-in, second half: exchange the one-time id for a session of our own. */
  const googleSession = useCallback(
    async (sessionId, termsVersion = "") => {
      const answer = await apiGoogleSession(sessionId, termsVersion);
      if (answer.mfa_required) return answer;
      adopt(answer.user);
      return answer;
    },
    [adopt]
  );

  /** Second step of a password sign-in: the code from the app, or a recovery code. */
  const loginMfa = useCallback(
    async (pendingId, code, recovery = false) => {
      const { data } = await http.post("/auth/2fa/login", {
        pending_id: pendingId, code, recovery,
      });
      adopt(data.user);
      return data.user;
    },
    [adopt]
  );

  /** Re-read the account after a change made outside this context (2FA, billing). */
  const refresh = useCallback(async () => {
    const { user: u } = await apiMe();
    setUser(u || null);
    return u;
  }, []);

  const register = useCallback(
    async (email, password, name, phone, billing, lang = "") => {
      // billing and the accepted policy version travel WITH the registration: the address
      // typed on the sign-up form was being collected and then dropped on the floor here.
      // `phone` is now a required top-level field (see `Credentials` in `/app/backend/auth.py`)
      // — the office reaches the buyer through it to arrange inspection and shipping.
      const { user: u } = await apiRegister({
        email,
        password,
        name: name || "",
        phone,
        lang,
        billing: billing || undefined,
        terms_version: TERMS_VERSION,
      });
      adopt(u);
      setJustRegistered(true);
      return u;
    },
    [adopt]
  );

  /** The six digits from the email. On success the user object carries email_verified. */
  const verifyEmail = useCallback(async (code) => {
    const { user: u } = await apiVerifyEmail(code);
    setUser(u || null);
    return u;
  }, []);

  const resendCode = useCallback((lang = "") => apiResendCode(lang), []);

  const logout = useCallback(async () => {
    await apiLogout().catch(() => {});
    hydratedFor.current = null;
    setUser(null);
    setAuthed(false);
    // Saving requires an account, so nothing that belonged to one may be left behind on
    // what could well be a shared machine.
    replaceFavourites([]);
    replaceSearches([]);
  }, [replaceFavourites, replaceSearches, setAuthed]);

  /** One tap, no email typed: the authenticator picks the passkey for this site. */
  const passkeyLogin = useCallback(async () => {
    const start = await apiPasskeyLoginOptions();
    const credential = await getCredential(start.options);
    const { user: u } = await apiPasskeyLoginVerify({
      flow_id: start.flow_id,
      credential,
    });
    adopt(u);
    return u;
  }, [adopt]);

  const addPasskey = useCallback(async () => {
    const start = await apiPasskeyRegisterOptions();
    const credential = await createCredential(start.options);
    const res = await apiPasskeyRegisterVerify({
      flow_id: start.flow_id,
      credential,
    });
    setUser((p) => (p ? { ...p, passkeys: res.passkeys } : p));
    return res;
  }, []);

  const clearJustRegistered = useCallback(() => setJustRegistered(false), []);

  const updateBilling = useCallback(async (billing) => {
    const u = await saveBilling(billing);
    setUser(u);
    return u;
  }, []);

  useEffect(() => {
    // Signed-in buyers get their profile mirrored to the account; taste.js needs to know,
    // and the session cookie is httpOnly so it cannot check for itself.
    markSignedIn(!!user);
    // Consent recorded on the account means we do not ask again on a new device.
    if (user?.consent_record?.cats) setConsent(user.consent_record);
    else if (user?.consent && !getConsent()) setConsent(user.consent);
  }, [user]);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      loginMfa,
      googleSession,
      refresh,
      register,
      verifyEmail,
      resendCode,
      logout,
      passkeyLogin,
      addPasskey,
      updateBilling,
      passkeySupported: passkeySupported(),
      errorMessage: message,
      justRegistered,
      clearJustRegistered,
    }),
    [user, loading, login, loginMfa, googleSession, refresh, register, verifyEmail, resendCode,
     logout, passkeyLogin,
     addPasskey,
     updateBilling,
     justRegistered,
     clearJustRegistered]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
