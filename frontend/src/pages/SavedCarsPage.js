import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HeartOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { CarGrid } from "@/components/CarGrid";
import { useApp } from "@/context/AppContext";
import { getCar } from "@/lib/api";

/** Saved cars, resolved from the locally stored favourite ids. */
export default function SavedCarsPage() {
  const { t, lang, favourites } = useApp();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!favourites.length) {
      setItems([]);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    Promise.all(favourites.map((id) => getCar(id, lang).catch(() => null)))
      .then((cars) => {
        if (cancelled) return;
        setItems(
          cars.filter(Boolean).map((c) => ({
            id: c.id,
            manufacturer_t: c.manufacturer,
            model_t: c.model,
            badge_t: c.grade,
            badge_detail_t: c.badge_detail,
            fuel_type_t: c.spec?.fuel,
            mileage: c.spec?.mileage,
            year_month: Number(c.year_month),
            form_year: c.form_year,
            sale_eur: c.quote?.suggested_sale,
            image: c.photos?.[0]?.full,
            photo_count: c.photo_count,
            under_contract: c.under_contract,
            has_inspection: !!c.inspection,
            has_record: !!c.insurance,
            diagnosed: !!c.diagnosis,
          }))
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [favourites, lang]);

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />
      <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
        <h1 className="mb-5 text-2xl font-semibold text-foreground">{t("savedCars")}</h1>

        {!loading && !items.length ? (
          <div
            data-testid="saved-empty-state"
            className="rounded-[16px] border border-border bg-card p-10 text-center"
          >
            <HeartOff className="mx-auto h-9 w-9 text-muted-foreground" aria-hidden="true" />
            <h2 className="mt-3 text-[16px] font-semibold text-foreground">{t("noSavedTitle")}</h2>
            <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground">
              {t("noSavedBody")}
            </p>
            <Link to="/">
              <Button className="mt-4 h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-primary-foreground hover:brightness-110">
                {t("navSearch")}
              </Button>
            </Link>
          </div>
        ) : (
          <CarGrid
            items={items}
            loading={loading}
            onOpen={(car) => {
              window.location.href = `/car/${car.id}`;
            }}
            pageSize={favourites.length || 4}
          />
        )}
      </main>
    </div>
  );
}
