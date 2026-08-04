import { useEffect, useRef, useState } from "react";
import { useApp } from "@/context/AppContext";
import { useLangNav } from "@/hooks/useLangNav";

const LANGS = [
  { code: "bg", short: "BG" },
  { code: "ro", short: "RO" },
  { code: "en", short: "EN" },
];

/**
 * Language switcher: a round badge with the current language, and a soft card underneath
 * holding only the OTHER two. The current language is already on the button, so repeating
 * it in the list would just be a row nobody can use.
 */
export const LanguageMenu = () => {
  const { lang } = useApp();
  const { switchLang } = useLangNav();
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    const escape = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, []);

  const current = LANGS.find((l) => l.code === lang) || LANGS[0];
  const others = LANGS.filter((l) => l.code !== current.code);

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        data-testid="header-language"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={current.short}
        onClick={() => setOpen((v) => !v)}
        className={`flex h-10 w-10 items-center justify-center rounded-full border bg-card text-[12.5px] font-semibold uppercase tracking-wide text-foreground shadow-sm transition-colors ${
          open ? "border-[hsl(var(--primary))]" : "border-input hover:bg-muted"
        }`}
      >
        {current.short}
      </button>

      {open && (
        <ul
          role="listbox"
          data-testid="header-language-menu"
          className="absolute right-0 top-[calc(100%+8px)] z-50 min-w-[104px] rounded-[18px] border border-border bg-card p-2 shadow-xl"
        >
          {others.map((l) => (
            <li key={l.code} role="option" aria-selected={false}>
              <button
                type="button"
                data-testid={`header-language-${l.code}`}
                onClick={() => {
                  setOpen(false);
                  switchLang(l.code);
                }}
                className="w-full rounded-[12px] px-3 py-2.5 text-left text-[15px] font-medium uppercase tracking-wide text-foreground transition-colors hover:bg-muted"
              >
                {l.short}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default LanguageMenu;
