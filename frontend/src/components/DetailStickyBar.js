import { useEffect, useState } from "react";
import { Heart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";

/**
 * Condensed car bar: what the car is, what it costs, and the save button.
 *
 * On mobile it is the ONLY place those live, so it is always on screen. On desktop the
 * page header already shows them at full size, so the bar only slides in once they have
 * scrolled away.
 */
export const DetailStickyBar = ({ car, price, saved, onToggleSave, showAfter = 340 }) => {
  const { t } = useApp();
  const [show, setShow] = useState(false);

  useEffect(() => {
    const onScroll = () => setShow(window.scrollY > showAfter);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [showAfter]);

  if (!car) return null;

  const subtitle = [car.grade, car.badge_detail].filter(Boolean).join(" \u00b7 ");

  return (
    <div
      data-testid="detail-sticky-bar"
      data-visible={show ? "true" : "false"}
      // `fixed`, not `sticky`: a sticky bar sits in normal flow and would reserve its
      // full height under the header even while invisible, pushing the page content down.
      className={`fixed inset-x-0 top-16 z-30 border-b border-border bg-card/95 shadow-sm backdrop-blur-md transition-all duration-200 ${
        show
          ? "pointer-events-auto translate-y-0 opacity-100"
          : "pointer-events-auto translate-y-0 opacity-100 lg:pointer-events-none lg:-translate-y-2 lg:opacity-0 lg:shadow-none"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-[1280px] items-center gap-3 px-4 sm:px-6">
        <div className="min-w-0 flex-1">
          <div
            data-testid="sticky-title"
            className="truncate text-[16px] font-semibold leading-tight text-foreground"
          >
            {car.title}
          </div>
          {subtitle ? (
            <div className="truncate text-[13px] text-muted-foreground">{subtitle}</div>
          ) : null}
        </div>

        <div
          data-testid="sticky-price"
          className="tnum shrink-0 text-[20px] font-semibold tracking-tight text-foreground"
        >
          {price}
        </div>

        <Button
          data-testid="sticky-save-button"
          variant="outline"
          onClick={onToggleSave}
          aria-label={saved ? t("saved") : t("save")}
          title={saved ? t("saved") : t("save")}
          className="h-10 w-10 shrink-0 rounded-[10px] border border-input bg-card p-0 shadow-sm hover:bg-muted"
        >
          <Heart
            className={`h-[18px] w-[18px] ${
              saved
                ? "fill-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                : "text-muted-foreground"
            }`}
            aria-hidden="true"
          />
        </Button>
      </div>
    </div>
  );
};

export default DetailStickyBar;
