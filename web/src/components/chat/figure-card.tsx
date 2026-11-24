"use client";

import { useState } from "react";
import { ChevronDown, Copy, Info, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Figure } from "@/lib/types";

const VISIBLE_GROUPS = 8;
const intFmt = new Intl.NumberFormat("es-SV", { maximumFractionDigits: 0 });
const decFmt = new Intl.NumberFormat("es-SV", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function formatValue(v: number): string {
  return Number.isInteger(v) ? intFmt.format(v) : decFmt.format(v);
}

// "CategoriaRiesgo" -> "Categoria Riesgo"; "estado_civil" -> "estado civil"
function humanize(name: string): string {
  return name
    .replace(/_+/g, " ")
    .replace(/([a-záéíóúñ0-9])([A-ZÁÉÍÓÚÑ])/g, "$1 $2")
    .trim();
}

export function FigureCard({ figure }: { figure: Figure }) {
  const { groups } = figure;
  const max = Math.max(0, ...groups.map((g) => Math.abs(g.value)));
  const shown = groups.slice(0, VISIBLE_GROUPS);
  const rest = groups.slice(VISIBLE_GROUPS);

  return (
    <section aria-label={figure.description} className="bg-card animate-in-up max-w-xl space-y-4 rounded-xl border p-4 shadow-xs">
      <div>
        <p className="text-muted-foreground text-xs font-medium">
          {figure.description}
          {figure.environment ? ` · ambiente: ${figure.environment}` : ""}
          {figure.server_alias ? ` · ${figure.server_alias}` : ""}
        </p>
        <p className="mt-0.5 text-4xl font-semibold tracking-tight tabular-nums">
          {figure.value == null ? (
            <span className="text-muted-foreground text-2xl">No se muestra</span>
          ) : (
            formatValue(figure.value)
          )}
        </p>
      </div>

      {groups.length > 0 && (
        <div className="space-y-2">
          {figure.group_by && <h4 className="text-muted-foreground text-xs font-medium">Por {humanize(figure.group_by)}</h4>}
          <ul className="space-y-1.5">
            {shown.map((g, i) => (
              <GroupRow key={`${g.label}-${i}`} label={g.label} value={g.value} max={max} />
            ))}
          </ul>
          {rest.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger className="text-primary group flex items-center gap-1 text-xs font-medium">
                Ver los {rest.length} restantes
                <ChevronDown className="size-3.5 transition group-data-[state=open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2">
                <ul className="space-y-1.5">
                  {rest.map((g, i) => (
                    <GroupRow key={`${g.label}-${i}`} label={g.label} value={g.value} max={max} />
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      )}

      {figure.notes.map((n) => (
        <p key={n} className="text-muted-foreground flex items-start gap-2 rounded-md bg-muted/60 px-3 py-2 text-xs">
          <Info className="mt-0.5 size-3.5 shrink-0" /> {n}
        </p>
      ))}

      <HowCalculated figure={figure} />
    </section>
  );
}

function GroupRow({ label, value, max }: { label: string; value: number; max: number }) {
  const width = max > 0 ? Math.max(2, (Math.abs(value) / max) * 100) : 0;
  return (
    <li className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-x-2 text-xs sm:grid-cols-[minmax(0,10rem)_1fr_auto]">
      <span className="truncate" title={label}>
        {label}
      </span>
      <span className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden="true">
        <span className="bg-primary/70 block h-full rounded-full" style={{ width: `${width}%` }} />
      </span>
      <span className="min-w-10 text-right font-medium tabular-nums">{formatValue(value)}</span>
    </li>
  );
}

function HowCalculated({ figure }: { figure: Figure }) {
  const [copied, setCopied] = useState(false);
  const sql = figure.sql.join(";\n\n");
  if (figure.sql.length === 0) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      toast.success("Consulta copiada");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("No pude copiar la consulta");
    }
  };

  return (
    <Collapsible>
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground group flex items-center gap-1 text-xs font-medium">
        Cómo se calculó <ChevronDown className="size-3.5 transition group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
        <p className="text-muted-foreground flex items-start gap-2">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Es un total calculado con tus permisos sobre <span className="font-mono">{figure.asset_key}</span>. Solo se calculan
            totales: no se muestran registros de clientes, y los grupos con muy pocos registros se ocultan.
          </span>
        </p>
        <div className="relative">
          <pre
            tabIndex={0}
            aria-label="Consultas SQL ejecutadas"
            className="bg-background overflow-x-auto rounded-md border p-2.5 pr-10 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words"
          >
            {sql}
          </pre>
          <Button
            size="icon-sm"
            variant="ghost"
            className="absolute top-1 right-1"
            aria-label={copied ? "Consulta copiada" : "Copiar consulta"}
            onClick={copy}
          >
            <Copy />
          </Button>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
