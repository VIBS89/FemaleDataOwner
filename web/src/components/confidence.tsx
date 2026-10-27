import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CONFIDENCE_LABEL, confidenceLevel, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE = {
  high: { text: "text-conf-high", bg: "bg-conf-high-bg", bar: "bg-conf-high" },
  mid: { text: "text-conf-mid", bg: "bg-conf-mid-bg", bar: "bg-conf-mid" },
  low: { text: "text-conf-low", bg: "bg-conf-low-bg", bar: "bg-conf-low" },
};

export function ConfidenceMeter({ value, className }: { value: number; className?: string }) {
  const level = confidenceLevel(value);
  const tone = TONE[level];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={cn("flex min-w-24 flex-col items-end gap-1", className)}>
          <span className={cn("text-lg leading-none font-semibold tabular-nums", tone.text)}>{pct(value)}</span>
          <div className="bg-muted h-1.5 w-24 overflow-hidden rounded-full">
            <div className={cn("h-full rounded-full transition-all", tone.bar)} style={{ width: `${Math.round(value * 100)}%` }} />
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="left">
        {CONFIDENCE_LABEL[level]}: combina relevancia, recuperación, evidencia, confirmaciones y acuerdo entre fuentes.
      </TooltipContent>
    </Tooltip>
  );
}

export function ConfidencePill({ value, className }: { value: number; className?: string }) {
  const tone = TONE[confidenceLevel(value)];
  return (
    <span className={cn("rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums", tone.bg, tone.text, className)}>
      {pct(value)}
    </span>
  );
}
