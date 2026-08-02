import { useEffect, useState } from "react";
import { Fingerprint, Loader2, LogOut, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useSeo } from "@/lib/seo";
import http from "@/lib/api";

export default function AccountPage() {
  const { t, lang } = useApp();
  const { user, loading, logout, addPasskey, passkeySupported, errorMessage } = useAuth();
  const { go } = useLangNav();

  useSeo({ lang, title: `${t("myAccount")} \u00b7 Encar` });

  const [passkeys, setPasskeys] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) go("/login", { replace: true });
  }, [loading, user, go]);

  const load = async () => {
    try {
      const { data } = await http.get("/auth/passkeys");
      setPasskeys(data.passkeys || []);
    } catch (e) {
      /* not fatal - the count on the user record is still shown */
    }
  };

  useEffect(() => {
    if (user) load();
  }, [user?.id]);

  const onAdd = async () => {
    setBusy(true);
    try {
      await addPasskey();
      await load();
      toast.success(t("passkeyAdded"));
    } catch (e) {
      const msg = errorMessage(e, t("authFailed"));
      if (msg) toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (id) => {
    try {
      await http.delete(`/auth/passkeys/${id}`);
      await load();
      toast.success(t("passkeyRemoved"));
    } catch (e) {
      const msg = errorMessage(e, t("authFailed"));
      if (msg) toast.error(msg);
    }
  };

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-background">
        <HeaderBar />
        <div className="flex justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />

      <main className="mx-auto max-w-[640px] px-4 py-10 sm:px-6">
        <h1
          data-testid="account-title"
          className="text-[26px] font-semibold tracking-tight text-foreground"
        >
          {t("myAccount")}
        </h1>

        <section className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-secondary text-[16px] font-semibold text-[hsl(var(--primary))]">
              {(user.email || "?").slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <div
                data-testid="account-email"
                className="truncate text-[15px] font-medium text-foreground"
              >
                {user.email}
              </div>
              {user.is_admin && (
                <div className="mt-0.5 inline-flex items-center gap-1 text-[12px] text-muted-foreground">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("administrator")}
                </div>
              )}
            </div>
          </div>

          <Separator className="my-5" />

          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-[14.5px] font-semibold text-foreground">{t("passkeys")}</h2>
              <p className="mt-1 max-w-sm text-[12.5px] leading-relaxed text-muted-foreground">
                {t("passkeysBlurb")}
              </p>
            </div>
            {passkeySupported && (
              <Button
                data-testid="add-passkey-button"
                onClick={onAdd}
                disabled={busy}
                className="h-10 shrink-0 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-3 text-[13px] font-medium text-primary-foreground hover:brightness-110"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Plus className="h-4 w-4" aria-hidden="true" />
                )}
                {t("addPasskey")}
              </Button>
            )}
          </div>

          <ul className="mt-4 flex flex-col gap-2" data-testid="passkey-list">
            {passkeys.length === 0 ? (
              <li className="rounded-[10px] bg-muted px-3 py-2.5 text-[13px] text-muted-foreground">
                {t("noPasskeys")}
              </li>
            ) : (
              passkeys.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 rounded-[10px] border border-border px-3 py-2.5"
                >
                  <Fingerprint
                    className="h-4 w-4 shrink-0 text-[hsl(var(--primary))]"
                    aria-hidden="true"
                  />
                  <span className="flex-1 text-[13px] text-foreground">
                    {p.created_at ? new Date(p.created_at).toLocaleDateString() : t("passkeys")}
                  </span>
                  <button
                    type="button"
                    data-testid={`delete-passkey-${p.id}`}
                    onClick={() => onDelete(p.id)}
                    aria-label={t("removePasskey")}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </li>
              ))
            )}
          </ul>
        </section>

        <Button
          data-testid="account-logout-button"
          variant="outline"
          onClick={async () => {
            await logout();
            go("/", { replace: true });
          }}
          className="mt-6 h-11 gap-2 rounded-[10px] border-border bg-card px-4 text-[14px] font-medium hover:bg-muted"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          {t("logout")}
        </Button>
      </main>
    </div>
  );
}
