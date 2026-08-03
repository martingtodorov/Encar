import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Anchor,
  Container,
  Loader2,
  MapPin,
  Navigation,
  Search,
  Ship,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HeaderBar } from "@/components/HeaderBar";
import { VesselMap } from "@/components/VesselMap";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import { useSeo } from "@/lib/seo";
import { carTitle, formatMileage, formatMoney, formatYearMonth } from "@/lib/format";
import { readJsonCookie, writeJsonCookie } from "@/lib/cookies";
import {
  getListingsByIds,
  getTrackedShipments,
  removeTrackedShipment,
  saveTrackedShipment,
  trackShipment,
} from "@/lib/api";

/**
 * Milestone copy. These are DCSA event codes the carrier returns; they are shipping terms
 * rather than app copy, so they live with the page instead of bloating the i18n files.
 */
const RECENT_COOKIE = "ab_track";

const EVENTS = {
  bg: {
    GTIN: "Приет в терминала", STUF: "Натоварен в контейнера",
    LOAD: "Натоварен на кораба", DEPA: "Отплава", ARRI: "Пристигна",
    DISC: "Разтоварен от кораба", STRP: "Разтоварен от контейнера",
    GTOT: "Излязъл от терминала", PICK: "Вдигнат", DROP: "Оставен",
    RESE: "Резервация потвърдена", CONF: "Потвърдено", ISSU: "Издаден документ",
    SURR: "Документът предаден",
    VD: "Отплава", VA: "Пристигна", AR: "Натоварен на кораба",
    UV: "Разтоварен от кораба", AG: "Приет в терминала", AL: "Натоварен контейнер приет",
    AE: "Предаден за доставка", OA: "Излязъл от терминала", RD: "Контейнерът върнат",
    EE: "Празен контейнер изпратен", AV: "Готов за доставка", CU: "Освободен от митницата",
    D: "Доставен",
  },
  ro: {
    GTIN: "Primit în terminal", STUF: "Încărcat în container",
    LOAD: "Încărcat pe navă", DEPA: "A plecat", ARRI: "A sosit",
    DISC: "Descărcat de pe navă", STRP: "Descărcat din container",
    GTOT: "A ieșit din terminal", PICK: "Ridicat", DROP: "Predat",
    RESE: "Rezervare confirmată", CONF: "Confirmat", ISSU: "Document emis",
    SURR: "Document predat",
    VD: "A plecat", VA: "A sosit", AR: "Încărcat pe navă",
    UV: "Descărcat de pe navă", AG: "Primit în terminal", AL: "Container plin primit",
    AE: "Predat pentru livrare", OA: "A ieșit din terminal", RD: "Container returnat",
    EE: "Container gol trimis", AV: "Gata de livrare", CU: "Eliberat de vamă",
    D: "Livrat",
  },
  en: {
    GTIN: "Received at terminal", STUF: "Stuffed into container",
    LOAD: "Loaded on vessel", DEPA: "Departed", ARRI: "Arrived",
    DISC: "Discharged from vessel", STRP: "Unloaded from container",
    GTOT: "Left the terminal", PICK: "Picked up", DROP: "Dropped off",
    RESE: "Booking confirmed", CONF: "Confirmed", ISSU: "Document issued",
    SURR: "Document surrendered",
    VD: "Vessel departed", VA: "Vessel arrived", AR: "Loaded on vessel",
    UV: "Unloaded from vessel", AG: "Received at terminal", AL: "Full container received",
    AE: "Released for delivery", OA: "Left the terminal", RD: "Container returned",
    EE: "Empty container dispatched", AV: "Available for delivery", CU: "Customs released",
    D: "Delivered",
  },
};

const label = (lang, code) => EVENTS[lang]?.[code] || EVENTS.en[code] || code;

const when = (iso, lang) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const opts = { day: "2-digit", month: "short", year: "numeric" };
  // A date-only value (an operator's ETA) must not pretend to be midnight.
  if (!/\d{2}:\d{2}/.test(iso)) return d.toLocaleDateString(lang === "en" ? "en-GB" : lang, opts);
  return d.toLocaleString(lang === "en" ? "en-GB" : lang, {
    ...opts, hour: "2-digit", minute: "2-digit",
  });
};

