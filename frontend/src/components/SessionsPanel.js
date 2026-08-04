import { useCallback, useEffect, useState } from "react";
import { Laptop, Loader2, LogOut, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import http from "@/lib/api";

const when = (iso, lang) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(lang === "en" ? "en-GB" : lang, {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
};

/** Every device signed in to this account, with a way to cut any of them off. */
export const SessionsPanel = () => {
  const { t, lang } = useApp();
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await http.get("/auth/sessions");
      setRows(data.items || []);
    } catch (e) {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const revoke = async (id) => {
    try {
      await http.delete(`/auth/sessions/${id}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not sign that device out");
    }
  };

  const revokeOthers = async () => {
    setBusy(true);
    try {
      await http.post("/auth/sessions/revoke-others");
      await load();
      toast.success(t("sessionsSignedOut"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not sign the other devices out");
    } finally {
      setBusy(false);
    }
  };

  const mobile = (row) => /iPhone|iPad|Android/i.test(`${row.os} ${row.browser}`);

  return (
    <section
      data-testid="account-sessions"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[14.5px] font-semibold text-foreground">{t("sessionsTitle")}</h2>
          <p className="mt-1 max-w-lg text-[12.5px] leading-relaxed text-muted-foreground">
            {t("sessionsBlurb")}
          </p>
        </div>
        {(rows?.length || 0) > 1 && (
          <Button
            data-testid="account-sessions-revoke-others"
            variant="outline"
            onClick={revokeOthers}
            disabled={busy}
            className="h-10 shrink-0 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px]"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
            {t("sessionsRevokeOthers")}
          </Button>
        )}
      </div>

      {rows === null ? (
        <div className="mt-4 flex justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
        </div>
      ) : (
        <ul className="mt-4 divide-y divide-border" data-testid="account-session-list">
          {rows.map((row) => {
            const Icon = mobile(row) ? Smartphone : Laptop;
            return (
              <li
                key={row.id}
                data-testid="account-session-row"
                className="flex flex-wrap items-center gap-3 py-3"
              >
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium text-foreground">
                    {row.label}
                    {row.current && (
                      <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--primary))]">
                        {t("sessionsCurrent")}
                      </span>
                    )}
                  </div>
                  <div className="tnum mt-0.5 text-[12px] text-muted-foreground">
                    {row.ip ? `${row.ip} · ` : ""}
                    {t("sessionsLastActive")} {when(row.last_seen, lang)}
                  </div>
                </div>
                {!row.current && (
                  <Button
                    data-testid={`account-session-revoke-${row.id}`}
                    variant="ghost"
                    onClick={() => revoke(row.id)}
                    className="h-9 rounded-[10px] px-3 text-[13px] text-muted-foreground hover:text-destructive"
                  >
                    {t("sessionsRevoke")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

export default SessionsPanel;
