import { ShieldCheck, FileText, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

export const Hero = ({ totalUpstream, onStart }) => {
  const { t, lang, cms } = useApp();
  // Owner-editable headline and standfirst (Admin -> Pages -> Home).
  const heroTitle = cms?.hero?.title || t("heroTitle");
  const heroSubtitle = cms?.hero?.subtitle || t("heroSubtitle");

  const chips = [
    { icon: ShieldCheck, label: t("heroChip1") },
    { icon: FileText, label: t("heroChip2") },
    { icon: Search, label: t("heroChip3") },
  ];

  return (
    <section
      data-testid="hero"
      className="hero-bg relative overflow-hidden border-b border-border"
    >
      <div className="hero-grid pointer-events-none absolute inset-0" aria-hidden="true" />

      {/* Centred, because the headline is the only thing here: left-aligned it left half the
          1280px column empty on desktop. Kept short vertically — the first car cards have to
          stay within reach on a phone. */}
      <div className="relative mx-auto flex max-w-[46rem] flex-col items-center px-4 py-8 text-center sm:px-6 sm:py-12">
        <h1
          className="animate-rise text-balance text-3xl font-extrabold leading-[1.1] tracking-tight text-foreground sm:text-4xl lg:text-5xl"
          style={{ animationDelay: "0ms" }}
        >
          {heroTitle}
        </h1>

        <p
          className="animate-rise mt-3.5 max-w-2xl text-balance text-base leading-relaxed text-muted-foreground sm:mt-4 sm:text-lg"
          style={{ animationDelay: "70ms" }}
        >
          {heroSubtitle}
        </p>

        {/* One row, always. On a narrow screen it scrolls sideways rather than dropping the
            third pill onto a line of its own, which read as a mistake. */}
        <div
          className="animate-rise no-scrollbar -mx-4 mt-5 flex w-full snap-x snap-mandatory items-center gap-2 overflow-x-auto px-4 sm:mx-0 sm:mt-6 sm:w-auto sm:justify-center sm:px-0"
          style={{ animationDelay: "140ms" }}
        >
          {chips.map(({ icon: Icon, label }) => (
            <span
              key={label}
              className="inline-flex shrink-0 snap-start items-center gap-1.5 rounded-full border border-[hsl(var(--primary)/0.22)] bg-[hsl(var(--primary)/0.06)] px-3 py-1.5 text-xs font-semibold tracking-wide text-[hsl(var(--primary))]"
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {label}
            </span>
          ))}
        </div>

        <div
          className="animate-rise mt-7 flex w-full flex-col items-center gap-3.5 sm:mt-8 sm:w-auto sm:flex-row sm:gap-5"
          style={{ animationDelay: "210ms" }}
        >
          <Button
            data-testid="hero-cta"
            onClick={onStart}
            className="h-12 w-full rounded-full bg-[hsl(var(--primary))] px-8 text-[15px] font-semibold text-primary-foreground shadow-[0_8px_20px_-8px_hsl(var(--primary)/0.65)] transition-transform duration-200 hover:-translate-y-0.5 hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:translate-y-0 sm:w-auto"
          >
            {t("heroCta")}
          </Button>
          {totalUpstream ? (
            <span
              data-testid="hero-catalogue-size"
              className="tnum inline-flex items-center gap-2 text-sm font-semibold tracking-tight text-foreground"
            >
              <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[hsl(var(--primary))] opacity-70" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[hsl(var(--primary))]" />
              </span>
              {t("indexNote", { total: formatNumber(totalUpstream, lang) })}
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
};

export default Hero;
