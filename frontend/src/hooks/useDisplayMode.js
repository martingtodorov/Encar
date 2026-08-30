import { useEffect, useState } from "react";

/**
 * Whether the site is running as a homescreen PWA (installed) or in a browser tab.
 *
 * Three checks cover every OS:
 *   * `display-mode: standalone` — the CSS/JS standard: Android, Chrome/Edge, iOS 16.4+.
 *   * `navigator.standalone` — Apple-only legacy flag, still the source of truth on iOS
 *     Safari's Add-to-Home-Screen shortcut.
 *   * `android-app://` referrer — a Google Trusted Web Activity wrapper.
 */
export function isStandalone() {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
  if (window.navigator?.standalone === true) return true;
  if (typeof document !== "undefined" && document.referrer.startsWith("android-app://")) return true;
  return false;
}

/**
 * Rough platform tag for the install-instructions dialog and analytics dimension. Not a
 * feature-detection: we ONLY use it to pick which set of steps to show.
 */
export function platformTag() {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent || "";
  if (/iPad|iPhone|iPod/.test(ua)) return "ios";
  if (/Android/.test(ua)) return "android";
  return "other";
}

/** Reactive standalone flag: re-evaluates if the OS toggles the display-mode mid-session. */
export function useDisplayMode() {
  const [standalone, setStandalone] = useState(isStandalone);
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const mq = window.matchMedia?.("(display-mode: standalone)");
    if (!mq) return undefined;
    const handler = () => setStandalone(isStandalone());
    // Older Safari uses addListener/removeListener.
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else mq.addListener?.(handler);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", handler);
      else mq.removeListener?.(handler);
    };
  }, []);
  return standalone;
}

export default useDisplayMode;
