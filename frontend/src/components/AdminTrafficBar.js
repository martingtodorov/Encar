import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ChevronDown, ChevronUp } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { getTraffic } from "@/lib/api";

const POLL_MS = 20000;

const fmt = (n) => new Intl.NumberFormat("bg-BG").format(n || 0);

/**
 * A thin strip above the header, for administrators only.
 *
 * It publishes its own measured height as `--admin-bar-h` and the header reads that as its
 * sticky offset, so the two stack instead of overlapping. The height is MEASURED, not a
 * constant: on a phone the numbers wrap onto a second row and the bar grows, and the header
 * has to follow or it covers the page's own title. Nobody else ever renders this: the endpoint
 * behind it refuses a non-admin, so a curious visitor editing state in devtools gets a 401
 * rather than the numbers.
 */
export const AdminTrafficBar = () => {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const barRef = useRef(null);

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
    const node = barRef.current;
    if (!isAdmin || !node) {
      root.style.removeProperty("--admin-bar-h");
      return undefined;
    }
    const publish = () =>
      root.style.setProperty("--admin-bar-h", `${Math.round(node.offsetHeight)}px`);
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(node);
    return () => {
      ro.disconnect();
      root.style.removeProperty("--admin-bar-h");
    };
  }, [isAdmin, open, data]);

  if (!isAdmin) return null;

  return (
    <div
      ref={barRef}
      data-testid="admin-traffic-bar"
      className="sticky top-0 z-50 border-b border-white/10 bg-[#0f1115] text-white"
    >
      <div className="mx-auto max-w-[1280px] px-3 text-[11.5px] sm:px-6">
        <div className="flex min-h-[28px] items-center gap-4">
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

          {/* Desktop: the three windows spelled out on the same line. */}
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

        {/* Phone: a second row, because the words do not fit beside the live count. Visitors
            and views are shown as "посетители / показвания" to keep it to one line. */}
        {open && (
          <div
            data-testid="traffic-windows-mobile"
            className="tnum flex items-center gap-3 whitespace-nowrap pb-1.5 pt-0.5 text-white/70 sm:hidden"
          >
            <Compact label="24ч" w={data?.day} />
            <span className="text-white/20">·</span>
            <Compact label="7д" w={data?.week} />
            <span className="text-white/20">·</span>
            <Compact label="30д" w={data?.month} />
          </div>
        )}
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

const Compact = ({ label, w }) => (
  <span>
    <span className="text-white/40">{label}</span>{" "}
    <span className="font-semibold text-white">{w ? fmt(w.visitors) : "—"}</span>
    <span className="text-white/40">/</span>
    <span className="font-semibold text-white">{w ? fmt(w.views) : "—"}</span>
  </span>
);

export default AdminTrafficBar;
