import { useState } from "react";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ImageWithFallback } from "@/components/ImageWithFallback";
import { useApp } from "@/context/AppContext";
import { formatNumber } from "@/lib/format";

/** One saved search: what it matches right now, and what has arrived since it was saved. */
export const SavedSearchCard = ({ item, state, onOpen, onRename, onRemove }) => {
  const { t, lang } = useApp();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.name);

  const total = state?.total;
  const fresh = total != null ? Math.max(0, total - (item.seen_total ?? total)) : 0;

  const commit = () => {
    const name = draft.trim();
    if (name) onRename(item.id, name);
    setEditing(false);
  };

  return (
    <article
      data-testid={`saved-search-${item.id}`}
      className="flex gap-4 rounded-[16px] border border-border bg-card p-3 shadow-sm transition-shadow hover:shadow-md"
    >
      <button
        type="button"
        data-testid={`saved-search-open-${item.id}`}
        onClick={() => onOpen(item)}
        aria-label={item.name}
        className="aspect-video w-[132px] shrink-0 overflow-hidden rounded-[10px] bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-[168px]"
      >
        <ImageWithFallback src={state?.thumb || null} alt={item.name} />
      </button>

      <div className="flex min-w-0 flex-1 flex-col justify-between gap-2 py-0.5">
        <div className="min-w-0">
          {editing ? (
            <div className="flex items-center gap-1.5">
              <Input
                autoFocus
                value={draft}
                data-testid={`saved-search-name-input-${item.id}`}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && commit()}
                className="h-9 rounded-[10px] text-sm"
              />
              <Button
                data-testid={`saved-search-name-save-${item.id}`}
                onClick={commit}
                className="h-9 w-9 shrink-0 rounded-[10px] bg-[hsl(var(--primary))] p-0 text-primary-foreground"
              >
                <Check className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                onClick={() => setEditing(false)}
                className="h-9 w-9 shrink-0 rounded-[10px] p-0 text-muted-foreground"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          ) : (
            <h3
              data-testid={`saved-search-title-${item.id}`}
              className="truncate text-[15px] font-semibold text-foreground"
            >
              {item.name}
            </h3>
          )}

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span data-testid={`saved-search-total-${item.id}`} className="tnum text-muted-foreground">
              {total == null
                ? t("loading")
                : t("matchesNow", { n: formatNumber(total, lang) })}
            </span>
            {fresh > 0 && (
              <span
                data-testid={`saved-search-new-${item.id}`}
                className="tnum rounded-full bg-secondary px-2 py-0.5 text-[12px] font-semibold text-[hsl(var(--primary))]"
              >
                {t("newSinceSaved", { n: formatNumber(fresh, lang) })}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            data-testid={`saved-search-view-${item.id}`}
            onClick={() => onOpen(item)}
            className="h-9 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {t("openSearch")}
          </Button>
          <Button
            data-testid={`saved-search-rename-${item.id}`}
            variant="outline"
            onClick={() => {
              setDraft(item.name);
              setEditing(true);
            }}
            className="h-9 gap-1.5 rounded-[10px] border-border bg-card px-3 text-[13.5px] text-muted-foreground hover:text-foreground"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            {t("rename")}
          </Button>
          <Button
            data-testid={`saved-search-delete-${item.id}`}
            variant="ghost"
            onClick={() => onRemove(item.id)}
            aria-label={t("delete")}
            className="ml-auto h-9 w-9 rounded-[10px] p-0 text-muted-foreground hover:text-[hsl(var(--primary))]"
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </article>
  );
};

export default SavedSearchCard;
