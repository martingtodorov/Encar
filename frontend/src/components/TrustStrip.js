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
    <section className="mx-auto max-w-[1280px] px-4 pb-5 pt-4 sm:px-6 sm:pb-7 sm:pt-6">
      {/* One panel divided into three, not three floating cards: it reads as a single
          statement and takes roughly half the vertical space on a phone, which matters
          because the car list starts right underneath. */}
      <div className="grid grid-cols-1 divide-y divide-border overflow-hidden rounded-[14px] border border-border bg-card shadow-[0_2px_10px_-4px_rgba(18,20,23,0.12)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {items.map(({ icon: Icon, title, body, tid }) => (
          <div
            key={tid}
            data-testid={tid}
            className="flex items-center gap-3 px-3.5 py-3 transition-colors hover:bg-muted/40 sm:items-start sm:px-4 sm:py-4"
          >
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.1)]">
              <Icon
                className="h-[17px] w-[17px] text-[hsl(var(--primary))]"
                aria-hidden="true"
              />
            </span>
            <div className="min-w-0">
              {/* Directly under the hero h1, so these are h2 - the size is set by the
                  classes, not by the tag. */}
              <h2 className="text-sm font-bold tracking-tight text-foreground">{title}</h2>
              <p className="mt-0.5 text-xs leading-snug text-muted-foreground sm:leading-relaxed">
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
