import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Heart,
  ShieldAlert,
  FileCheck2,
  Stethoscope,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  Calculator,
  ExternalLink,
  SearchX,
  Share,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { HeaderBar } from "@/components/HeaderBar";
import { DetailStickyBar } from "@/components/DetailStickyBar";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { PhotoSwiper } from "@/components/PhotoSwiper";
import { CarGrid } from "@/components/CarGrid";
import { ReserveCar } from "@/components/ReserveCar";
import { useApp } from "@/context/AppContext";
import { useGate } from "@/components/SignInGate";
import { EnquiryDialog } from "@/components/EnquiryDialog";
import { CallButton } from "@/components/CallButton";
import { DescriptionPanelBody } from "@/components/DescriptionPanelBody";
import { ClampBlock } from "@/components/ClampBlock";
import { PriceNote } from "@/components/PriceNote";
import { YouMightLike } from "@/components/YouMightLike";
import { MoreFromModel } from "@/components/MoreFromModel";
import { useLangNav } from "@/hooks/useLangNav";
import { useDisplayMode } from "@/hooks/useDisplayMode";
import { useShare } from "@/hooks/useShare";
import { usePhotoPreload } from "@/hooks/usePhotoPreload";
import { getCar, warmCar, forgetCar, countView } from "@/lib/api";
import { noteView, WEIGHT } from "@/lib/taste";
import { setBackScroll } from "@/lib/backScroll";
import { allows } from "@/lib/consent";
import Lightbox from "@/components/Lightbox";
import BodyDiagram from "@/components/BodyDiagram";
import MechChecks from "@/components/MechChecks";
import PostToMobileBg from "@/components/admin/PostToMobileBg";
import { useSeo, useJsonLd } from "@/lib/seo";
import { formatMileage, formatMoney, formatNumber, formatYearMonth,
         titleModel } from "@/lib/format";

// Panels stay in the site's palette: white card, grey tile, red only where something is
// actually wrong. Coloured tiles (blue/amber/green) fought with the rest of the page, so any
// legacy tone falls through to neutral.
const Panel = ({ title, icon: Icon, children, testId, tone = "info", className = "" }) => (
  <section
    data-testid={testId}
    className={`overflow-hidden rounded-[16px] border border-border bg-card shadow-sm ${className}`}
  >
    <header className="flex items-center gap-2.5 border-b border-border px-4 py-3">
      <span
        className={`flex h-8 w-8 items-center justify-center rounded-[9px] bg-[hsl(var(--${tone}-soft))]`}
      >
        <Icon className={`h-4 w-4 text-[hsl(var(--${tone}))]`} aria-hidden="true" />
      </span>
      <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
    </header>
    <div className="px-4 py-3">{children}</div>
  </section>
);

const Row = ({ label, value, strong, testId }) => (
  <div className="flex items-baseline justify-between gap-4 border-b border-border/60 py-2 last:border-0">
    <span className="text-[13px] text-muted-foreground">{label}</span>
    <span
      data-testid={testId}
      className={`tnum text-right text-[13px] ${
        strong ? "text-[15px] font-semibold text-foreground" : "text-foreground"
      }`}
    >
      {value}
    </span>
  </div>
);

