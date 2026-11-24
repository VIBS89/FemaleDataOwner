"use client";

import { Check, ChevronDown, Copy, Database, FileSearch, Filter, Server, Table2 } from "lucide-react";
import { toast } from "sonner";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number, shortName } from "@/lib/format";
import type { DataAnswer } from "@/lib/types";

const MAX_VISIBLE_ROWS = 50;

/** Encabezado legible a partir del alias de la columna: `total_clientes` → "Total clientes". */
function label(column: string): string {
  const text = column.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").trim().toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function cell(value: string | number | boolean | null): string {
  if (value == null) return "—";
  if (typeof value === "number") return value.toLocaleString("es-SV", { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (/^\d{4}-\d{2}-\d{2}(T[\d:.]+)?$/.test(value)) {
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    return value.length === 10 ? date.toLocaleDateString("es-SV") : date.toLocaleString("es-SV");
  }
  return value;
}

/** El resultado: una tabla cuando hay más de un valor que mostrar. Una cifra sola ya va en la frase de respuesta. */
export function DataResult({ data }: { data: DataAnswer }) {
  const single = data.row_count === 1 && data.columns.length <= 1;
  if (single || data.row_count === 0) return null;
  const rows = data.rows.slice(0, MAX_VISIBLE_ROWS);
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="max-h-96 overflow-auto">
        <Table>
          <TableHeader className="bg-muted/50 sticky top-0">
            <TableRow>
              {data.columns.map((c) => (
                <TableHead key={c} className="text-xs">
                  {label(c)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={i}>
                {r.map((v, j) => (
                  <TableCell key={j} className={typeof v === "number" ? "text-right tabular-nums" : ""}>
                    {cell(v)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {(data.row_count > rows.length || data.truncated) && (
        <p className="text-muted-foreground border-t px-3 py-2 text-xs">
          Mostrando {number(rows.length)} de {data.truncated ? "más de " : ""}
          {number(data.row_count)} filas.
        </p>
      )}
    </div>
  );
}

/** Sección desplegable con la evidencia: de dónde salió el dato, cómo se calculó y la consulta exacta. */
export function DataEvidence({ data }: { data: DataAnswer }) {
  return (
    <Collapsible className="rounded-lg border bg-muted/30">
      <CollapsibleTrigger className="hover:bg-muted/60 group flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition">
        <FileSearch className="text-primary size-4" />
        ¿De dónde salió este dato?
        <ChevronDown className="text-muted-foreground ml-auto size-4 transition group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-4 border-t px-3 pt-3 pb-4 text-sm">
        {data.explanation && <p>{data.explanation}</p>}

        {data.filters.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
              <Filter className="size-3.5" /> Criterios aplicados
            </h4>
            <ul className="space-y-1">
              {data.filters.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <Check className="text-conf-high mt-0.5 size-3.5 shrink-0" /> {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-1.5">
          <h4 className="text-muted-foreground text-xs font-medium">Fuente</h4>
          <dl className="grid gap-1.5 text-xs sm:grid-cols-[auto_1fr] sm:gap-x-4">
            <dt className="text-muted-foreground flex items-center gap-1.5">
              <Server className="size-3.5" /> Servidor
            </dt>
            <dd>{data.server}</dd>
            <dt className="text-muted-foreground flex items-center gap-1.5">
              <Database className="size-3.5" /> Base de datos
            </dt>
            <dd className="font-mono">{data.database}</dd>
            <dt className="text-muted-foreground flex items-center gap-1.5">
              <Table2 className="size-3.5" /> {data.tables.length === 1 ? "Tabla" : "Tablas"}
            </dt>
            <dd className="font-mono">{data.tables.map(shortName).join(", ")}</dd>
            <dt className="text-muted-foreground">Filas obtenidas</dt>
            <dd>
              {number(data.row_count)}
              {data.truncated ? " (hay más)" : ""}
            </dd>
          </dl>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <h4 className="text-muted-foreground text-xs font-medium">Consulta ejecutada (solo lectura, con tus permisos)</h4>
            <button
              className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs"
              onClick={() => {
                navigator.clipboard.writeText(data.sql);
                toast.success("Consulta copiada");
              }}
            >
              <Copy className="size-3" /> Copiar
            </button>
          </div>
          <pre className="bg-background overflow-x-auto rounded-md border p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {data.sql}
          </pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
