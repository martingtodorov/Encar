import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * The "why did this price change" note that sits beside a price.
 *
 * Every price here is a Korean won amount converted at the day's rate, so it genuinely does
 * move overnight. Saying so next to the number is what stops it reading as a mistake.
 *
 * Hover opens it on a desktop, tap opens it on a phone, and it closes again on the way out,
 * on Escape, or on a tap anywhere else.
 *
 * Deliberately NOT a Radix popover or tooltip: the tooltip never opens on touch, and the
 * popover hands focus to its panel and hands it back on close, which reopened this the moment
 * the mouse left — it looked stuck open for good. A plain panel has no such argument with the
 * pointer.
 */
export const PriceNote = ({ className = "", testId = "price-note" }) => {
  const { t } = useApp();
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  // Only bind hover on a device that really hovers. A phone's browser fires mouseenter on a
  // tap as well, immediately followed by click — the panel would open and shut in one gesture.
  const hovers = useRef(
    typeof window !== "undefined"
      && window.matchMedia?.("(hover: hover) and (pointer: fine)").matches
  );

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    const onDown = (e) => {
      if (!wrap.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  return (
    <span
      ref={wrap}
      className="relative inline-flex"
      onMouseEnter={hovers.current ? () => setOpen(true) : undefined}
      onMouseLeave={hovers.current ? () => setOpen(false) : undefined}
    >
      <button
        type="button"
        data-testid={testId}
        aria-label={t("fxNoteLabel")}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-[hsl(var(--primary))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary))] ${className}`}
      >
        <Info className="h-[18px] w-[18px]" aria-hidden="true" />
      </button>

      {open && (
        <span
          role="note"
          data-testid={`${testId}-content`}
          // Right-aligned: the icon always sits at the end of a price, so a left-aligned
          // panel would hang off the edge of the page.
          className="absolute right-0 top-full z-50 mt-2 w-[250px] rounded-[10px] border border-border bg-card p-3 text-left text-[12.5px] font-normal leading-relaxed text-foreground shadow-lg sm:w-[270px]"
        >
          {t("fxNote")}
        </span>
      )}
    </span>
  );
};

export default PriceNote;
