/**
 * Wordmark: the Europe Encar logo.
 *
 * Served as WebP when the browser accepts it (~7 KB) with a PNG fallback (~13 KB),
 * and at two densities so retina screens get the sharp copy without every visitor
 * paying for it. Lighthouse flagged the earlier 776×220 PNG (113 KB) as one of the
 * biggest single-file savings on the landing.
 */
export const BrandLogo = ({ compact = false, className = "" }) => (
  <picture>
    <source
      type="image/webp"
      srcSet="/logo-220.webp 1x, /logo-440.webp 2x"
    />
    <img
      src="/logo-220.png"
      srcSet="/logo-220.png 1x, /logo-440.png 2x"
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
