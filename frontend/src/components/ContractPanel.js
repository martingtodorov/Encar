import { useCallback, useEffect, useState } from "react";
import { Download, FileSignature, Loader2, Printer, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { downloadContractDocx, getContract, saveContract } from "@/lib/api";
import { toast } from "sonner";

/**
 * The consultancy contract, on the page the buyer lands on once the deposit has cleared.
 *
 * Everything the ad and the account already know is filled in by the backend; these seven
 * fields are the ones only the buyer can answer. They are saved on the ACCOUNT, so a second
 * purchase arrives already complete.
 *
 * Printing uses a print stylesheet rather than a second window: a popup blocker eats the
 * window, and a blocked print button looks like a broken one.
 */
const FIELDS = [
  ["buyer_name", "text"],
  ["buyer_egn", "text"],
  ["buyer_id_no", "text"],
  ["buyer_id_date", "text"],
  ["buyer_id_issuer", "text"],
  ["buyer_address", "text"],
  ["buyer_phone", "tel"],
];

export const ContractPanel = ({ sessionId }) => {
  const { t, lang } = useApp();
  const [doc, setDoc] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getContract(sessionId, lang)
      .then((d) => {
        if (!alive) return;
        setDoc(d);
        setForm(d.buyer || {});
      })
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [sessionId, lang]);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const d = await saveContract(sessionId, lang, form);
      setDoc(d);
      toast.success(t("contractSaved"));
    } catch {
      toast.error(t("contractSaveFailed"));
    } finally {
      setSaving(false);
    }
  }, [sessionId, lang, form, t]);

  if (error) return null;
  if (!doc) {
    return (
      <div className="mt-10 flex justify-center" data-testid="contract-loading">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  const incomplete = (doc.missing || []).length > 0;

  return (
    <section data-testid="contract-panel" className="mt-10 text-left">
      <div className="rounded-[14px] border border-border bg-card p-4 sm:p-6">
        <div className="flex items-start gap-3">
          <FileSignature
            className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--primary))]"
            aria-hidden="true"
          />
          <div>
            <h2 className="text-base font-semibold text-foreground md:text-lg">
              {t("contractTitle")}
            </h2>
            <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
              {t("contractIntro")}
            </p>
          </div>
        </div>

        {/* the seven things only the buyer knows */}
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {FIELDS.map(([key, type]) => (
            <label key={key} className="block">
              <span className="mb-1 block text-[12.5px] font-medium text-muted-foreground">
                {t(key)}
              </span>
              <Input
                data-testid={`contract-${key.replaceAll("_", "-")}`}
                type={type}
                value={form[key] || ""}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                placeholder={t(`${key}_hint`)}
                className="h-10 border-border bg-background text-sm"
              />
            </label>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            data-testid="contract-save"
            onClick={save}
            disabled={saving}
            className="h-10 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {saving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            ) : null}
            {t("contractSave")}
          </Button>
          <Button
            data-testid="contract-print"
            variant="outline"
            onClick={() => window.print()}
            className="h-10 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
          >
            <Printer className="h-4 w-4" aria-hidden="true" />
            {t("contractPrint")}
          </Button>
          <Button
            data-testid="contract-download"
            variant="outline"
            onClick={() => downloadContractDocx(sessionId, lang)}
            className="h-10 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            {t("contractDownload")}
          </Button>
          {incomplete && (
            <span
              data-testid="contract-incomplete"
              className="text-[12.5px] text-muted-foreground"
            >
              {t("contractIncomplete").replace("{n}", doc.missing.length)}
            </span>
          )}
        </div>

        {/* the document itself */}
        <div
          id="contract-print"
          data-testid="contract-text"
          className="mt-5 max-h-[420px] overflow-y-auto whitespace-pre-line rounded-[10px] border border-border bg-background p-4 font-serif text-[13px] leading-relaxed text-foreground sm:p-6"
        >
          {doc.text}
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-[10px] bg-secondary/60 p-3">
          <ShieldCheck
            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="text-[12.5px] leading-relaxed text-muted-foreground">
            {t("contractKepNote")}
          </p>
        </div>
      </div>
    </section>
  );
};

export default ContractPanel;
