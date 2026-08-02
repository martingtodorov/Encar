import { useState } from "react";
import { Languages, Loader2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { streamDescription, translateDescription } from "@/lib/api";

/** Dealer descriptions stay in the seller's own words until the visitor asks for a
 *  translation. Streamed as it is generated, then cached forever, never on page load. */
export const DescriptionPanelBody = ({ carId, original }) => {
  const { t, lang } = useApp();
  const [translated, setTranslated] = useState(null);
  const [partial, setPartial] = useState("");
  const [showing, setShowing] = useState("original");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (translated) {
      setShowing("translated");
      return;
    }
    setBusy(true);
    setPartial("");
    setShowing("translated");
    try {
      const text = await streamDescription(carId, lang, setPartial);
      setTranslated(text);
    } catch (e) {
      // streaming can be cut off by a proxy or an unsupported browser; the plain
      // request still works, it just makes the visitor wait for the whole thing
      try {
        const { text } = await translateDescription(carId, lang);
        setTranslated(text);
      } catch (e2) {
        setShowing("original");
        toast.error(e2?.response?.data?.detail || t("translateFailed"));
      }
    } finally {
      setBusy(false);
      setPartial("");
    }
  };

  const body =
    showing === "translated" ? translated || partial || original : original;

  return (
    <>
      <div className="mb-3 flex flex-wrap gap-2">
        {showing === "translated" && !busy ? (
          <Button
            data-testid="description-show-original"
            variant="outline"
            onClick={() => setShowing("original")}
            className="h-9 gap-2 rounded-[10px] border border-input bg-card px-3 text-[13px] font-medium shadow-sm hover:bg-muted"
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
            className="h-9 gap-2 rounded-[10px] border border-input bg-card px-3 text-[13px] font-medium shadow-sm hover:bg-muted"
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
        {busy && partial ? (
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-[hsl(var(--primary))] align-text-bottom" />
        ) : null}
      </p>
    </>
  );
};

export default DescriptionPanelBody;
