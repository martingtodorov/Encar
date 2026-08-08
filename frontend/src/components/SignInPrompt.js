import { Link } from "react-router-dom";
import { LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";

/** Shown where a signed-out visitor's own list would be: there is nothing to show them. */
export const SignInPrompt = ({ icon: Icon, title, body, testId }) => {
  const { t } = useApp();
  const { path } = useLangNav();

  return (
    <div
      data-testid={testId}
      className="rounded-[16px] border border-border bg-card p-10 text-center"
    >
      <Icon className="mx-auto h-9 w-9 text-muted-foreground" aria-hidden="true" />
      <h2 className="mt-3 text-[16px] font-semibold text-foreground">{title}</h2>
      <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground">{body}</p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <Link to={path("/login")}>
          <Button
            data-testid={`${testId}-login`}
            className="h-10 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-primary-foreground hover:brightness-110"
          >
            <LogIn className="h-4 w-4" aria-hidden="true" />
            {t("login")}
          </Button>
        </Link>
        <Link to={path("/login?mode=register")}>
          <Button
            variant="outline"
            data-testid={`${testId}-register`}
            className="h-10 rounded-[10px] border-border bg-card px-5 hover:bg-muted"
          >
            {t("register")}
          </Button>
        </Link>
      </div>
    </div>
  );
};

export default SignInPrompt;
