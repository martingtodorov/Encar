import { useCallback, useEffect, useState } from "react";
import { Activity, ChevronDown, ChevronUp } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { getTraffic } from "@/lib/api";

const POLL_MS = 20000;
const BAR_HEIGHT = "28px";

const fmt = (n) => new Intl.NumberFormat("bg-BG").format(n || 0);

/**
 * A thin strip above the header, for administrators only.
 *
 * It sets `--admin-bar-h` on the document while it is mounted and the header reads that as its
 * sticky offset, so the two stack instead of overlapping. Nobody else ever renders this: the
 * endpoint behind it refuses a non-admin, so a curious visitor editing state in devtools gets
 * a 401 rather than the numbers.
 */
export const AdminTrafficBar = () => {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;

  const [data, setData] = useState(null);
  const [open, setOpen] = useState(true);

  const load = useCallback(async () => {
    try {
      setData(await getTraffic());
    } catch {
      setData(null);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return undefined;
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [isAdmin, load]);

  useEffect(() => {
    const root = document.documentElement;
    if (!isAdmin) {
      root.style.removeProperty("--admin-bar-h");
      return undefined;
    }
    root.style.setProperty("--admin-bar-h", BAR_HEIGHT);
    return () => root.style.removeProperty("--admin-bar-h");
  }, [isAdmin]);

  if (!isAdmin) return null;

  return (
    <div
      data-testid="admin-traffic-bar"
      className="sticky top-0 z-50 border-b border-white/10 bg-[#0f1115] text-white"
      style={{ height: BAR_HEIGHT }}
    >
      <div className="mx-auto flex h-full max-w-[1280px] items-center gap-4 px-3 text-[11.5px] sm:px-6">
        <span className="flex items-center gap-1.5 font-semibold">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
          </span>
          <span data-testid="traffic-live" className="tnum">
            {data ? fmt(data.live) : "—"}
          </span>
          <span className="font-normal text-white/60">
            онлайн{data ? ` (${data.live_minutes} мин)` : ""}
          </span>
        </span>

        {open && data?.pages?.length ? (
          <span
            data-testid="traffic-pages"
            className="hidden min-w-0 flex-1 truncate text-white/70 md:block"
          >
            {data.pages.map((p) => `${p.count}× ${p.label}`).join(" · ")}
          </span>
        ) : (
          <span className="flex-1" />
        )}

        {open && (
          <span data-testid="traffic-windows" className="tnum hidden gap-4 sm:flex">
            <Window label="24ч" w={data?.day} />
            <Window label="7дни" w={data?.week} />
            <Window label="30дни" w={data?.month} />
          </span>
        )}

        <button
          type="button"
          data-testid="traffic-bar-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Скрий числата" : "Покажи числата"}
          className="flex items-center gap-1 rounded px-1 text-white/50 transition-colors hover:text-white"
        >
          <Activity className="h-3 w-3" aria-hidden="true" />
          {open ? (
            <ChevronUp className="h-3 w-3" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  );
};

const Window = ({ label, w }) => (
  <span className="whitespace-nowrap">
    <span className="text-white/40">{label}</span>{" "}
    <span className="font-semibold">{w ? fmt(w.visitors) : "—"}</span>
    <span className="text-white/40"> посетители · </span>
    <span className="font-semibold">{w ? fmt(w.views) : "—"}</span>
    <span className="text-white/40"> показвания</span>
  </span>
);

export default AdminTrafficBar;
