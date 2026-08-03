import { ShieldCheck, FileText, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

export const Hero = ({ totalUpstream, onStart }) => {
  const { t, lang } = useApp();

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
      <div className="hero-grain absolute inset-0" aria-hidden="true" />
      <div className="relative mx-auto max-w-[1280px] px-4 py-7 sm:px-6 sm:py-10">
        <div className="max-w-3xl">
          <h1 className="text-3xl font-semibold leading-[1.12] tracking-tight text-foreground sm:text-4xl lg:text-5xl">
            {t("heroTitle")}
          </h1>
          <p className="mt-2.5 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            {t("heroSubtitle")}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {chips.map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[13px] font-medium text-foreground"
              >
                <Icon className="h-3.5 w-3.5 text-[hsl(var(--accent))]" aria-hidden="true" />
                {label}
              </span>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-4">
            <Button
              data-testid="hero-cta"
              onClick={onStart}
              className="h-12 rounded-[12px] bg-[hsl(var(--primary))] px-6 text-[15px] font-semibold text-primary-foreground transition-colors hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              {t("heroCta")}
            </Button>
            {totalUpstream ? (
              <span data-testid="hero-catalogue-size" className="tnum text-sm text-muted-foreground">
                {t("indexNote", { total: formatNumber(totalUpstream, lang) })}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
};

export default Hero;
