import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HeaderBar } from "@/components/HeaderBar";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";
import { getSitemapIndex } from "@/lib/api";

/**
 * The HTML sitemap: every make and every model on a single indexable page.
 *
 * Purpose is SEO — Googlebot walks all 200+ makes and 1200+ model landing pages
 * from one hop, distributing internal PageRank without needing JS. All three
 * languages render the same catalogue (makes and models are proper nouns).
 */
export default function SitemapPage() {
  const { t, lang } = useApp();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getSitemapIndex(lang)
      .then((res) => alive && setData(res))
      .catch(() => alive && setData({ makes: [] }))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [lang]);

  useSeo({
    lang,
    title: `${t("sitemapTitle")} \u00b7 Encar`,
    description: t("sitemapIntro"),
  });

  const makes = data?.makes || [];
  const totalMakes = makes.length;
  const totalModels = makes.reduce((n, m) => n + (m.models?.length || 0), 0);

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main
        data-testid="sitemap-page"
        className="mx-auto max-w-[1080px] px-4 py-8 sm:px-6"
      >
        <h1
          data-testid="sitemap-title"
          className="text-2xl font-semibold text-foreground sm:text-3xl"
        >
          {t("sitemapTitle")}
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
          {t("sitemapIntro")}
        </p>

        {!loading && totalMakes > 0 && (
          <p
            data-testid="sitemap-counts"
            className="mt-1 text-[13px] text-muted-foreground"
          >
            {t("sitemapCounts", { makes: totalMakes, models: totalModels })}
          </p>
        )}

        {loading ? (
          <div
            data-testid="sitemap-loading"
            className="mt-8 text-[14px] text-muted-foreground"
          >
            {t("loading")}
          </div>
        ) : (
          <div className="mt-6 grid gap-6">
            {makes.map((make) => (
              <section
                key={make.slug}
                data-testid={`sitemap-make-${make.slug}`}
                className="rounded-[16px] border border-border bg-card p-5"
              >
                <h2 className="text-[17px] font-semibold text-foreground">
                  <Link
                    to={`/${lang}/${make.slug}`}
                    data-testid={`sitemap-make-link-${make.slug}`}
                    className="hover:text-primary hover:underline"
                  >
                    {make.label}
                  </Link>
                  <span className="ml-2 text-[12px] font-normal text-muted-foreground">
                    ({make.count})
                  </span>
                </h2>

                {(make.models || []).length > 0 && (
                  <ul className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
                    {make.models.map((model) => (
                      <li key={model.slug}>
                        <Link
                          to={`/${lang}/${make.slug}/${model.slug}`}
                          data-testid={`sitemap-model-link-${make.slug}-${model.slug}`}
                          className="text-[13.5px] text-foreground hover:text-primary hover:underline"
                        >
                          {model.label}
                        </Link>
                        <span className="ml-1.5 text-[12px] text-muted-foreground">
                          ({model.count})
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
