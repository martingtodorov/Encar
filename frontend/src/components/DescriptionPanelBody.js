import { useState } from "react";
import { Languages, Loader2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { translateDescription } from "@/lib/api";

/** Dealer descriptions stay in the seller's own words until the visitor asks for a
 *  translation. One LLM call, cached forever, never on page load. */
export const DescriptionPanelBody = ({ carId, original }) => {
  const { t, lang } = useApp();
  const [translated, setTranslated] = useState(null);
  const [showing, setShowing] = useState("original");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (translated) {
      setShowing("translated");
      return;
    }
    setBusy(true);
    try {
      const { text } = await translateDescription(carId, lang);
      setTranslated(text);
      setShowing("translated");
    } catch (e) {
      toast.error(e?.response?.data?.detail || t("translateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const body = showing === "translated" && translated ? translated : original;

  return (
    <>
      <div className="mb-3 flex flex-wrap gap-2">
        {showing === "translated" ? (
          <Button
            data-testid="description-show-original"
            variant="outline"
            onClick={() => setShowing("original")}
            className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px] font-medium hover:bg-muted"
          >
            <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
            {t("showOriginal")}
          </Button>
        ) : (
          <Button
            data-testid="description-translate"
            variant="outline"
            onClick={run}
            disabled={busy}
            className="h-9 gap-2 rounded-[10px] border-border bg-card px-3 text-[13px] font-medium hover:bg-muted"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Languages className="h-3.5 w-3.5 text-[hsl(var(--primary))]" aria-hidden="true" />
            )}
            {busy ? t("translating") : t("translateThis")}
          </Button>
        )}
      </div>

      <p
        data-testid="description-text"
        className="whitespace-pre-line text-[13px] leading-relaxed text-foreground"
      >
        {body}
      </p>
    </>
  );
};

export default DescriptionPanelBody;