const Row = ({ m, lang, last }) => (
  <li className="relative flex gap-4 pb-6 last:pb-0" data-testid="track-milestone">
    <span className="absolute left-[7px] top-5 h-full w-px bg-border last:hidden" />
    <span
      className={`relative z-10 mt-1.5 h-[15px] w-[15px] shrink-0 rounded-full border-2 ${
        m.estimated
          ? "border-dashed border-muted-foreground bg-background"
          : last
            ? "border-primary bg-primary"
            : "border-primary bg-background"
      }`}
    />
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-semibold text-foreground">
          {label(lang, m.code) || m.text}
        </span>
        {m.estimated && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            est.
          </span>
        )}
      </div>
      <div className="tnum mt-0.5 text-[12px] text-muted-foreground">{when(m.when, lang)}</div>
      {(m.location || m.vessel_name) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          {m.location && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3 w-3" aria-hidden="true" />
              {m.location}
              {m.country ? `, ${m.country}` : ""}
            </span>
          )}
          {m.vessel_name && (
            <span className="inline-flex items-center gap-1">
              <Ship className="h-3 w-3" aria-hidden="true" />
              {m.vessel_name}
              {m.voyage ? ` · ${m.voyage}` : ""}
            </span>
          )}
        </div>
      )}
    </div>
  </li>
);

