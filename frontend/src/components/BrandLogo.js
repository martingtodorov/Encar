/**
 * Wordmark: the Europe Encar logo.
 *
 * Served as WebP when the browser accepts it (~7 KB) with a PNG fallback (~13 KB), and
 * a density switch: the compact header wordmark (106x30 CSS px, so 212x60 on a 2x screen)
 * uses only the 220 asset - Lighthouse flagged 440 as oversized here (15 KB waste per
 * visit). The larger, non-compact logo (141x40 = 282x80 on 2x) still needs both sizes
 * so a retina screen gets the sharper copy.
 */
export const BrandLogo = ({ compact = false, className = "" }) => (
  <picture>
    {compact ? (
      <source type="image/webp" srcSet="/logo-220.webp" />
    ) : (
      <source
        type="image/webp"
        srcSet="/logo-220.webp 1x, /logo-440.webp 2x"
      />
    )}
    <img
      src="/logo-220.png"
      srcSet={compact ? undefined : "/logo-220.png 1x, /logo-440.png 2x"}
      alt="Europe Encar"
      data-testid="brand-logo"
      width={compact ? 106 : 141}
      height={compact ? 30 : 40}
      decoding="async"
      className={`block w-auto select-none ${compact ? "h-[30px]" : "h-10"} ${className}`}
    />
  </picture>
);

export default BrandLogo;
