import { useEffect, useState } from "react";
import {
  Ship,
  FileSearch,
  Receipt,
  Truck,
  CreditCard,
  FileSignature,
  MapPin,
} from "lucide-react";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";
import { getCmsPage } from "@/lib/api";
import { cachedPageHtml, rememberPageHtml } from "@/lib/cmsCache";
import { helpDoc } from "@/content/help";

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

/* Same panel as a Step, without the number: these are facts, not an ordered process. */
const Detail = ({ icon: Icon, title, body, tid, className = "" }) => (
  <div
    data-testid={tid}
    className={`rounded-[16px] border border-border bg-card p-5 shadow-sm ${className}`}
  >
    <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-[10px] bg-secondary">
      <Icon className="h-[18px] w-[18px] text-[hsl(var(--primary))]" aria-hidden="true" />
    </div>
    <h2 className="text-[16px] font-semibold text-foreground">{title}</h2>
    <p className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground">{body}</p>
  </div>
);

export default function HowItWorksPage() {
  const { t, lang, cms } = useApp();
  // Replaced wholesale when the owner writes their own version of this page. Seeded from the
  // cache so a refresh does not flash the built-in page first.
  const [html, setHtml] = useState(() => cachedPageHtml("how-it-works", lang));

  useEffect(() => {
    let alive = true;
    setHtml(cachedPageHtml("how-it-works", lang));
    getCmsPage("how-it-works", lang)
      .then((r) => {
        if (!alive) return;
        setHtml(r.html || "");
        rememberPageHtml("how-it-works", lang, r.html || "");
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [lang]);

  const seo = cms?.seo?.["how-it-works"] || {};
  useSeo({
    lang,
    title: seo.title || `${t("navHowItWorks")} \u00b7 Encar`,
    description: seo.description || t("howIntro"),
  });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[900px] px-4 py-8 sm:px-6">
        {html ? (
          <div
            data-testid="how-it-works-html"
            className="cms-html"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <>
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
                <li>• {t("domestic")}</li>
              </ul>
              <p className="mt-3 text-[13px] leading-relaxed text-foreground">{t("trust1Body")}</p>
            </section>

            {/* What happens after the price: the deposit, the contract and the shipment. The
                figures here mirror DEPOSIT_RATE, AUTH_DAYS and COMMISSION_EUR in the backend
                — change the copy if those change. */}
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Detail
                tid="how-deposit"
                icon={CreditCard}
                title={t("howDepositTitle")}
                body={t("howDepositBody")}
              />
              <Detail
                tid="how-contract"
                icon={FileSignature}
                title={t("howContractTitle")}
                body={t("howContractBody")}
              />
              <Detail
                tid="how-tracking"
                icon={MapPin}
                title={t("howTrackTitle")}
                body={t("howTrackBody")}
                className="sm:col-span-2"
              />
            </div>

            <section
              data-testid="how-faq"
              className="mt-4 rounded-[16px] border border-border bg-card p-5"
            >
              <h2 className="text-[16px] font-semibold text-foreground">{t("howFaqTitle")}</h2>
              <dl className="mt-3 divide-y divide-border">
                {/* The four mechanics questions (deposit hold, sold-out, documents, ship
                    position) live in i18n_extra.js because they mirror deposits.py rules and
                    tracking.py behaviour - things engineers change without touching content. */}
                {[1, 2, 3, 4].map((n) => (
                  <div key={`m${n}`} className="py-3 first:pt-0 last:pb-0">
                    <dt className="text-[14px] font-semibold text-foreground">
                      {t(`howFaq${n}Q`)}
                    </dt>
                    <dd className="mt-1 text-[13.5px] leading-relaxed text-muted-foreground">
                      {t(`howFaq${n}A`)}
                    </dd>
                  </div>
                ))}
                {/* The remaining questions come straight from help.js so the owner can edit
                    them in one place. This is why /faq is no longer a separate route: the
                    same source of truth is rendered inline here. */}
                {(helpDoc(lang, "faq")?.sections || []).map(([question, answers], i) => (
                  <div key={`h${i}`} className="py-3 first:pt-0 last:pb-0">
                    <dt className="text-[14px] font-semibold text-foreground">{question}</dt>
                    {(answers || []).map((line, j) => (
                      <dd
                        key={j}
                        className="mt-1 text-[13.5px] leading-relaxed text-muted-foreground"
                      >
                        {line}
                      </dd>
                    ))}
                  </div>
                ))}
              </dl>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
