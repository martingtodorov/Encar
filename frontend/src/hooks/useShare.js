import { useCallback } from "react";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";

/**
 * Hand the current page (or any URL) to the OS share sheet.
 *
 * One hook rather than three copies: the same gesture now exists on the car page, on the
 * search page and nowhere else needs to know how it works. `navigator.share` only exists
 * on phones and only over HTTPS, so the clipboard is the fallback — a share button that
 * silently does nothing is worse than no button.
 */
export function useShare() {
  const { t } = useApp();

  return useCallback(async ({ url, title, text } = {}) => {
    const payload = {
      url: url || window.location.href,
      title: title || document.title,
      ...(text ? { text } : {}),
    };
    if (navigator.share) {
      try {
        await navigator.share(payload);
      } catch {
        /* the visitor dismissed the sheet — not an error worth a toast */
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(payload.url);
      toast.success(t("pwaShareCopied"));
    } catch {
      toast.error(t("pwaShareFailed"));
    }
  }, [t]);
}

export default useShare;
