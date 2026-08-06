import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * Clamps a tall block to about ten rows with a "show all" button under it.
 *
 * The equipment list and the dealer's description are the two blocks that can run to a couple
 * of screens on their own, pushing everything a buyer actually came for below the fold.
 *
 * The height is measured, not guessed: chips wrap differently at every width and a translated
 * description is a different length from the original, so a fixed line-clamp would either cut
 * a short list that fits or leave a long one uncut. Below the ceiling nothing is rendered at
 * all — no button, no fade.
 */
export const ClampBlock = ({ children, maxHeight = 300, testId = "clamp", disabled = false }) => {
  const { t } = useApp();
  const [open, setOpen] = useState(false);
  const [tall, setTall] = useState(false);
  const inner = useRef(null);

  useEffect(() => {
    const el = inner.current;
    if (!el) return undefined;
    const measure = () => setTall(el.scrollHeight > maxHeight + 24);
    measure();
    // Content that arrives late (a streamed translation) or a window resize both change the
    // answer, so it is measured again rather than once on mount.
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [maxHeight, children]);

  const clamped = tall && !open && !disabled;

  return (
    <div data-testid={testId}>
      <div
        className="relative overflow-hidden transition-[max-height] duration-300"
        style={{ maxHeight: clamped ? maxHeight : "none" }}
      >
        <div ref={inner}>{children}</div>
        {clamped && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-card to-transparent"
          />
        )}
      </div>

      {tall && !disabled && (
        <button
          type="button"
          data-testid={`${testId}-toggle`}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-[hsl(var(--primary))] transition-opacity hover:opacity-80"
        >
          {open ? t("showLess") : t("showAll")}
          {open ? (
            <ChevronUp className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
      )}
    </div>
  );
};

export default ClampBlock;