const CountRow = ({ label, count, testId }) => {
  const { t } = useApp();
  const n = Number(count) || 0;
  const bad = n > 0;
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 py-2 last:border-0">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span
        data-testid={testId}
        className={`tnum inline-flex items-center gap-1.5 text-[13px] font-medium ${
          bad ? "text-destructive" : "text-[hsl(var(--success))]"
        }`}
      >
        {bad ? (
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {bad ? `${n} ${t("times")}` : t("no")}
      </span>
    </div>
  );
};

export default function CarDetailPage() {
  const { id, slug: urlSlug } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { path } = useLangNav();
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();
  const { requireAccount } = useGate();
  const standalone = useDisplayMode();
  const share = useShare();

  const [car, setCar] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sold, setSold] = useState(null);
  const [active, setActive] = useState(0);
  const [shot, setShot] = useState(null);
  // Mobile: tap the hero photo → open the vertical column of all photos. Tapping any
  // photo inside that column then hands off to the single-photo lightbox (`shot`),
  // which owns the zoom (pinch + double tap, ours, not the browser's).
  const [lightbox, setLightbox] = useState(false);
  // No zoom at all in the photo column. `touch-action: pan-y` on the panel covers
  // Chrome/Android, but Safari's pinch arrives as `gesture*` events on the document and
  // is only stoppable here — and only with a non-passive listener.
  useEffect(() => {
    if (!lightbox) return undefined;
    const stop = (e) => e.preventDefault();
    document.addEventListener("gesturestart", stop, { passive: false });
    document.addEventListener("gesturechange", stop, { passive: false });
    document.addEventListener("gestureend", stop, { passive: false });
    return () => {
      document.removeEventListener("gesturestart", stop);
      document.removeEventListener("gesturechange", stop);
      document.removeEventListener("gestureend", stop);
    };
  }, [lightbox]);

  const openPhotos = (i) => {
    if (window.matchMedia("(min-width: 1024px)").matches) setShot(i);
    else setLightbox(true);
  };

  // Opening a car from halfway down the result list must not keep that scroll offset:
  // the visitor expects to land at the top of the car they just tapped.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    let retry = null;
    let retries = 0;
    setLoading(true);
    setError(null);
    setSold(null);

    const load = (isRetry) => {
      // A row the visitor hovered has already been warmed, so this resolves instantly.
      // Retries must bypass that cache, otherwise the pending translation never arrives.
      if (isRetry) forgetCar(id, lang);
      return (isRetry ? getCar(id, lang) : warmCar(id, lang))
        .then((d) => {
          if (cancelled) return;
          setCar(d);
          noteView(d);
          // How often an ad is opened feeds the "popular cars" ranking - statistics, so it
          // waits for that consent.
          if (allows("statistics")) countView(id);
          // Per-car freeform text (dealer branch, address, plate) is translated in the
          // background so the page renders immediately; pick it up when it lands. The
          // diagnosis comment can take the LLM a while, so we wait it out rather than
          // leaving the buyer with a paragraph of Korean: 4s, 7s, 11s, 16s.
          //
          // `sections_pending` is the same idea for the insurance record, inspection
          // sheet and diagnosis: the backend now serves the page as soon as it has the
          // car itself and fetches those four documents behind it (they cost 5-16s of
          // upstream pacing), so they are polled for sooner - 2s, 4s, 7s, 11s.
          const pending = d?.description_pending || d?.translation_pending
            || d?.sections_pending;
          if (pending && retries < 4) {
            retries += 1;
            const wait = d?.sections_pending && !d?.description_pending
              ? 1000 + retries * 1500
              : 1000 + retries * 3500;
            retry = setTimeout(() => load(true), wait);
          }
        })
        .catch((e) => {
          if (cancelled) return;
          // 410 Gone: Encar has retired the ad. Not an error to apologise for — offer the
          // cars the backend already picked out instead.
          if (e?.response?.status === 410 && e.response.data?.sold) {
            forgetCar(id, lang);
            setSold(e.response.data);
            return;
          }
          setError(e?.response?.data?.detail || e.message);
        })
        .finally(() => !cancelled && setLoading(false));
    };

    load(false);
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
    };
  }, [id, lang]);

  const money = (v) => formatMoney(v, currency, lang, rates);
  const pct = (f) => `${Math.round((f || 0) * 100)}%`;
  const saved = isFavourite(id);
  // Time on the page is the honest measure of interest: a 30-second read counts for more
  // than a click that bounced. One extra signal, once, then the timer is done.
  useEffect(() => {
    if (!car) return undefined;
    const timer = setTimeout(() => noteView(car, WEIGHT.dwell), 30000);
    return () => clearTimeout(timer);
  }, [car?.id]);

  const photos = car?.photos || [];
  const q = car?.quote;

  // The mobile viewer is a column of every photo. While it is open they are pulled into
  // the browser cache one after another, in the order they are scrolled past, so
  // scrolling down the column does not wait on the CDN photo by photo.
  usePhotoPreload(
    photos.map((p) => p.full_lightbox || p.full),
    0,
    lightbox
  );

  // The SEO/preview title carries the trim: "Mercedes-Benz AMG GT 4-door 43 4MATIC+" says far
  // more in a search result or a chat bubble than the make and model alone. The H1 keeps its
  // shorter form. Parts already contained in the title are not repeated.
  // Brackets and "All New" are stripped for the title only: the factory code (PO536) and the
  // production years belong on the page, not in a search result or a chat bubble.
  const seoTitle = [titleModel(car?.title || ""), car?.grade, car?.badge_detail]
    .filter(Boolean)
    // A part that is nothing but a parenthetical is Encar's own filler — "(No detailed
    // trim)" — and belongs in no title. Same rule as the backend's _share_title.
    .filter((p) => !/^\(.*\)$/.test(String(p).trim()))
    .reduce((acc, part) => (
      acc.toLowerCase().includes(String(part).toLowerCase()) ? acc : `${acc} ${part}`.trim()
    ), "")
    // "BMW M2" + "M2 Coupe" joins as "BMW M2 M2 Coupe" — the same word twice in a row is a
    // stutter, so consecutive repeats collapse. Same rule as the backend's _share_title.
    .split(/\s+/)
    .filter((w, i, a) => !i || w.toLowerCase() !== a[i - 1].toLowerCase())
    .join(" ");

  // URL slug: transliterate the SEO title down to `[a-z0-9-]+` so shareable / indexable
  // links carry the make + model in the address bar. Keeps the numeric id at the front
  // so lookups still work with either shape (`/car/{id}` and `/car/{id}/{slug}`).
  const seoSlug = seoTitle
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")           // strip combining diacritics
    .replace(/[^a-z0-9]+/g, "-")               // collapse anything non-slug
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);

  // Once the car has loaded, canonicalise the URL: if the visitor is on
  // /bg/car/{id} we drop them on /bg/car/{id}/{slug} so the URL reflects the
  // listing, without changing the underlying page or its data. Uses `replace`
  // so the browser back button skips this bookkeeping hop.
  useEffect(() => {
    if (!car || !seoSlug) return;
    if (urlSlug === seoSlug) return;
    navigate(`/${lang}/car/${id}/${seoSlug}${location.search}${location.hash}`, {
      replace: true,
    });
  }, [car, seoSlug, urlSlug, id, lang, location.search, location.hash, navigate]);

  // Title and description are built from the SAME cleaned name and the SAME facts the share
  // page uses (backend `share_car`), so a Google snippet and a Messenger preview of one car
  // never read differently.
  const km = car?.mileage ?? car?.spec?.mileage ?? null;
  const facts = [
    car?.year_month ? formatYearMonth(car.year_month) : "",
    km ? formatMileage(km, lang) : "",
    q?.suggested_sale ? money(q.suggested_sale) : "",
  ].filter(Boolean).join(" · ");

  useSeo({
    lang,
    title: seoTitle ? `${seoTitle} \u00b7 Encar` : "Encar",
    description: facts ? `${facts} \u2014 ${t("seoCarDesc")}` : t("seoCarDesc"),
    // Two shared-preview paths need this og:image and they read it in different places:
    //   * A social crawler (Messenger, Viber, Facebook, iMessage's own fetch) hits the URL
    //     directly - nginx routes it to /api/share/car/{id}, which is SSR and has the right
    //     picture baked into the initial HTML response. This hook is invisible to them.
    //   * Safari's iOS Share sheet does NOT run a fresh crawler fetch. It reads whatever
    //     og:image the CURRENT TAB'S DOM carries at the moment the user taps Share, and
    //     hands that to Messages. Without this line the DOM keeps the shell fallback (the
    //     site logo from index.html) and Messages then previews a logo instead of the car.
    // The picture is our /api/og/{id}.jpg proxy - the same URL the SSR endpoint uses - so
    // there is exactly one image address for a listing across every share path.
    image: `${window.location.origin}/api/og/${id}.jpg`,
    // An ad is a product listing, not an article or a plain page: Facebook, Pinterest and
    // Google all read og:type, and the prerendered HTML (backend/prerender.py) says the
    // same thing, so the two never disagree.
    ogType: "product",
    // A retired ad, or one we could not load at all, must not stay in the index — but its
    // links (the similar cars we offer instead) are worth following.
    noindex: !!sold || !!error,
    follow: true,
  });

  // Structured data: this is what earns a car a rich result with its price and mileage
  // instead of a plain blue link. Only the facts we actually hold are declared.
  useJsonLd(
    car
      ? {
          "@context": "https://schema.org",
          "@type": "Car",
          name: car.title,
          image: photos.slice(0, 8).map((p) => p.full),
          ...(car.manufacturer_t || car.manufacturer
            ? { brand: { "@type": "Brand", name: car.manufacturer_t || car.manufacturer } }
            : {}),
          ...(car.model_t || car.model ? { model: car.model_t || car.model } : {}),
          ...(car.form_year ? { vehicleModelDate: String(car.form_year) } : {}),
          ...(car.mileage
            ? {
                mileageFromOdometer: {
                  "@type": "QuantitativeValue",
                  value: car.mileage,
                  unitCode: "KMT",
                },
              }
            : {}),
          ...(car.fuel_t || car.fuel_type ? { fuelType: car.fuel_t || car.fuel_type } : {}),
          ...(car.transmission_t ? { vehicleTransmission: car.transmission_t } : {}),
          itemCondition: "https://schema.org/UsedCondition",
          ...(q?.sale_eur
            ? {
                offers: {
                  "@type": "Offer",
                  price: q.sale_eur,
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                  url: window.location.href,
                },
              }
            : {}),
        }
      : null,
    "car-jsonld"
  );

  // "Back to results" must land on the SAME result set the visitor came from. The
  // search page hands us its query string; otherwise step back through history, and
  // only fall back to the car's own make/model search when this page was opened cold
  // (shared link, Google result, direct paste). "Home" is the last-resort — a shared
  // link at least tells us the make and model of the car the visitor is looking at,
  // so a Back to that search is a better landing than an empty catalogue.
  const goBack = () => {
    const from = location.state?.from;
    // Hand the list back the offset it was left at, so the visitor returns to the car
    // they tapped rather than to the top of 200 results.
    if (location.state?.scrollY != null) setBackScroll(location.state.scrollY);
    // A real history POP whenever this page was opened from inside the app, so the button
    // behaves EXACTLY like the browser's own Back: the entry the list already occupies is
    // reused instead of a second copy being pushed on top of it (which was both slower and
    // left a Back that went nowhere). Pushing is only for a cold open of a shared link.
    if (location.key !== "default") return navigate(-1);
    if (typeof from === "string") return navigate({ pathname: path("/"), search: from });
    // Cold open: build the same URL the model breadcrumb points to. Prefer the
    // English make/model so the search page's chips read "Hyundai / Santa Fe" and
    // not raw Korean — the search resolver looks up both shapes, so either works
    // for matching listings, but only the English form gives us readable labels
    // without waiting for the taxonomy roundtrip.
    const mk = car?.manufacturer || car?.manufacturer_raw;
    const md = car?.model || car?.model_raw;
    if (mk) {
      const params = new URLSearchParams();
      params.set("make", mk);
      if (md) params.set("model", md);
      return navigate({ pathname: path("/"), search: `?${params.toString()}` });
    }
    navigate(path("/"));
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar onBack={goBack} />
      <DetailStickyBar
        car={car}
        price={money(q?.suggested_sale ?? 0)}
        saved={saved}
        onToggleSave={() => requireAccount("car") && toggleFavourite(id, car)}
      />

      {/* The car bar is now sticky IN FLOW on mobile, so it reserves its own height —
          no manual `pt-[72px]` compensation (that used to double up as a gap). */}
      <div className="mx-auto max-w-[1280px] px-4 pb-5 pt-3 sm:px-6 lg:pt-2">
        {/* Breadcrumbs: Home > Make > Model > Submodel. Each step is a Link to the
            search filtered to that exact scope, so a buyer can jump back one level at a
            time — tapping "W205" leads to every W205 we carry, not to the model page. */}
        {car && (
          <Breadcrumbs
            testId="car-breadcrumbs"
            items={[
              { label: t("breadcrumbHome"), to: `/${lang}` },
              ...(car.manufacturer_raw || car.manufacturer
                ? [{
                    label: car.manufacturer_t || car.manufacturer,
                    to: `/${lang}?make=${encodeURIComponent(car.manufacturer_raw || car.manufacturer)}`,
                  }]
                : []),
              ...(car.model_raw || car.model
                ? [{
                    label: car.model_t || car.model,
                    to: `/${lang}?make=${encodeURIComponent(car.manufacturer_raw || car.manufacturer || "")}`
                        + `&model=${encodeURIComponent(car.model_raw || car.model)}`,
                  }]
                : []),
              ...(car.badge_raw || car.badge
                ? [{
                    label: car.badge_t || car.badge,
                    to: `/${lang}?make=${encodeURIComponent(car.manufacturer_raw || car.manufacturer || "")}`
                        + `&model=${encodeURIComponent(car.model_raw || car.model || "")}`
                        + `&badge=${encodeURIComponent(car.badge_raw || car.badge)}`,
                  }]
                : []),
            ]}
          />
        )}
        <Button
          data-testid="back-to-results-button"
          variant="ghost"
          onClick={goBack}
          // Mobile has the arrow in the header instead; two back affordances is one too many.
          className="mb-1 hidden h-9 gap-1.5 px-2 text-sm text-muted-foreground hover:bg-muted lg:inline-flex"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("backToResults")}
        </Button>

        {loading && (
          <div className="space-y-4" data-testid="detail-loading">
            <Skeleton className="h-8 w-2/3 bg-muted" />
            <Skeleton className="aspect-[16/9] w-full rounded-[16px] bg-muted" />
            <div className="grid gap-4 sm:grid-cols-2">
              <Skeleton className="h-48 rounded-[16px] bg-muted" />
              <Skeleton className="h-48 rounded-[16px] bg-muted" />
            </div>
          </div>
        )}

        {/* The ad is gone from Encar. Nobody wants a dead end, so the page says what
            happened and offers the same make and model instead. */}
        {!loading && sold && (
          <div data-testid="detail-sold">
            <div className="rounded-[18px] border border-border bg-card px-6 py-10 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
                <SearchX className="h-7 w-7 text-[hsl(var(--primary))]" aria-hidden="true" />
              </div>
              <h1
                data-testid="detail-sold-title"
                className="mt-4 text-2xl font-semibold text-foreground sm:text-3xl"
              >
                {t("soldTitle")}
              </h1>
              <p className="mx-auto mt-2 max-w-lg text-base leading-relaxed text-muted-foreground">
                {t("soldBody")}
              </p>
              {(sold.make || sold.model) && (
                <div className="mt-3 text-sm font-medium text-foreground">
                  {[sold.make, sold.model].filter(Boolean).join(" ")}
                </div>
              )}
              <Button
                data-testid="detail-sold-browse"
                variant="secondary"
                onClick={() => navigate(path("/"))}
                className="mt-5 h-10 rounded-[10px] bg-secondary px-5 text-[hsl(var(--primary))] hover:brightness-95"
              >
                {t("soldBrowseAll")}
              </Button>
            </div>

            {sold.similar?.length > 0 && (
              <div className="mt-8">
                <h2 className="mb-3 text-base font-semibold text-foreground md:text-lg">
                  {t("soldSimilar")}
                </h2>
                <CarGrid
                  items={sold.similar}
                  onOpen={(c) => navigate(path(`/car/${c.id}`))}
                />
              </div>
            )}
          </div>
        )}

        {!loading && error && (
          <div
            data-testid="detail-error"
            className="rounded-[16px] border border-destructive/40 bg-secondary p-8 text-center"
          >
            <AlertTriangle className="mx-auto h-8 w-8 text-destructive" aria-hidden="true" />
            <h2 className="mt-3 text-[16px] font-semibold text-foreground">{t("notFound")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{String(error)}</p>
          </div>
        )}

        {!loading && car && (
          <>
            {/* Encar could not be reached, so this page was built from our own index:
                photos, model, year, mileage and price are real, the history and option
                list are simply not available yet. Saying so is better than an empty
                section that looks like the car has no history. */}
            {car.partial && (
              <div
                data-testid="detail-partial-banner"
                className="mb-4 flex flex-wrap items-center gap-3 rounded-[14px] border border-amber-500/40 bg-amber-500/10 px-4 py-3"
              >
                <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" aria-hidden="true" />
                <p className="min-w-0 flex-1 text-[13px] text-foreground">
                  {t("partialData")}
                </p>
                <Button
                  data-testid="detail-partial-retry"
                  variant="outline"
                  onClick={() => window.location.reload()}
                  className="h-8 rounded-[9px] px-3 text-[12.5px]"
                >
                  {t("retry")}
                </Button>
              </div>
            )}
            {car.under_contract && (
              <div
                data-testid="detail-contract-banner"
                className="mb-4 flex items-start gap-3 rounded-[14px] border-2 border-[hsl(var(--primary))] bg-secondary px-4 py-3"
              >
                <ShieldAlert
                  className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--primary))]"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-[14px] font-bold uppercase tracking-wide text-[hsl(var(--primary))]">
                    {t("underContract")}
                  </p>
                  <p className="mt-0.5 text-[13px] text-foreground">{t("underContractNote")}</p>
                </div>
              </div>
            )}

            {/* Price and save live in the persistent bar on mobile, so they would only
                repeat here. The TITLE stays in the DOM at every width though — it is the
                page's only h1, and Google crawls the mobile layout. */}
            <div className="flex-wrap items-start justify-between gap-4 lg:flex">
              <div className="min-w-0">
                {/* The owner wants the full name — model, submodel AND trim — as the page's
                    h1, the same deduped string the SEO title carries. */}
                <h1
                  data-testid="detail-title"
                  className="sr-only text-2xl font-semibold leading-tight text-foreground sm:text-3xl lg:not-sr-only"
                >
                  {seoTitle || titleModel(car.title)}
                </h1>
              </div>
              <div className="hidden shrink-0 items-center gap-3 lg:flex">
                <div className="text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <div
                      data-testid="detail-price"
                      className="tnum text-3xl font-semibold tracking-tight text-foreground"
                    >
                      {money(q?.suggested_sale ?? 0)}
                    </div>
                    <PriceNote testId="detail-price-note" />
                  </div>
                  <div className="text-[12px] text-muted-foreground">{t("finalPrice")}</div>
                </div>
                <div className="flex items-center gap-2">
                  {/* Homescreen app only: sharing a car is the single most common thing a
                      buyer does from a phone, and in the installed app there is no browser
                      share button to fall back on. */}
                  {standalone && (
                    <Button
                      data-testid="detail-share-button"
                      variant="outline"
                      onClick={() => share({ title: car?.title || document.title })}
                      aria-label={t("pwaShareAria")}
                      title={t("pwaShareAria")}
                      className="h-11 w-11 border-border bg-card p-0 hover:bg-muted"
                    >
                      <Share className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                    </Button>
                  )}
                  <Button
                    data-testid="detail-save-button"
                    variant="outline"
                    onClick={() => requireAccount("car") && toggleFavourite(id, car)}
                    aria-label={saved ? t("saved") : t("save")}
                    title={saved ? t("saved") : t("save")}
                    className="h-11 w-11 border-border bg-card p-0 hover:bg-muted"
                  >
                    <Heart
                      className={`h-5 w-5 ${
                        saved
                          ? "fill-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                          : "text-muted-foreground"
                      }`}
                      aria-hidden="true"
                    />
                  </Button>
                </div>
              </div>
            </div>

            {/* ── gallery: every photo Encar has, loaded from their CDN ──
                Desktop puts the thumbnails in a scrollable column beside a smaller main
                image, so more of the car is visible without scrolling the page. Mobile
                keeps the stacked layout with a horizontal strip. */}
            <div className="mt-4">
              {/* The main image keeps a true 16:9 - its height then defines the row, and
                  the thumbnail column is pinned to that height so it scrolls internally
                  instead of stretching the layout or cropping the photo. */}
              <div className="relative flex flex-col gap-2 lg:block">
                <div className="aspect-[16/9] w-full cursor-zoom-in overflow-hidden rounded-[16px] border border-border lg:w-[calc(100%-286px)]">
                  <PhotoSwiper
                    images={photos.map((p) => p.full)}
                    imagesMobile={photos.map((p) => p.full_mobile || p.full)}
                    alt={car.title}
                    testId="detail-main-photo"
                    index={active}
                    onIndexChange={setActive}
                    onTap={() => photos.length && openPhotos(active)}
                    countOnHover
                    hint={t("zoom")}
                    arrows
                    // The main gallery picture is the LCP element on this route: telling
                    // the browser to load it eagerly and prioritise it removes the "lazy"
                    // flag Lighthouse kept flagging on `detail-main-photo-image`.
                    eager
                    priority
                  />
                </div>

                {photos.length > 1 && (
                  <div
                    data-testid="detail-thumb-strip"
                    className="thin-scroll flex gap-2 overflow-x-auto pb-2 lg:absolute lg:inset-y-0 lg:right-0 lg:w-[276px] lg:flex-col lg:overflow-x-hidden lg:overflow-y-auto lg:pb-0 lg:pr-1"
                  >
                    {photos.map((p, i) => (
                      <button
                        key={p.full || p.thumb || i}
                        type="button"
                        data-testid="detail-photo-thumb"
                        onClick={() => setActive(i)}
                        onDoubleClick={() => openPhotos(i)}
                        aria-label={`${t("allPhotos")} ${i + 1}`}
                        aria-current={i === active ? "true" : undefined}
                        className={`h-[76px] w-[112px] shrink-0 overflow-hidden rounded-[8px] border-2 transition-colors lg:aspect-video lg:h-auto lg:w-full ${
                          i === active ? "border-[hsl(var(--primary))]" : "border-border"
                        }`}
                      >
                        <ImageWithFallback src={p.thumb} alt="" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

            </div>

            {/* On mobile the enquiry is the next thing after the photos: by then the buyer
                has seen the car and the price, and nothing should sit between that and
                getting in touch. Desktop keeps it beside the specs. */}
            {/* Both actions sit directly under the photos: by then the buyer has seen the
                car and the price, and enquiring or holding it must be one glance away. */}
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {/* Enquire and call share what used to be the enquiry button's width, so the
                  buyer can pick the channel they actually want without hunting for a number. */}
              <div className="grid grid-cols-2 gap-3">
                <EnquiryDialog car={car} title={car.title} />
                <CallButton car={car} title={car.title} />
              </div>
              <ReserveCar car={car} />
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              {/* Cost and margin — only present in the payload for signed-in admins. */}
              {car.admin && (
                <Panel
                  title="Cost & margin (admin only)"
                  icon={Calculator}
                  testId="detail-admin-pricing"
                  tone="warning"
                >
                  <Row
                    label="Encar price"
                    value={`\u20a9${formatNumber(car.admin.price_krw, lang)}`}
                    testId="admin-price-krw"
                  />
                  <Row label="Car cost (Encar)" value={money(car.admin.encar_eur)} />
                  <Row label="Autowini fee" value={money(car.admin.autowini_fee_eur)} />
                  <Row label="Inland + buffer" value={money(car.admin.domestic_total)} />
                  <Row
                    label={`Duty + VAT \u2014 ${pct(car.admin.customs_fraction_low)} base`}
                    value={money(car.admin.taxes_low)}
                    testId="admin-taxes-low"
                  />
                  <Row
                    label={`Duty + VAT \u2014 ${pct(car.admin.customs_fraction_high)} base`}
                    value={money(car.admin.taxes_high)}
                    testId="admin-taxes-high"
                  />
                  <Row
                    label={`Landed cost \u2014 ${pct(car.admin.customs_fraction_low)} base`}
                    strong
                    testId="admin-landed-low"
                    value={money(car.admin.landed_at_low)}
                  />
                  <Row
                    label={`Landed cost \u2014 ${pct(car.admin.customs_fraction_high)} base`}
                    strong
                    testId="admin-landed-high"
                    value={money(car.admin.landed_at_high)}
                  />
                  <Row label="Sale price" strong value={money(car.admin.sale_eur)} />
                  <Row
                    label={`Margin \u2014 ${pct(car.admin.customs_fraction_low)} base`}
                    strong
                    testId="admin-margin-low"
                    value={money(car.admin.margin_at_low)}
                  />
                  <Row
                    label={`Margin \u2014 ${pct(car.admin.customs_fraction_high)} base`}
                    strong
                    testId="admin-margin-high"
                    value={money(car.admin.margin_at_high)}
                  />
                  {car.admin.floored_low && car.admin.floored_high && (
                    <p
                      data-testid="admin-customs-floor-note"
                      className="pt-2 text-[12px] leading-relaxed text-muted-foreground"
                    >
                      Both scenarios are identical here: {pct(car.admin.customs_fraction_low)} and{" "}
                      {pct(car.admin.customs_fraction_high)} of the car cost are both below the
                      USD 3,000 minimum customs value, so duty and VAT are charged on that floor
                      ({money(car.admin.customs_base_low)}) either way.
                    </p>
                  )}
                  {car.admin.floored_low && !car.admin.floored_high && (
                    <p
                      data-testid="admin-customs-floor-note"
                      className="pt-2 text-[12px] leading-relaxed text-muted-foreground"
                    >
                      The {pct(car.admin.customs_fraction_low)} scenario hits the USD 3,000 minimum
                      customs value, so its base is {money(car.admin.customs_base_low)} rather than
                      the percentage.
                    </p>
                  )}
                  {/* The original ad, one click away: an operator checking a margin usually
                      wants to see what Encar itself is showing for the same car. Only the id
                      changes - the rest of the address is fixed. */}
                  <a
                    data-testid="admin-encar-link"
                    href={`https://fem.encar.com/cars/detail/${car.id}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[hsl(var(--primary))] underline-offset-4 transition-opacity hover:opacity-80 hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    Original ad on Encar ({car.id})
                  </a>
                  <PostToMobileBg carId={car.id} />
                </Panel>
              )}
              <Panel title={t("specs")} icon={FileCheck2} testId="detail-specs" tone="info">
                <Row label={t("year")} value={formatYearMonth(Number(car.year_month), car.form_year)} />
                <Row label={t("mileage")} value={formatMileage(car.spec?.mileage, lang, t("km"))} />
                {car.spec?.fuel && <Row label={t("fuel")} value={car.spec.fuel} />}
                {car.spec?.transmission && (
                  <Row label={t("transmission")} value={car.spec.transmission} />
                )}
                {car.spec?.displacement ? (
                  <Row
                    label={t("engine")}
                    value={`${formatNumber(car.spec.displacement, lang)} cc`}
                  />
                ) : null}
                {car.spec?.colour && <Row label={t("colour")} value={car.spec.colour} />}
                {car.spec?.seats ? <Row label={t("seats")} value={car.spec.seats} /> : null}
                {car.spec?.vin && <Row label={t("vin")} value={car.spec.vin} />}
              </Panel>

              {/* enquiry and reserve both live under the photos now */}

              {/* insurance history */}
              <Panel
                title={t("insuranceHistory")}
                icon={ShieldAlert}
                testId="detail-insurance"
                tone="warning"
              >
                {car.insurance ? (
                  <>
                    {car.insurance.accident_free && (
                      <Badge className="mb-2 rounded-full border-0 bg-[hsl(var(--success-soft))] px-2.5 py-1 text-[12px] font-medium text-[hsl(var(--success))]">
                        {t("accidentFree")}
                      </Badge>
                    )}
                    <CountRow
                      label={t("ownAccidents")}
                      count={car.insurance.own_accidents}
                      testId="insurance-own-accidents"
                    />
                    <CountRow
                      label={t("otherAccidents")}
                      count={car.insurance.other_accidents}
                      testId="insurance-other-accidents"
                    />
                    <CountRow label={t("totalLoss")} count={car.insurance.total_loss} />
                    <CountRow label={t("floodDamage")} count={car.insurance.flood_total_loss} />
                    <CountRow label={t("theftRecords")} count={car.insurance.theft} />
                    <CountRow label={t("commercialUse")} count={car.insurance.commercial_use} />
                    <CountRow label={t("rentalUse")} count={car.insurance.rental_use} />
                    <Row
                      label={t("ownerChanges")}
                      value={formatNumber(car.insurance.owner_changes || 0, lang)}
                      testId="insurance-owner-changes"
                    />
                    {car.insurance.first_registration && (
                      <Row label={t("year")} value={car.insurance.first_registration} />
                    )}
                    {car.insurance.own_accident_cost_eur ? (
                      <Row
                        label={t("ownClaimAmount")}
                        value={formatMoney(
                          car.insurance.own_accident_cost_eur,
                          currency,
                          lang,
                          rates
                        )}
                        testId="insurance-own-claim-amount"
                      />
                    ) : null}
                    {/* The third-party claim amount is deliberately NOT shown: it is what the
                        car's insurer paid to SOMEBODY ELSE, so it says nothing about the
                        condition of this car and only made buyers think the car itself had
                        995 EUR of damage. The claim COUNT above is the useful figure. */}
                  </>
                ) : (
                  <p className="py-2 text-[13px] text-muted-foreground">
                    {/* Still on its way from Encar is not the same statement as "this car
                        has no history", so the panel says which one it is. */}
                    {car.sections_pending ? t("loading") : t("docNotAvailable")}
                  </p>
                )}
              </Panel>

              {/* inspection sheet */}
              <Panel
                title={t("inspectionReport")}
                icon={FileCheck2}
                testId="detail-inspection"
                tone="info"
              >
                {car.inspection ? (
                  <>
                    <CountRow
                      label={t("accidentRepair")}
                      count={car.inspection.accident ? 1 : 0}
                    />
                    <CountRow
                      label={t("simpleRepair")}
                      count={car.inspection.simple_repair ? 1 : 0}
                    />
                    {car.inspection.mileage ? (
                      <Row
                        label={t("mileage")}
                        value={formatMileage(car.inspection.mileage, lang, t("km"))}
                      />
                    ) : null}
                    {car.inspection.guaranty && (
                      <Row label={t("documents")} value={car.inspection.guaranty} />
                    )}
                    {car.inspection.board_state && (
                      <Row label={t("chassisCondition")} value={car.inspection.board_state} />
                    )}
                    {car.inspection.vin && <Row label={t("vin")} value={car.inspection.vin} />}
                    {car.inspection.validity_end && (
                      <Row label={t("to")} value={car.inspection.validity_end} />
                    )}
                  </>
                ) : (
                  <p className="py-2 text-[13px] text-muted-foreground">
                    {/* Still on its way from Encar is not the same statement as "this car
                        has no history", so the panel says which one it is. */}
                    {car.sections_pending ? t("loading") : t("docNotAvailable")}
                  </p>
                )}
              </Panel>

              {/* body condition diagram */}
              {car.body_panels && <BodyDiagram panels={car.body_panels} />}

              {/* mechanical checks, beside the body diagram */}
              {car.mech_checks && <MechChecks checks={car.mech_checks} />}

              {/* Encar diagnosis */}
              {car.diagnosis && (
                <Panel
                  title={t("diagnosisReport")}
                  icon={Stethoscope}
                  testId="detail-diagnosis"
                  tone="success"
                >
                  <div className="mb-2 flex flex-wrap gap-2">
                    <Badge className="rounded-full border-0 bg-[hsl(var(--info-soft))] px-2.5 py-1 text-[12px] text-[hsl(var(--info))]">
                      {formatNumber(car.diagnosis.total, lang)} {t("panelsChecked")}
                    </Badge>
                    <Badge
                      className={`rounded-full border-0 px-2.5 py-1 text-[12px] ${
                        car.diagnosis.abnormal
                          ? "bg-secondary text-destructive"
                          : "bg-[hsl(var(--success-soft))] text-[hsl(var(--success))]"
                      }`}
                    >
                      {formatNumber(car.diagnosis.abnormal, lang)} {t("abnormalPanels")}
                    </Badge>
                  </div>
                  {(car.diagnosis.comments || []).map((c, i) => (
                    <p
                      key={i}
                      data-testid="diagnosis-comment"
                      className="mb-2 rounded-[10px] border border-[hsl(var(--success))]/30 bg-[hsl(var(--success-soft))] px-3 py-2 text-[12px] leading-relaxed text-[hsl(var(--success))]"
                    >
                      {c}
                    </p>
                  ))}
                  <div className="thin-scroll max-h-56 overflow-y-auto">
                    {car.diagnosis.items.map((it, i) => (
                      <div
                        key={`${it.panel}-${i}`}
                        className="flex items-center justify-between gap-3 border-b border-border/60 py-1.5 last:border-0"
                      >
                        <span className="text-[12px] text-muted-foreground">{it.panel}</span>
                        <span
                          className={`text-[12px] font-medium ${
                            it.result_code === "NORMAL"
                              ? "text-[hsl(var(--success))]"
                              : "text-destructive"
                          }`}
                        >
                          {it.result}
                        </span>
                      </div>
                    ))}
                  </div>
                </Panel>
              )}

              {/* equipment */}
              {car.options && (
                <Panel
                  title={t("optionsTitle")}
                  icon={FileCheck2}
                  testId="detail-options"
                  // The equipment list is the tallest block on the page. Across the full
                  // width its categories sit side by side, which halves its height.
                  className="lg:col-span-2"
                  >
                  {/* The tallest block on the page by far — clamped to about ten rows so the
                      description and the shelf below it are not pushed off the screen. */}
                  <ClampBlock maxHeight={300} testId="options-clamp">
                  <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
                    {(car.options.groups || []).map((g) => (
                      <div key={g.category}>
                        <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {g.category}
                        </h3>
                        <div className="flex flex-wrap gap-1.5">
                          {g.items.map((x) => (
                            <span
                              key={x}
                              className="rounded-full bg-muted px-2.5 py-1 text-[12px] text-foreground"
                            >
                              {x}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  {(car.options.factory || []).length > 0 && (
                    <div className="mt-4">
                      <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("factoryOptions")}
                      </h3>
                      <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
                      {car.options.factory.map((f) => (
                        <Row
                          key={f.name}
                          label={f.name}
                          value={
                            f.price_manwon
                              ? formatMoney(
                                  (f.price_manwon * 10000) / (rates?.fx_krw_eur || 1664),
                                  currency,
                                  lang,
                                  rates
                                )
                              : "\u2014"
                          }
                        />
                      ))}
                      </div>
                    </div>
                  )}
                  {(car.options.tuning || []).length > 0 && (
                    <div className="mt-3">
                      <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("tuningOptions")}
                      </h3>
                      <div className="flex flex-wrap gap-1.5">
                        {car.options.tuning.map((x) => (
                          <span
                            key={x}
                            className="rounded-full bg-muted px-2.5 py-1 text-[12px] text-foreground"
                          >
                            {x}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  </ClampBlock>
                </Panel>
              )}
            </div>

            {/* dealer description */}
            {car.description && (
              <div className="mt-4">
                <Panel
                  title={t("descriptionTitle")}
                  icon={FileCheck2}
                  testId="detail-description"
                  >
                  <DescriptionPanelBody carId={id} original={car.description} />
                </Panel>
              </div>
            )}

            {/* Read the description, liked the car — the next question is "what else?"
                First the strict same-model shelf ("more 5-Series like this one"), then
                a broader taste-blended one. Shopper who is model-locked jumps within the
                model without redoing filters; a shopper who is open to alternatives
                still gets the wider net below. */}
            <MoreFromModel
              carId={id}
              onOpen={(c) => navigate(path(`/car/${c.id}`))}
            />
            <YouMightLike
              car={car}
              excludeId={id}
              onOpen={(c) => navigate(path(`/car/${c.id}`))}
            />

          </>
        )}
      </div>

      {/* Mobile viewer: a vertical column of every photo, close to how a phone gallery
          reads. Tapping any photo inside hands off to the single-photo lightbox, which
          is where iOS pinch-zoom actually works (no scrolling container to compete with
          the visualViewport pan). */}
      <Dialog open={lightbox} onOpenChange={setLightbox}>
        <DialogContent
          data-testid="detail-lightbox"
          // The stock close button is absolute inside this scrolling column, so it slides
          // out of reach on the second photo. Hidden here in favour of the sticky one below.
          className="max-h-[92vh] max-w-4xl overflow-y-auto border-border bg-black p-0 [&>button]:hidden"
          // Native zoom off entirely in the photo column: `pan-y` leaves scrolling intact
          // but forbids pinch, and the `gesture*` handlers below stop Safari's own
          // document zoom. Zooming here dragged the sticky close button out of reach.
          style={{ touchAction: "pan-y" }}
        >
          <DialogTitle className="sr-only">{car?.title || t("allPhotos")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("allPhotos")} — {photos.length}
          </DialogDescription>
          {/* Sticky, zero-height rail: the close button rides along at the top of the
              viewport however far down the photos the visitor has scrolled. */}
          <div className="pointer-events-none sticky top-0 z-20 flex h-0 justify-end">
            <button
              type="button"
              data-testid="lightbox-close-button"
              onClick={() => setLightbox(false)}
              aria-label={t("close")}
              className="pointer-events-auto mr-3 mt-14 flex h-11 w-11 items-center justify-center rounded-full bg-white text-black shadow-[0_2px_10px_rgba(0,0,0,.45)] transition-transform active:scale-95"
            >
              <X className="h-6 w-6" aria-hidden="true" />
            </button>
          </div>

          <div className="flex flex-col gap-1.5 bg-black py-1.5">
            {photos.map((p, i) => (
              <button
                key={p.full || i}
                type="button"
                data-testid={`detail-lightbox-photo-${i}`}
                onClick={() => {
                  // Close the column and open the zoomable single-photo viewer at the
                  // photo the visitor just tapped. `setShot` after the dialog transition
                  // starts avoids a two-modal flash.
                  setLightbox(false);
                  setShot(i);
                }}
                className="block w-full bg-black text-left"
                // `content-visibility: auto` lets Safari drop the render trees for photos
                // that are far off-screen, which stops a 40-photo column from tripping
                // the "a problem repeatedly occurred" out-of-memory bail-out on lower-
                // memory iPhones. The intrinsic-size hint keeps the scroll bar behaving
                // while photos below the fold have not yet materialised.
                style={{
                  contentVisibility: "auto",
                  containIntrinsicSize: "1px 60vw",
                }}
              >
                <ImageWithFallback
                  // `full_lightbox` is the CDN's uncropped variant - portrait photos
                  // arrive portrait so `object-contain` letterboxes instead of hacking
                  // top and bottom off a 16:9 crop the way `full` does.
                  src={p.full_lightbox || p.full}
                  alt={car?.title || ""}
                  fit="contain"
                  testId={i === 0 ? "detail-lightbox-photo" : undefined}
                />
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Single-photo viewer: horizontal swipe navigates, native pinch-zoom works
          because there is no scrolling container competing with the visualViewport pan,
          and only the current photo is in memory. */}
      {shot !== null && (
        <Lightbox
          // Uncropped variant so a portrait source displays fully - `p.full` is the
          // 1280x720 hero card crop, which chops top and bottom off portrait photos.
          images={photos.map((p) => p.full_lightbox || p.full)}
          thumbnails={photos.map((p) => p.thumb)}
          index={shot}
          label={car?.title || ""}
          onClose={() => setShot(null)}
          onChange={(i) => {
            setShot(i);
            setActive(i);
          }}
        />
      )}
    </div>
  );
}
