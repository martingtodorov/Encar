import { useParams } from "react-router-dom";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";
import { legalDoc } from "@/content/legal";
import { helpDoc } from "@/content/help";
import { COMPANY } from "@/content/company";

/** One page for every legal document: the route decides which one. */
export default function LegalPage({ slug }) {
  const { lang } = useApp();
  const { lang: urlLang } = useParams();
  const doc = helpDoc(urlLang || lang, slug) || legalDoc(urlLang || lang, slug);

  useSeo({ title: `${doc.title} · ${COMPANY.name}`, description: doc.intro });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[820px] px-4 py-10 sm:px-6" data-testid={`legal-${slug}`}>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          {doc.title}
        </h1>
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">{doc.intro}</p>
        <p className="tnum mt-1.5 text-[12px] text-muted-foreground">
          {doc.updated}
        </p>

        <div className="mt-8 flex flex-col gap-7">
          {doc.sections.map(([heading, paragraphs]) => (
            <section key={heading}>
              <h2 className="text-base font-semibold text-foreground md:text-lg">{heading}</h2>
              <div className="mt-2 flex flex-col gap-2">
                {paragraphs.map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-muted-foreground">
                    {p}
                  </p>
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
