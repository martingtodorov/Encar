import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Bookmark, Heart, LogIn, UserPlus } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { stripLang } from "@/lib/seo";

/**
 * Saving is for people with an account.
 *
 * A favourite or a saved search that lives only in one browser is a promise we cannot keep —
 * it is gone on the next device, and the price-drop and new-match emails have nowhere to go.
 * So the heart and "save this search" ask for an account FIRST, in a dialog rather than a
 * redirect, and the buyer comes straight back to the car or the search they were on.
 */
const GateContext = createContext(null);

export function SignInGate({ children }) {
  const { t } = useApp();
  const { user, loading } = useAuth();
  const { go } = useLangNav();
  const location = useLocation();
  const [asking, setAsking] = useState("");

  const requireAccount = useCallback(
    (what = "car") => {
      if (user) return true;
      // Still checking the session: refusing here would be wrong, asking would flash a
      // dialog at somebody who is in fact signed in.
      if (loading) return false;
      setAsking(what);
      return false;
    },
    [user, loading]
  );

  const value = useMemo(() => ({ requireAccount }), [requireAccount]);

  const leave = (to) => {
    setAsking("");
    // Without the language prefix: `go` puts it back, and the login page navigates with `go`.
    go(to, { state: { from: `${stripLang(location.pathname)}${location.search}` } });
  };

  const Icon = asking === "search" ? Bookmark : Heart;

  return (
    <GateContext.Provider value={value}>
      {children}
      <Dialog open={!!asking} onOpenChange={(open) => !open && setAsking("")}>
        <DialogContent
          data-testid="signin-gate-dialog"
          className="max-h-[88svh] w-[calc(100vw-2rem)] max-w-[400px] overflow-y-auto bg-card"
        >
          <DialogHeader>
            <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-[12px] bg-secondary">
              <Icon className="h-[21px] w-[21px] text-[hsl(var(--primary))]" aria-hidden="true" />
            </div>
            <DialogTitle data-testid="signin-gate-title" className="text-[17px]">
              {asking === "search" ? t("gateSearchTitle") : t("gateCarTitle")}
            </DialogTitle>
            <DialogDescription className="text-[13px] leading-relaxed">
              {asking === "search" ? t("gateSearchBody") : t("gateCarBody")}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-1 flex flex-col gap-2.5">
            <Button
              data-testid="signin-gate-login"
              onClick={() => leave("/login")}
              className="h-11 w-full justify-center gap-2 rounded-[11px] bg-[hsl(var(--primary))] text-[14.5px] font-semibold text-primary-foreground hover:brightness-110"
            >
              <LogIn className="h-[17px] w-[17px]" aria-hidden="true" />
              {t("login")}
            </Button>
            <Button
              variant="outline"
              data-testid="signin-gate-register"
              onClick={() => leave("/login?mode=register")}
              className="h-11 w-full justify-center gap-2 rounded-[11px] border-border bg-card text-[14.5px] font-medium hover:bg-muted"
            >
              <UserPlus className="h-[17px] w-[17px]" aria-hidden="true" />
              {t("register")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </GateContext.Provider>
  );
}

/** Components rendered outside the provider (tests, storybook) simply are not gated. */
export function useGate() {
  return useContext(GateContext) || { requireAccount: () => true };
}

export default SignInGate;
