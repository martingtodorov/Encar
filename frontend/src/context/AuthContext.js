import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
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
} from "@/lib/api";
import { createCredential, getCredential, passkeySupported } from "@/lib/passkey";
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
      const { user: u } = await apiLogin({ email, password });
      await adopt(u, local, localSearches);
      return u;
    },
    [adopt, favourites, searches]
  );

  const register = useCallback(
    async (email, password, name) => {
      const local = favourites;
      const localSearches = searches;
      const { user: u } = await apiRegister({ email, password, name: name || "" });
      await adopt(u, local, localSearches);
      setJustRegistered(true);
      return u;
    },
    [adopt, favourites, searches]
  );

  const logout = useCallback(async () => {
    await apiLogout().catch(() => {});
    setUser(null);
  }, []);

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

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      passkeyLogin,
      addPasskey,
      passkeySupported: passkeySupported(),
      errorMessage: message,
      justRegistered,
      clearJustRegistered,
    }),
    [user, loading, login, register, logout, passkeyLogin, addPasskey, justRegistered,
     clearJustRegistered]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
