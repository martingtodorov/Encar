import { ShieldCheck, FileText, Search, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

export const Hero = ({ totalUpstream, onStart }) => {
  const { t, lang, cms } = useApp();
  // Owner-editable headline and standfirst (Admin -> Pages -> Home).
  const heroTitle = cms?.hero?.title || t("heroTitle");
  const heroSubtitle = cms?.hero?.subtitle || t("heroSubtitle");

  // What Encar actually hands over with every car, as a specification sheet rather than
  // marketing pills: a label and what it contains.
  const facts = [
    { icon: ShieldCheck, label: t("heroChip1"), note: t("heroChip1Note") },
    { icon: FileText, label: t("heroChip2"), note: t("heroChip2Note") },
    { icon: Search, label: t("heroChip3"), note: t("heroChip3Note") },
  ];

  return (
    <section data-testid="hero" className="hero-bg border-b border-border">
      <div className="mx-auto max-w-[1280px] px-4 py-4 sm:px-6 sm:py-8 lg:py-9">
        <div className="grid gap-5 sm:gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end lg:gap-16">
          <div className="max-w-[36rem]">
            {/* h2, not h1: the page's single h1 is the site name, kept screen-reader-only in
                SearchPage. The size here is set by the classes, not by the tag. */}
            <h2
              className="animate-rise text-3xl font-semibold leading-[1.12] tracking-tight text-foreground sm:text-4xl lg:text-5xl"
              style={{ animationDelay: "0ms" }}
            >
              {heroTitle}
            </h2>

            <p
              className="animate-rise mt-3 max-w-[34rem] text-base leading-relaxed text-muted-foreground sm:mt-3.5"
              style={{ animationDelay: "60ms" }}
            >
              {heroSubtitle}
            </p>

            <div
              className="animate-rise mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 sm:mt-7"
              style={{ animationDelay: "120ms" }}
            >
              <Button
                data-testid="hero-cta"
                onClick={onStart}
                className="group h-12 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-7 text-[15px] font-semibold text-primary-foreground transition-colors hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {t("heroCta")}
                <ArrowRight
                  className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Button>
              {totalUpstream ? (
                <span
                  data-testid="hero-catalogue-size"
                  className="tnum text-[13px] text-muted-foreground"
                >
                  {t("indexNote", { total: formatNumber(totalUpstream, lang) })}
                </span>
              ) : null}
            </div>
          </div>

          {/* The specification panel. It uses the width the headline leaves empty on desktop,
              and on a phone it simply sits underneath — no pills to orphan on a second row. */}
          <ul
            className="animate-rise hero-panel divide-y divide-border rounded-[12px] border border-border"
            style={{ animationDelay: "180ms" }}
          >
            {facts.map(({ icon: Icon, label, note }) => (
              <li key={label} className="flex items-start gap-3 px-4 py-3 sm:py-3.5">
                <Icon
                  className="mt-[3px] h-[17px] w-[17px] shrink-0 text-[hsl(var(--primary))]"
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <div className="text-sm font-semibold leading-tight text-foreground">
                    {label}
                  </div>
                  <div className="mt-1 text-[13px] leading-tight text-muted-foreground">
                    {note}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
};

export default Hero;
