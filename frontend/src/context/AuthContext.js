import { getConsent, markSignedIn, setConsent } from "@/lib/taste";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  apiGoogleSession,
  apiLogin,
  apiLogout,
  apiMe,
  apiMergeFavourites,
  apiMergeSearches,
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
  const { favourites, replaceFavourites, searches, replaceSearches } = useApp();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // Drives the one-time passkey offer: set by registration, cleared once it is answered.
  const [justRegistered, setJustRegistered] = useState(false);

  // Fold whatever the browser collected while logged out into the account, then adopt
  // the account's list locally so the two never silently diverge.
  const adopt = useCallback(
    async (nextUser, localIds, localSearches) => {
      setUser(nextUser);
      try {
        const { ids } = await apiMergeFavourites(localIds || []);
        replaceFavourites(ids);
      } catch (e) {
        /* favourites sync is best-effort; never block sign-in on it */
      }
      try {
        const { items } = await apiMergeSearches(localSearches || []);
        replaceSearches(items);
      } catch (e) {
        /* same for saved searches */
      }
    },
    [replaceFavourites, replaceSearches]
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
        setUser(u);
        if (u?.favourites?.length) replaceFavourites(u.favourites);
        if (u?.saved_searches?.length) replaceSearches(u.saved_searches);
      } catch (e) {
        /* not signed in */
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Keep the account copy up to date while signed in.
  useEffect(() => {
    if (!user) return;
    const id = setTimeout(() => {
      apiPutFavourites(favourites).catch(() => {});
    }, 800);
    return () => clearTimeout(id);
  }, [favourites, user?.id]);

  useEffect(() => {
    if (!user) return;
    const id = setTimeout(() => {
      apiPutSearches(searches).catch(() => {});
    }, 800);
    return () => clearTimeout(id);
  }, [searches, user?.id]);

  const login = useCallback(
    async (email, password) => {
      const local = favourites;
      const localSearches = searches;
      const answer = await apiLogin({ email, password });
      // With 2FA on the password buys a ticket, not a session: the caller collects the code.
      if (answer.mfa_required) return answer;
      await adopt(answer.user, local, localSearches);
      return answer.user;
    },
    [adopt, favourites, searches]
  );

  /** Google sign-in, second half: exchange the one-time id for a session of our own. */
  const googleSession = useCallback(
    async (sessionId) => {
      const local = favourites;
      const localSearches = searches;
      const answer = await apiGoogleSession(sessionId);
      if (answer.mfa_required) return answer;
      await adopt(answer.user, local, localSearches);
      return answer;
    },
    [adopt, favourites, searches]
  );

  /** Second step of a password sign-in: the code from the app, or a recovery code. */
  const loginMfa = useCallback(
    async (pendingId, code, recovery = false) => {
      const local = favourites;
      const localSearches = searches;
      const { data } = await http.post("/auth/2fa/login", {
        pending_id: pendingId, code, recovery,
      });
      await adopt(data.user, local, localSearches);
      return data.user;
    },
    [adopt, favourites, searches]
  );

  /** Re-read the account after a change made outside this context (2FA, billing). */
  const refresh = useCallback(async () => {
    const { user: u } = await apiMe();
    setUser(u || null);
    return u;
  }, []);

  const register = useCallback(
    async (email, password, name, billing, lang = "") => {
      const local = favourites;
      const localSearches = searches;
      // billing and the accepted policy version travel WITH the registration: the address
      // typed on the sign-up form was being collected and then dropped on the floor here.
      const { user: u } = await apiRegister({
        email,
        password,
        name: name || "",
        lang,
        billing: billing || undefined,
        terms_version: TERMS_VERSION,
      });
      await adopt(u, local, localSearches);
      setJustRegistered(true);
      return u;
    },
    [adopt, favourites, searches]
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
    setUser(null);
    // Saving requires an account, so nothing that belonged to one may be left behind on
    // what could well be a shared machine.
    replaceFavourites([]);
    replaceSearches([]);
  }, [replaceFavourites, replaceSearches]);

  /** One tap, no email typed: the authenticator picks the passkey for this site. */
  const passkeyLogin = useCallback(async () => {
    const local = favourites;
    const localSearches = searches;
    const start = await apiPasskeyLoginOptions();
    const credential = await getCredential(start.options);
    const { user: u } = await apiPasskeyLoginVerify({
      flow_id: start.flow_id,
      credential,
    });
    await adopt(u, local, localSearches);
    return u;
  }, [adopt, favourites, searches]);

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