export default function TrackPage() {
  const { t, lang, currency, rates, favourites } = useApp();
  const { user } = useAuth();
  const [by, setBy] = useState("container");
  const [ref, setRef] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState([]);
  const [cars, setCars] = useState([]);
  const polls = useRef(0);
  const [params] = useSearchParams();
  // Numbers this browser has looked up before, kept in a 90-day cookie so a returning
  // buyer never has to dig the reference out of an email again.
  const [recent, setRecent] = useState(() => {
    const rows = readJsonCookie(RECENT_COOKIE, []);
    return Array.isArray(rows) ? rows.filter((r) => r?.ref).slice(0, 6) : [];
  });

  useSeo({ lang, title: `${t("trackTitle")} · Encar`, description: t("seoTrackDesc") });

  useEffect(() => {
    if (!user) {
      setSaved([]);
      return;
    }
    getTrackedShipments().then(setSaved).catch(() => setSaved([]));
  }, [user]);

  // The cars a buyer might attach: everything they saved, plus anything already linked to a
  // shipment even if it is no longer in their saved list.
  useEffect(() => {
    const ids = [...new Set([...(favourites || []), ...saved.map((s) => s.car_id).filter(Boolean)])];
    if (!ids.length) {
      setCars([]);
      return;
    }
    getListingsByIds(ids, lang)
      .then((d) => setCars(d.items || []))
      .catch(() => setCars([]));
  }, [favourites, saved, lang]);

  const lookup = useCallback(
    (value, mode, silent = false) => {
      const r = (value ?? "").trim();
      if (!r) return;
      if (!silent) {
        polls.current = 0;
        setBusy(true);
        setError("");
        setData(null);
        setRecent((prev) => {
          const item = { ref: r.toUpperCase(), by: mode };
          const next = [item, ...prev.filter((x) => x.ref !== item.ref)].slice(0, 6);
          writeJsonCookie(RECENT_COOKIE, next, 90);
          return next;
        });
      }
      trackShipment(r, mode)
        .then(setData)
        .catch((e) => {
          if (!silent) setError(e?.response?.data?.detail || e.message);
        })
        .finally(() => {
          if (!silent) setBusy(false);
        });
    },
    []
  );

  const forget = (r) =>
    setRecent((prev) => {
      const next = prev.filter((x) => x.ref !== r);
      writeJsonCookie(RECENT_COOKIE, next, 90);
      return next;
    });

  // The first lookup for a reference schedules a read of the carrier's public page in the
  // background (a real browser, ~30s), so the answer comes back marked "checking". Pick the
  // milestones up when they land, a bounded number of times.
  useEffect(() => {
    if (!data?.checking || polls.current >= 3) return;
    const id = setTimeout(() => {
      polls.current += 1;
      lookup(data.reference, data.by, true);
    }, 12000);
    return () => clearTimeout(id);
  }, [data, lookup]);

  // Deep link from the account page: /track?ref=MSKU1234567&by=container
  useEffect(() => {
    const r = params.get("ref");
    if (!r) return;
    const mode = params.get("by") === "bol" ? "bol" : "container";
    setRef(r.toUpperCase());
    setBy(mode);
    lookup(r, mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openSaved = (item) => {
    setRef(item.ref);
    setBy(item.by || "container");
    lookup(item.ref, item.by || "container");
  };

  const save = (carId) =>
    saveTrackedShipment({
      ref: data.reference,
      by: data.by,
      label: "",
      car_id: carId ?? entry?.car_id ?? "",
    })
      .then(setSaved)
      .catch(() => {});

  const drop = (r) => removeTrackedShipment(r).then(setSaved).catch(() => {});

  const entry = data ? saved.find((s) => s.ref === data.reference) : null;
  const linked = entry?.car_id ? cars.find((c) => c.id === entry.car_id) : null;
  const isSaved = Boolean(entry);
  const status = data?.found
    ? t(
        data.status === "delivered"
          ? "trackDelivered"
          : data.status === "in_transit"
            ? "trackInTransit"
            : "trackBooked"
      )
    : "";

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[820px] px-4 py-6 sm:px-6" data-testid="track-page">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
          {t("trackTitle")}
        </h1>
        <p className="mt-3 max-w-[60ch] text-base text-muted-foreground">{t("trackLead")}</p>

        <form
          className="mt-8 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            lookup(ref, by);
          }}
        >
          <div className="flex overflow-hidden rounded-[10px] border border-input">
            {["container", "bol"].map((m) => (
              <button
                key={m}
                type="button"
                data-testid={`track-by-${m}`}
                onClick={() => setBy(m)}
                className={`px-3 py-2 text-[13px] font-medium transition-colors ${
                  by === m
                    ? "bg-primary text-primary-foreground"
                    : "bg-background text-muted-foreground hover:text-foreground"
                }`}
              >
                {t(m === "container" ? "trackByContainer" : "trackByBol")}
              </button>
            ))}
          </div>
          <Input
            data-testid="track-input"
            value={ref}
            onChange={(e) => setRef(e.target.value.toUpperCase())}
            placeholder={t(by === "container" ? "trackRefHint" : "trackBolHint")}
            className="h-11 flex-1 bg-background"
          />
          <Button data-testid="track-submit" type="submit" disabled={busy || !ref.trim()} className="h-11 gap-2">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {t("trackSearch")}
          </Button>
        </form>

        {/* Numbers this browser looked up before. Kept only in a cookie on the visitor's own
            machine, so it works signed out too — which is how most buyers arrive. */}
        {recent.length > 0 && (
          <div className="mt-4" data-testid="track-recent">
            <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
              {t("trackRecent")}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {recent.map((r) => (
                <span
                  key={r.ref}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-card py-1 pl-3 pr-1 text-[12px]"
                >
                  <button
                    type="button"
                    className="tnum font-medium text-foreground"
                    onClick={() => openSaved(r)}
                    data-testid={`track-recent-${r.ref}`}
                  >
                    {r.ref}
                  </button>
                  <button
                    type="button"
                    aria-label={t("trackRemove")}
                    onClick={() => forget(r.ref)}
                    data-testid={`track-recent-forget-${r.ref}`}
                    className="rounded-full p-1 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        {saved.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2" data-testid="track-saved-list">
            {saved.map((s) => (
              <span
                key={s.ref}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-card py-1 pl-3 pr-1 text-[12px]"
              >
                <button
                  type="button"
                  className="tnum font-medium text-foreground"
                  onClick={() => openSaved(s)}
                  data-testid={`track-saved-${s.ref}`}
                >
                  {s.ref}
                </button>
                <button
                  type="button"
                  aria-label={t("trackRemove")}
                  onClick={() => drop(s.ref)}
                  className="rounded-full p-1 text-muted-foreground hover:text-destructive"
                  data-testid={`track-remove-${s.ref}`}
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
        )}

        {error && (
          <p data-testid="track-error" className="mt-6 text-sm text-destructive">
            {error}
          </p>
        )}

        {data && data.configured === false && (
          <div
            data-testid="track-not-connected"
            className="mt-6 rounded-[14px] border border-dashed border-border bg-card p-5"
          >
            <h2 className="text-base font-semibold text-foreground">{t("trackNotReady")}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{t("trackNotReadyBody")}</p>
          </div>
        )}

        {data?.configured && !data.found && (
          <p data-testid="track-not-found" className="mt-6 text-sm text-muted-foreground">
            {data.checking ? t("trackChecking") : t("trackNotFound")}
          </p>
        )}

        {data?.found && (
          <div className="mt-8 space-y-4">
            <div className="rounded-[14px] border border-border bg-card p-5" data-testid="track-summary">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="inline-flex items-center gap-2 text-[12px] uppercase tracking-wide text-muted-foreground">
                    <Container className="h-3.5 w-3.5" aria-hidden="true" />
                    {t(data.by === "container" ? "trackByContainer" : "trackByBol")}
                  </div>
                  <div className="tnum mt-1 text-2xl font-semibold text-foreground">
                    {data.reference}
                  </div>
                  {data.container && data.container !== data.reference && (
                    <div
                      data-testid="track-container-no"
                      className="tnum mt-0.5 text-[12.5px] text-muted-foreground"
                    >
                      {t("trackByContainer")} {data.container}
                      {data.route?.type ? ` · ${data.route.type}` : ""}
                    </div>
                  )}
                  <div className="mt-1 text-sm font-medium text-primary">{status}</div>
                  {data.checking && (
                    <div
                      data-testid="track-checking"
                      className="mt-1 inline-flex items-center gap-1.5 text-[12px] text-muted-foreground"
                    >
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                      {t("trackChecking")}
                    </div>
                  )}
                </div>
                {user && (
                  <Button
                    variant={isSaved ? "outline" : "default"}
                    onClick={() => (isSaved ? drop(data.reference) : save(""))}
                    data-testid="track-save-button"
                    className="gap-2"
                  >
                    <Anchor className="h-4 w-4" aria-hidden="true" />
                    {t(isSaved ? "trackSaved" : "trackSave")}
                  </Button>
                )}
              </div>

              <div className="mt-4 grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
                {data.route?.from && data.route?.to && (
                  <div data-testid="track-route" className="sm:col-span-2">
                    <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
                      {t("trackRoute")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">
                      {data.route.from} → {data.route.to}
                    </div>
                    {(data.route.from_terminal || data.route.to_terminal) && (
                      <div className="mt-0.5 text-[12px] text-muted-foreground">
                        {[data.route.from_terminal, data.route.to_terminal]
                          .filter(Boolean)
                          .join(" → ")}
                      </div>
                    )}
                  </div>
                )}
                {data.eta && (
                  <div data-testid="track-eta">
                    <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
                      {t("trackEta")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">
                      {when(data.eta.when, lang)}
                    </div>
                    <div className="text-[12px] text-muted-foreground">
                      {label(lang, data.eta.code) || data.eta.text}
                      {data.eta.location ? ` · ${data.eta.location}` : ""}
                    </div>
                  </div>
                )}
                {data.last && (
                  <div data-testid="track-last">
                    <div className="text-[12px] uppercase tracking-wide text-muted-foreground">
                      {t("trackLastSeen")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">
                      {label(lang, data.last.code) || data.last.text}
                    </div>
                    <div className="text-[12px] text-muted-foreground">
                      {when(data.last.when, lang)}
                      {data.last.location ? ` · ${data.last.location}` : ""}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {user && isSaved && (
              <div className="rounded-[14px] border border-border bg-card p-5" data-testid="track-car">
                <h2 className="text-base font-semibold text-foreground">{t("trackYourCar")}</h2>
                {linked ? (
                  <div className="mt-3 flex gap-4">
                    <img
                      src={linked.image}
                      alt={carTitle(linked)}
                      className="h-[86px] w-[130px] shrink-0 rounded-[10px] object-cover"
                    />
                    <div className="min-w-0">
                      <div className="line-clamp-1 text-sm font-semibold text-foreground">
                        {carTitle(linked)}
                      </div>
                      <div className="tnum mt-0.5 text-[12px] text-muted-foreground">
                        {formatYearMonth(linked.year_month, lang)} ·{" "}
                        {formatMileage(linked.mileage, lang)}
                      </div>
                      <div className="tnum mt-1 text-sm font-semibold text-foreground">
                        {formatMoney(linked.sale_eur, currency, lang, rates)}
                      </div>
                      <div className="mt-1 flex gap-3">
                        <Link
                          to={`/${lang}/car/${linked.id}`}
                          className="text-[12px] font-medium text-primary hover:underline"
                          data-testid="track-car-link"
                        >
                          {t("viewDetails")}
                        </Link>
                        <button
                          type="button"
                          onClick={() => save("")}
                          className="text-[12px] text-muted-foreground hover:text-destructive"
                          data-testid="track-car-unlink"
                        >
                          {t("trackUnlinkCar")}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : cars.length ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <select
                      data-testid="track-car-select"
                      defaultValue=""
                      onChange={(e) => e.target.value && save(e.target.value)}
                      className="h-10 rounded-[10px] border border-input bg-background px-3 text-sm"
                    >
                      <option value="">{t("trackPickCar")}</option>
                      {cars.map((c) => (
                        <option key={c.id} value={c.id}>
                          {carTitle(c)}
                        </option>
                      ))}
                    </select>
                    <span className="text-[12px] text-muted-foreground">{t("trackLinkHint")}</span>
                  </div>
                ) : (
                  <p className="mt-2 text-[12px] text-muted-foreground">{t("trackNoCars")}</p>
                )}
              </div>
            )}

            {data.milestones.some((m) => m.lat) && (
              <VesselMap
                milestones={data.milestones}
                position={data.vessel?.position}
                vesselName={data.vessel?.name}
                labelFor={(code) => label(lang, code)}
              />
            )}

            {data.vessel && (
              <div className="rounded-[14px] border border-border bg-card p-5" data-testid="track-vessel">
                <div className="flex items-center gap-2">
                  <Ship className="h-4 w-4 text-primary" aria-hidden="true" />
                  <span className="text-base font-semibold text-foreground">
                    {data.vessel.name || t("trackVessel")}
                  </span>
                  {data.vessel.voyage && (
                    <span className="tnum text-[12px] text-muted-foreground">
                      {t("trackVoyage")} {data.vessel.voyage}
                    </span>
                  )}
                </div>
                {data.vessel.position ? (
                  <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3" data-testid="track-position">
                    <div>
                      <div className="text-[12px] text-muted-foreground">{t("trackPosition")}</div>
                      <div className="tnum font-medium text-foreground">
                        {data.vessel.position.lat?.toFixed(3)}, {data.vessel.position.lon?.toFixed(3)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[12px] text-muted-foreground">{t("trackSpeed")}</div>
                      <div className="tnum font-medium text-foreground">
                        {data.vessel.position.speed ?? "—"} kn
                      </div>
                    </div>
                    <div>
                      <div className="text-[12px] text-muted-foreground">{t("trackHeading")}</div>
                      <div className="tnum inline-flex items-center gap-1 font-medium text-foreground">
                        <Navigation className="h-3 w-3" aria-hidden="true" />
                        {data.vessel.position.course ?? "—"}°
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="mt-2 text-[12px] text-muted-foreground">{t("trackNoAis")}</p>
                )}
                {data.vessel.imo && (
                  <a
                    href={`https://www.marinetraffic.com/en/ais/details/ships/imo:${data.vessel.imo}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    data-testid="track-vessel-link"
                    className="mt-3 inline-block text-[12px] font-medium text-primary hover:underline"
                  >
                    IMO {data.vessel.imo} · MarineTraffic
                  </a>
                )}
              </div>
            )}

            {data.note && (
              <div
                data-testid="track-note"
                className="rounded-[14px] border border-border bg-card p-5 text-sm leading-relaxed text-muted-foreground"
              >
                {data.note}
              </div>
            )}

            {data.milestones.length > 0 && (
              <div className="rounded-[14px] border border-border bg-card p-5">
                <h2 className="text-base font-semibold text-foreground">{t("trackJourney")}</h2>
                <ol className="mt-4">
                  {data.milestones.map((m, i) => (
                    <Row
                      key={`${m.code}-${m.when}-${i}`}
                      m={m}
                      lang={lang}
                      last={i === data.milestones.length - 1}
                    />
                  ))}
                </ol>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
