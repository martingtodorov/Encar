import { Ship, FileSearch, Receipt, Truck } from "lucide-react";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";

const Step = ({ icon: Icon, title, body, n }) => (
  <div className="rounded-[16px] border border-border bg-card p-5 shadow-sm">
    <div className="mb-3 flex items-center gap-3">
      <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-secondary">
        <Icon className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
      </span>
      <span className="tnum text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
        {n}
      </span>
    </div>
    <h2 className="text-[16px] font-semibold text-foreground">{title}</h2>
    <p className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground">{body}</p>
  </div>
);

export default function HowItWorksPage() {
  const { t, lang } = useApp();

  useSeo({ lang, title: `${t("navHowItWorks")} \u00b7 Encar`, description: t("howIntro") });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[900px] px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold text-foreground sm:text-3xl">
          {t("navHowItWorks")}
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
          {t("howIntro")}
        </p>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <Step n="01" icon={FileSearch} title={t("howStep1Title")} body={t("howStep1Body")} />
          <Step n="02" icon={Receipt} title={t("howStep2Title")} body={t("howStep2Body")} />
          <Step n="03" icon={Ship} title={t("howStep3Title")} body={t("howStep3Body")} />
          <Step n="04" icon={Truck} title={t("howStep4Title")} body={t("howStep4Body")} />
        </div>

        <section
          data-testid="how-price-formula"
          className="mt-6 rounded-[16px] border border-border bg-card p-5"
        >
          <h2 className="text-[16px] font-semibold text-foreground">{t("priceBreakdown")}</h2>
          <ul className="mt-3 space-y-2 text-[14px] text-muted-foreground">
            <li>• {t("encarPrice")}</li>
            <li>• {t("exportFee")}</li>
            <li>• {t("customsDuty")}</li>
            <li>• {t("vat")}</li>
            <li>• {t("domestic")}</li>
          </ul>
          <p className="mt-3 text-[13px] leading-relaxed text-foreground">{t("trust1Body")}</p>
        </section>
      </main>
    </div>
  );
}
