import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  apiLogin,
  apiLogout,
  apiMe,
  apiMergeFavourites,
  apiPasskeyLoginOptions,
  apiPasskeyLoginVerify,
  apiPasskeyRegisterOptions,
  apiPasskeyRegisterVerify,
  apiPutFavourites,
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
  const { favourites, replaceFavourites } = useApp();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fold whatever the browser collected while logged out into the account, then adopt
  // the account's list locally so the two never silently diverge.
  const adopt = useCallback(
    async (nextUser, localIds) => {
      setUser(nextUser);
      try {
        const { ids } = await apiMergeFavourites(localIds || []);
        replaceFavourites(ids);
      } catch (e) {
        /* favourites sync is best-effort; never block sign-in on it */
      }
    },
    [replaceFavourites]
  );

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { user: u } = await apiMe();
        if (!alive) return;
        setUser(u);
        if (u?.favourites?.length) replaceFavourites(u.favourites);
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

  const login = useCallback(
    async (email, password) => {
      const local = favourites;
      const { user: u } = await apiLogin({ email, password });
      await adopt(u, local);
      return u;
    },
    [adopt, favourites]
  );

  const register = useCallback(
    async (email, password, name) => {
      const local = favourites;
      const { user: u } = await apiRegister({ email, password, name: name || "" });
      await adopt(u, local);
      return u;
    },
    [adopt, favourites]
  );

  const logout = useCallback(async () => {
    await apiLogout().catch(() => {});
    setUser(null);
  }, []);

  /** One tap, no email typed: the authenticator picks the passkey for this site. */
  const passkeyLogin = useCallback(async () => {
    const local = favourites;
    const start = await apiPasskeyLoginOptions();
    const credential = await getCredential(start.options);
    const { user: u } = await apiPasskeyLoginVerify({
      flow_id: start.flow_id,
      credential,
    });
    await adopt(u, local);
    return u;
  }, [adopt, favourites]);

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
    }),
    [user, loading, login, register, logout, passkeyLogin, addPasskey]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
