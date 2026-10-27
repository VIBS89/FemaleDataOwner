import { DatabaseZap } from "lucide-react";

import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "bg-primary text-primary-foreground flex size-8 shrink-0 items-center justify-center rounded-lg shadow-sm",
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
        <span className="font-semibold tracking-tight">ConverData</span>
        <span className="text-muted-foreground text-xs">{subtitle}</span>
      </div>
    </div>
  );
}
