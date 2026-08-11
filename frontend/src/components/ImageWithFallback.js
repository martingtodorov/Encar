import { useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * Encar CDN images are loaded DIRECTLY by the visitor's browser (never proxied).
 * They arrive at arbitrary aspect ratios and can be slow or fail, so this handles
 * skeleton -> slow label -> loaded, plus a real fallback panel on error.
 */
export const ImageWithFallback = ({ src, srcMobile, alt, className = "", testId, fit = "cover", eager = false, priority = false }) => {
  const { t } = useApp();
  const [state, setState] = useState(src ? "loading" : "error");
  const [slow, setSlow] = useState(false);
  const timer = useRef(null);
  const imgRef = useRef(null);

  useEffect(() => {
    setState(src ? "loading" : "error");
    setSlow(false);
    if (timer.current) clearTimeout(timer.current);
    if (src) {
      timer.current = setTimeout(() => setSlow(true), 800);
    }
    // Eager images (LCP candidates) start downloading during HTML parse, before React
    // hydrates. If the picture is small or already in the browser cache the load event
    // fires BEFORE React attaches the JSX `onLoad` handler, so the state never leaves
    // "loading" and the shimmer overlay hangs over a picture that has been rendered for
    // seconds. Checking `img.complete` on mount catches that race: the image is already
    // painted, so we mark it loaded and drop the overlay immediately.
    if (imgRef.current?.complete && imgRef.current.naturalWidth > 0) {
      setState("loaded");
      if (timer.current) clearTimeout(timer.current);
      setSlow(false);
    }
    return () => timer.current && clearTimeout(timer.current);
  }, [src]);

  const done = () => {
    if (timer.current) clearTimeout(timer.current);
    setSlow(false);
  };

  if (state === "error") {
    return (
      <div
        data-testid={testId ? `${testId}-fallback` : "image-fallback"}
        className={`flex h-full w-full flex-col items-center justify-center gap-2 bg-muted ${className}`}
      >
        <ImageOff className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        <span className="px-2 text-center text-[11px] leading-tight text-muted-foreground">
          {t("noImage")}
        </span>
      </div>
    );
  }

  return (
    <div
      className={`relative w-full overflow-hidden bg-muted ${
        fit === "contain" ? "" : "h-full"
      } ${className}`}
    >
      {state === "loading" && (
        <div className="shimmer absolute inset-0" aria-hidden="true">
          {slow && (
            <span className="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-full bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t("loading")}
            </span>
          )}
        </div>
      )}
      <picture>
        {/* Under `md` (768 px) the swiper serves a smaller crop so a phone does not
            pull the desktop 1280x720 gallery frame. Above that breakpoint the primary
            `src` (highest resolution) is used. */}
        {srcMobile && (
          <source media="(max-width: 767px)" srcSet={srcMobile} />
        )}
        <img
          ref={imgRef}
          data-testid={testId}
          src={src}
          alt={alt}
          loading={eager ? "eager" : "lazy"}
          fetchPriority={priority ? "high" : "auto"}
          decoding="async"
          onLoad={() => {
            done();
            setState("loaded");
          }}
          onError={() => {
            done();
            setState("error");
          }}
          className={`w-full transition-opacity duration-300 ${
            fit === "contain" ? "h-auto object-contain" : "h-full object-cover"
          } ${state === "loaded" ? "opacity-100" : "opacity-0"}`}
        />
      </picture>
    </div>
  );
};

export default ImageWithFallback;
