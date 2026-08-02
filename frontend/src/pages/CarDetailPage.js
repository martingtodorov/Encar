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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { HeaderBar } from "@/components/HeaderBar";
import { DetailStickyBar } from "@/components/DetailStickyBar";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { PhotoSwiper } from "@/components/PhotoSwiper";
import { useApp } from "@/context/AppContext";
import { EnquiryDialog } from "@/components/EnquiryDialog";
import { DescriptionPanelBody } from "@/components/DescriptionPanelBody";
import { getCar } from "@/lib/api";
import { formatMileage, formatMoney, formatNumber, formatYearMonth } from "@/lib/format";

const Panel = ({ title, icon: Icon, children, testId, tone = "info" }) => (
  <section
    data-testid={testId}
    className="overflow-hidden rounded-[16px] border border-border bg-card shadow-sm"
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
  const { t, lang, currency, rates, isFavourite, toggleFavourite } = useApp();

  const [car, setCar] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [active, setActive] = useState(0);
  const [lightbox, setLightbox] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let retry = null;
    setLoading(true);
    setError(null);

    const load = (isRetry) =>
      getCar(id, lang)
        .then((d) => {
          if (cancelled) return;
          setCar(d);
          // A long dealer description is translated in the background so the page can
          // render instantly; pick it up once it lands.
          if (d?.description_pending && !isRetry) {
            retry = setTimeout(() => load(true), 3500);
          }
        })
        .catch((e) => !cancelled && setError(e?.response?.data?.detail || e.message))
        .finally(() => !cancelled && setLoading(false));

    load(false);
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
    };
  }, [id, lang]);

  const money = (v) => formatMoney(v, currency, lang, rates);
  const saved = isFavourite(id);
  const photos = car?.photos || [];
  const q = car?.quote;

  // "Back to results" must land on the SAME result set the visitor came from. The
  // search page hands us its query string; otherwise step back through history, and
  // only fall back to a bare "/" when this page was opened cold (shared link).
  const goBack = () => {
    const from = location.state?.from;
    if (typeof from === "string") navigate({ pathname: "/", search: from });
    else if (location.key !== "default") navigate(-1);
    else navigate("/");
  };

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <DetailStickyBar
        car={car}
        price={money(q?.suggested_sale ?? 0)}
        saved={saved}
        onToggleSave={() => toggleFavourite(id)}
      />

      <div className="mx-auto max-w-[1280px] px-4 pb-5 pt-2 sm:px-6">
        <Button
          data-testid="back-to-results"
          variant="ghost"
          onClick={goBack}
          className="mb-1 h-9 gap-1.5 px-2 text-sm text-muted-foreground hover:bg-muted"
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

            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h1
                  data-testid="detail-title"
                  className="text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
                >
                  {car.title}
                </h1>
                <p className="mt-1 text-[14px] text-muted-foreground">
                  {[car.grade, car.badge_detail].filter(Boolean).join(" \u00b7 ")}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <div className="text-right">
                  <div
                    data-testid="detail-price"
                    className="tnum text-3xl font-semibold tracking-tight text-foreground"
                  >
                    {money(q?.suggested_sale ?? 0)}
                  </div>
                  <div className="text-[12px] text-muted-foreground">{t("finalPrice")}</div>
                </div>
                <Button
                  data-testid="detail-save-button"
                  variant="outline"
                  onClick={() => toggleFavourite(id)}
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
                <div className="aspect-[16/9] w-full cursor-zoom-in overflow-hidden rounded-[16px] border border-border lg:w-[calc(100%-226px)]">
                  <PhotoSwiper
                    images={photos.map((p) => p.full)}
                    alt={car.title}
                    testId="detail-main-photo"
                    index={active}
                    onIndexChange={setActive}
                    onTap={() => photos.length && setLightbox(true)}
                    showCount={false}
                    arrows
                  />
                </div>

                {photos.length > 1 && (
                  <div
                    data-testid="detail-thumb-strip"
                    className="thin-scroll flex gap-2 overflow-x-auto pb-2 lg:absolute lg:inset-y-0 lg:right-0 lg:w-[218px] lg:flex-col lg:overflow-x-hidden lg:overflow-y-auto lg:pb-0 lg:pr-1"
                  >
                    {photos.map((p, i) => (
                      <button
                        key={i}
                        type="button"
                        data-testid="detail-photo-thumb"
                        onClick={() => setActive(i)}
                        aria-label={`${t("allPhotos")} ${i + 1}`}
                        aria-current={i === active ? "true" : undefined}
                        className={`h-16 w-24 shrink-0 overflow-hidden rounded-[8px] border-2 transition-colors lg:aspect-video lg:h-auto lg:w-full ${
                          i === active ? "border-[hsl(var(--primary))]" : "border-border"
                        }`}
                      >
                        <ImageWithFallback src={p.thumb} alt="" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {photos.length > 1 && (
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-[12px] font-medium text-muted-foreground">
                    {t("allPhotos")}
                  </span>
                  <span
                    data-testid="detail-photo-count"
                    className="tnum text-[12px] text-muted-foreground"
                  >
                    {formatNumber(active + 1, lang)} / {formatNumber(photos.length, lang)}
                  </span>
                </div>
              )}
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-2">
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

              {/* enquiry: the primary call to action */}
              <div className="mb-5">
                <EnquiryDialog car={car} title={car.title} />
              </div>

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
                  tone="info"
                >
                  {(car.options.groups || []).map((g) => (
                    <div key={g.category} className="mb-3 last:mb-0">
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
                  {(car.options.factory || []).length > 0 && (
                    <div className="mt-3">
                      <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("factoryOptions")}
                      </h3>
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
                  tone="info"
                >
                  <DescriptionPanelBody carId={id} original={car.description} />
                </Panel>
              </div>
            )}

          </>
        )}
      </div>

      {/* Tapping the main photo opens every photo as one vertical column, separated by
          thin black bars - closer to how a phone gallery reads than a one-at-a-time
          lightbox. */}
      <Dialog open={lightbox} onOpenChange={setLightbox}>
        <DialogContent
          data-testid="detail-lightbox"
          className="max-h-[92vh] max-w-4xl overflow-y-auto border-border bg-black p-0"
        >
          <DialogTitle className="sr-only">{car?.title || t("allPhotos")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("allPhotos")} — {photos.length}
          </DialogDescription>
          <div className="flex flex-col gap-1.5 bg-black py-1.5">
            {photos.map((p, i) => (
              <div key={i} className="w-full bg-black">
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
    </div>
  );
}
