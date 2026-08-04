/** Wordmark: the Europe Encar logo, served from /public so it is cached by the CDN. */
export const BrandLogo = ({ compact = false, className = "" }) => (
  <img
    src="/logo-220.png"
    alt="Europe Encar"
    data-testid="brand-logo"
    width={compact ? 106 : 141}
    height={compact ? 30 : 40}
    decoding="async"
    className={`block w-auto select-none ${compact ? "h-[30px]" : "h-10"} ${className}`}
  />
);

export default BrandLogo;
