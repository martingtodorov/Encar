import { BadgeEuro, FileCheck2, Zap } from "lucide-react";
import { useApp } from "@/context/AppContext";

export const TrustStrip = () => {
  const { t } = useApp();

  const items = [
    { icon: BadgeEuro, title: t("trust1Title"), body: t("trust1Body"), tid: "trust-strip-final-price" },
    { icon: FileCheck2, title: t("trust2Title"), body: t("trust2Body"), tid: "trust-strip-docs" },
    { icon: Zap, title: t("trust3Title"), body: t("trust3Body"), tid: "trust-strip-fast-search" },
  ];

  return (
    <section className="mx-auto max-w-[1280px] px-4 pb-5 pt-1 sm:px-6 sm:pb-7 sm:pt-2">
      <div className="grid gap-2.5 sm:grid-cols-3 sm:gap-4">
        {items.map(({ icon: Icon, title, body, tid }) => (
          <div
            key={tid}
            data-testid={tid}
            className="flex gap-3 rounded-[14px] border border-border bg-card p-3 shadow-[0_1px_2px_rgba(18,20,23,0.06)] sm:block sm:p-4"
          >
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-secondary sm:mb-3 sm:h-9 sm:w-9">
              <Icon className="h-[17px] w-[17px] text-[hsl(var(--primary))] sm:h-[18px] sm:w-[18px]" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              {/* Directly under the hero h1, so these are h2 - the size is set by the
                  classes, not by the tag. */}
              <h2 className="text-[14.5px] font-semibold text-foreground sm:text-[15px]">{title}</h2>
              <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground sm:mt-1 sm:text-sm sm:leading-relaxed">
                {body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

export default TrustStrip;
