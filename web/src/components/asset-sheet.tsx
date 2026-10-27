"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Copy, KeyRound, Link2, Server, ShieldAlert, Users } from "lucide-react";
import { toast } from "sonner";

import { SourceBadge } from "@/components/source-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { ENV_LABEL, KIND_LABEL, number } from "@/lib/format";
import type { ObjectDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

export type AssetTab = "columns" | "relations" | "rules";
export type AssetRef = ({ assetKey: string } | { id: string }) & { tab?: AssetTab };

export function AssetSheet({ target, onClose }: { target: AssetRef | null; onClose: () => void }) {
  const [data, setData] = useState<ObjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const highlight = target && "assetKey" in target && target.assetKey.split(".").length > 3 ? target.assetKey.split(".").slice(3).join(".") : null;

  useEffect(() => {
    if (!target) return;
    setData(null);
    setError(null);
    const load = "assetKey" in target ? api.asset(target.assetKey) : api.object(target.id);
    load.then(setData).catch((e: Error) => setError(e.message));
  }, [target]);

  return (
    <Sheet open={!!target} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-2xl">
        <SheetHeader className="border-b p-5">
          {data ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{KIND_LABEL[data.kind]}</Badge>
                <Badge variant="outline">{ENV_LABEL[data.environment] ?? data.environment}</Badge>
                {data.domain && <Badge variant="outline">{data.domain}</Badge>}
              </div>
              <SheetTitle className="flex items-center gap-2 font-mono text-lg">
                {data.schema}.{data.name}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Copiar nombre completo"
                  onClick={() => {
                    navigator.clipboard.writeText(data.asset_key);
                    toast.success("Nombre copiado");
                  }}
                >
                  <Copy />
                </Button>
              </SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>Base de datos {data.database}</span>
                <span className="flex items-center gap-1">
                  <Server className="size-3" /> {data.server_alias}
                </span>
                {data.row_count != null && <span>~{number(data.row_count)} filas</span>}
              </SheetDescription>
            </>
          ) : (
            <>
              <SheetTitle className="sr-only">Ficha del activo</SheetTitle>
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-7 w-64" />
              <Skeleton className="h-4 w-48" />
            </>
          )}
        </SheetHeader>

        {error && (
          <div className="p-5">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </div>
        )}

        {data && (
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-5 p-5">
              <div className="space-y-2">
                <p className="text-sm leading-relaxed">{data.description || <span className="text-muted-foreground">Sin descripción todavía.</span>}</p>
                <SourceBadge source={data.description_source} />
                {data.synonyms.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {data.synonyms.map((s) => (
                      <Badge key={s} variant="outline" className="font-normal">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <Tabs defaultValue={target?.tab ?? "columns"}>
                <TabsList className="w-full">
                  <TabsTrigger value="columns">
                    {data.kind === "procedure" ? `Parámetros (${data.parameters.length})` : `Columnas (${data.columns.length})`}
                  </TabsTrigger>
                  <TabsTrigger value="relations">Relaciones</TabsTrigger>
                  <TabsTrigger value="rules">Reglas y responsables</TabsTrigger>
                </TabsList>

                <TabsContent value="columns" className="mt-3">
                  <div className="overflow-hidden rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted/50">
                          <TableHead>Nombre</TableHead>
                          <TableHead>Tipo</TableHead>
                          <TableHead>Descripción</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.kind === "procedure"
                          ? data.parameters.map((p) => (
                              <TableRow key={p.name}>
                                <TableCell className="font-mono text-xs">{p.name}</TableCell>
                                <TableCell className="font-mono text-xs">{p.type}</TableCell>
                                <TableCell className="text-muted-foreground text-xs">{p.direction}</TableCell>
                              </TableRow>
                            ))
                          : data.columns.map((c) => (
                              <TableRow
                                key={c.name}
                                className={cn(highlight && c.name.toLowerCase() === highlight.toLowerCase() && "bg-accent/70 hover:bg-accent")}
                              >
                                <TableCell className="align-top font-mono text-xs">
                                  <div className="flex items-center gap-1.5">
                                    {data.primary_key.includes(c.name) && <KeyRound className="text-conf-mid size-3" aria-label="Llave primaria" />}
                                    {c.name}
                                  </div>
                                  {c.pii && (
                                    <Badge variant="outline" className="border-conf-low/30 text-conf-low mt-1 gap-1 px-1 py-0 font-sans text-[10px]">
                                      <ShieldAlert className="size-2.5" /> Dato personal
                                    </Badge>
                                  )}
                                </TableCell>
                                <TableCell className="text-muted-foreground align-top font-mono text-xs whitespace-nowrap">
                                  {c.type}
                                  {c.nullable === false && <span className="ml-1 opacity-60">not null</span>}
                                </TableCell>
                                <TableCell className="align-top text-xs whitespace-normal">
                                  {c.description ?? <span className="text-muted-foreground">—</span>}
                                </TableCell>
                              </TableRow>
                            ))}
                      </TableBody>
                    </Table>
                  </div>
                </TabsContent>

                <TabsContent value="relations" className="mt-3 space-y-4">
                  <Section title="Referencia a" empty="No tiene llaves foráneas.">
                    {data.foreign_keys.map((fk, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
                        {fk.columns.join(", ")} <ArrowRight className="text-muted-foreground size-3" /> {fk.ref} ({fk.ref_columns.join(", ")})
                      </li>
                    ))}
                  </Section>
                  <Section title="Referenciada por" empty="Ninguna tabla visible la referencia.">
                    {data.referenced_by.map((r) => (
                      <li key={r} className="flex items-center gap-1.5 font-mono text-xs">
                        <Link2 className="text-muted-foreground size-3" /> {r}
                      </li>
                    ))}
                  </Section>
                  <Section title="Otras copias" empty="No hay copias en otros ambientes visibles.">
                    {data.copies.map((c) => (
                      <li key={c.id} className="flex items-center gap-2 text-xs">
                        <Badge variant="outline">{ENV_LABEL[c.environment] ?? c.environment}</Badge> {c.server_alias}
                      </li>
                    ))}
                  </Section>
                </TabsContent>

                <TabsContent value="rules" className="mt-3 space-y-4">
                  <Section title="Reglas de negocio" empty="No hay reglas registradas para este activo.">
                    {data.business_rules.map((r) => (
                      <li key={r.id} className="rounded-md border p-2.5 text-sm">
                        <span className="font-mono text-xs font-medium">{r.id}</span>
                        {!r.reviewed && <span className="text-conf-mid ml-2 text-xs">sugerida, sin revisar</span>}
                        <p className="mt-1">{r.text}</p>
                      </li>
                    ))}
                  </Section>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Owner label="Responsable de negocio" name={data.owners.business} />
                    <Owner label="Responsable técnico" name={data.owners.technical} />
                  </div>
                </TabsContent>
              </Tabs>
            </div>
          </ScrollArea>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Section({ title, empty, children }: { title: string; empty: string; children: React.ReactNode[] }) {
  return (
    <div className="space-y-2">
      <h4 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{title}</h4>
      {children.length ? <ul className="space-y-1.5">{children}</ul> : <p className="text-muted-foreground text-sm">{empty}</p>}
    </div>
  );
}

function Owner({ label, name }: { label: string; name: string | null }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <div className="bg-muted flex size-8 items-center justify-center rounded-full">
        <Users className="text-muted-foreground size-4" />
      </div>
      <div className="grid text-sm">
        <span className="text-muted-foreground text-xs">{label}</span>
        <span className="font-medium">{name ?? "Sin asignar"}</span>
      </div>
    </div>
  );
}
