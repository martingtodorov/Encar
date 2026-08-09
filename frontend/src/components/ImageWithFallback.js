import { useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * Encar CDN images are loaded DIRECTLY by the visitor's browser (never proxied).
 * They arrive at arbitrary aspect ratios and can be slow or fail, so this handles
 * skeleton -> slow label -> loaded, plus a real fallback panel on error.
 */
export const ImageWithFallback = ({ src, alt, className = "", testId, fit = "cover", eager = false }) => {
  const { t } = useApp();
  const [state, setState] = useState(src ? "loading" : "error");
  const [slow, setSlow] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    setState(src ? "loading" : "error");
    setSlow(false);
    if (timer.current) clearTimeout(timer.current);
    if (src) {
      timer.current = setTimeout(() => setSlow(true), 800);
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
      <img
        data-testid={testId}
        src={src}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        fetchPriority={eager ? "high" : "auto"}
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
    </div>
  );
};

export default ImageWithFallback;
