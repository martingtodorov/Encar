import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";
import { legalDoc } from "@/content/legal";
import { helpDoc } from "@/content/help";
import { COMPANY } from "@/content/company";
import { getCmsPage } from "@/lib/api";
import { cachedPageHtml, rememberPageHtml } from "@/lib/cmsCache";

/** One page for every legal document: the route decides which one. */
export default function LegalPage({ slug }) {
  const { lang, cms } = useApp();
  const { lang: urlLang } = useParams();
  const pageLang = urlLang || lang;
  const doc = helpDoc(pageLang, slug) || legalDoc(pageLang, slug);
  // The owner's own body, when they have written one. Seeded from the cache so a refresh
  // does not flash the built-in text first.
  const [html, setHtml] = useState(() => cachedPageHtml(slug, urlLang || lang));

  useEffect(() => {
    let alive = true;
    setHtml(cachedPageHtml(slug, pageLang));
    getCmsPage(slug, pageLang)
      .then((r) => {
        if (!alive) return;
        setHtml(r.html || "");
        rememberPageHtml(slug, pageLang, r.html || "");
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [slug, pageLang]);

  const seo = cms?.seo?.[slug] || {};
  const co = { ...COMPANY, ...(cms?.company || {}) };
  useSeo({
    lang: pageLang,
    title: seo.title || `${doc.title} · ${co.name}`,
    description: seo.description || doc.intro,
  });

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[820px] px-4 py-10 sm:px-6" data-testid={`legal-${slug}`}>
        {html ? (
          <div
            data-testid={`legal-html-${slug}`}
            className="cms-html"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              {doc.title}
            </h1>
            <p className="mt-3 text-base leading-relaxed text-muted-foreground">{doc.intro}</p>
            <p className="tnum mt-1.5 text-[12px] text-muted-foreground">{doc.updated}</p>

            <div className="mt-8 flex flex-col gap-7">
              {doc.sections.map(([heading, paragraphs]) => (
                <section key={heading}>
                  <h2 className="text-base font-semibold text-foreground md:text-lg">
                    {heading}
                  </h2>
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
          </>
        )}
      </main>
    </div>
  );
}
