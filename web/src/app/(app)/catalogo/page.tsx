"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Database, Eye, FileCode2, Search, ShieldAlert, Table2, X } from "lucide-react";

import { AssetSheet, type AssetRef } from "@/components/asset-sheet";
import { PageHeader } from "@/components/page-header";
import { useSession } from "@/components/session-provider";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { ENV_LABEL, number } from "@/lib/format";
import type { DatabaseSummary, ObjectRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON = { table: Table2, view: Eye, procedure: FileCode2 };

export default function CatalogPage() {
  const { status, isAdmin } = useSession();
  const [dbs, setDbs] = useState<DatabaseSummary[] | null>(null);
  const [database, setDatabase] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [rows, setRows] = useState<{ total: number; items: ObjectRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asset, setAsset] = useState<AssetRef | null>(null);

  useEffect(() => {
    if (!status?.has_catalog) return;
    api.databases().then(setDbs).catch((e: Error) => setError(e.message));
  }, [status?.has_catalog]);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!status?.has_catalog) return;
    setRows(null);
    api
      .objects({ database: database ?? undefined, q: query, kind: kind === "all" ? undefined : kind, limit: 300 })
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [database, query, kind, status?.has_catalog]);

  const totals = useMemo(
    () =>
      (dbs ?? []).reduce(
        (acc, d) => ({ tables: acc.tables + d.tables, views: acc.views + d.views, columns: acc.columns + d.columns }),
        { tables: 0, views: 0, columns: 0 },
      ),
    [dbs],
  );

  if (status && !status.has_catalog) {
    return (
      <div className="flex h-svh flex-col">
        <PageHeader title="Catálogo" />
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-md text-center">
            <CardContent className="space-y-4 py-10">
              <Database className="text-muted-foreground mx-auto size-8" />
              <p className="text-muted-foreground text-sm">El catálogo está vacío hasta que se descubran los esquemas.</p>
              {isAdmin && (
                <Button asChild>
                  <Link href="/admin">Descubrir esquemas</Link>
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Catálogo">
        {dbs && (
          <span className="text-muted-foreground hidden truncate text-xs lg:block">
            {dbs.length} BDs · {number(totals.tables)} tablas · {number(totals.views)} vistas · {number(totals.columns)} columnas
          </span>
        )}
      </PageHeader>

      <div className="mx-auto w-full max-w-6xl space-y-6 p-4 sm:p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Explora lo que puedes ver</h2>
          <p className="text-muted-foreground text-sm">Bases de datos, tablas y columnas a las que tu login tiene acceso. Abre una ficha para ver columnas, relaciones y reglas.</p>
        </div>

        <div className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3">
          {dbs === null
            ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)
            : dbs.map((d) => {
                const on = database === d.database;
                return (
                  <button
                    key={`${d.environment}-${d.server}-${d.database}`}
                    onClick={() => setDatabase(on ? null : d.database)}
                    className={cn(
                      "bg-card rounded-xl border p-3.5 text-left shadow-xs transition hover:shadow-sm",
                      on ? "border-primary ring-primary/15 ring-4" : "hover:border-primary/30",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Database className={cn("size-4 shrink-0", on ? "text-primary" : "text-muted-foreground")} />
                      <span className="truncate text-sm font-medium" title={d.database}>
                        {d.database}
                      </span>
                    </div>
                    <p className="text-muted-foreground mt-2 text-xs">
                      {d.tables} tablas · {d.views} vistas{d.procedures ? ` · ${d.procedures} SPs` : ""}
                    </p>
                    <p className="text-muted-foreground mt-0.5 truncate text-[11px]">
                      {ENV_LABEL[d.environment] ?? d.environment} · {d.server_alias}
                    </p>
                  </button>
                );
              })}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="text-muted-foreground absolute top-2.5 left-3 size-4" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Busca por tabla, columna, descripción o sinónimo…"
              className="bg-card pl-9"
            />
          </div>
          <Tabs value={kind} onValueChange={setKind}>
            <TabsList>
              <TabsTrigger value="all">Todo</TabsTrigger>
              <TabsTrigger value="table">Tablas</TabsTrigger>
              <TabsTrigger value="view">Vistas</TabsTrigger>
              <TabsTrigger value="procedure">SPs</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {(database || query) && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">{rows ? `${rows.total} resultados` : "Buscando…"}</span>
            {database && (
              <Badge variant="secondary" className="gap-1">
                {database}
                <button onClick={() => setDatabase(null)} aria-label="Quitar filtro de base de datos">
                  <X className="size-3" />
                </button>
              </Badge>
            )}
          </div>
        )}

        {error && <p className="text-destructive text-sm">{error}</p>}

        <div className="bg-card overflow-hidden rounded-xl border shadow-xs">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead>Objeto</TableHead>
                <TableHead className="hidden md:table-cell">Descripción</TableHead>
                <TableHead className="text-right">Columnas</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Filas aprox.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows === null
                ? Array.from({ length: 8 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={4}>
                        <Skeleton className="h-8 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                : rows.items.map((r) => {
                    const Icon = KIND_ICON[r.kind];
                    return (
                      <TableRow key={r.id} className="cursor-pointer" onClick={() => setAsset({ id: r.id })}>
                        <TableCell className="align-top">
                          <div className="flex items-start gap-2.5">
                            <Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                            <div className="min-w-0">
                              <div className="font-mono text-sm font-medium">
                                {r.schema}.{r.name}
                              </div>
                              <div className="text-muted-foreground text-xs">
                                {r.database} · {ENV_LABEL[r.environment] ?? r.environment}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="hidden max-w-md align-top whitespace-normal md:table-cell">
                          <p className="line-clamp-2 text-sm">{r.description ?? <span className="text-muted-foreground">—</span>}</p>
                          {r.description && <SourceBadge source={r.description_source} className="mt-1" />}
                        </TableCell>
                        <TableCell className="text-right align-top tabular-nums">
                          {r.columns}
                          {r.pii_columns > 0 && (
                            <div className="text-conf-low mt-0.5 flex items-center justify-end gap-1 text-[11px]">
                              <ShieldAlert className="size-3" /> {r.pii_columns} personales
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground hidden text-right align-top tabular-nums sm:table-cell">
                          {number(r.row_count)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
              {rows && rows.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground py-10 text-center">
                    No hay objetos que coincidan.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <AssetSheet target={asset} onClose={() => setAsset(null)} />
    </div>
  );
}
