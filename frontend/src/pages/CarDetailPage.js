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
  SearchX,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { HeaderBar } from "@/components/HeaderBar";
import { DetailStickyBar } from "@/components/DetailStickyBar";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { PhotoSwiper } from "@/components/PhotoSwiper";
import { CarGrid } from "@/components/CarGrid";
import { ReserveCar } from "@/components/ReserveCar";
import { useApp } from "@/context/AppContext";
import { EnquiryDialog } from "@/components/EnquiryDialog";
import { DescriptionPanelBody } from "@/components/DescriptionPanelBody";
import { ClampBlock } from "@/components/ClampBlock";
import { PriceNote } from "@/components/PriceNote";
import { YouMightLike } from "@/components/YouMightLike";
import { useLangNav } from "@/hooks/useLangNav";
import { getCar, warmCar, forgetCar, countView } from "@/lib/api";
import { noteView, WEIGHT } from "@/lib/taste";
import Lightbox from "@/components/Lightbox";
import BodyDiagram from "@/components/BodyDiagram";
import MechChecks from "@/components/MechChecks";
import { useSeo, useJsonLd } from "@/lib/seo";
import { formatMileage, formatMoney, formatNumber, formatYearMonth,
         stripGenerationYears } from "@/lib/format";

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
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { path } = useLangNav();
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();

  const [car, setCar] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sold, setSold] = useState(null);
  const [active, setActive] = useState(0);
  const [lightbox, setLightbox] = useState(false);
  // Desktop opens the full lightbox; the phone keeps the vertical photo column, which
  // reads better on a small screen than a one-at-a-time viewer.
  const [shot, setShot] = useState(null);

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
          countView(id);
          // Per-car freeform text (dealer branch, address, plate) is translated in the
          // background so the page renders immediately; pick it up when it lands. The
          // diagnosis comment can take the LLM a while, so we wait it out rather than
          // leaving the buyer with a paragraph of Korean: 4s, 7s, 11s, 16s.
          if ((d?.description_pending || d?.translation_pending) && retries < 4) {
            retries += 1;
            retry = setTimeout(() => load(true), 1000 + retries * 3500);
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

  useSeo({
    lang,
    title: car?.title ? `${car.title} \u00b7 Encar` : "Encar",
    description: car?.title ? `${car.title} \u2014 ${t("seoCarDesc")}` : t("seoHomeDesc"),
    image: photos[0]?.full,
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
  // only fall back to a bare "/" when this page was opened cold (shared link).
  const goBack = () => {
    const from = location.state?.from;
    // Hand the list back the offset it was left at, so the visitor returns to the car
    // they tapped rather than to the top of 200 results.
    const restoreScroll = location.state?.scrollY;
    if (typeof from === "string") {
      navigate({ pathname: path("/"), search: from }, { state: { restoreScroll } });
    } else if (location.key !== "default") navigate(-1);
    else navigate(path("/"));
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar onBack={goBack} />
      <DetailStickyBar
        car={car}
        price={money(q?.suggested_sale ?? 0)}
        saved={saved}
        onToggleSave={() => toggleFavourite(id, car)}
      />

      {/* Mobile clears the always-visible car bar; desktop only needs the normal gap. */}
      <div className="mx-auto max-w-[1280px] px-4 pb-5 pt-[72px] sm:px-6 lg:pt-2">
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
                <h1
                  data-testid="detail-title"
                  className="sr-only text-2xl font-semibold leading-tight text-foreground sm:text-3xl lg:not-sr-only"
                >
                  {stripGenerationYears(car.title)}
                </h1>
                <p className="mt-1 hidden text-[14px] text-muted-foreground lg:block">
                  {[car.grade, car.badge_detail].filter(Boolean).join(" \u00b7 ")}
                </p>
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
                <Button
                  data-testid="detail-save-button"
                  variant="outline"
                  onClick={() => toggleFavourite(id, car)}
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
                    alt={car.title}
                    testId="detail-main-photo"
                    index={active}
                    onIndexChange={setActive}
                    onTap={() => photos.length && openPhotos(active)}
                    countOnHover
                    hint={t("zoom")}
                    arrows
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
              <EnquiryDialog car={car} title={car.title} />
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
                </Panel>
              )}

              {/* specs */}
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
                    {car.insurance.other_accident_cost_eur ? (
                      <Row
                        label={t("otherClaimAmount")}
                        value={formatMoney(
                          car.insurance.other_accident_cost_eur,
                          currency,
                          lang,
                          rates
                        )}
                        testId="insurance-other-claim-amount"
                      />
                    ) : null}
                  </>
                ) : (
                  <p className="py-2 text-[13px] text-muted-foreground">{t("docNotAvailable")}</p>
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
                  <p className="py-2 text-[13px] text-muted-foreground">{t("docNotAvailable")}</p>
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

            {/* Read the description, liked the car — the next question is "what else?" */}
            <YouMightLike
              car={car}
              excludeId={id}
              onOpen={(c) => navigate(path(`/car/${c.id}`))}
            />

          </>
        )}
      </div>

      {/* Tapping the main photo opens every photo as one vertical column, separated by
          thin black bars - closer to how a phone gallery reads than a one-at-a-time
          lightbox. */}
      <Dialog open={lightbox} onOpenChange={setLightbox}>
        <DialogContent
          data-testid="detail-lightbox"
          // The stock close button is absolute inside this scrolling column, so it slides
          // out of reach on the second photo. Hidden here in favour of the sticky one below.
          className="max-h-[92vh] max-w-4xl overflow-y-auto border-border bg-black p-0 [&>button]:hidden"
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
              <div key={p.full || i} className="w-full bg-black">
                <ImageWithFallback
                  src={p.full}
                  alt={car?.title || ""}
                  fit="contain"
                  testId={i === 0 ? "detail-lightbox-photo" : undefined}
                />
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Desktop viewer: one photo at a time with a thumbnail strip, arrows, keyboard,
          drag and trackpad swipe. The phone keeps the vertical column above. */}
      {shot !== null && (
        <Lightbox
          images={photos.map((p) => p.full)}
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
