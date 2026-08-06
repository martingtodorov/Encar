import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import http from "@/lib/api";

/**
 * Access and portability (GDPR Art. 15 and 20) in one button.
 *
 * The file is built server-side and downloaded straight to the buyer's machine — we never mail
 * a copy of somebody's data to an address that could be wrong.
 */
export const DataExportPanel = () => {
  const { t } = useApp();
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      const { data } = await http.get("/account/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `my-data-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(t("exportDone"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "could not build the file");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="account-export"
      className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
        <Download className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
        {t("exportTitle")}
      </h2>
      <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted-foreground">
        {t("exportBlurb")}
      </p>
      <Button
        data-testid="account-export-button"
        onClick={download}
        disabled={busy}
        className="mt-4 h-10 rounded-[10px] px-4 text-[13px] font-semibold"
      >
        {busy ? t("exportBusy") : t("exportButton")}
      </Button>
    </section>
  );
};

export default DataExportPanel;
