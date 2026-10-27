"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  ChevronDown,
  Copy,
  Layers,
  Lightbulb,
  Network,
  PanelRightOpen,
  Scale,
  Server,
  ThumbsDown,
  ThumbsUp,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import type { Verdict } from "@/components/chat/conversations";
import { ConfidenceMeter } from "@/components/confidence";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ENV_LABEL, KIND_LABEL } from "@/lib/format";
import type { Candidate } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  candidate: Candidate;
  best: boolean;
  verdict?: Verdict;
  onVerdict: (verdict: Verdict) => Promise<void>;
  onOpen: () => void;
  onRelated: () => void;
}

export function CandidateCard({ candidate: c, best, verdict, onVerdict, onOpen, onRelated }: Props) {
  const [sending, setSending] = useState<Verdict | null>(null);
  const name = c.column ?? c.table;
  const details =
    c.business_rules.length + c.lineage.upstream.length + c.lineage.downstream.length + c.copies.length + c.evidence.length +
    (c.owners.business || c.owners.technical ? 1 : 0);

  const vote = async (v: Verdict) => {
    setSending(v);
    try {
      await onVerdict(v);
    } finally {
      setSending(null);
    }
  };

  return (
    <article
      className={cn(
        "bg-card animate-in-up rounded-xl border shadow-xs transition-shadow hover:shadow-sm",
        best && "border-primary/30 ring-primary/10 ring-4",
      )}
    >
      <div className="flex gap-3 p-4 pb-3">
        <div
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
            best ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {c.rank}
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-[15px] font-semibold break-all">{name}</h3>
            <Badge variant="secondary" className="font-normal">
              {KIND_LABEL[c.kind]}
            </Badge>
            {c.data_type && <span className="text-muted-foreground font-mono text-xs">{c.data_type}</span>}
            {best && <Badge className="bg-primary/10 text-primary hover:bg-primary/10 font-normal">Mejor coincidencia</Badge>}
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span>
              <span className="text-foreground font-medium">{c.database}</span> · {c.schema}.{c.table}
            </span>
            {c.locations.map((l, i) => (
              <span key={i} className="flex items-center gap-1">
                <Badge variant="outline" className="px-1.5 py-0 text-[11px] font-normal">
                  {ENV_LABEL[l.environment] ?? l.environment}
                </Badge>
                <Server className="size-3" /> {l.server}
              </span>
            ))}
          </div>
        </div>
        <ConfidenceMeter value={c.confidence} />
      </div>

      <div className="space-y-3 px-4 pb-3 pl-14">
        {c.drift_warning && (
          <p className="text-conf-mid bg-conf-mid-bg flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {c.drift_warning}
          </p>
        )}
        <div className="space-y-1.5">
          <p className="text-sm leading-relaxed">
            {c.description || <span className="text-muted-foreground italic">Sin descripción registrada.</span>}
          </p>
          <SourceBadge source={c.description_source} />
        </div>
        {c.business_rules.slice(0, 1).map((r) => (
          <p key={r.id} className="flex items-start gap-2 text-xs">
            <Scale className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
            <span>
              <span className="font-mono font-medium">{r.id}</span> · {r.text}
              {!r.reviewed && <span className="text-conf-mid"> (sugerida, sin revisar)</span>}
            </span>
          </p>
        ))}
        {c.why && (
          <p className="text-muted-foreground flex items-start gap-2 text-xs">
            <Lightbulb className="mt-0.5 size-3.5 shrink-0" /> <span>{c.why}</span>
          </p>
        )}

        {details > 0 && (
          <Collapsible>
            <CollapsibleTrigger className="text-primary group flex items-center gap-1 text-xs font-medium">
              Más detalles <ChevronDown className="size-3.5 transition group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2 space-y-2.5 rounded-lg border bg-muted/30 p-3 text-xs">
              {c.business_rules.length > 1 && (
                <Detail icon={Scale} label="Reglas">
                  {c.business_rules.map((r) => (
                    <div key={r.id}>
                      <span className="font-mono">{r.id}</span> · {r.text}
                    </div>
                  ))}
                </Detail>
              )}
              {(c.owners.business || c.owners.technical) && (
                <Detail icon={Users} label="Responsables">
                  Negocio: {c.owners.business ?? "—"} · Técnico: {c.owners.technical ?? "—"}
                </Detail>
              )}
              {(c.lineage.upstream.length > 0 || c.lineage.downstream.length > 0) && (
                <Detail icon={ArrowLeftRight} label="Linaje">
                  ← {c.lineage.upstream.join(", ") || "—"} · → {c.lineage.downstream.join(", ") || "—"}
                </Detail>
              )}
              {c.copies.length > 0 && (
                <Detail icon={Layers} label="El mismo dato en">
                  <span className="font-mono">{c.copies.join(" · ")}</span>
                </Detail>
              )}
              {c.evidence.length > 0 && (
                <Detail icon={Lightbulb} label="Evidencia">
                  {c.evidence.map((e, i) => (
                    <span key={i} className="mr-2 inline-block">
                      {e.source}
                      {e.reviewed ? " ✓" : ""}
                    </span>
                  ))}
                </Detail>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-t px-3 py-2">
        {verdict ? (
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium",
              verdict === "confirm" ? "bg-conf-high-bg text-conf-high" : "bg-muted text-muted-foreground",
            )}
          >
            {verdict === "confirm" ? <ThumbsUp className="size-3.5" /> : <ThumbsDown className="size-3.5" />}
            {verdict === "confirm" ? "Marcaste que es este" : "Marcaste que no es"}
          </span>
        ) : (
          <>
            <Button size="sm" variant="outline" disabled={!!sending} onClick={() => vote("confirm")}>
              <ThumbsUp /> Es este
            </Button>
            <Button size="sm" variant="ghost" disabled={!!sending} onClick={() => vote("reject")}>
              <ThumbsDown /> No es
            </Button>
          </>
        )}
        <div className="ml-auto flex gap-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              navigator.clipboard.writeText(c.asset_key);
              toast.success("Nombre copiado", { description: c.asset_key });
            }}
          >
            <Copy /> <span className="hidden sm:inline">Copiar</span>
          </Button>
          <Button size="sm" variant="ghost" onClick={onRelated} className="hidden sm:inline-flex">
            <Network /> Ver relacionadas
          </Button>
          <Button size="sm" variant="ghost" onClick={onOpen}>
            <PanelRightOpen /> Ver ficha
          </Button>
        </div>
      </div>
    </article>
  );
}

function Detail({ icon: Icon, label, children }: { icon: React.ElementType; label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <Icon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
      <div>
        <span className="text-muted-foreground">{label}: </span>
        {children}
      </div>
    </div>
  );
}
