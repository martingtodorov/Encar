import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { useApp } from "@/context/AppContext";
import { useDialCodes, splitNumber } from "@/lib/dialcodes";
import { phoneProblem } from "@/lib/phone";

/**
 * A phone field that cannot produce a number nobody can dial.
 *
 * The prefix is a dropdown of every country's dial code, starting on the one the visitor's own
 * IP suggests, and it is always the buyer's to change. The value handed back is E.164
 * ("+359881234567"), so the office dials what it sees and the API stores one shape everywhere.
 */
export const PhoneInput = ({
  value = "",
  onChange,
  testId = "phone",
  required = false,
  showError = false,
  className = "",
}) => {
  const { t, lang } = useApp();
  const { codes, dial, country } = useDialCodes();
  const [iso, setIso] = useState("");
  const [national, setNational] = useState("");
  // Flip the moment the visitor picks a different flag or types a digit. Once set,
  // an IP-guess refresh (see dialcodes.js — refetches every 10 minutes) is ignored so
  // it never quietly rewrites a country the buyer already chose.
  const [touched, setTouched] = useState(false);

  const byIso = useMemo(
    () => Object.fromEntries(codes.map((c) => [c.iso, c])),
    [codes]
  );
  const code = byIso[iso]?.dial || "";

  // An incoming number (the account's own, prefilled) decides the prefix; an empty field
  // takes the guess from the IP. Typing or manually picking a country freezes the choice.
  useEffect(() => {
    if (!codes.length) return;
    const parsed = splitNumber(value, codes);
    if (touched && !parsed.dial) return;   // buyer already chose — do not override
    const wanted = parsed.dial || dial || "";
    setIso((prev) => {
      if (prev && byIso[prev]?.dial === wanted) return prev;
      // +1 is Canada, the United States and a dozen islands: the country the visitor is
      // actually in wins, or the alphabet would greet a New Yorker with "Canada".
      const mine = codes.find((c) => c.dial === wanted && c.iso === country);
      return (mine || codes.find((c) => c.dial === wanted) || {}).iso || prev;
    });
    setNational(parsed.national);
  }, [codes.length, dial, country, value, touched, byIso, codes]);

  const emit = (nextCode, nextNational) => {
    const digits = String(nextNational || "").replace(/[^\d]/g, "");
    onChange(digits ? `+${nextCode}${digits}` : "");
  };

  const problem = useMemo(
    () => (showError ? phoneProblem(value, lang, required) : ""),
    [showError, value, lang, required]
  );

  const sorted = useMemo(
    () => [...codes].sort((a, b) => a.name.localeCompare(b.name)),
    [codes]
  );

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex gap-2">
        <select
          data-testid={`${testId}-prefix`}
          aria-label={t("phonePrefix")}
          value={iso}
          onChange={(e) => {
            setTouched(true);
            setIso(e.target.value);
            emit(byIso[e.target.value]?.dial || "", national);
          }}
          className="h-10 w-[92px] min-w-0 shrink-0 rounded-[9px] border border-border bg-background px-2 text-[13px] text-foreground outline-none transition-colors focus:border-[hsl(var(--primary))] sm:w-[104px]"
        >
          {sorted.map((c) => (
            <option key={c.iso} value={c.iso}>
              {`+${c.dial} ${c.iso}`}
            </option>
          ))}
        </select>
        <Input
          data-testid={`${testId}-input`}
          type="tel"
          inputMode="numeric"
          autoComplete="tel-national"
          placeholder="88 123 4567"
          value={national}
          onChange={(e) => {
            const digits = e.target.value.replace(/[^\d]/g, "").slice(0, 14);
            setTouched(true);
            setNational(digits);
            emit(code, digits);
          }}
          className={`tnum h-10 min-w-0 flex-1 bg-background text-[14px] tracking-[0.02em] ${
            problem ? "border-[hsl(var(--destructive))]" : ""
          }`}
        />
      </div>
      {problem && (
        <span data-testid={`${testId}-error`} className="text-[11.5px] text-[hsl(var(--destructive))]">
          {t(problem)}
        </span>
      )}
    </div>
  );
};

export default PhoneInput;
