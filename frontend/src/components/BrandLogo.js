/** Wordmark: bold red "Encar", rendered as text (no bitmap asset). */
export const BrandLogo = ({ compact = false, className = "" }) => (
  <span
    data-testid="brand-logo"
    className={`select-none font-bold leading-none tracking-tight text-[hsl(var(--primary))] ${className}`}
    style={{ fontSize: compact ? "26px" : "34px", letterSpacing: "-0.03em" }}
    aria-label="Encar"
  >
    Encar
  </span>
);

export default BrandLogo;
