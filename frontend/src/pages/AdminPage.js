import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Activity, Inbox, PieChart, RefreshCcw, Ship, Users } from "lucide-react";
import { HeaderBar } from "@/components/HeaderBar";
import { useAuth } from "@/context/AuthContext";
import { useLangNav } from "@/hooks/useLangNav";
import { useApp } from "@/context/AppContext";
import { useSeo } from "@/lib/seo";
import { Spinner } from "@/components/admin/AdminBits";
import { AdminOverview } from "@/components/admin/AdminOverview";
import { AdminCoverage } from "@/components/admin/AdminCoverage";
import { AdminEnquiries } from "@/components/admin/AdminEnquiries";
import { AdminCatalogueSync } from "@/components/admin/AdminCatalogueSync";
import { AdminShipments } from "@/components/admin/AdminShipments";
import { AdminBuyers } from "@/components/admin/AdminBuyers";

const TABS = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "coverage", label: "Brand coverage", icon: PieChart },
  { id: "enquiries", label: "Enquiries", icon: Inbox },
  { id: "sync", label: "Catalogue sync", icon: RefreshCcw },
  { id: "shipments", label: "Shipments", icon: Ship },
  { id: "buyers", label: "Buyers", icon: Users },
];

export default function AdminPage() {
  const { user, loading } = useAuth();
  const { lang } = useApp();
  const { go } = useLangNav();

  useSeo({ lang, title: "Operations \u00b7 Encar", noindex: true });
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") || "overview");

  // Anything but a signed-in admin has no business here. The API enforces this too;
  // this is only so the page does not flash before the 401s land.
  useEffect(() => {
    if (loading) return;
    if (!user) go("/login", { replace: true });
    else if (!user.is_admin) go("/", { replace: true });
  }, [loading, user, go]);

  const pick = (id) => {
    setTab(id);
    setParams({ tab: id }, { replace: true });
  };

  if (loading || !user?.is_admin) {
    return (
      <div className="min-h-screen bg-background">
        <HeaderBar />
        <Spinner />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <HeaderBar />

      <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6">
        <h1
          data-testid="admin-title"
          className="text-[26px] font-semibold tracking-tight text-foreground"
        >
          Operations
        </h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Signed in as {user.email}
        </p>

        {/* Seven tabs cannot fit a phone: the row bleeds to the screen edges and scrolls
            sideways instead of running off the viewport. */}
        <div className="-mx-4 mt-6 overflow-x-auto px-4 sm:mx-0 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <div className="inline-flex w-max rounded-[12px] border border-border bg-muted p-0.5">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                data-testid={`admin-tab-${id}`}
                onClick={() => pick(id)}
                className={`inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-[10px] px-3.5 py-2 text-[13px] font-medium transition-colors ${
                  tab === id
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6">
          {tab === "overview" && <AdminOverview />}
          {tab === "coverage" && <AdminCoverage />}
          {tab === "enquiries" && <AdminEnquiries />}
          {tab === "sync" && <AdminCatalogueSync />}
          {tab === "shipments" && <AdminShipments />}
          {tab === "buyers" && <AdminBuyers />}
        </div>
      </main>
    </div>
  );
}
