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
    <section className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {items.map(({ icon: Icon, title, body, tid }) => (
          <div
            key={tid}
            data-testid={tid}
            className="rounded-[14px] border border-border bg-card p-4 shadow-[0_1px_2px_rgba(18,20,23,0.06)]"
          >
            <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-[10px] bg-secondary">
              <Icon className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
            </span>
            <h3 className="text-[15px] font-semibold text-foreground">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{body}</p>
          </div>
        ))}
      </div>
    </section>
  );
};

export default TrustStrip;
