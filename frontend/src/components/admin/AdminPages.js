import { useCallback, useEffect, useState } from "react";
import { Globe, Loader2, RotateCcw, Save, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  adminCmsPage,
  adminCmsPages,
  adminGetCompany,
  adminResetCmsPage,
  adminSaveCmsPage,
  adminSaveCompany,
  adminTranslateCmsPage,
} from "@/lib/api";
import { COMPANY } from "@/content/company";
import { legalDoc } from "@/content/legal";
import { helpDoc } from "@/content/help";
import { t as translate } from "@/i18n";
import { Spinner, stampSofia } from "@/components/admin/AdminBits";

const LANGS = ["bg", "ro", "en"];
const LANG_LABEL = { bg: "Български", ro: "Română", en: "English" };
const PAGE_LABEL = {
  home: "Home / search",
  "how-it-works": "How it works",
  faq: "FAQ",
  fees: "Fees & commission",
  contact: "Contact",
  terms: "Terms",
  privacy: "Privacy",
  cookies: "Cookies",
};
// Google cuts a title at roughly 60 characters and a description at roughly 155.
const TITLE_MAX = 60;
const DESC_MAX = 155;

const esc = (s) =>
  String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** The copy that ships with the app, as HTML, so the owner can start from it instead of a
 *  blank box. Built here rather than on the server: this is where the content lives. */
function builtInHtml(slug, lang) {
  if (slug === "how-it-works") {
    const tt = (k) => translate(lang, k);
    const steps = [1, 2, 3, 4]
      .map((n) => `  <h2>${esc(tt(`howStep${n}Title`))}</h2>\n  <p>${esc(tt(`howStep${n}Body`))}</p>`)
      .join("\n");
    const parts = ["encarPrice", "exportFee", "customsDuty", "vat", "domestic"]
      .map((k) => `    <li>${esc(tt(k))}</li>`)
      .join("\n");
    return `<h1>${esc(tt("navHowItWorks"))}</h1>
<p>${esc(tt("howIntro"))}</p>
${steps}
<h2>${esc(tt("priceBreakdown"))}</h2>
<ul>
${parts}
</ul>
<p>${esc(tt("trust1Body"))}</p>`;
  }
  const doc = helpDoc(lang, slug) || legalDoc(lang, slug);
  if (!doc) return "";
  const body = doc.sections
    .map(
      ([heading, paragraphs]) =>
        `<h2>${esc(heading)}</h2>\n` +
        paragraphs.map((p) => `<p>${esc(p)}</p>`).join("\n")
    )
    .join("\n");
  return `<h1>${esc(doc.title)}</h1>\n<p>${esc(doc.intro)}</p>\n${body}`;
}

function builtInSeo(slug, lang) {
  if (slug === "home") {
    return { title: translate(lang, "seoHomeTitle"), description: translate(lang, "seoHomeDesc") };
  }
  if (slug === "how-it-works") {
    return {
      title: `${translate(lang, "navHowItWorks")} · Encar`,
      description: translate(lang, "howIntro"),
    };
  }
  const doc = helpDoc(lang, slug) || legalDoc(lang, slug);
  return { title: `${doc.title} · ${COMPANY.name}`, description: doc.intro };
}

const Counter = ({ value, max }) => {
  const n = (value || "").length;
  const over = n > max;
  return (
    <span
      className={`tnum text-[11px] font-medium ${over ? "text-destructive" : "text-muted-foreground"}`}
    >
      {n}/{max}
      {over ? " · Google will cut this" : ""}
    </span>
  );
};

