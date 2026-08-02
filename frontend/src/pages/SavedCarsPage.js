import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { HeartOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeaderBar } from "@/components/HeaderBar";
import { CarGrid } from "@/components/CarGrid";
import { useApp } from "@/context/AppContext";
import { getListingsByIds } from "@/lib/api";

/** Saved cars, resolved from the locally stored favourite ids. */
export default function SavedCarsPage() {
  const navigate = useNavigate();
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
    // One read from our own index. Resolving each favourite through /car/{id} used to
    // pull the detail, insurance, inspection and diagnosis documents from Encar per
    // car - seconds of waiting for data this grid never shows.
    getListingsByIds(favourites, lang)
      .then((d) => !cancelled && setItems(d.items || []))
      .catch(() => !cancelled && setItems([]))
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
            onOpen={(car) => navigate(`/car/${car.id}`)}
            pageSize={favourites.length || 4}
          />
        )}
      </main>
    </div>
  );
}
