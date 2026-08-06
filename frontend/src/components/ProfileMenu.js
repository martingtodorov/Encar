import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, Package, ShieldCheck, User } from "lucide-react";
import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";

/** The signed-in buyer's menu: their pages, and the way out. */
export const ProfileMenu = () => {
  const { t } = useApp();
  const { user, logout } = useAuth();
  const { path } = useLangNav();
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    const escape = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, []);

  if (!user) return null;

  const items = [
    { to: "/account", label: t("myAccount"), Icon: User },
    { to: "/purchases", label: t("navPurchases"), Icon: Package },
  ];

  // The person's own first name reads far better on a button than "My account". Falls back
  // to the part of the email before the @ when nobody filled a name in.
  const firstName =
    (user.name || "").trim().split(/\s+/)[0] || (user.email || "").split("@")[0];

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        data-testid="header-profile"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-[10px] border border-input bg-card px-3 text-[13.5px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-[hsl(var(--primary))]">
          {(firstName || "?").slice(0, 1).toUpperCase()}
        </span>
        <span data-testid="header-profile-name" className="max-w-[130px] truncate">
          {firstName}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div
          role="menu"
          data-testid="header-profile-menu"
          className="absolute right-0 top-[calc(100%+8px)] z-50 min-w-[230px] rounded-[16px] border border-border bg-card p-2 shadow-xl"
        >
          <div className="truncate px-3 pb-2 pt-1 text-[12px] text-muted-foreground">
            {user.email}
          </div>

          {items.map(({ to, label, Icon }) => (
            <Link
              key={to}
              to={path(to)}
              role="menuitem"
              data-testid={`header-profile-${to.slice(1)}`}
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[13.5px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              {label}
            </Link>
          ))}

          {user.is_admin && (
            <Link
              to={path("/admin")}
              role="menuitem"
              data-testid="header-profile-admin"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-[13.5px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              Operations
            </Link>
          )}

          <div className="my-1 h-px bg-border" />

          <button
            type="button"
            role="menuitem"
            data-testid="header-logout"
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-left text-[13.5px] font-medium text-destructive transition-colors hover:bg-destructive/10"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {t("logout")}
          </button>
        </div>
      )}
    </div>
  );
};

export default ProfileMenu;