/** What the entry looks like in a search result, so the owner can see it before saving. */
const SerpPreview = ({ slug, lang, title, description }) => {
  const site = COMPANY.site;
  const url = `${site}/${lang}${slug === "home" ? "" : `/${slug}`}`;
  return (
    <div
      data-testid="cms-serp-preview"
      className="rounded-[12px] border border-border bg-card p-4"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Google preview
      </div>
      <div className="mt-2.5 max-w-[600px]">
        <div className="truncate text-[12px] text-muted-foreground">{url}</div>
        <div className="mt-0.5 truncate text-[18px] leading-snug text-[#1a0dab] dark:text-[#8ab4f8]">
          {title || "—"}
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground line-clamp-2">
          {description || "—"}
        </p>
      </div>
    </div>
  );
};

const CompanyCard = () => {
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminGetCompany()
      .then((d) => setForm({ ...COMPANY, ...Object.fromEntries(
        Object.entries(d).filter(([, v]) => v)) }))
      .catch(() => setForm({ ...COMPANY }));
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      await adminSaveCompany(form);
      toast.success("Company details saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  if (!form) return <Spinner />;
  const field = (key, label) => (
    <div className="flex flex-col gap-1.5">
      <Label className="text-[12px] font-medium">{label}</Label>
      <Input
        data-testid={`cms-company-${key}`}
        value={form[key] || ""}
        onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
        className="h-10 bg-background text-[14px]"
      />
    </div>
  );

  return (
    <div
      data-testid="cms-company"
      className="rounded-[14px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="text-[15px] font-semibold text-foreground">Company details</h2>
      <p className="mt-1 text-[12.5px] text-muted-foreground">
        Shown in the footer, in every legal page and in the emails we send.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {field("name", "Registered name")}
        {field("eik", "Company number (ЕИК)")}
        {field("vat", "VAT number")}
        {field("email", "Contact email")}
        {field("phone", "Phone")}
        {field("site", "Domain")}
        <div className="sm:col-span-2">{field("address", "Registered address")}</div>
      </div>

      <div className="mt-6 border-t border-border pt-4">
        <h3 className="text-[13.5px] font-semibold text-foreground">Launch checklist</h3>
        <p className="mt-0.5 text-[12px] text-muted-foreground">
          Optional. Blank fields are simply not rendered.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {field("ga_id", "Google Analytics 4 measurement id (e.g. G-XXXXXX)")}
          {field("response_hours",
                 "Response-time promise, hours (e.g. 24 or “2 business”)")}
          {field("google_maps_url", "Google Maps link (used by directions button)")}
          {field("geo_lat", "Office latitude (for AutoDealer schema)")}
          {field("geo_lng", "Office longitude (for AutoDealer schema)")}
        </div>
      </div>
      <Button
        data-testid="cms-company-save"
        onClick={save}
        disabled={busy}
        className="mt-4 h-10 gap-2 rounded-[10px]"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        Save company details
      </Button>
    </div>
  );
};

export const AdminPages = () => {
  const [index, setIndex] = useState(null);
  const [slug, setSlug] = useState("home");
  const [lang, setLang] = useState("bg");
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState(false);

  const bodyAllowed = slug !== "home";

  const loadIndex = useCallback(() => {
    adminCmsPages().then(setIndex).catch(() => setIndex([]));
  }, []);

  useEffect(loadIndex, [loadIndex]);

  useEffect(() => {
    setDoc(null);
    adminCmsPage(slug, lang)
      .then(setDoc)
      .catch(() => setDoc({ seo_title: "", seo_description: "", html: "", hero_title: "", hero_subtitle: "" }));
  }, [slug, lang]);

  const set = (k, v) => setDoc((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy("save");
    try {
      await adminSaveCmsPage(slug, lang, {
        seo_title: doc.seo_title || "",
        seo_description: doc.seo_description || "",
        html: doc.html || "",
        hero_title: doc.hero_title || "",
        hero_subtitle: doc.hero_subtitle || "",
      });
      toast.success(`${PAGE_LABEL[slug]} (${lang.toUpperCase()}) saved`);
      loadIndex();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy("");
    }
  };

  const reset = async () => {
    if (!window.confirm("Throw away your version and go back to the built-in text?")) return;
    setBusy("reset");
    try {
      await adminResetCmsPage(slug, lang);
      setDoc({ seo_title: "", seo_description: "", html: "", hero_title: "", hero_subtitle: "" });
      toast.success("Back to the built-in text");
      loadIndex();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not reset");
    } finally {
      setBusy("");
    }
  };

  const doTranslate = async () => {
    setBusy("translate");
    try {
      const { translated } = await adminTranslateCmsPage(slug, "bg");
      toast.success(`Translated into ${translated.map((l) => l.toUpperCase()).join(" and ")}`);
      loadIndex();
      if (lang !== "bg") adminCmsPage(slug, lang).then(setDoc);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Translation failed");
    } finally {
      setBusy("");
    }
  };

  if (!index) return <Spinner />;
  const row = index.find((i) => i.slug === slug);
  const fallback = builtInSeo(slug, lang);

  return (
    <div data-testid="admin-pages" className="flex flex-col gap-5">
      {/* page picker */}
      <div className="flex flex-wrap gap-2">
        {index.map((i) => {
          const touched = LANGS.some((l) => i.langs[l].seo || i.langs[l].body);
          return (
            <button
              key={i.slug}
              type="button"
              data-testid={`cms-page-${i.slug}`}
              onClick={() => setSlug(i.slug)}
              className={`rounded-[10px] border px-3 py-2 text-[13px] font-medium transition-colors ${
                slug === i.slug
                  ? "border-[hsl(var(--primary))] bg-card text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {PAGE_LABEL[i.slug]}
              {touched ? <span className="ml-1.5 text-[hsl(var(--primary))]">•</span> : null}
            </button>
          );
        })}
      </div>

      {/* language picker */}
      <div className="inline-flex w-max rounded-[10px] border border-border bg-muted p-0.5">
        {LANGS.map((l) => (
          <button
            key={l}
            type="button"
            data-testid={`cms-lang-${l}`}
            onClick={() => setLang(l)}
            className={`rounded-[8px] px-3 py-1.5 text-[13px] font-medium transition-colors ${
              lang === l ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
            }`}
          >
            {LANG_LABEL[l]}
            {row?.langs?.[l]?.seo || row?.langs?.[l]?.body ? (
              <span className="ml-1.5 text-[hsl(var(--primary))]">•</span>
            ) : null}
          </button>
        ))}
      </div>

      {!doc ? (
        <Spinner />
      ) : (
        <>
          <div className="rounded-[14px] border border-border bg-card p-5 shadow-sm">
            <h2 className="text-[15px] font-semibold text-foreground">
              Search engine title &amp; description
            </h2>
            <p className="mt-1 text-[12.5px] text-muted-foreground">
              Leave a field empty and the built-in text is used instead.
            </p>

            <div className="mt-4 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-[12px] font-medium">Title</Label>
                  <Counter value={doc.seo_title} max={TITLE_MAX} />
                </div>
                <Input
                  data-testid="cms-seo-title"
                  value={doc.seo_title || ""}
                  placeholder={fallback.title}
                  onChange={(e) => set("seo_title", e.target.value)}
                  className="h-10 bg-background text-[14px]"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-[12px] font-medium">Description</Label>
                  <Counter value={doc.seo_description} max={DESC_MAX} />
                </div>
                <Textarea
                  data-testid="cms-seo-description"
                  rows={3}
                  value={doc.seo_description || ""}
                  placeholder={fallback.description}
                  onChange={(e) => set("seo_description", e.target.value)}
                  className="bg-background text-[14px]"
                />
              </div>

              <SerpPreview
                slug={slug}
                lang={lang}
                title={doc.seo_title || fallback.title}
                description={doc.seo_description || fallback.description}
              />
            </div>
          </div>

          {slug === "home" && (
            <div className="rounded-[14px] border border-border bg-card p-5 shadow-sm">
              <h2 className="text-[15px] font-semibold text-foreground">Homepage headline</h2>
              <div className="mt-4 grid gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px] font-medium">Headline</Label>
                  <Input
                    data-testid="cms-hero-title"
                    value={doc.hero_title || ""}
                    placeholder={translate(lang, "heroTitle")}
                    onChange={(e) => set("hero_title", e.target.value)}
                    className="h-10 bg-background text-[14px]"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-[12px] font-medium">Sub-headline</Label>
                  <Textarea
                    data-testid="cms-hero-subtitle"
                    rows={2}
                    value={doc.hero_subtitle || ""}
                    placeholder={translate(lang, "heroSubtitle")}
                    onChange={(e) => set("hero_subtitle", e.target.value)}
                    className="bg-background text-[14px]"
                  />
                </div>
              </div>
            </div>
          )}

          {bodyAllowed && (
            <div className="rounded-[14px] border border-border bg-card p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-[15px] font-semibold text-foreground">Page content (HTML)</h2>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    data-testid="cms-load-builtin"
                    onClick={() => set("html", builtInHtml(slug, lang))}
                    className="h-9 rounded-[9px] text-[13px]"
                  >
                    Load the built-in text
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    data-testid="cms-toggle-preview"
                    onClick={() => setPreview((v) => !v)}
                    className="h-9 rounded-[9px] text-[13px]"
                  >
                    {preview ? "Edit" : "Preview"}
                  </Button>
                </div>
              </div>
              <p className="mt-1 text-[12.5px] text-muted-foreground">
                Plain HTML: &lt;h1&gt;, &lt;h2&gt;, &lt;p&gt;, &lt;ul&gt;/&lt;li&gt;,
                &lt;strong&gt;, &lt;a href&gt;, &lt;table&gt;, &lt;img&gt;. Scripts and event
                handlers are stripped when saved. Empty means the built-in page is shown.
              </p>

              {preview ? (
                <div
                  data-testid="cms-html-preview"
                  className="cms-html mt-4 rounded-[12px] border border-border bg-background p-5"
                  dangerouslySetInnerHTML={{ __html: doc.html || "" }}
                />
              ) : (
                <Textarea
                  data-testid="cms-html"
                  rows={18}
                  spellCheck={false}
                  value={doc.html || ""}
                  onChange={(e) => set("html", e.target.value)}
                  className="mt-4 bg-background font-mono text-[12.5px] leading-relaxed"
                />
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              data-testid="cms-save"
              onClick={save}
              disabled={!!busy}
              className="h-10 gap-2 rounded-[10px]"
            >
              {busy === "save" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save {LANG_LABEL[lang]}
            </Button>

            {lang === "bg" && (
              <Button
                variant="outline"
                data-testid="cms-translate"
                onClick={doTranslate}
                disabled={!!busy}
                className="h-10 gap-2 rounded-[10px]"
              >
                {busy === "translate" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Translate to RO + EN
              </Button>
            )}

            <Button
              variant="outline"
              data-testid="cms-reset"
              onClick={reset}
              disabled={!!busy}
              className="h-10 gap-2 rounded-[10px] text-destructive"
            >
              {busy === "reset" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="h-4 w-4" />
              )}
              Back to built-in
            </Button>

            <a
              href={`/${lang}${slug === "home" ? "" : `/${slug}`}`}
              target="_blank"
              rel="noreferrer"
              data-testid="cms-open-page"
              className="inline-flex h-10 items-center gap-2 rounded-[10px] px-3 text-[13px] font-medium text-muted-foreground hover:text-foreground"
            >
              <Globe className="h-4 w-4" />
              Open the page
            </a>

            {doc.updated_at ? (
              <span className="text-[12px] text-muted-foreground">
                Saved {stampSofia(doc.updated_at)}
                {doc.updated_by ? ` by ${doc.updated_by}` : ""}
              </span>
            ) : (
              <span className="text-[12px] text-muted-foreground">Built-in text in use</span>
            )}
          </div>

          <CompanyCard />
        </>
      )}
    </div>
  );
};

export default AdminPages;
