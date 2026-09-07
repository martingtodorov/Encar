import { useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import BrandLogo from "@/components/BrandLogo";

/** An iPhone, and not an iPad pretending to be a Mac. */
const isPhone = () => {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  if (!/iPhone|iPod/.test(ua)) return false;
  // iPadOS reports "Macintosh" with touch points; it is never an iPhone.
  return true;
};

/**
 * Portrait only, and only on an installed iPhone.
 *
 * A phone turned sideways gives a photo column two inches of height and a header that eats
 * half the screen — the layout is built for one hand, held upright. iOS has no orientation
 * lock a web app can call (`screen.orientation.lock` is Android/Chrome only), and the
 * manifest's `orientation` field would take the iPad with it, where landscape is genuinely
 * useful. So the phone is asked to turn back, and nothing else changes.
 */
export const PortraitLock = () => {
  const { t } = useApp();
  const standalone = useDisplayMode();
  const [sideways, setSideways] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(orientation: landscape)");
    const check = () => setSideways(mq.matches);
    check();
    if (mq.addEventListener) mq.addEventListener("change", check);
    else mq.addListener?.(check);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", check);
      else mq.removeListener?.(check);
    };
  }, []);

  if (!standalone || !sideways || !isPhone()) return null;

  return (
    <div
      data-testid="portrait-lock"
      // Above every other fixed layer, the cookie bar (z-200) and the tab bar included:
      // sideways there is nothing worth reading underneath it.
      className="fixed inset-0 z-[300] flex flex-col items-center justify-center gap-6 bg-black px-10 text-center"
    >
      <BrandLogo />
      <RotateCw className="h-10 w-10 text-white/70" aria-hidden="true" />
      <p className="text-base text-white">{t("portraitOnly")}</p>
    </div>
  );
};

export default PortraitLock;
