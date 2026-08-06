import { useCallback, useEffect, useState } from "react";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { getContractTemplate, resetContractTemplate, saveContractTemplate } from "@/lib/api";
import { toast } from "sonner";

/**
 * The contract template, one per language, editable without a deploy.
 *
 * Placeholders in double braces are replaced with what the ad and the account know. An unknown
 * placeholder is left as the dotted blank of the paper form, so a typo shows up as a gap to
 * fill rather than as silently missing text.
 */
const SELLER_FIELDS = ["name", "eik", "address", "email", "manager", "city"];
const LANG_LABEL = { bg: "Български", ro: "Română", en: "English" };

export const AdminContract = () => {
  const [data, setData] = useState(null);
  const [lang, setLang] = useState("bg");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getContractTemplate()
      .then(setData)
      .catch(() => toast.error("Could not load the template"));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await saveContractTemplate({ seller: data.seller, bodies: data.bodies });
      toast.success("Template saved");
    } catch {
      toast.error("Could not save");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const d = await resetContractTemplate(lang);
      setData({ ...data, bodies: { ...data.bodies, [lang]: d.body } });
      toast.success(`${LANG_LABEL[lang]} reset to the shipped wording`);
    } catch {
      toast.error("Could not reset");
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div className="flex justify-center py-16" data-testid="admin-contract-loading">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div data-testid="admin-contract" className="space-y-6">
      {/* who the seller is — printed into every contract */}
      <section className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <h3 className="text-base font-semibold text-foreground">Seller details</h3>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          Printed into every contract as the ИЗПЪЛНИТЕЛ / PRESTATOR / AGENT.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SELLER_FIELDS.map((k) => (
            <label key={k} className="block">
              <span className="mb-1 block text-[12px] font-medium uppercase tracking-wide text-muted-foreground">
                {k}
              </span>
              <Input
                data-testid={`admin-contract-seller-${k}`}
                value={data.seller?.[k] || ""}
                onChange={(e) =>
                  setData({ ...data, seller: { ...data.seller, [k]: e.target.value } })
                }
                className="h-10 border-border bg-background text-sm"
              />
            </label>
          ))}
        </div>
      </section>

      {/* the wording */}
      <section className="rounded-[14px] border border-border bg-card p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-base font-semibold text-foreground">Contract wording</h3>
          <div className="flex items-center gap-1.5">
            {(data.langs || ["bg", "ro", "en"]).map((l) => (
              <Button
                key={l}
                data-testid={`admin-contract-lang-${l}`}
                variant={l === lang ? "default" : "outline"}
                onClick={() => setLang(l)}
                className={`h-9 rounded-[10px] px-3 text-[13px] ${
                  l === lang
                    ? "bg-[hsl(var(--primary))] text-primary-foreground hover:brightness-110"
                    : "border-border bg-card"
                }`}
              >
                {LANG_LABEL[l] || l}
              </Button>
            ))}
          </div>
        </div>

        <Textarea
          data-testid="admin-contract-body"
          value={data.bodies?.[lang] || ""}
          onChange={(e) =>
            setData({ ...data, bodies: { ...data.bodies, [lang]: e.target.value } })
          }
          spellCheck={false}
          className="mt-4 min-h-[420px] border-border bg-background font-mono text-[12.5px] leading-relaxed"
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            data-testid="admin-contract-save"
            onClick={save}
            disabled={busy}
            className="h-10 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-5 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
          >
            <Save className="h-4 w-4" aria-hidden="true" />
            Save
          </Button>
          <Button
            data-testid="admin-contract-reset"
            variant="outline"
            onClick={reset}
            disabled={busy}
            className="h-10 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Reset {LANG_LABEL[lang]}
          </Button>
        </div>

        <div className="mt-5 rounded-[10px] bg-secondary/60 p-3">
          <p className="text-[12px] font-medium text-foreground">
            Placeholders — type them in double braces
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(data.placeholders || []).map((p) => (
              <code
                key={p}
                className="rounded bg-background px-1.5 py-0.5 font-mono text-[11.5px] text-muted-foreground"
              >
                {`{{${p}}}`}
              </code>
            ))}
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
            The buyer fills in their own name, national ID, ID card, address and phone on the
            page they land on after paying; those values are saved on their account.
          </p>
        </div>
      </section>
    </div>
  );
};

export default AdminContract;
