import { DatabaseZap } from "lucide-react";

import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "bg-brand-gradient text-white flex size-8 shrink-0 items-center justify-center rounded-lg shadow-sm ring-1 ring-black/5",
        className,
      )}
    >
      <DatabaseZap className="size-4" />
    </div>
  );
}

export function Brand({ subtitle = "Descubrimiento de datos" }: { subtitle?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <div className="grid leading-tight">
        <span className="font-heading text-[15px] font-extrabold tracking-tight">Discovery Data Agent</span>
        <span className="text-muted-foreground text-xs">{subtitle}</span>
      </div>
    </div>
  );
}
