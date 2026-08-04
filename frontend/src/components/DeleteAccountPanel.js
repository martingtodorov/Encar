import { useState } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import http from "@/lib/api";

const WORDS = { bg: "ИЗТРИЙ", ro: "ȘTERGE", en: "DELETE" };

/**
 * Erasure under GDPR.
 *
 * Two locks, because this cannot be undone: the account password, and the confirmation word
 * typed out in full. Paid deposits survive as anonymised accounting records — the money moved
 * and the books must still say so.
 */
export const DeleteAccountPanel = () => {
  const { t, lang } = useApp();
  const { logout } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const word = WORDS[lang] || WORDS.en;

  const remove = async () => {
    setBusy(true);
    try {
      await http.delete("/account", { data: { password, confirm } });
      toast.success(t("deleteDone"));
      await logout();
      window.location.assign(`/${lang}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not delete the account");
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="account-delete"
      className="mt-6 rounded-[16px] border border-destructive/40 bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
        {t("deleteTitle")}
      </h2>
      <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted-foreground">
        {t("deleteBlurb")}
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("twofaPasswordLabel")}
          </span>
          <Input
            data-testid="account-delete-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-10 w-48 bg-background"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("deleteConfirmLabel")}
          </span>
          <Input
            data-testid="account-delete-confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={word}
            className="h-10 w-48 bg-background"
          />
        </label>
        <Button
          data-testid="account-delete-button"
          variant="ghost"
          onClick={remove}
          disabled={busy || !password || confirm.trim().toUpperCase() !== word}
          className="h-10 rounded-[10px] px-4 text-[13.5px] font-semibold text-destructive hover:bg-destructive/10"
        >
          {t("deleteButton")}
        </Button>
      </div>
    </section>
  );
};

export default DeleteAccountPanel;
