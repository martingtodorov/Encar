import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Ship } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { carTitle } from "@/lib/format";
import { getListingsByIds, getTrackedShipments, trackShipment } from "@/lib/api";

const when = (iso, lang) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(lang === "en" ? "en-GB" : lang, {
    day: "2-digit", month: "short", year: "numeric",
  });
};

/** The shipments an operator attached to this account, with the state of each. */
export const AccountShipments = () => {
  const { t, lang } = useApp();
  const [rows, setRows] = useState(null);
  const [cars, setCars] = useState({});

  useEffect(() => {
    let alive = true;
    getTrackedShipments()
      .then(async (items) => {
        if (!alive) return;
        const states = await Promise.all(
          items.slice(0, 8).map((s) =>
            trackShipment(s.ref, s.by || "container").catch(() => null))
        );
        if (!alive) return;
        setRows(items.slice(0, 8).map((s, i) => ({ ...s, state: states[i] })));
        const ids = [...new Set(items.map((s) => s.car_id).filter(Boolean))];
        if (!ids.length) return;
        const d = await getListingsByIds(ids, lang).catch(() => ({ items: [] }));
        if (alive) setCars(Object.fromEntries((d.items || []).map((c) => [c.id, c])));
      })
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [lang]);

  if (!rows) return null;

  return (
    <section
      data-testid="account-shipments"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
          <Ship className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          {t("accountShipments")}
        </h2>
        <Link
          to={`/${lang}/track`}
          data-testid="account-shipments-track-link"
          className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline"
        >
          {t("trackTitle")}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>

      {rows.length === 0 ? (
        <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">
          {t("accountNoShipments")}
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2" data-testid="account-shipment-list">
          {rows.map((s) => {
            const st = s.state;
            const car = s.car_id ? cars[s.car_id] : null;
            const status = st?.found
              ? t(st.status === "delivered" ? "trackDelivered"
                  : st.status === "in_transit" ? "trackInTransit" : "trackBooked")
              : st?.checking ? t("trackChecking") : t("trackNotFound");
            return (
              <li
                key={s.ref}
                data-testid={`account-shipment-${s.ref}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] border border-border px-3 py-2.5"
              >
                <div className="min-w-0">
                  <div className="tnum text-[13.5px] font-semibold text-foreground">
                    {s.ref}
                    <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {t(s.by === "bol" ? "trackByBol" : "trackByContainer")}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-muted-foreground">
                    {status}
                    {st?.eta?.when ? ` · ${t("trackEta")} ${when(st.eta.when, lang)}` : ""}
                    {st?.vessel?.name ? ` · ${st.vessel.name}` : ""}
                  </div>
                  {car && (
                    <Link
                      to={`/${lang}/car/${car.id}`}
                      data-testid={`account-shipment-car-${s.ref}`}
                      className="mt-0.5 line-clamp-1 text-[12px] font-medium text-primary hover:underline"
                    >
                      {carTitle(car)}
                    </Link>
                  )}
                </div>
                <Link
                  to={`/${lang}/track/${encodeURIComponent(s.ref)}`}
                  data-testid={`account-shipment-open-${s.ref}`}
                  className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-border px-3 text-[12.5px] font-medium text-foreground hover:bg-muted"
                >
                  {t("trackSearch")}
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

export default AccountShipments;
