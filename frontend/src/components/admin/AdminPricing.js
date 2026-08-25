import { useEffect, useState } from "react";
import { toast } from "sonner";
import { getPricingSettings, putPricingSettings } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/admin/AdminBits";

/**
 * Shipping surcharges tab.
 *
 * Today the only editable field is the EV surcharge. Battery packs ship as Class 9
 * dangerous goods on a different vessel schedule, so the freight-forwarder charges
 * extra for every electric car. The value flows through `pricing.compute_landed`
 * whenever `is_ev_fuel(fuel_type)` is true — see `backend/pricing.py`.
 *
 * Kept as its own tab (not folded into an "everything" pricing screen) so the
 * intent is obvious: this is the surcharge for electric cars, nothing else.
 */
export const AdminPricing = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [evExtra, setEvExtra] = useState("");
  const [reprice, setReprice] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await getPricingSettings();
        if (!alive) return;
        setEvExtra(String(d?.constants?.EV_EXTRA_SHIPPING_EUR ?? 0));
      } catch {
        if (alive) toast.error("Could not load pricing settings");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const save = async (e) => {
    e.preventDefault();
    const n = Number(evExtra);
    if (!Number.isFinite(n) || n < 0) {
      toast.error("Enter a non-negative number");
      return;
    }
    setSaving(true);
    try {
      const d = await putPricingSettings({ EV_EXTRA_SHIPPING_EUR: n }, { reprice });
      toast.success(
        reprice ? `Saved · repriced ${d?.repriced ?? 0} listings` : "Saved"
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner />;

  return (
    <form
      onSubmit={save}
      className="max-w-lg space-y-6 rounded-[14px] border border-border bg-card p-6"
      data-testid="admin-pricing-form"
    >
      <div>
        <h2 className="text-[18px] font-semibold">Shipping surcharges</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Extra costs that only apply to certain cars. Edited here, applied on every
          quote in real time.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="ev-extra" className="text-[13px] font-medium">
          Electric car surcharge (EUR)
        </Label>
        <Input
          id="ev-extra"
          data-testid="admin-pricing-ev-extra"
          type="number"
          min="0"
          step="1"
          value={evExtra}
          onChange={(e) => setEvExtra(e.target.value)}
          className="h-10 max-w-[220px]"
        />
        <p className="text-[12px] text-muted-foreground">
          Applied only when the listing's fuel type is electric or hydrogen (Class 9
          dangerous-goods handling and a dedicated vessel schedule). Leave at 0 to
          disable.
        </p>
      </div>

      <label className="flex items-start gap-2 text-[13px] text-muted-foreground">
        <input
          type="checkbox"
          data-testid="admin-pricing-reprice"
          checked={reprice}
          onChange={(e) => setReprice(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-border"
        />
        <span>
          Reprice every listing after saving. Recommended when you change the value; the
          sale prices shown on the site will not reflect the new surcharge until they
          are repriced.
        </span>
      </label>

      <Button
        type="submit"
        data-testid="admin-pricing-save"
        disabled={saving}
        className="h-10 bg-[hsl(var(--primary))] px-5 text-primary-foreground hover:brightness-110"
      >
        {saving ? "Saving…" : "Save"}
      </Button>
    </form>
  );
};

export default AdminPricing;
