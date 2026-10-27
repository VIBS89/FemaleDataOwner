"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Clock, Inbox, KeyRound, PanelRightOpen, SearchX } from "lucide-react";

import { AssetSheet, type AssetRef } from "@/components/asset-sheet";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { MyRequest } from "@/lib/types";

const STATUS = {
  open: { label: "Esperando al responsable", icon: Clock, className: "bg-conf-mid-bg text-conf-mid" },
  answered: { label: "Respondida", icon: CheckCircle2, className: "bg-conf-high-bg text-conf-high" },
  no_source: { label: "No está en las fuentes catalogadas", icon: SearchX, className: "bg-muted text-muted-foreground" },
};

export default function MyRequestsPage() {
  const [items, setItems] = useState<MyRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asset, setAsset] = useState<AssetRef | null>(null);

  useEffect(() => {
    api.myRequests().then((d) => setItems(d.items)).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Mis solicitudes" />
      <div className="mx-auto w-full max-w-3xl space-y-6 p-4 sm:p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Dudas que escalaste a los responsables</h2>
          <p className="text-muted-foreground text-sm">
            Cuando el responsable del dominio responde, la respuesta queda en el conocimiento del agente para todos.
          </p>
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
        {items === null ? (
          <div className="space-y-3">
            <Skeleton className="h-28 rounded-xl" />
            <Skeleton className="h-28 rounded-xl" />
          </div>
        ) : items.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Inbox className="text-muted-foreground size-8" />
              <p className="text-muted-foreground max-w-sm text-sm">
                Aún no escalaste ninguna duda. Si el agente no encuentra un dato, usa “Preguntar al responsable” en la respuesta.
              </p>
              <Button asChild variant="outline">
                <Link href="/">Ir a preguntar</Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {items.map((r) => {
              const st = STATUS[r.status];
              return (
                <Card key={r.id} className="animate-in-up gap-3 py-4">
                  <CardContent className="space-y-3 px-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${st.className}`}>
                        <st.icon className="size-3.5" /> {st.label}
                      </span>
                      <Badge variant="outline" className="font-normal">
                        {r.domain}
                      </Badge>
                      <span className="text-muted-foreground ml-auto text-xs">{dateTime(r.created_at)}</span>
                    </div>
                    <p className="text-[15px] font-medium">“{r.question}”</p>
                    {r.answer && (
                      <div className="bg-muted/40 space-y-2 rounded-lg border p-3 text-sm">
                        {r.answer.asset_key && (
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-muted-foreground">El dato está en</span>
                            <span className="font-mono font-medium">{r.answer.asset_key}</span>
                            <Button size="xs" variant="outline" onClick={() => setAsset({ assetKey: r.answer!.asset_key! })}>
                              <PanelRightOpen /> Ver ficha
                            </Button>
                          </div>
                        )}
                        {r.answer.needs_access && (
                          <p className="text-conf-mid flex items-start gap-2">
                            <KeyRound className="mt-0.5 size-4 shrink-0" />
                            El responsable indicó que requieres acceso a ese dato; solicítalo por el proceso de accesos.
                          </p>
                        )}
                        {r.answer.note && <p className="text-muted-foreground">{r.answer.note}</p>}
                        <p className="text-muted-foreground text-xs">Respondida el {dateTime(r.answer.at)}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
      <AssetSheet target={asset} onClose={() => setAsset(null)} />
    </div>
  );
}
