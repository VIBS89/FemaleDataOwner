"use client";

import { useEffect, useState } from "react";
import { History } from "lucide-react";

import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { dateTime, ENV_LABEL } from "@/lib/format";
import type { DescriptionHistory as HistoryData } from "@/lib/types";

/** Versiones de la descripción de un activo, con su autor y su fecha (RF-34). Solo para responsables. */
export function DescriptionHistory({ assetKey, onClose }: { assetKey: string | null; onClose: () => void }) {
  const [data, setData] = useState<HistoryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assetKey) return;
    setData(null);
    setError(null);
    api
      .descriptionHistory(assetKey)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [assetKey]);

  return (
    <Dialog open={!!assetKey} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="size-4" /> Historial de la descripción
          </DialogTitle>
          <DialogDescription className="font-mono">{assetKey}</DialogDescription>
        </DialogHeader>
        {error ? (
          <p className="text-destructive text-sm">{error}</p>
        ) : data === null ? (
          <Skeleton className="h-28 w-full" />
        ) : !data.available ? (
          <p className="text-muted-foreground text-sm">
            El historial se guarda en la base de datos DiscoveryDataAgent. Esta instalación trabaja con archivos (modo de desarrollo o demo) y no lo
            conserva.
          </p>
        ) : data.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">Este activo aún no tiene cambios registrados.</p>
        ) : (
          <ScrollArea className="max-h-[26rem] pr-3">
            <ol className="space-y-3">
              {data.items.map((v, i) => (
                <li key={i} className="rounded-lg border p-3">
                  <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-foreground font-medium">{v.modified_by}</span>
                    <span>{dateTime(v.valid_from)}</span>
                    <Badge variant="outline" className="font-normal">
                      {ENV_LABEL[v.environment] ?? v.environment} · {v.server_alias}
                    </Badge>
                    {v.valid_to === null ? <Badge className="font-normal">Vigente</Badge> : <span>hasta {dateTime(v.valid_to)}</span>}
                  </div>
                  <p className="mt-1.5 text-sm">{v.description ?? <span className="text-muted-foreground">Sin descripción.</span>}</p>
                  {v.description && (
                    <div className="mt-1.5">
                      <SourceBadge source={v.description_source} />
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
}
