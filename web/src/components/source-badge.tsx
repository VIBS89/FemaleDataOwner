import { BadgeCheck, BookOpen, FileText, Sparkles, Tag } from "lucide-react";

import { SOURCE_LABEL } from "@/lib/format";
import type { DescriptionSource } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON = { human: BadgeCheck, data_dictionary: BookOpen, ms_description: Tag, document: FileText, generated: Sparkles };

// F12: la fuente de la descripción siempre es visible; las generadas se marcan "sugerida por IA, sin revisar".
export function SourceBadge({ source, className }: { source: DescriptionSource; className?: string }) {
  const Icon = ICON[source];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap",
        source === "generated"
          ? "border-conf-mid/30 bg-conf-mid-bg text-conf-mid"
          : source === "human"
            ? "border-conf-high/30 bg-conf-high-bg text-conf-high"
            : "bg-muted text-muted-foreground",
        className,
      )}
    >
      <Icon className="size-3" />
      {SOURCE_LABEL[source]}
    </span>
  );
}
